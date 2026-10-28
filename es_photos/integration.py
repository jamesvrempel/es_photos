"""Bridges into ES Social: feed posts, moderation rules, rate limits."""

import json
import re

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, escape_html, now_datetime

from es_photos.gallery import photo_src, social_settings

FEED_VISIBILITY = {"Public": "Public", "Connections": "Connections", "Group": "Group"}


def absolute(url: str | None) -> str | None:
	"""Site-relative URLs stay relative (ES Social renders them same-origin,
	which also keeps multi-domain sites right); remote URLs pass through."""
	return url or None


def _es(path: str):
	"""Resolve an ES Social helper, or None if this ES Social version lacks it."""
	try:
		return frappe.get_attr(path)
	except Exception:
		return None


def _create_social_post(
	content: str,
	media: list,
	visibility: str,
	group: str | None = None,
	link_url: str | None = None,
	link_title: str | None = None,
	link_image: str | None = None,
) -> str:
	"""Create a post through ES Social's own API (es_social.api.posts.create_post)
	so its login/suspension gate, rate limits, keyword hold, group membership
	checks, feed fan-out and notifications all apply. Falls back to inserting a
	Social Post directly only if that API isn't importable."""
	fn = _es("es_social.api.posts.create_post")
	if fn:
		args = {
			"content": content,
			"post_type": "Photo" if media else "Link",
			"visibility": visibility,
		}
		if media:
			args["media"] = json.dumps(media)
		if group:
			args["group"] = group
		if not media and link_url:
			args.update({"link_url": link_url, "link_title": link_title, "link_image": link_image})
		res = fn(**args)
		if isinstance(res, dict):
			return res.get("name") or res.get("post") or (res.get("data") or {}).get("name")
		return res

	profile = frappe.db.get_value("Social Profile", {"user": frappe.session.user}, "name")
	post = frappe.get_doc(
		{
			"doctype": "Social Post",
			"author": frappe.session.user,
			"author_profile": profile,
			"post_type": "Photo" if media else "Link",
			"visibility": visibility,
			"group": group,
			"content": content,
			"link_url": link_url,
			"link_title": link_title,
			"link_image": link_image,
			"approval_status": "Approved",
			"posted_on": now_datetime(),
			"media": [{"image": m["image"], "caption": m.get("caption"), "sort_order": i} for i, m in enumerate(media)],
		}
	)
	post.insert(ignore_permissions=True)
	return post.name


def require_login():
	"""ES Social's write gate (logged in + not suspended)."""
	fn = _es("es_social.social.utils.require_login")
	if fn:
		return fn()
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in or sign up to do that."), frappe.PermissionError)
	if frappe.db.get_value("Social Profile", {"user": frappe.session.user}, "suspended"):
		frappe.throw(_("Your account is suspended."), frappe.PermissionError)


def assert_not_blocked(other_user: str, msg: str | None = None):
	if not other_user or other_user == frappe.session.user:
		return
	fn = _es("es_social.social.moderation.assert_not_blocked")
	if fn:
		return fn(frappe.session.user, other_user, msg)
	if frappe.db.sql(
		"""SELECT 1 FROM `tabSocial Block` WHERE (blocker=%(a)s AND blocked=%(b)s)
		OR (blocker=%(b)s AND blocked=%(a)s) LIMIT 1""",
		{"a": frappe.session.user, "b": other_user},
	):
		frappe.throw(msg or _("You can't interact with this member."), frappe.PermissionError)


def share_photo(photo, album_row, message: str = "") -> str:
	vis = FEED_VISIBILITY.get(album_row.privacy or "Public")
	if not vis:
		frappe.throw(_("Photos in a private album can't be shared to the feed."))
	link = absolute(f"/social/gallery/photo/{photo.name}")
	body = f"<p>{escape_html(message)}</p>" if message else ""
	body += f'<p>📷 <a href="{link}">{escape_html(photo.title or _("View photo"))}</a> · {escape_html(album_row.title)}</p>'
	if photo.media_type == "Video":
		# a video shares as a link card (thumbnail + title) pointing at the gallery page
		media = []
	else:
		media = [{"image": absolute(photo_src(photo, "large")), "caption": photo.title}]
	post = _create_social_post(
		body,
		media,
		vis,
		album_row.social_group if vis == "Group" else None,
		link_url=link,
		link_title=photo.title or album_row.title,
		link_image=absolute(photo_src(photo, "thumb")),
	)
	if post:
		frappe.db.set_value("Photo", photo.name, "social_post", post, update_modified=False)
	return post


