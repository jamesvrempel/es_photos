# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Album photo order: gallery default vs. an album's own order."""

import frappe
from frappe.tests.utils import FrappeTestCase

from es_photos import api
from es_photos import gallery as G
from es_photos.tests.helpers import album, fresh_viewer, user


def _photo(album_name, title, taken, added):
	doc = frappe.get_doc(
		{"doctype": "Photo", "album": album_name, "title": title, "media_type": "Image",
		 "original_url": "/files/x.jpg", "date_taken": taken, "date_added": added}
	)
	doc.flags.esp_skip_processing = True
	return doc.insert(ignore_permissions=True).name


class TestSorting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		owner = user("esp_s_owner@example.com")
		cls.album = album(owner, "ESP S Album")
		# taken order: old -> new is A, B, C ; added order is the reverse
		cls.a = _photo(cls.album, "A", "2020-01-01 10:00:00", "2026-03-03 10:00:00")
		cls.b = _photo(cls.album, "B", "2022-01-01 10:00:00", "2026-02-02 10:00:00")
		cls.c = _photo(cls.album, "C", "2024-01-01 10:00:00", "2026-01-01 10:00:00")

	def setUp(self):
		frappe.db.set_single_value("ES Photos Settings", "default_album_order", "Date taken (newest first)")
		frappe.db.set_value("Photo Album", self.album, "image_order", None)
		frappe.clear_document_cache("ES Photos Settings", "ES Photos Settings")
		G.reset_request_cache()

	def titles(self, **kw):
		return [r.title for r in G.photo_query(fresh_viewer("Guest"), albums=[self.album], limit=10, **kw)]

	def test_album_without_own_order_uses_gallery_default(self):
		row = G.album_map()[self.album]
		self.assertEqual(G.album_order(row), "Date taken (newest first)")
		self.assertEqual(self.titles(order=G.album_order(row)), ["C", "B", "A"])

	def test_album_own_order_wins(self):
		frappe.db.set_value("Photo Album", self.album, "image_order", "Date added (newest first)")
		G.reset_request_cache()
		row = G.album_map()[self.album]
		self.assertEqual(self.titles(order=G.album_order(row)), ["A", "B", "C"])

	def test_slideshow_follows_default(self):
		frappe.set_user("Guest")
		try:
			self.assertEqual([x["title"] for x in api.slideshow(album=self.album)], ["C", "B", "A"])
		finally:
			frappe.set_user("Administrator")

	def test_changing_gallery_default(self):
		frappe.db.set_single_value("ES Photos Settings", "default_album_order", "Title")
		frappe.clear_document_cache("ES Photos Settings", "ES Photos Settings")
		self.assertEqual(G.default_order(), "Title")
