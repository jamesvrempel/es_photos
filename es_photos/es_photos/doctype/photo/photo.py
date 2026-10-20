# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from es_photos.utils import video_thumb, video_embed


class Photo(Document):
	def before_insert(self):
		if not self.date_added:
			self.date_added = now_datetime()
		if not self.uploaded_by:
			self.uploaded_by = frappe.session.user

	def validate(self):
		if not self.title:
			src = self.image or self.original_url or ""
			base = os.path.splitext(os.path.basename(src.split("?")[0]))[0]
			self.title = base.replace("_", " ").replace("-", " ").strip() or _("Untitled")
		if self.media_type == "Video":
			if not self.video_url:
				frappe.throw(_("Add the video link."))
			if not video_embed(self.video_url):
				frappe.throw(_("Only YouTube and Vimeo links are supported."))
			if not self.thumb_url:
				self.thumb_url = video_thumb(self.video_url)
		elif not (self.image or self.original_url or self.large_url or self.medium_url):
			frappe.throw(_("Attach an image."))
		# don't list the primary album again under "also show in"
		self.additional_albums = [r for r in self.additional_albums if r.album and r.album != self.album]
		seen = set()
		self.keywords = [r for r in self.keywords if r.keyword and not (r.keyword in seen or seen.add(r.keyword))]

	def on_update(self):
		if self.image and self.has_value_changed("image") and self.image.startswith("/files/"):
			from es_photos.imaging import process_local_image

			if not self.flags.esp_skip_processing:
				process_local_image(self)
		if not self.flags.esp_skip_recount:
			from es_photos.gallery import recount_for_photo

			before = self.get_doc_before_save()
			recount_for_photo(self, old_album=before.album if before else None)

	def on_trash(self):
		from es_photos.imaging import delete_renditions

		delete_renditions(self.name)
		frappe.db.delete("Photo Reaction", {"photo": self.name})
		frappe.db.delete("Photo Comment", {"photo": self.name})
		for album in frappe.get_all("Photo Album", filters={"cover_photo": self.name}, pluck="name"):
			frappe.db.set_value("Photo Album", album, {"cover_photo": None, "cover_url": None})

	def after_delete(self):
		from es_photos.gallery import recount_album_and_ancestors

		recount_album_and_ancestors(self.album)
		for r in self.additional_albums:
			recount_album_and_ancestors(r.album)
