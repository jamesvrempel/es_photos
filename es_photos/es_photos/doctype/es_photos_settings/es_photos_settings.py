# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import cint

SLIDESHOW_MIN, SLIDESHOW_MAX, SLIDESHOW_DEFAULT = 1, 120, 5


class ESPhotosSettings(Document):
	def validate(self):
		secs = cint(self.slideshow_seconds)
		if secs < SLIDESHOW_MIN:  # empty, zero or negative -> default
			secs = SLIDESHOW_DEFAULT
		self.slideshow_seconds = min(secs, SLIDESHOW_MAX)
