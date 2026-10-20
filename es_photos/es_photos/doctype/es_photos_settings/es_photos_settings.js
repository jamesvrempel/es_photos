// Copyright (c) 2026, Enterprise Systems Australia and contributors

frappe.ui.form.on("ES Photos Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Open gallery"), () => window.open("/social/gallery", "_blank"));
		frm.add_custom_button(__("New Piwigo import"), () => {
			frappe
				.call("es_photos.es_photos.doctype.photo_import_log.photo_import_log.new_import_from_settings")
				.then((r) => frappe.set_route("Form", "Photo Import Log", r.message));
		});
		frm.add_custom_button(__("Recount albums"), () => {
			frappe
				.call({ method: "es_photos.api.recount", freeze: true })
				.then(() => frappe.show_alert({ message: __("Counts refreshed"), indicator: "green" }));
		});
	},
});
