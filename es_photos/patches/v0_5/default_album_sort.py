"""0.5.0: albums follow a gallery-wide default sort (Date taken, newest first).

Orders nobody chose in ES Photos are cleared so those albums follow
ES Photos Settings → Default album sort:
* "Date added (newest first)" — filled in automatically as the old field default;
* any order on an album imported from Piwigo (it was copied from Piwigo).
An order a member picked for their own album in the gallery is kept.
"""

import frappe


def execute():
	frappe.reload_doc("es_photos", "doctype", "es_photos_settings")
	frappe.reload_doc("es_photos", "doctype", "photo_album")

	never_set = not frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE doctype='ES Photos Settings' AND field='default_album_order'"
	)
	if never_set:
		frappe.db.set_single_value("ES Photos Settings", "default_album_order", "Date taken (newest first)")

	cond = """image_order IS NOT NULL AND image_order != '' AND (
		image_order = 'Date added (newest first)' OR (source_ref IS NOT NULL AND source_ref != ''))"""
	n = frappe.db.sql(f"SELECT COUNT(*) FROM `tabPhoto Album` WHERE {cond}")[0][0]
	frappe.db.sql(f"UPDATE `tabPhoto Album` SET image_order=NULL WHERE {cond}")
	if n:
		print(f"ES Photos: {n} albums now follow the gallery default sort")
