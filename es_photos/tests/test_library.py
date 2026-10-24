# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Folder import and copying linked photos in."""

import os
import shutil
import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from es_photos import gallery as G
from es_photos import library as L
from es_photos.tests.helpers import album, fresh_viewer, jpeg


def _job(**kw):
	return frappe.get_doc(
		dict({"doctype": L.DOCTYPE, "job_type": "Import folder", "album_owner": "Administrator", "privacy": "Public",
			  "hide_missing": 1}, **kw)
	).insert(ignore_permissions=True)


def _write(path, content):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "wb") as f:
		f.write(content)


class TestLibrary(FrappeTestCase):
	def setUp(self):
		self.sub = f"esp_t_{uuid.uuid4().hex[:8]}"
		self.base = os.path.join(L.library_root(), self.sub)
		_write(os.path.join(self.base, "Trip A", "a1.JPG"), jpeg(1800, 1200))
		_write(os.path.join(self.base, "Trip A", "Day_2", "a2.jpg"), jpeg(1200, 1800))
		_write(os.path.join(self.base, "Trip A", ".DS_Store"), b"x")
		_write(os.path.join(self.base, "Trip A", "._a1.JPG"), b"x")
		_write(os.path.join(self.base, "Trip A", "@eaDir", "thumb.jpg"), jpeg(100, 100))
		_write(os.path.join(self.base, "Trip A", "clip.mov"), b"x")
		_write(os.path.join(self.base, "Café 50%", "c1.jpg"), jpeg(900, 600))

	def tearDown(self):
		shutil.rmtree(self.base, ignore_errors=True)
		G.reset_request_cache()

	def _import(self, **kw):
		job = _job(source_folder=self.sub, **kw)
		names = L.scan_folder(job)
		if not kw.get("dry_run"):
			L.process_batch(job.name, names, "render")
		return frappe.get_doc(L.DOCTYPE, job.name), names

	def test_import_builds_albums_and_photos(self):
		job, names = self._import()
		self.assertEqual(len(names), 3)  # junk, @eaDir, ._ files and the video are ignored
		self.assertEqual(job.photos_created, 3)
		self.assertEqual(job.rendered, 3)
		refs = frappe.get_all("Photo Album", {"source_ref": ("like", f"{L.DIR_REF}{self.sub}%")}, pluck="source_ref")
		self.assertIn(f"{L.DIR_REF}{self.sub}/Trip A/Day_2", refs)
		day2 = frappe.db.get_value("Photo Album", {"source_ref": f"{L.DIR_REF}{self.sub}/Trip A/Day_2"}, ["title", "parent_photo_album"], as_dict=True)
		self.assertEqual(day2.title, "Day 2")
		trip = frappe.db.get_value("Photo Album", {"source_ref": f"{L.DIR_REF}{self.sub}/Trip A"}, "name")
		self.assertEqual(day2.parent_photo_album, trip)
		p = frappe.db.get_value("Photo", {"source_ref": f"{L.REF}{self.sub}/Trip A/a1.JPG"},
			["original_url", "thumb_url", "width", "height", "camera_model", "image"], as_dict=True)
		self.assertTrue(p.original_url.startswith("/files/es_photos/library/"))
		self.assertTrue(os.path.isfile(L.path_for_url(p.original_url)))  # original stays in place
		self.assertTrue(p.thumb_url and p.thumb_url.startswith("/files/es_photos/"))
		self.assertEqual((p.width, p.height, p.camera_model), (1800, 1200, "X-T5"))
		self.assertFalse(p.image)  # no File record for library photos
		cafe = frappe.db.get_value("Photo", {"source_ref": f"{L.REF}{self.sub}/Café 50%/c1.jpg"}, "original_url")
		self.assertIn("Caf%C3%A9%2050%25", cafe)  # URL-safe
		self.assertTrue(os.path.isfile(L.path_for_url(cafe)))

	def test_rerun_only_processes_new_or_changed(self):
		self._import()
		job, names = self._import()
		self.assertEqual(names, [])
		self.assertEqual(job.photos_skipped, 3)
		_write(os.path.join(self.base, "Trip A", "a1.JPG"), jpeg(2000, 1000))  # changed file
		_write(os.path.join(self.base, "Trip A", "a3.jpg"), jpeg(800, 600))  # new file
		job, names = self._import()
		self.assertEqual((job.photos_created, job.photos_updated, len(names)), (1, 1, 2))
		w = frappe.db.get_value("Photo", {"source_ref": f"{L.REF}{self.sub}/Trip A/a1.JPG"}, "width")
		self.assertEqual(w, 2000)

	def test_removed_file_is_hidden_and_comes_back(self):
		self._import()
		ref = f"{L.REF}{self.sub}/Café 50%/c1.jpg"
		path = os.path.join(self.base, "Café 50%", "c1.jpg")
		data = open(path, "rb").read()
		os.remove(path)
		job, _ = self._import()
		self.assertEqual(job.photos_hidden, 1)
		self.assertEqual(frappe.db.get_value("Photo", {"source_ref": ref}, "is_deleted"), 1)
		_write(path, data)
		self._import()
		self.assertEqual(frappe.db.get_value("Photo", {"source_ref": ref}, "is_deleted"), 0)

	def test_unprocessed_photos_are_not_shown(self):
		job = _job(source_folder=self.sub)
		L.scan_folder(job)  # records only, no thumbnails yet
		trip = frappe.db.get_value("Photo Album", {"source_ref": f"{L.DIR_REF}{self.sub}/Trip A"}, "name")
		self.assertEqual(G.photo_query(fresh_viewer("Guest"), albums=[trip], count=True), 0)
		L.process_batch(job.name, frappe.get_all("Photo", {"album": trip}, pluck="name"), "render")
		self.assertEqual(G.photo_query(fresh_viewer("Guest"), albums=[trip], count=True), 1)

	def test_dry_run_changes_nothing(self):
		job, names = self._import(dry_run=1)
		self.assertEqual(len(names), 3)
		self.assertFalse(frappe.db.exists("Photo", {"source_ref": ("like", f"{L.REF}{self.sub}%")}))
		self.assertFalse(frappe.db.exists("Photo Album", {"source_ref": ("like", f"{L.DIR_REF}{self.sub}%")}))

	def test_subfolder_must_stay_inside_library(self):
		for bad in ("../../site_config.json", "a/../../b", ".."):
			with self.assertRaises(frappe.ValidationError):
				L.safe_subfolder(bad)
		self.assertEqual(L.safe_subfolder(" /Trip A/Day 2/ "), "Trip A/Day 2")
		self.assertEqual(L.safe_subfolder("/etc"), "etc")  # always relative to the library

	def test_cancel_stops_batch(self):
		job = _job(source_folder=self.sub)
		names = L.scan_folder(job)
		frappe.db.set_value(L.DOCTYPE, job.name, {"cancel_requested": 1, "batches_total": 1})
		L.process_batch(job.name, names, "render")
		j = frappe.get_doc(L.DOCTYPE, job.name)
		self.assertEqual((j.rendered, j.status), (0, "Cancelled"))


