# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PhotoReaction(Document):
	def validate(self):
		dup = frappe.db.exists(
			"Photo Reaction", {"photo": self.photo, "user": self.user, "name": ("!=", self.name)}
		)
		if dup:
			frappe.throw(_("Already reacted to this photo."))

	def on_update(self):
		self._recount()

	def after_delete(self):
		self._recount()

	def _recount(self):
		n = frappe.db.count("Photo Reaction", {"photo": self.photo})
		frappe.db.set_value("Photo", self.photo, "like_count", n, update_modified=False)
