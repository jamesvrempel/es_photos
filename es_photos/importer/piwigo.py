"""Import albums, photos, videos and keywords from a Piwigo gallery.

Uses Piwigo's public web API (ws.php). Re-runnable: albums and photos are
matched by source_ref ("<host>:cat:<id>" / "<host>:img:<id>"), so a second
run only adds new photos and refreshes counts.

Piwigo "virtual" album membership (one photo in several albums, e.g. the
Videos album) maps to Photo.additional_albums.
"""

import html
import json
import os
import re
import time
from urllib.parse import urlparse

import frappe
import requests
from frappe.utils import cint, get_datetime, now_datetime

from es_photos.gallery import recount_all
from es_photos.utils import strip_html, unique_slug

PER_PAGE = 500
VIDEO_FILE = re.compile(r"^(youtube|vimeo|dailymotion)-([A-Za-z0-9_-]+?)-[0-9a-f]{6,}\.", re.I)


class PiwigoError(Exception):
	pass


class Piwigo:
	def __init__(self, base_url: str):
		self.base = base_url.rstrip("/")
		self.ws = f"{self.base}/ws.php"
		self.s = requests.Session()
		self.s.headers["User-Agent"] = "ES-Photos-Importer/1.0 (+Frappe)"

	def call(self, method: str, post: bool = False, **params):
		params = {"format": "json", "method": method, **params}
		last = None
		for attempt in range(4):
			try:
				if post:
					r = self.s.post(self.ws, params={"format": "json"}, data=params, timeout=60)
				else:
					r = self.s.get(self.ws, params=params, timeout=60)
				r.raise_for_status()
				data = self._json(r.text)
				if data.get("stat") != "ok":
					raise PiwigoError(f"{method}: {data.get('message') or data}")
				return data.get("result")
			except PiwigoError:
				raise
			except Exception as e:
				last = e
				time.sleep(2 * (attempt + 1))
		raise PiwigoError(f"{method} failed: {last}")

	@staticmethod
	def _json(text: str) -> dict:
		"""Parse ws.php output. Piwigo with display_errors on prints PHP
		notices (e.g. an unreadable image file) ahead of the JSON body, so
		skip anything before the first '{'."""
		try:
			return json.loads(text)
		except ValueError:
			i = text.find('{"stat"')
			if i < 0:
				raise
			return json.loads(text[i:])

	def login(self, username: str, password: str):
		self.call("pwg.session.login", post=True, username=username, password=password)

	def paged(self, method: str, key: str = "images", **params):
		page = 0
		while True:
			res = self.call(method, page=page, per_page=PER_PAGE, **params)
			items = res.get(key) or []
			yield from items
			paging = res.get("paging") or {}
			total = cint(paging.get("total_count"))
			if len(items) < PER_PAGE or (total and (page + 1) * PER_PAGE >= total):
				break
			page += 1