class TestCopyLinked(FrappeTestCase):
	def test_copy_linked_photo_into_site(self):
		a = album("Administrator", "ESP L Linked")
		doc = frappe.get_doc(
			{"doctype": "Photo", "album": a, "title": "remote", "media_type": "Image",
			 "original_url": "https://photos.example.com/galleries/Trip/IMG_1.jpg",
			 "large_url": "https://photos.example.com/_data/i/IMG_1-xx.jpg",
			 "thumb_url": "https://photos.example.com/_data/i/IMG_1-me.jpg"}
		)
		doc.flags.esp_skip_processing = True
		doc.insert(ignore_permissions=True)
		self.assertIn(doc.name, L.linked_photo_names())
		with patch.object(L, "_download", return_value=jpeg(2400, 1600)) as dl:
			L.copy_linked_photo(doc.name, "Original (full size)")
		dl.assert_called_once_with("https://photos.example.com/galleries/Trip/IMG_1.jpg")
		p = frappe.db.get_value("Photo", doc.name, ["image", "original_url", "thumb_url", "large_url", "width"], as_dict=True)
		self.assertTrue(p.image.startswith("/files/es_photos/originals/"))
		self.assertEqual(p.original_url, p.image)
		self.assertTrue(p.thumb_url.startswith("/files/es_photos/") and p.large_url.startswith("/files/es_photos/"))
		self.assertEqual(p.width, 2400)
		self.assertNotIn(doc.name, L.linked_photo_names())  # done; re-runs skip it

	def test_large_copy_option_downloads_large(self):
		a = album("Administrator", "ESP L Linked 2")
		doc = frappe.get_doc(
			{"doctype": "Photo", "album": a, "title": "remote2", "media_type": "Image",
			 "original_url": "https://photos.example.com/o.png", "large_url": "https://photos.example.com/o.png",
			 "medium_url": "https://photos.example.com/xl.jpg"}
		)
		doc.flags.esp_skip_processing = True
		doc.insert(ignore_permissions=True)
		with patch.object(L, "_download", return_value=jpeg(1656, 1104)) as dl:
			L.copy_linked_photo(doc.name, "Large copy only (about 1200-1600 px)")
		dl.assert_called_once_with("https://photos.example.com/xl.jpg")  # not the original


