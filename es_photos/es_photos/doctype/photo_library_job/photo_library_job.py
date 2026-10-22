# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from es_photos import library as L


class PhotoLibraryJob(Document):
	def before_insert(self):
		self.status = "Draft"

	def validate(self):
		self.library_path = L.library_root()
		if self.job_type == "Import folder":
			L.safe_subfolder(self.source_folder)  # raises on ../ or absolute paths
			if not self.album_owner:
				self.album_owner = "Administrator"


@frappe.whitelist()
def start(name: str):
	frappe.only_for(("System Manager", "Gallery Manager"))
	job = frappe.get_doc("Photo Library Job", name)
	if job.status in ("Queued", "Running"):
		frappe.throw(_("This job is already {0}.").format(_(job.status).lower()))
	L.reset_counters(job.name)
	frappe.db.set_value("Photo Library Job", job.name, "status", "Queued")
	frappe.enqueue(
		"es_photos.library.run",
		queue="long",
		timeout=24 * 3600,
		library_job=job.name,  # not "job_name": frappe.enqueue reserves that
		job_id=f"es_photos_library::{job.name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)
	return "Queued"


@frappe.whitelist()
def cancel(name: str):
	frappe.only_for(("System Manager", "Gallery Manager"))
	frappe.db.set_value("Photo Library Job", name, "cancel_requested", 1)
	return "ok"
