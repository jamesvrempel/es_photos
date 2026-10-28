# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Uploading a photo that is already in the album is skipped."""

import io
import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from es_photos import api
from es_photos import gallery as G
from es_photos.tests.helpers import album, jpeg, user

OWNER = "esp_dup_owner@example.com"


class TestDuplicates(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		user(OWNER)
		frappe.db.set_single_value("ES Photos Settings", "max_upload_mb", 50)

	def setUp(self):
		frappe.set_user(OWNER)
		G.reset_request_cache()
		self._req = getattr(frappe.local, "request", None)
		frappe.set_user("Administrator")
		self.a = album(OWNER, "ESP Dup A")  # fresh albums for each test
		self.b = album(OWNER, "ESP Dup B")
		frappe.set_user(OWNER)

	def tearDown(self):
		frappe.local.request = self._req
		frappe.set_user("Administrator")
		G.reset_request_cache()

	def _upload(self, album_name, content, filename="DSCF0001.jpg"):
		env = EnvironBuilder(
			path="/api/method/es_photos.api.upload_photo",
			method="POST",
			data={"file": (io.BytesIO(content), filename), "album": album_name},
		).get_environ()
		frappe.local.request = Request(env)
		return api.upload_photo(album=album_name)

	def _count(self, album_name):
		return frappe.db.count("Photo", {"album": album_name, "is_deleted": 0})

	def test_same_content_is_skipped_in_same_album(self):
		pic = jpeg(900, 600)
		first = self._upload(self.a, pic)
		self.assertFalse(first.get("duplicate"))
		again = self._upload(self.a, pic, "renamed copy.jpg")  # name doesn't matter
		self.assertTrue(again.get("duplicate"))
		self.assertEqual(again["name"], first["name"])
		self.assertEqual(self._count(self.a), 1)

	def test_same_name_different_content_is_added(self):
		self._upload(self.b, jpeg(640, 480), "DSCF0002.jpg")
		res = self._upload(self.b, jpeg(641, 480), "DSCF0002.jpg")  # camera counter rolled over
		self.assertFalse(res.get("duplicate"))
		self.assertEqual(self._count(self.b), 2)

	def test_same_content_in_another_album_is_added(self):
		pic = jpeg(700, 500)
		self._upload(self.a, pic)
		res = self._upload(self.b, pic)
		self.assertFalse(res.get("duplicate"))

	def test_deleted_photo_does_not_block_reupload(self):
		pic = jpeg(720, 480)
		first = self._upload(self.a, pic)
		frappe.db.set_value("Photo", first["name"], "is_deleted", 1)
		res = self._upload(self.a, pic)
		self.assertFalse(res.get("duplicate"))
		self.assertNotEqual(res["name"], first["name"])
