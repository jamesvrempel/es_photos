"""Thin bridge to ES Social internals.

Every helper resolves the ES Social implementation first, so the gallery
always agrees with ES Social about who is connected, blocked, suspended or a
moderator. The fallbacks only exist so an older/newer ES Social with a
renamed helper degrades gracefully instead of breaking the gallery.
"""

import frappe
from frappe.utils import cint, get_datetime, now_datetime

GUEST = "Guest"


def es(path: str):
	"""Return an ES Social callable by dotted path, or None."""
	try:
		return frappe.get_attr(path)
	except Exception:
		return None


def connection_ids(user: str) -> set:
	if user == GUEST:
		return set()
	fn = es("es_social.social.utils.get_connection_ids")
	if fn:
		return set(fn(user))
	rows = frappe.db.sql(
		"""SELECT IF(from_user=%(u)s, to_user, from_user) FROM `tabSocial Connection`
		WHERE status='Accepted' AND (from_user=%(u)s OR to_user=%(u)s)""",
		{"u": user},
	)
	return {r[0] for r in rows}


def group_ids(user: str) -> set:
	if user == GUEST:
		return set()
	fn = es("es_social.social.utils.get_group_ids")
	if fn:
		return set(fn(user))
	return set(frappe.get_all("Social Group Member", {"user": user, "status": "Active"}, pluck="group"))


def block_ids(user: str) -> set:
	if user == GUEST:
		return set()
	fn = es("es_social.social.moderation.get_block_ids")
	if fn:
		return set(fn(user))
	rows = frappe.db.sql(
		"""SELECT blocked FROM `tabSocial Block` WHERE blocker=%(u)s
		UNION SELECT blocker FROM `tabSocial Block` WHERE blocked=%(u)s""",
		{"u": user},
	)
	return {r[0] for r in rows if r[0]}


def is_suspended(user: str) -> bool:
	if user in (GUEST, "Administrator"):
		return False
	fn = es("es_social.social.moderation.is_suspended")
	if fn:
		return bool(fn(user))
	row = frappe.db.get_value("Social Profile", {"user": user}, ["suspended", "suspended_until"], as_dict=True)
	if not row or not cint(row.suspended):
		return False
	return not (row.suspended_until and get_datetime(row.suspended_until) <= now_datetime())


def is_moderator(user: str) -> bool:
	"""ES Social moderator/admin (can remove anyone's gallery comments)."""
	if user == GUEST:
		return False
	fn = es("es_social.social.moderation.is_privileged")
	if fn:
		return bool(fn(user))
	return user == "Administrator" or bool(
		{"System Manager", "Social Moderator", "Social Admin"} & set(frappe.get_roles(user))
	)


def page_context(context, path: str):
	"""Run ES Social's page guard and fill the shared page context
	(is_guest, es_brand, es_v, es_flags, signup_url, login_providers) so the
	gallery renders the same top bar as every other /social page."""
	guard = es("es_social.social.utils.guard_page")
	apply = es("es_social.social.utils.apply_guest_context")
	if guard:
		guard(path)
	elif frappe.session.user == GUEST:
		ss = social_settings()
		if ss.get("allow_guest_browsing") is not None and not cint(ss.get("allow_guest_browsing")):
			frappe.local.flags.redirect_location = f"/login?redirect-to={path}"
			raise frappe.Redirect
	if apply:
		apply(context)
	else:
		ss = social_settings()
		context.is_guest = frappe.session.user == GUEST
		context.signup_url = ss.get("signup_url") or "/login#signup"
		context.es_brand = ss.get("brand_name") or "ES Social"
		context.es_v = "0"
		context.login_providers = []
		context.es_flags = {"groups": True, "pages": cint(ss.get("enable_pages")), "messaging": False}
	# nav links contributed by other apps (es_social >= 0.9.7 renders these itself)
	if context.get("es_nav_links") is None:
		context.es_nav_links = nav_links()
	return context


def nav_links() -> list:
	out = []
	for item in frappe.get_hooks("es_social_nav_links") or []:
		if isinstance(item, dict) and item.get("route"):
			out.append(item)
	return out


def social_settings():
	try:
		return frappe.get_cached_doc("ES Social Settings")
	except Exception:
		return frappe._dict()
