import frappe

ROLE = "Gallery Manager"


def after_install():
	ensure_role()
	ensure_settings()


def after_migrate():
	ensure_role()


def ensure_role():
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": ROLE, "desk_access": 1, "is_custom": 0}
		).insert(ignore_permissions=True)


def ensure_settings():
	s = frappe.get_single("ES Photos Settings")
	defaults = {
		"gallery_title": "Gallery",
		"photos_per_page": 48,
		"slideshow_seconds": 5,
		"default_privacy": "Public",
		"allow_member_albums": 1,
		"enable_downloads": 1,
		"show_exif": 1,
		"enable_comments": 1,
		"enable_reactions": 1,
		"show_community_albums": 1,
		"feed_preview_photos": 4,
	}
	for k, v in defaults.items():
		if not s.get(k):
			s.set(k, v)
	s.flags.ignore_permissions = True
	s.save()

	# Make sure the album tree has a valid nested-set state
	from frappe.utils.nestedset import rebuild_tree

	if frappe.db.count("Photo Album"):
		rebuild_tree("Photo Album")
