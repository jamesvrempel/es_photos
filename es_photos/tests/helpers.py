# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Shared fixtures for the ES Photos tests (test sites only)."""

import io

import frappe
from PIL import Image

PW = "Es-Photos-Test-1!"


def user(email, roles=("Social User",)):
	if not frappe.db.exists("User", email):
		u = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"user_type": "Website User",
				"send_welcome_email": 0,
				"new_password": PW,
			}
		).insert(ignore_permissions=True)
		u.add_roles(*roles)
	return email


def jpeg(w=1200, h=800, exif=True) -> bytes:
	img = Image.new("RGB", (w, h), (40, 120, 90))
	ex = Image.Exif()
	if exif:
		ex[0x010F] = "FUJIFILM"
		ex[0x0110] = "X-T5"
		sub = ex.get_ifd(0x8769)
		sub[0x9003] = "2026:03:14 10:20:30"
		sub[0x829D] = 5.6
		sub[0x829A] = 1 / 250
		sub[0x8827] = 200
	buf = io.BytesIO()
	img.save(buf, "JPEG", quality=80, exif=ex)
	return buf.getvalue()


def album(owner, title, privacy="Public", group=None, parent=None):
	doc = frappe.get_doc(
		{
			"doctype": "Photo Album",
			"title": title,
			"owner_user": owner,
			"privacy": privacy,
			"social_group": group,
			"parent_photo_album": parent,
			"published": 1,
		}
	).insert(ignore_permissions=True)
	return doc.name


def photo(album_name, title="t", owner="Administrator"):
	doc = frappe.get_doc(
		{
			"doctype": "Photo",
			"album": album_name,
			"title": title,
			"media_type": "Image",
			"original_url": "/files/es_photos_test.jpg",
			"uploaded_by": owner,
		}
	)
	doc.flags.esp_skip_processing = True
	doc.insert(ignore_permissions=True)
	return doc.name


def fresh_viewer(email):
	"""A Viewer for *email* with request and ES Social caches cleared."""
	from es_photos import gallery as G
	from es_photos import social as S

	G.reset_request_cache()
	for fn in ("es_social.social.utils.clear_connection_cache", "es_social.social.moderation.clear_block_cache"):
		f = S.es(fn)
		if f:
			f(email)
	return G.Viewer(email)
