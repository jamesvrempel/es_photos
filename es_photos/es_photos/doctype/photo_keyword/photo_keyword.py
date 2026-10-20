# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from es_photos.utils import unique_slug


class PhotoKeyword(Document):
	def before_insert(self):
		self.keyword_name = (self.keyword_name or "").strip()
		if not self.slug:
			self.slug = unique_slug("Photo Keyword", "slug", self.keyword_name)

	def on_trash(self):
		frappe.db.delete("Photo Keyword Link", {"keyword": self.name})
