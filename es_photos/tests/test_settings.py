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
