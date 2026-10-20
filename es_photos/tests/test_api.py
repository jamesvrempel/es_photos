# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Gallery endpoints: comments, moderation, reactions, feed sharing."""

import frappe
from frappe.tests.utils import FrappeTestCase

from es_photos import api
from es_photos import gallery as G
from es_photos.tests.helpers import album, photo, user

OWNER, FAN, OTHER = "esp_a_owner@example.com", "esp_a_fan@example.com", "esp_a_other@example.com"


def as_user(email):
	frappe.set_user(email)
	G.reset_request_cache()


class TestApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for u in (OWNER, FAN, OTHER):
			user(u)
		cls.public = album(OWNER, "ESP A Public")
		cls.private = album(OWNER, "ESP A Private", "Only Me")
		cls.pic = photo(cls.public, "Giant Tingle Tree", OWNER)
		cls.secret = photo(cls.private, "secret", OWNER)
		ss = frappe.get_single("ES Social Settings")
		cls._saved = {k: ss.get(k) for k in ("enable_profanity_filter", "blocked_keywords", "keyword_action", "comments_per_minute")}
		ss.update({"enable_profanity_filter": 1, "blocked_keywords": "espbadword", "keyword_action": "Reject", "comments_per_minute": 0})
		ss.save(ignore_permissions=True)
		s = frappe.get_single("ES Photos Settings")
		s.enable_comments = s.enable_reactions = 1
		s.save(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		ss = frappe.get_single("ES Social Settings")
		ss.update(cls._saved)
		ss.save(ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		as_user("Administrator")

	def test_guest_cannot_write(self):
		as_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.add_comment(self.pic, "hello")

	def test_comment_is_escaped_and_listed(self):
		as_user(FAN)
		c = api.add_comment(self.pic, "Nice <b>light</b>\nsecond line")
		self.assertIn("&lt;b&gt;", c["content"])
		as_user("Guest")
		self.assertIn(c["name"], [x["name"] for x in api.get_comments(self.pic)])

	def test_blocked_keyword_rejected(self):
		as_user(FAN)
		with self.assertRaises(frappe.ValidationError):
			api.add_comment(self.pic, "this has espbadword in it")

	def test_blocked_keyword_held_for_review(self):
		frappe.db.set_single_value("ES Social Settings", "keyword_action", "Hold for review")
		frappe.clear_document_cache("ES Social Settings", "ES Social Settings")
		try:
			as_user(FAN)
			c = api.add_comment(self.pic, "held espbadword")
			self.assertTrue(c["pending"])
			as_user(OTHER)  # others don't see a held comment
			self.assertNotIn(c["name"], [x["name"] for x in api.get_comments(self.pic)])
		finally:
			frappe.db.set_single_value("ES Social Settings", "keyword_action", "Reject")
			frappe.clear_document_cache("ES Social Settings", "ES Social Settings")

	def test_only_author_or_album_owner_can_delete(self):
		as_user(FAN)
		c = api.add_comment(self.pic, "delete me")
		as_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			api.delete_comment(c["name"])
		as_user(OWNER)
		self.assertEqual(api.delete_comment(c["name"]), "ok")

	def test_reaction_toggles(self):
		as_user(OTHER)
		r = api.react(self.pic, "Love")
		self.assertEqual(r["mine"], "Love")
		r = api.react(self.pic, "Love")
		self.assertIsNone(r["mine"])

	def test_private_photo_is_not_found(self):
		as_user(FAN)
		with self.assertRaises(frappe.DoesNotExistError):
			api.get_comments(self.secret)

	def test_share_public_photo_to_feed(self):
		as_user(FAN)
		res = api.share_to_feed(self.pic, "Look at this")
		post = frappe.get_doc("Social Post", res["post"])
		self.assertEqual(post.post_type, "Photo")
		self.assertIn(f"/social/gallery/photo/{self.pic}", post.content)

	def test_cannot_change_someone_elses_album(self):
		as_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			api.save_album("Hijack", name=self.public)