def post_album(album_row, photos: list, message: str = "") -> str:
	vis = FEED_VISIBILITY.get(album_row.privacy or "Public")
	if not vis:
		frappe.throw(_("Private albums can't be posted to the feed."))
	link = absolute(f"/social/gallery/album/{album_row.name}")
	n = cint(album_row.total_photo_count or album_row.photo_count)
	body = f"<p>{escape_html(message)}</p>" if message else ""
	body += (
		f'<p>🖼️ New album: <a href="{link}">{escape_html(album_row.title)}</a>'
		f" — {n} photo{'s' if n != 1 else ''}</p>"
	)
	media = [
		{"image": absolute(photo_src(p, "large")), "caption": p.title}
		for p in photos
		if p.media_type != "Video" and photo_src(p, "large")
	]
	post = _create_social_post(
		body,
		media,
		vis,
		album_row.social_group if vis == "Group" else None,
		link_url=link,
		link_title=album_row.title,
		link_image=absolute(album_row.cover_url),
	)
	if post:
		frappe.db.set_value("Photo Album", album_row.name, "social_post", post, update_modified=False)
	return post


def on_social_post_trash(doc, method=None):
	frappe.db.sql("UPDATE `tabPhoto Album` SET social_post=NULL WHERE social_post=%s", doc.name)
	frappe.db.sql("UPDATE `tabPhoto` SET social_post=NULL WHERE social_post=%s", doc.name)


# --------------------------------------------------------------------------- moderation


def check_text(text: str) -> str:
	"""ES Social's blocked-keyword filter. Returns the approval status for a
	comment: "Pending" when ES Social is set to "Hold for review", raises when
	set to "Reject", "Approved" when clean."""
	fn = _es("es_social.social.utils.check_content")
	if fn:
		return "Pending" if fn(text, allow_hold=True) else "Approved"
	ss = social_settings()
	words = [w.strip().lower() for w in re.split(r"[\n,]", ss.get("blocked_keywords") or "") if w.strip()]
	low = (text or "").lower()
	if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
		if (ss.get("keyword_action") or "Reject") == "Hold for review":
			return "Pending"
		frappe.throw(_("Your content contains language that isn't allowed here."))
	return "Approved"


def rate_limit_comments(user: str):
	per_min = cint(social_settings().get("comments_per_minute"))
	if not per_min:
		return
	fn = _es("es_social.social.utils.enforce_rate_limit")
	if fn:
		return fn("photo_comment", per_min)
	since = add_to_date(now_datetime(), minutes=-1)
	n = frappe.db.count("Photo Comment", {"author": user, "creation": (">", since)})
	if n >= per_min:
		frappe.throw(_("You're doing that too quickly. Please wait a moment and try again."))


def request_limit_bytes() -> int:
	"""Largest request Frappe accepts on es_photos.api.upload_photo.

	Frappe applies System Settings → Max File Size only to its own
	/api/method/upload_file; every other endpoint is capped by the site config
	key `max_file_size` (bytes), or 25 MB when that isn't set."""
	return cint(frappe.conf.get("max_file_size")) or 25 * 1024 * 1024


def max_upload_bytes() -> int:
	"""Largest photo the gallery accepts: the ES Photos / ES Social setting,
	but never more than Frappe will let through (less room for the form)."""
	mb = cint(frappe.db.get_single_value("ES Photos Settings", "max_upload_mb")) or cint(
		social_settings().get("max_upload_size_mb")
	)
	setting = (mb or 25) * 1024 * 1024
	return max(1024 * 1024, min(setting, request_limit_bytes() - 64 * 1024))
