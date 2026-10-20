# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Album/photo visibility — the place a private photo leak would come from.

Run on a TEST site only:  bench --site <test-site> run-tests --app es_photos
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from es_photos import gallery as G
from es_photos.tests.helpers import album, fresh_viewer, photo, user

OWNER, FRIEND, MEMBER, STRANGER, BLOCKED, MANAGER = (
	"esp_t_owner@example.com",
	"esp_t_friend@example.com",
	"esp_t_member@example.com",
	"esp_t_stranger@example.com",
	"esp_t_blocked@example.com",
	"esp_t_manager@example.com",
)
GROUP = "esp-t-hikers"


class TestPrivacy(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for u in (OWNER, FRIEND, MEMBER, STRANGER, BLOCKED):
			user(u)
		user(MANAGER, roles=("Social User", "Gallery Manager"))
		if not frappe.db.exists("Social Connection", {"from_user": OWNER, "to_user": FRIEND}):
			frappe.get_doc(
				{"doctype": "Social Connection", "from_user": OWNER, "to_user": FRIEND, "status": "Accepted"}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Social Group", GROUP):
			frappe.get_doc(
				{"doctype": "Social Group", "group_name": "ESP Hikers", "slug": GROUP, "privacy": "Closed",
				 "created_by": "Administrator"}
			).insert(ignore_permissions=True)
		for u in (OWNER, MEMBER):
			if not frappe.db.exists("Social Group Member", {"group": GROUP, "user": u}):
				frappe.get_doc(
					{"doctype": "Social Group Member", "group": GROUP, "user": u, "status": "Active", "role": "Member"}
				).insert(ignore_permissions=True)
		if not frappe.db.exists("Social Block", {"blocker": OWNER, "blocked": BLOCKED}):
			frappe.get_doc({"doctype": "Social Block", "blocker": OWNER, "blocked": BLOCKED}).insert(
				ignore_permissions=True
			)
		cls.public = album(OWNER, "ESP T Public")
		cls.conn = album(OWNER, "ESP T Connections", "Connections")
		cls.grp = album(OWNER, "ESP T Group", "Group", GROUP)
		cls.private = album(OWNER, "ESP T Private", "Only Me")
		cls.inside_private = album(OWNER, "ESP T Inside Private", "Public", parent=cls.private)
		cls.p_private = photo(cls.private, "secret")
		cls.p_shared = photo(cls.private, "also public")
		doc = frappe.get_doc("Photo", cls.p_shared)
		doc.append("additional_albums", {"album": cls.public})
		doc.flags.esp_skip_processing = True
		doc.save(ignore_permissions=True)

	def sees(self, who, album_name):
		return album_name in G.visible_albums(fresh_viewer(who))

	def test_public(self):
		for who in ("Guest", FRIEND, STRANGER, OWNER):
			self.assertTrue(self.sees(who, self.public), who)

	def test_connections(self):
		self.assertTrue(self.sees(FRIEND, self.conn))
		self.assertFalse(self.sees(STRANGER, self.conn))
		self.assertFalse(self.sees("Guest", self.conn))

	def test_group(self):
		self.assertTrue(self.sees(MEMBER, self.grp))
		self.assertFalse(self.sees(FRIEND, self.grp))
		self.assertFalse(self.sees("Guest", self.grp))

	def test_only_me(self):
		self.assertTrue(self.sees(OWNER, self.private))
		self.assertFalse(self.sees(FRIEND, self.private))
		self.assertTrue(self.sees(MANAGER, self.private))

	def test_child_of_private_album_is_hidden(self):
		self.assertFalse(self.sees(STRANGER, self.inside_private))
		self.assertTrue(self.sees(OWNER, self.inside_private))

	def test_block_hides_everything(self):
		self.assertFalse(self.sees(BLOCKED, self.public))

	def test_unpublished(self):
		frappe.db.set_value("Photo Album", self.public, "published", 0)
		try:
			self.assertFalse(self.sees(STRANGER, self.public))
			self.assertTrue(self.sees(OWNER, self.public))
		finally:
			frappe.db.set_value("Photo Album", self.public, "published", 1)

	def test_photo_visibility_follows_albums(self):
		v = fresh_viewer(STRANGER)
		self.assertEqual(G.photo_visible(self.p_private, v), (None, None))
		doc, shown_in = G.photo_visible(self.p_shared, fresh_viewer(STRANGER))
		self.assertIsNotNone(doc)
		self.assertEqual(shown_in.name, self.public)  # reachable only through the public album
		ids = [r.name for r in G.photo_query(fresh_viewer("Guest"), limit=500)]
		self.assertNotIn(self.p_private, ids)
		self.assertIn(self.p_shared, ids)

	def test_upload_rights(self):
		self.assertFalse(fresh_viewer("Guest").can_upload())
		self.assertTrue(fresh_viewer(STRANGER).can_upload())
		frappe.db.set_value("Social Profile", {"user": STRANGER}, "suspended", 1)
		try:
			self.assertFalse(fresh_viewer(STRANGER).can_upload())
		finally:
			frappe.db.set_value("Social Profile", {"user": STRANGER}, "suspended", 0)

	def test_group_album_needs_group(self):
		with self.assertRaises(frappe.ValidationError):
			album(OWNER, "ESP T Bad Group", "Group")
