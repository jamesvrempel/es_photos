"""Where gallery image files live on disk.

Everything the gallery stores — uploaded originals and the thumb / medium /
large renditions — sits under one folder:

    sites/<site>/public/files/es_photos/            renditions  (<photo>-th.jpg …)
    sites/<site>/public/files/es_photos/originals/  originals   (<photo>-<name>.jpg)

Keeping it in one folder lets backups leave the whole gallery out with a
single exclude (see es_photos.backup).
"""

import os
import re
import shutil

import frappe

FOLDER = "es_photos"
ORIGINALS = f"{FOLDER}/originals"
URL_PREFIX = f"/files/{FOLDER}/"


def files_root() -> str:
	return frappe.get_site_path("public", "files")


def gallery_path() -> str:
	"""Absolute-or-site-relative path of the gallery folder, in the same form
	Frappe's backup passes to tar (so exclude patterns match)."""
	return os.path.join(files_root(), FOLDER)


def _originals_dir() -> str:
	path = frappe.get_site_path("public", "files", *ORIGINALS.split("/"))
	os.makedirs(path, exist_ok=True)
	return path


def _safe_name(photo_name: str, filename: str) -> str:
	base, ext = os.path.splitext(os.path.basename(filename or "photo.jpg"))
	if base.startswith(f"{photo_name}-"):  # already named for this photo
		base = base[len(photo_name) + 1 :]
	base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "photo"
	ext = re.sub(r"[^A-Za-z0-9.]", "", ext.lower()) or ".jpg"
	return f"{photo_name}-{base[:80]}{ext}"


def in_gallery_folder(file_url: str | None) -> bool:
	return bool(file_url) and file_url.startswith(URL_PREFIX)


def save_original(photo_name: str, filename: str, content: bytes) -> "frappe.model.document.Document":
	"""Store an uploaded original as a public File attached to the Photo and
	move it into es_photos/originals. Returns the File doc.

	Frappe always writes new File content into the top of public/files (and
	re-writes it there if handed a sub-folder URL), so the file is saved the
	normal way first and then moved with relocate_original()."""
	f = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": _safe_name(photo_name, filename),
			"content": content,
			"is_private": 0,
			"attached_to_doctype": "Photo",
			"attached_to_name": photo_name,
			"attached_to_field": "image",
		}
	)
	f.flags.ignore_duplicate_entry_error = True
	f.insert(ignore_permissions=True)
	relocate_original(photo_name, f.file_url)
	f.reload()
	return f


def relocate_original(photo_name: str, file_url: str) -> str | None:
	"""Move a Photo's original from the general files folder into
	es_photos/originals and repoint its File record(s).

	A file that other records also use is copied instead of moved, so nothing
	else on the site loses its file. Returns the new URL, or None when there
	was nothing to do."""
	if not file_url or not file_url.startswith("/files/") or in_gallery_folder(file_url):
		return None
	rel = file_url[len("/files/") :]
	src = frappe.get_site_path("public", "files", *rel.split("/"))
	if not os.path.isfile(src):
		return None

	def users():
		return frappe.get_all(
			"File",
			filters={"file_url": file_url, "is_private": 0},
			fields=["name", "attached_to_doctype", "attached_to_name"],
		)

	# 1. make sure the Photo has its own File record (created while the file is
	#    still in place, so this works the same on every Frappe v15 release)
	if not any(u.attached_to_doctype == "Photo" and u.attached_to_name == photo_name for u in users()):
		f = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": os.path.basename(rel),
				"file_url": file_url,
				"is_private": 0,
				"attached_to_doctype": "Photo",
				"attached_to_name": photo_name,
				"attached_to_field": "image",
			}
		)
		f.flags.ignore_duplicate_entry_error = True
		f.insert(ignore_permissions=True)
		if f.file_url != file_url:  # Frappe pointed it at an identical existing file
			frappe.db.set_value("File", f.name, "file_url", file_url, update_modified=False)

	all_users = users()
	ours = [u for u in all_users if u.attached_to_doctype == "Photo" and u.attached_to_name == photo_name]
	shared = len(all_users) > len(ours) or frappe.db.count("Photo", {"name": ("!=", photo_name), "image": file_url})

	# 2. move (or copy, when shared) into the gallery folder
	fname = _safe_name(photo_name, os.path.basename(rel))
	dest = os.path.join(_originals_dir(), fname)
	new_url = f"/files/{ORIGINALS}/{fname}"
	if shared:
		shutil.copy2(src, dest)
	else:
		shutil.move(src, dest)

	# 3. repoint this Photo's File record(s) and the Photo itself
	for u in ours:
		frappe.db.set_value("File", u.name, {"file_url": new_url, "file_name": fname}, update_modified=False)
	vals = {"image": new_url}
	if frappe.db.get_value("Photo", photo_name, "original_url") in (file_url, None, "", "pending"):
		vals["original_url"] = new_url
	frappe.db.set_value("Photo", photo_name, vals, update_modified=False)
	return new_url
