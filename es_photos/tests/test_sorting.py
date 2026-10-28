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


class TestAlbumOrder(FrappeTestCase):
	def _rows(self):
		mk = lambda t, c, d=None, so=0: frappe._dict(title=t, creation=c, date_last=d, sort_order=so)  # noqa: E731
		return [
			mk("walpole-mtb.com", "2026-01-03", "2026-10-01", 3),
			mk("Avon National Park WA", "2026-10-27", "2026-10-27", 0),
			mk("Trip 10", "2026-01-01", None, 1),
			mk("Trip 2", "2026-01-02", "2026-05-01", 2),
			mk("albany WA", "2026-02-01", "2026-03-01", 5),
		]

	def test_orders(self):
		from es_photos import gallery as G

		titles = lambda rows: [r.title for r in rows]  # noqa: E731
		rows = self._rows()
		self.assertEqual(
			titles(G.sort_albums(rows, "Name (A to Z)")),
			["albany WA", "Avon National Park WA", "Trip 2", "Trip 10", "walpole-mtb.com"],
		)
		self.assertEqual(titles(G.sort_albums(rows, "Name (Z to A)"))[0], "walpole-mtb.com")
		self.assertEqual(titles(G.sort_albums(rows, "Recently updated"))[:2], ["Avon National Park WA", "walpole-mtb.com"])
		self.assertEqual(titles(G.sort_albums(rows, "Newest albums first"))[0], "Avon National Park WA")
		self.assertEqual(titles(G.sort_albums(rows, "Manual (sort order)"))[:2], ["Avon National Park WA", "Trip 10"])

	def test_setting_and_visitor_choice(self):
		from es_photos import gallery as G

		s = frappe.get_single("ES Photos Settings")
		old = s.album_order
		try:
			s.album_order = "Manual (sort order)"
			s.save(ignore_permissions=True)
			self.assertEqual(G.album_list_order(), "Manual (sort order)")
			self.assertEqual(G.album_list_order("name-desc"), "Name (Z to A)")  # ?asort= wins
			self.assertEqual(G.album_list_order("bogus"), "Manual (sort order)")
			s.album_order = ""
			s.save(ignore_permissions=True)
			self.assertEqual(G.album_list_order(), "Name (A to Z)")  # unset -> A to Z
		finally:
			s.album_order = old
			s.save(ignore_permissions=True)
