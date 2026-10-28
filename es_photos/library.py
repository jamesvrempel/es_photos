"""Bulk photo jobs for large libraries (tens of thousands of photos).

Two jobs, both run from a **Photo Library Job** record in the desk:

Import folder
    Photos are copied onto the server (rsync, scp, a network share …) into the
    library folder, ``sites/<site>/public/files/es_photos/library/``. The job
    walks it: every folder becomes an album (sub-folders become sub-albums) and
    every image becomes a Photo whose original is served straight from that
    folder — nothing is copied. Re-running only picks up new or changed files,
    and (optionally) hides photos whose files were removed.

Copy linked photos in
    Photos that are still shown from another website (the old Piwigo site,
    after a "Link remote images" import) are downloaded into this server so
    the other site can be switched off. Albums, comments and reactions stay.

Both work in two phases. A quick scan creates/updates records, then the slow
part — reading each image, its EXIF details and making the thumb / medium /
large copies — is split into batches queued on the ``long`` queue, so several
background workers can process them in parallel. Imported photos stay hidden
from the gallery until their small copies exist.
"""

import os
import traceback
from datetime import datetime
from urllib.parse import quote, unquote, urlparse

import frappe
from frappe.utils import cint, now_datetime

from es_photos.imaging import FOLDER

DOCTYPE = "Photo Library Job"
LIBRARY = f"{FOLDER}/library"
REF = "library:"  # Photo.source_ref prefix for imported files
DIR_REF = "library:dir:"  # Photo Album.source_ref prefix for imported folders
BATCH = 100
COMMIT_EVERY = 200
LOG_LIMIT = 200_000

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
HEIF_EXT = {".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".mts"}
SKIP_DIRS = {
	"@eaDir", "__MACOSX", ".AppleDouble", "#recycle", ".Trashes", ".Spotlight-V100", ".fseventsd", "lost+found",
	"_data",  # Piwigo's cache of resized copies
}

try:  # iPhone photos — optional: pip install pillow-heif
	from pillow_heif import register_heif_opener

	register_heif_opener()
	IMAGE_EXT |= HEIF_EXT
	HEIF_OK = True
except Exception:
	HEIF_OK = False


# --------------------------------------------------------------------------- paths


def library_root() -> str:
	return frappe.get_site_path("public", "files", *LIBRARY.split("/"))


def safe_subfolder(sub: str | None) -> str:
	"""Normalise a sub-folder typed by a user; refuse anything outside the library."""
	sub = (sub or "").strip().replace("\\", "/").strip("/")
	if not sub:
		return ""
	parts = [p for p in sub.split("/") if p not in ("", ".")]
	if any(p == ".." for p in parts) or os.path.isabs(sub):
		frappe.throw(frappe._("The sub-folder must be inside the library folder."))
	return "/".join(parts)


def url_for(rel: str) -> str:
	return f"/files/{LIBRARY}/{quote(rel)}"


def path_for_url(url: str) -> str | None:
	prefix = f"/files/{LIBRARY}/"
	if not url or not url.startswith(prefix):
		return None
	return os.path.join(library_root(), *unquote(url[len(prefix) :]).split("/"))


def _like_prefix(text: str) -> str:
	"""LIKE pattern matching *text* literally at the start (folder names may hold _ or %)."""
	return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _skip_dir(name: str) -> bool:
	return name.startswith(".") or name in SKIP_DIRS


def _skip_file(name: str) -> bool:
	return name.startswith(".") or name.startswith("._") or name in ("Thumbs.db", "desktop.ini")


# --------------------------------------------------------------------------- job bookkeeping


COUNTERS = (
	"total", "rendered", "albums_created", "photos_created", "photos_updated", "photos_skipped",
	"photos_hidden", "error_count", "batches_total", "batches_done",
)


def reset_counters(job_name: str):
	vals = {c: 0 for c in COUNTERS}
	vals.update({"cancel_requested": 0, "log": "", "started_on": None, "finished_on": None})
	frappe.db.set_value(DOCTYPE, job_name, vals, update_modified=False)


def bump(job_name: str, **deltas):
	"""Atomic counter increments (batches run in parallel)."""
	sets = ", ".join(f"`{k}` = IFNULL(`{k}`, 0) + %({k})s" for k in deltas)
	frappe.db.sql(f"UPDATE `tab{DOCTYPE}` SET {sets} WHERE name=%(name)s", dict(deltas, name=job_name))


def log(job_name: str, msg: str):
	line = f"{now_datetime():%Y-%m-%d %H:%M:%S}  {msg}\n"
	frappe.db.sql(
		f"""UPDATE `tab{DOCTYPE}` SET log = CONCAT(IFNULL(log, ''), %s)
		WHERE name=%s AND LENGTH(IFNULL(log, '')) < {LOG_LIMIT}""",
		(line, job_name),
	)


def cancelled(job_name: str) -> bool:
	return bool(cint(frappe.db.get_value(DOCTYPE, job_name, "cancel_requested")))


# --------------------------------------------------------------------------- entry point


def run(library_job: str):
	"""Phase 1 (scan / select) and queueing of phase 2 batches."""
	job_name = library_job
	job = frappe.get_doc(DOCTYPE, job_name)
	frappe.db.set_value(DOCTYPE, job_name, {"status": "Running", "started_on": now_datetime()}, update_modified=False)
	frappe.db.commit()
	try:
		if job.job_type == "Import folder":
			names = scan_folder(job)
			kind = "render"
		elif (job.copy_source or "").startswith("Use files"):
			names = relink_local(job)
			kind = "render"
		else:
			names = linked_photo_names()
			frappe.db.set_value(DOCTYPE, job_name, "total", len(names), update_modified=False)
			log(job_name, f"{len(names)} photos are still shown from another website")
			kind = "copy"

		if cint(job.dry_run):
			# the scan writes nothing in dry-run mode except this job's own counters and log
			log(job_name, f"Dry run — would process {len(names)} photos. Nothing was changed.")
			_finish(job_name, "Completed")
			return
		frappe.db.commit()

		batches = [names[i : i + BATCH] for i in range(0, len(names), BATCH)]
		frappe.db.set_value(DOCTYPE, job_name, "batches_total", len(batches), update_modified=False)
		if not batches:
			log(job_name, "Nothing to process")
			finalize(job_name)
			return
		log(job_name, f"Queued {len(names)} photos in {len(batches)} batches of up to {BATCH}")
		frappe.db.commit()
		for i, batch in enumerate(batches):
			frappe.enqueue(
				"es_photos.library.process_batch",
				queue="long",
				timeout=6 * 3600,
				library_job=job_name,  # not "job_name": frappe.enqueue reserves that
				names=batch,
				kind=kind,
				copy_size=job.copy_size,
				job_id=f"es_photos_library::{job_name}::{i}",
				enqueue_after_commit=True,
			)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		log(job_name, "FAILED\n" + traceback.format_exc()[-3000:])
		_finish(job_name, "Failed")


def process_batch(library_job: str, names: list, kind: str, copy_size: str | None = None):
	job_name = library_job
	for name in names:
		if cancelled(job_name):
			break
		try:
			if kind == "render":
				render_library_photo(name)
			else:
				copy_linked_photo(name, copy_size)
			bump(job_name, rendered=1)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			bump(job_name, error_count=1)
			log(job_name, f"ERROR {name}: {str(e)[:300]}")
			frappe.db.commit()
	bump(job_name, batches_done=1)
	frappe.db.commit()
	done, total = frappe.db.get_value(DOCTYPE, job_name, ["batches_done", "batches_total"])
	if cint(done) >= cint(total):
		finalize(job_name)


def finalize(job_name: str):
	from es_photos.gallery import recount_all

	try:
		recount_all()
	except Exception:
		log(job_name, "Recount failed: " + traceback.format_exc()[-500:])
	j = frappe.db.get_value(DOCTYPE, job_name, ["rendered", "error_count", "cancel_requested"], as_dict=True)
	status = "Cancelled" if cint(j.cancel_requested) else "Completed"
	log(job_name, f"{status}: {j.rendered} photos processed, {j.error_count} errors")
	_finish(job_name, status)


def _finish(job_name: str, status: str):
	frappe.db.set_value(DOCTYPE, job_name, {"status": status, "finished_on": now_datetime()}, update_modified=False)
	frappe.db.commit()


# --------------------------------------------------------------------------- import folder


def scan_folder(job) -> list:
	"""Create / update albums and photo records; return photos needing processing."""
	sub = safe_subfolder(job.source_folder)
	root = library_root()
	base = os.path.join(root, *sub.split("/")) if sub else root
	if not os.path.isdir(base):
		os.makedirs(root, exist_ok=True)
		if not os.path.isdir(base):
			frappe.throw(frappe._("Folder not found on the server: {0}").format(base))

	scope = REF + (f"{sub}/" if sub else "")
	existing = {
		r.source_ref: r
		for r in frappe.db.sql(
			"""SELECT name, source_ref, filesize, is_deleted, thumb_url FROM `tabPhoto`
			WHERE source_ref LIKE %s""",
			(_like_prefix(scope),),
			as_dict=True,
		)
	}
	albums = {
		r.source_ref[len(DIR_REF) :]: r.name
		for r in frappe.db.sql(
			"SELECT name, source_ref FROM `tabPhoto Album` WHERE source_ref LIKE %s", (_like_prefix(DIR_REF),), as_dict=True
		)
	}
	# files that existing gallery photos already use (e.g. relinked Piwigo originals) are not
	# imported a second time
	in_use = set(
		frappe.db.sql_list(
			"""SELECT original_url FROM `tabPhoto`
			WHERE original_url LIKE %s AND IFNULL(source_ref, '') NOT LIKE 'library:%%'""",
			(_like_prefix(f"/files/{LIBRARY}/"),),
		)
	)
	already = 0
	counts = dict(albums_created=0, photos_created=0, photos_updated=0, photos_skipped=0, photos_hidden=0)
	to_render, seen, found = [], set(), 0
	unsupported, videos = 0, 0
	dry = cint(job.dry_run)

	def ensure_album(rel_dir: str) -> str:
		if rel_dir in albums:
			return albums[rel_dir]
		parent_rel = os.path.dirname(rel_dir)
		parent = ensure_album(parent_rel) if parent_rel else (job.parent_album or None)
		title = os.path.basename(rel_dir).replace("_", " ").strip() or "Library"
		if dry:
			albums[rel_dir] = f"(new) {title}"
		else:
			doc = frappe.get_doc(
				{
					"doctype": "Photo Album",
					"title": title[:140],
					"parent_photo_album": parent if parent and not parent.startswith("(new)") else None,
					"owner_user": job.album_owner or "Administrator",
					"privacy": job.privacy or "Public",
					"published": 1,
					"source_ref": DIR_REF + rel_dir,
				}
			).insert(ignore_permissions=True)
			albums[rel_dir] = doc.name
		counts["albums_created"] += 1
		return albums[rel_dir]

	for dirpath, dirnames, filenames in os.walk(base):
		dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
		rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
		rel_dir = "" if rel_dir == "." else rel_dir
		for fn in sorted(filenames):
			if _skip_file(fn):
				continue
			ext = os.path.splitext(fn)[1].lower()
			if ext in VIDEO_EXT:
				videos += 1
				continue
			if ext not in IMAGE_EXT:
				if ext in HEIF_EXT:
					unsupported += 1
				continue
			rel = f"{rel_dir}/{fn}" if rel_dir else fn
			if url_for(rel) in in_use:
				already += 1
				continue
			found += 1
			ref = REF + rel
			seen.add(ref)
			st = os.stat(os.path.join(dirpath, fn))
			album = ensure_album(rel_dir or "Library")
			row = existing.get(ref)
			if row:
				changes = {}
				if cint(row.is_deleted):
					changes["is_deleted"] = 0
				if cint(row.filesize) != st.st_size:
					changes.update({"filesize": st.st_size, "thumb_url": None, "medium_url": None, "large_url": None})
				if changes:
					if not dry:
						frappe.db.set_value("Photo", row.name, changes, update_modified=False)
					counts["photos_updated"] += 1
				else:
					counts["photos_skipped"] += 1
				if changes.get("filesize") or not row.thumb_url:
					to_render.append(row.name)
				continue
			if dry:
				counts["photos_created"] += 1
				to_render.append(f"(new) {rel}")
				continue
			photo = frappe.get_doc(
				{
					"doctype": "Photo",
					"album": album,
					"title": os.path.splitext(fn)[0].replace("_", " ")[:140],
					"media_type": "Image",
					"original_url": url_for(rel),
					"uploaded_by": job.album_owner or "Administrator",
					"date_added": datetime.fromtimestamp(st.st_mtime),
					"filesize": st.st_size,
					"source_ref": ref,
				}
			)
			photo.flags.esp_skip_recount = True
			photo.flags.esp_skip_processing = True
			photo.insert(ignore_permissions=True)
			to_render.append(photo.name)
			counts["photos_created"] += 1
			if counts["photos_created"] % COMMIT_EVERY == 0:
				frappe.db.commit()
				frappe.db.set_value(DOCTYPE, job.name, dict(counts, total=found), update_modified=False)
				frappe.db.commit()
				if cancelled(job.name):
					log(job.name, "Cancelled during scan")
					return []

	if cint(job.hide_missing):
		gone = [r.name for ref, r in existing.items() if ref not in seen and not cint(r.is_deleted)]
		if gone and not dry:
			for i in range(0, len(gone), 1000):
				frappe.db.sql(
					"UPDATE `tabPhoto` SET is_deleted=1 WHERE name IN %s", (tuple(gone[i : i + 1000]),)
				)
		counts["photos_hidden"] = len(gone)

	frappe.db.set_value(DOCTYPE, job.name, dict(counts, total=len(to_render)), update_modified=False)
	log(
		job.name,
		f"Scanned {base}: {found} images in folder, {counts['albums_created']} new albums, "
		f"{counts['photos_created']} new photos, {counts['photos_updated']} changed, "
		f"{counts['photos_skipped']} unchanged, {counts['photos_hidden']} hidden (file removed); "
		f"{len(to_render)} to process",
	)
	if already:
		log(job.name, f"{already} files skipped because gallery photos already use them")
	if videos:
		log(job.name, f"{videos} video files skipped (add videos as YouTube/Vimeo links)")
	if unsupported:
		log(job.name, f"{unsupported} HEIC/HEIF files skipped — install pillow-heif on the server to include them")
	return to_render


def render_library_photo(name: str):
	from es_photos.imaging import process_image_file

	doc = frappe.get_doc("Photo", name)
	path = path_for_url(doc.original_url)
	if not path or not os.path.isfile(path):
		raise FileNotFoundError(f"file not found: {doc.original_url}")
	vals = process_image_file(doc, path)
	frappe.db.set_value("Photo", name, vals, update_modified=False)


# --------------------------------------------------------------------------- copy linked photos in


def local_path_for_remote(url: str | None, folder: str) -> str | None:
	"""Where a website URL's file lives under the library, if it is there.

	https://site/galleries/A/b.png          -> library/<folder>/galleries/A/b.png
	https://site/upload/2026/05/06/x.jpg    -> library/<folder>/upload/2026/05/06/x.jpg
	https://site/_data/i/galleries/A/b-me.png -> library/<folder>/_data/i/galleries/A/b-me.png
	https://site/i.php?/galleries/A/b-xl.png  -> library/<folder>/_data/i/galleries/A/b-xl.png
	"""
	if not url or not url.startswith("http"):
		return None
	u = urlparse(url)
	path = unquote(u.path)
	if path.endswith("/i.php") and u.query:
		path = "/_data/i/" + unquote(u.query.split("&")[0]).lstrip("/")
	rel = path.lstrip("/")
	if not rel or ".." in rel.split("/"):
		return None
	return f"{folder}/{rel}" if folder else rel


def relink_local(job) -> list:
	"""Point remotely-linked photos at copies of the same files on this server.

	Each photo's original (and, where present, the website's own resized copies) is
	looked up under the library folder; found files are used in place, so the photos
	work again straight away. Returns the photos to (re)process for proper resized
	copies and EXIF details."""
	folder = safe_subfolder(job.local_folder)
	root = library_root()
	names = linked_photo_names()
	dry = cint(job.dry_run)
	frappe.db.set_value(DOCTYPE, job.name, "total", len(names), update_modified=False)
	log(job.name, f"{len(names)} photos are still shown from another website; looking for their files "
		f"under {os.path.join(root, *folder.split('/')) if folder else root}")

	def local(url):
		rel = local_path_for_remote(url, folder)
		if rel and os.path.isfile(os.path.join(root, *rel.split("/"))):
			return url_for(rel)
		return None

	done, missing, examples = [], 0, []
	for i, name in enumerate(names, 1):
		p = frappe.db.get_value("Photo", name, ["original_url", "large_url", "medium_url", "thumb_url"], as_dict=True)
		original = local(p.original_url)
		if not original:
			missing += 1
			if len(examples) < 5:
				examples.append(p.original_url)
			continue
		vals = {"original_url": original}
		for f in ("large_url", "medium_url", "thumb_url"):
			# use the website's resized copy if it's on the drive; otherwise fall back to
			# the original until ES Photos has made its own
			vals[f] = local(p.get(f)) if (p.get(f) or "").startswith("http") else p.get(f)
		if not dry:
			frappe.db.set_value("Photo", name, vals, update_modified=False)
		done.append(name)
		if i % 500 == 0 and not dry:
			frappe.db.commit()
			frappe.db.set_value(DOCTYPE, job.name, "photos_updated", len(done), update_modified=False)
			frappe.db.commit()
	# photos whose file isn't on the server are left as they are (counted under "skipped")
	frappe.db.set_value(
		DOCTYPE, job.name, {"photos_updated": len(done), "photos_skipped": missing, "total": len(done)},
		update_modified=False,
	)
	verb = "Would switch" if dry else "Switched"
	log(job.name, f"{verb} {len(done)} photos to the files on this server; "
		f"{missing} files not found (those photos are left unchanged)")
	for e in examples:
		log(job.name, f"  not found: {e}")
	if not dry:
		from es_photos.gallery import recount_all

		frappe.db.commit()
		recount_all()  # album covers now point at local files too
		frappe.db.commit()
	return done


def linked_photo_names() -> list:
	return frappe.db.sql_list(
		"""SELECT name FROM `tabPhoto`
		WHERE media_type='Image' AND is_deleted=0 AND IFNULL(image, '')=''
		AND (original_url LIKE 'http%%' OR large_url LIKE 'http%%' OR medium_url LIKE 'http%%')
		ORDER BY creation"""
	)


def _download(url: str) -> bytes:
	import time

	import requests

	last = None
	for attempt in range(3):
		if attempt:
			time.sleep(5 * attempt)
		try:
			r = requests.get(url, timeout=(15, 300), headers={"User-Agent": "ES-Photos/copy-in"})
			r.raise_for_status()
			ctype = (r.headers.get("content-type") or "").lower()
			if "html" in ctype or not r.content:
				raise ValueError(f"not an image ({ctype or 'empty'})")
			return r.content
		except Exception as e:
			last = e
	raise last


LARGE_EDGE = 1600


def _remote_filename(url: str) -> str:
	"""File name from a URL, including Piwigo's i.php?/galleries/…/name-xl.png form."""
	u = urlparse(url)
	base = unquote(os.path.basename(u.path))
	if base.endswith(".php") and u.query:
		base = unquote(os.path.basename(u.query.split("&")[0]))
	return base


def _shrink(content: bytes, fname: str) -> tuple[bytes, str]:
	"""At most LARGE_EDGE px on the long side, as JPEG, keeping the EXIF details."""
	import io

	from PIL import Image

	from es_photos.imaging import _flatten

	with Image.open(io.BytesIO(content)) as img:
		exif = img.getexif()
		if img.format == "JPEG":
			img.draft("RGB", (LARGE_EDGE, LARGE_EDGE))
		out = _flatten(img.convert("RGBA") if img.mode == "P" else img)
		out.thumbnail((LARGE_EDGE, LARGE_EDGE), Image.LANCZOS)
		buf = io.BytesIO()
		out.save(buf, "JPEG", quality=90, optimize=True, progressive=True, exif=exif)
	stem = os.path.splitext(fname)[0]
	for suffix in ("-xxl", "-xl", "-la", "-me", "-sm", "-xs", "-th", "-sq"):  # Piwigo derivative suffixes
		if stem.endswith(suffix):
			stem = stem[: -len(suffix)]
			break
	return buf.getvalue(), f"{stem}.jpg"


def copy_linked_photo(name: str, copy_size: str | None):
	from es_photos.imaging import process_image_bytes
	from es_photos.storage import save_original

	doc = frappe.get_doc("Photo", name)
	if doc.image:
		return
	large_only = (copy_size or "").startswith("Large")
	if large_only:
		# the biggest reduced copy that isn't the original (Piwigo's "XX-large" link is
		# often the original file itself)
		reduced = [u for u in (doc.large_url, doc.medium_url) if u and u != doc.original_url]
		candidates = reduced + [doc.original_url]
	else:
		candidates = [doc.original_url, doc.large_url]
	url = next((u for u in candidates if u and u.startswith("http")), None)
	if not url:
		return
	content = _download(url)
	fname = _remote_filename(url) or f"{name}.jpg"
	if large_only:
		content, fname = _shrink(content, fname)
	f = save_original(name, fname, content)
	vals = process_image_bytes(doc, content)
	vals.update({"image": f.file_url, "original_url": f.file_url})
	frappe.db.set_value("Photo", name, vals, update_modified=False)
