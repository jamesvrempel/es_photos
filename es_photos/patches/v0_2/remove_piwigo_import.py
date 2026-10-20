"""0.2.0: the Piwigo importer was removed.

Drops the Photo Import Log DocType and its table, and clears the Piwigo
fields (URL, username, password, import options) from ES Photos Settings.
Every other ES Photos setting is left exactly as it was.
"""

import frappe

DOCTYPE = "Photo Import Log"
OLD_FIELDS = ("piwigo_url", "piwigo_username", "piwigo_password", "import_owner", "import_mode", "download_size")


def execute():
	if frappe.db.exists("DocType", DOCTYPE):
		frappe.delete_doc("DocType", DOCTYPE, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{DOCTYPE}`")

	frappe.db.delete("Singles", {"doctype": "ES Photos Settings", "field": ("in", OLD_FIELDS)})
	frappe.db.delete("__Auth", {"doctype": "ES Photos Settings", "fieldname": "piwigo_password"})
	frappe.clear_cache(doctype="ES Photos Settings")
