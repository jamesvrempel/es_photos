# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""ES Photos Settings validation."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestSettings(FrappeTestCase):
	def _save(self, secs):
		s = frappe.get_single("ES Photos Settings")
		s.slideshow_seconds = secs
		s.save(ignore_permissions=True)
		return frappe.db.get_single_value("ES Photos Settings", "slideshow_seconds")

	def test_slideshow_seconds_clamped(self):
		self.assertEqual(self._save(8), 8)
		self.assertEqual(self._save(0), 5)      # empty -> default
		self.assertEqual(self._save(500), 120)  # upper bound
		self.assertEqual(self._save(-3), 5)

	def test_slideshow_seconds_reaches_page(self):
		import json

		from es_photos import gallery as G
		from es_photos.www.social import gallery as page

		self._save(9)
		frappe.set_user("Guest")
		G.reset_request_cache()
		try:
			frappe.local.form_dict = frappe._dict(gpath="")
			ctx = frappe._dict()
			page.get_context(ctx)
			self.assertEqual(json.loads(ctx.cfg_json)["slideshow_seconds"], 9)
		finally:
			frappe.set_user("Administrator")
			G.reset_request_cache()


class TestUploadLimit(FrappeTestCase):
	def _limit(self, setting_mb, conf_bytes):
		from es_photos.integration import max_upload_bytes

		frappe.db.set_single_value("ES Photos Settings", "max_upload_mb", setting_mb)
		old = frappe.conf.get("max_file_size")
		try:
			if conf_bytes is None:
				frappe.conf.pop("max_file_size", None)
			else:
				frappe.conf["max_file_size"] = conf_bytes
			return max_upload_bytes()
		finally:
			if old is None:
				frappe.conf.pop("max_file_size", None)
			else:
				frappe.conf["max_file_size"] = old

	def test_capped_by_frappe_request_limit(self):
		mb = 1024 * 1024
		# Frappe's 25 MB default caps a 100 MB setting (System Settings doesn't apply here)
		self.assertEqual(self._limit(100, None), 25 * mb - 64 * 1024)
		# raising max_file_size in the site config lifts the cap
		self.assertEqual(self._limit(100, 200 * mb), 100 * mb)
		self.assertEqual(self._limit(10, 200 * mb), 10 * mb)
		# site config values are often strings
		self.assertEqual(self._limit(60, str(100 * mb)), 60 * mb)