class Run:
	def __init__(self, log):
		self.log = log
		self.s = frappe.get_single("ES Photos Settings")
		self.dry = cint(log.dry_run)
		self.overwrite = cint(log.overwrite_metadata)
		self.client = Piwigo(log.source_url)
		self.host = urlparse(self.client.base).netloc
		self.lines = []
		self.counts = dict(albums_created=0, albums_updated=0, photos_created=0, photos_updated=0,
		                   keywords_created=0, error_count=0)
		self.album_by_cat = {}
		self.photo_by_img = {}
		self.extra_albums = {}
		self.download = (self.s.import_mode or "").startswith("Download")
		self.owner = self.s.import_owner or "Administrator"

	# ------------------------------------------------------------------ helpers

	def note(self, msg: str):
		self.lines.append(f"{now_datetime():%H:%M:%S} {msg}")

	def error(self, msg: str):
		self.counts["error_count"] += 1
		self.note(f"ERROR {msg}")

	def flush(self, status: str | None = None):
		vals = dict(self.counts, log="\n".join(self.lines[-2000:]))
		if status:
			vals["status"] = status
		frappe.db.set_value("Photo Import Log", self.log.name, vals, update_modified=False)
		frappe.db.commit()

	# ------------------------------------------------------------------ albums

	def import_albums(self):
		cats = self.client.call("pwg.categories.getList", recursive="true", fullname="false")["categories"]
		cats.sort(key=lambda c: (len(str(c.get("uppercats") or "").split(",")), str(c.get("global_rank") or "")))
		default_priv = self.s.default_privacy or "Public"
		self.cats = cats
		for c in cats:
			ref = f"{self.host}:cat:{c['id']}"
			parent = self.album_by_cat.get(str(c.get("id_uppercat") or "")) or self.log.root_album or None
			title = html.unescape(c.get("name_raw") or c.get("name") or f"Album {c['id']}").strip()
			desc = strip_html(html.unescape(c.get("comment_raw") or c.get("comment") or ""))
			rank = str(c.get("global_rank") or "0").split(".")[-1]
			privacy = default_priv if c.get("status", "public") == "public" else "Only Me"
			existing = frappe.db.get_value("Photo Album", {"source_ref": ref}, "name")
			if self.dry:
				self.album_by_cat[str(c["id"])] = existing or f"dry-{c['id']}"
				self.counts["albums_updated" if existing else "albums_created"] += 1
				continue
			if existing:
				doc = frappe.get_doc("Photo Album", existing)
				if self.overwrite:
					doc.title, doc.description = title, desc
				doc.parent_photo_album = parent
				doc.sort_order = cint(rank)
				doc.save(ignore_permissions=True)
				self.counts["albums_updated"] += 1
			else:
				doc = frappe.get_doc(
					{
						"doctype": "Photo Album",
						"title": title,
						"slug": unique_slug("Photo Album", "slug", title),
						"description": desc,
						"parent_photo_album": parent,
						"owner_user": self.owner,
						"privacy": privacy,
						"published": 1,
						"sort_order": cint(rank),
						"image_order": "Date taken (oldest first)",
						"source_ref": ref,
					}
				).insert(ignore_permissions=True)
				self.counts["albums_created"] += 1
			self.album_by_cat[str(c["id"])] = doc.name
		frappe.db.commit()
		self.note(f"{len(cats)} albums processed")

	# ------------------------------------------------------------------ photos

	def import_photos(self):
		for c in self.cats:
			if not cint(c.get("nb_images")):
				continue
			album = self.album_by_cat.get(str(c["id"]))
			n = shared = 0
			try:
				for img in self.client.paged("pwg.categories.getImages", cat_id=c["id"], order="id"):
					ref = f"{self.host}:img:{img['id']}"
					if ref in self.photo_by_img:
						if self.photo_by_img[ref] and album:
							self.extra_albums.setdefault(ref, set()).add(album)
						shared += 1
						continue
					try:
						# savepoint: a bad photo must not roll back the good ones since the last commit
						frappe.db.savepoint("esp_photo")
						self.photo_by_img[ref] = self.import_photo(img, album, ref)
					except Exception as e:
						frappe.db.rollback(save_point="esp_photo")
						self.photo_by_img[ref] = None
						self.error(f"photo {img.get('id')} ({img.get('file')}): {e}")
					n += 1
					if n % 50 == 0:
						frappe.db.commit()
						self.flush()
			except Exception as e:
				self.error(f"album {c.get('name')}: {e}")
			frappe.db.commit()
			self.note(f"{c.get('name')}: {n} photos" + (f" (+{shared} already imported from another album)" if shared else ""))
			self.flush()

	def import_photo(self, img: dict, album: str, ref: str) -> str | None:
		existing = frappe.db.get_value("Photo", {"source_ref": ref}, "name")
		if self.dry:
			self.counts["photos_updated" if existing else "photos_created"] += 1
			return existing or ref
		d = img.get("derivatives") or {}

		def url(*keys):
			for k in keys:
				u = (d.get(k) or {}).get("url")
				if u:
					return u
			return None

		file = img.get("file") or ""
		vm = VIDEO_FILE.match(file)
		video_url = None
		if vm:
			kind, vid = vm.group(1).lower(), vm.group(2)
			video_url = {
				"youtube": f"https://www.youtube.com/watch?v={vid}",
				"vimeo": f"https://vimeo.com/{vid}",
			}.get(kind)
		values = {
			"thumb_url": url("medium", "small", "thumb"),
			"medium_url": url("xlarge", "large", "medium"),
			"large_url": url("xxlarge", "xlarge", "large"),
			"original_url": img.get("element_url"),
			"width": cint(img.get("width")),
			"height": cint(img.get("height")),
			"date_taken": get_datetime(img["date_creation"]) if img.get("date_creation") else None,
			"date_added": get_datetime(img["date_available"]) if img.get("date_available") else now_datetime(),
		}
		title = html.unescape(img.get("name") or os.path.splitext(file)[0]).strip()
		desc = strip_html(html.unescape(img.get("comment") or ""))
		if desc == title:
			desc = ""

		if existing:
			doc = frappe.get_doc("Photo", existing)
			if not doc.image:  # don't overwrite locally stored renditions
				doc.update({k: v for k, v in values.items() if v})
			if self.overwrite:
				doc.title, doc.description = title, desc
			doc.view_count = max(cint(doc.view_count), cint(img.get("hit")))
			doc.flags.esp_skip_recount = True
			doc.save(ignore_permissions=True)
			self.counts["photos_updated"] += 1
			return doc.name

		doc = frappe.get_doc(
			{
				"doctype": "Photo",
				"album": album,
				"title": title,
				"description": desc,
				"media_type": "Video" if video_url else "Image",
				"video_url": video_url,
				"uploaded_by": self.owner,
				"view_count": cint(img.get("hit")),
				"source_ref": ref,
				**values,
			}
		)
		doc.flags.esp_skip_recount = True
		doc.flags.esp_skip_processing = True
		doc.insert(ignore_permissions=True)
		if self.download and not video_url:
			self.download_into_site(doc, img)
		self.counts["photos_created"] += 1
		return doc.name

	def download_into_site(self, doc, img):
		from es_photos.imaging import process_image_bytes

		d = img.get("derivatives") or {}
		src = img.get("element_url") if (self.s.download_size or "").startswith("Original") else (
			(d.get("xxlarge") or {}).get("url") or img.get("element_url")
		)
		r = self.client.s.get(src, timeout=120)
		r.raise_for_status()
		fname = os.path.basename(urlparse(img.get("element_url") or src).path) or f"{doc.name}.jpg"
		f = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": fname,
				"content": r.content,
				"is_private": 0,
				"attached_to_doctype": "Photo",
				"attached_to_name": doc.name,
				"attached_to_field": "image",
			}
		).save(ignore_permissions=True)
		values = process_image_bytes(doc, r.content)
		values.update({"image": f.file_url, "original_url": f.file_url})
		frappe.db.set_value("Photo", doc.name, values, update_modified=False)

	# ------------------------------------------------------------------ memberships, keywords, covers

	def apply_memberships(self):
		if self.dry:
			self.note(f"{len(self.extra_albums)} photos also appear in other albums")
			return
		for ref, albums in self.extra_albums.items():
			name = self.photo_by_img.get(ref)
			if not name:
				continue
			doc = frappe.get_doc("Photo", name)
			have = {r.album for r in doc.additional_albums} | {doc.album}
			new = [a for a in albums if a not in have]
			if not new:
				continue
			for a in new:
				doc.append("additional_albums", {"album": a})
			doc.flags.esp_skip_recount = True
			doc.save(ignore_permissions=True)
		frappe.db.commit()

	def import_keywords(self):
		if not cint(self.log.include_keywords):
			return
		tags = self.client.call("pwg.tags.getList")["tags"]
		for t in tags:
			kw = html.unescape(t.get("name_raw") or t.get("name") or "").strip()[:140]
			if not kw:
				continue
			if not frappe.db.exists("Photo Keyword", kw):
				self.counts["keywords_created"] += 1
				if not self.dry:
					frappe.get_doc(
						{"doctype": "Photo Keyword", "keyword_name": kw, "source_ref": f"{self.host}:tag:{t['id']}"}
					).insert(ignore_permissions=True)
			if self.dry:
				continue
			try:
				for img in self.client.paged("pwg.tags.getImages", tag_id=t["id"]):
					name = self.photo_by_img.get(f"{self.host}:img:{img['id']}") or frappe.db.get_value(
						"Photo", {"source_ref": f"{self.host}:img:{img['id']}"}, "name"
					)
					if not name:
						continue
					if frappe.db.exists("Photo Keyword Link", {"parent": name, "keyword": kw}):
						continue
					doc = frappe.get_doc("Photo", name)
					doc.append("keywords", {"keyword": kw})
					doc.flags.esp_skip_recount = True
					doc.flags.esp_skip_processing = True
					doc.save(ignore_permissions=True)
			except Exception as e:
				self.error(f"keyword {kw}: {e}")
			frappe.db.commit()
		self.note(f"{len(tags)} keywords processed")

	def apply_covers(self):
		if self.dry:
			return
		for c in self.cats:
			rep = c.get("representative_picture_id")
			album = self.album_by_cat.get(str(c["id"]))
			if not rep or not album:
				continue
			photo = self.photo_by_img.get(f"{self.host}:img:{rep}") or frappe.db.get_value(
				"Photo", {"source_ref": f"{self.host}:img:{rep}"}, "name"
			)
			if photo and not frappe.db.get_value("Photo Album", album, "cover_photo"):
				frappe.db.set_value("Photo Album", album, "cover_photo", photo, update_modified=False)
		frappe.db.commit()

	# ------------------------------------------------------------------ main

	def go(self):
		if self.s.piwigo_username:
			pwd = self.s.get_password("piwigo_password", raise_exception=False)
			if pwd:
				self.client.login(self.s.piwigo_username, pwd)
				self.note("Logged in to Piwigo")
		self.import_albums()
		self.flush()
		self.import_photos()
		self.apply_memberships()
		self.import_keywords()
		self.apply_covers()
		if not self.dry:
			recount_all()
		self.note("Done" + (" (dry run — nothing written)" if self.dry else ""))


def run(log_name: str):
	log = frappe.get_doc("Photo Import Log", log_name)
	frappe.db.set_value("Photo Import Log", log_name, {"status": "Running", "started_on": now_datetime(),
	                                                   "finished_on": None, "log": ""})
	frappe.db.commit()
	job = Run(log)
	try:
		job.go()
		job.flush("Completed")
	except Exception as e:
		frappe.db.rollback()
		job.error(str(e))
		job.flush("Failed")
		frappe.log_error(title=f"ES Photos import {log_name} failed")
	finally:
		frappe.db.set_value("Photo Import Log", log_name, "finished_on", now_datetime(), update_modified=False)
		frappe.db.commit()
