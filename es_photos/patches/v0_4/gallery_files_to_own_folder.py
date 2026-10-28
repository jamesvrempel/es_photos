"""0.4.0: keep every gallery image under public/files/es_photos/.

Moves existing uploaded originals of Photos from the general files folder into
public/files/es_photos/originals/ (copying instead of moving when another record
also uses the same file) and turns on "Exclude gallery photos from Google Drive
backup" (the new setting). Photos that point at remote URLs are left alone.
"""

import frappe


def execute():
	from es_photos.storage import relocate_original

	frappe.reload_doc("es_photos", "doctype", "es_photos_settings")
	# a Check that was never saved reads as 0, so look at the raw row
	never_set = not frappe.db.sql(
		"SELECT 1 FROM `tabSingles` WHERE doctype='ES Photos Settings' AND field='exclude_from_google_drive'"
	)
	if never_set:
		frappe.db.set_single_value("ES Photos Settings", "exclude_from_google_drive", 1)

	rows = frappe.db.sql(
		"""SELECT name, image FROM `tabPhoto`
		WHERE image LIKE '/files/%%' AND image NOT LIKE '/files/es_photos/%%'""",
		as_dict=True,
	)
	moved = 0
	for r in rows:
		try:
			if relocate_original(r.name, r.image):
				moved += 1
		except Exception:
			frappe.log_error(title=f"ES Photos: could not move original of {r.name}")
	if rows:
		print(f"ES Photos: moved {moved} of {len(rows)} gallery originals into public/files/es_photos/originals")
