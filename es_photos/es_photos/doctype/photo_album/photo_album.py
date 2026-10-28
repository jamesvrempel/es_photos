# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

from es_photos.utils import unique_slug


class PhotoAlbum(NestedSet):
	nsm_parent_field = "parent_photo_album"

	def before_insert(self):
		if not self.slug:
			self.slug = unique_slug("Photo Album", "slug", self.title)
		if not self.owner_user:
			self.owner_user = frappe.session.user
		if not self.privacy:
			self.privacy = frappe.db.get_single_value("ES Photos Settings", "default_privacy") or "Public"

	def autoname(self):
		if not self.slug:
			self.slug = unique_slug("Photo Album", "slug", self.title)
		self.name = self.slug

	def validate(self):
		self.is_group = 1
		if self.privacy == "Group" and not self.social_group:
			frappe.throw(_("Choose the ES Social group that can see this album."))
		if self.privacy != "Group":
			self.social_group = None
		if self.parent_photo_album == self.name:
			frappe.throw(_("An album can't be its own parent."))
		if self.cover_photo and self.has_value_changed("cover_photo"):
			from es_photos.gallery import photo_src

			p = frappe.db.get_value(
				"Photo",
				self.cover_photo,
				["thumb_url", "medium_url", "large_url", "original_url", "image", "video_url", "media_type"],
				as_dict=True,
			)
			self.cover_url = photo_src(p, "thumb") if p else None

	def on_update(self):
		super().on_update()
		from es_photos.gallery import clear_gallery_cache

		clear_gallery_cache()

	def on_trash(self):
		if frappe.db.exists("Photo", {"album": self.name}):
			frappe.throw(_("Move or delete the photos in this album first."))
		frappe.db.delete("Photo Album Membership", {"album": self.name})
		super().on_trash(allow_root_deletion=True)
		from es_photos.gallery import clear_gallery_cache

		clear_gallery_cache()
