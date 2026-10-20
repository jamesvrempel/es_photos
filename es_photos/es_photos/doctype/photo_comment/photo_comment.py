# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class PhotoComment(Document):
	def before_insert(self):
		if not self.posted_on:
			self.posted_on = now_datetime()

	def on_update(self):
		self._recount()

	def after_delete(self):
		self._recount()

	def _recount(self):
		n = frappe.db.count(
			"Photo Comment", {"photo": self.photo, "is_deleted": 0, "approval_status": "Approved"}
		)
		frappe.db.set_value("Photo", self.photo, "comment_count", n, update_modified=False)
