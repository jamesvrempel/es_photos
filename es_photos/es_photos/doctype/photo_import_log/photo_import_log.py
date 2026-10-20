# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PhotoImportLog(Document):
	def before_insert(self):
		if not self.source_url:
			self.source_url = frappe.db.get_single_value("ES Photos Settings", "piwigo_url")
		self.source_url = (self.source_url or "").rstrip("/")
		self.status = "Draft"


@frappe.whitelist()
def start_import(name: str):
	frappe.only_for(("System Manager", "Gallery Manager"))
	log = frappe.get_doc("Photo Import Log", name)
	if log.status in ("Queued", "Running"):
		frappe.throw(_("This import is already {0}.").format(log.status.lower()))
	log.db_set("status", "Queued")
	frappe.enqueue(
		"es_photos.importer.piwigo.run",
		queue="long",
		timeout=6 * 3600,
		log_name=log.name,
		job_id=f"es_photos_import::{log.name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)
	return "Queued"


@frappe.whitelist()
def new_import_from_settings():
	frappe.only_for(("System Manager", "Gallery Manager"))
	url = frappe.db.get_single_value("ES Photos Settings", "piwigo_url")
	if not url:
		frappe.throw(_("Set the Piwigo site URL first."))
	log = frappe.get_doc({"doctype": "Photo Import Log", "source_url": url}).insert()
	return log.name
