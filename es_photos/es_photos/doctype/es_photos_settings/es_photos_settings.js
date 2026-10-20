// Copyright (c) 2026, Enterprise Systems Australia and contributors

frappe.ui.form.on("ES Photos Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Open gallery"), () => window.open("/social/gallery", "_blank"));
		frm.add_custom_button(__("Recount albums"), () => {
			frappe
				.call({ method: "es_photos.api.recount", freeze: true })
				.then(() => frappe.show_alert({ message: __("Counts refreshed"), indicator: "green" }));
		});
	},
});