class TestRelinkLocal(FrappeTestCase):
	def test_url_mapping(self):
		f = L.local_path_for_remote
		self.assertEqual(f("https://p.example.com/galleries/A%20B/x.png", "piwigo"), "piwigo/galleries/A B/x.png")
		self.assertEqual(f("https://p.example.com/upload/2026/05/06/y.jpg", "piwigo"), "piwigo/upload/2026/05/06/y.jpg")
		self.assertEqual(f("https://p.example.com/_data/i/galleries/A/x-me.png", "piwigo"), "piwigo/_data/i/galleries/A/x-me.png")
		self.assertEqual(f("https://p.example.com/i.php?/galleries/A/x-xl.png", "piwigo"), "piwigo/_data/i/galleries/A/x-xl.png")
		self.assertIsNone(f("/files/local.jpg", "piwigo"))
		self.assertIsNone(f("https://p.example.com/../../etc/passwd", "piwigo"))

	def test_relink_switches_found_photos_and_leaves_missing(self):
		folder = f"esp_r_{uuid.uuid4().hex[:8]}"
		base = os.path.join(L.library_root(), folder)
		try:
			_write(os.path.join(base, "galleries", "Trip", "a.jpg"), jpeg(1600, 1000))
			_write(os.path.join(base, "_data", "i", "galleries", "Trip", "a-me.jpg"), jpeg(400, 250))
			a = album("Administrator", "ESP R Album")

			def remote(title, fn):
				d = frappe.get_doc(
					{"doctype": "Photo", "album": a, "title": title, "media_type": "Image",
					 "original_url": f"https://p.example.com/galleries/Trip/{fn}",
					 "thumb_url": f"https://p.example.com/_data/i/galleries/Trip/{fn.replace('.jpg', '-me.jpg')}"}
				)
				d.flags.esp_skip_processing = True
				return d.insert(ignore_permissions=True).name

			found, missing = remote("found", "a.jpg"), remote("missing", "zz.jpg")
			job = frappe.get_doc(
				{"doctype": L.DOCTYPE, "job_type": "Copy linked photos in", "copy_source": "Use files already on this server",
				 "local_folder": folder}
			).insert(ignore_permissions=True)
			names = L.relink_local(job)
			self.assertIn(found, names)
			self.assertNotIn(missing, names)
			p = frappe.db.get_value("Photo", found, ["original_url", "thumb_url"], as_dict=True)
			self.assertEqual(p.original_url, L.url_for(f"{folder}/galleries/Trip/a.jpg"))
			self.assertEqual(p.thumb_url, L.url_for(f"{folder}/_data/i/galleries/Trip/a-me.jpg"))  # usable at once
			self.assertTrue(frappe.db.get_value("Photo", missing, "original_url").startswith("https://"))
			L.process_batch(job.name, names, "render")  # proper ES Photos copies + EXIF
			p = frappe.db.get_value("Photo", found, ["thumb_url", "width", "camera_model"], as_dict=True)
			self.assertTrue(p.thumb_url.endswith("-th.jpg"))
			self.assertEqual((p.width, p.camera_model), (1600, "X-T5"))
			# a later folder import doesn't create a second photo for the same file
			imp = frappe.get_doc(
				{"doctype": L.DOCTYPE, "job_type": "Import folder", "source_folder": folder, "album_owner": "Administrator"}
			).insert(ignore_permissions=True)
			self.assertEqual(L.scan_folder(imp), [])
		finally:
			shutil.rmtree(base, ignore_errors=True)
