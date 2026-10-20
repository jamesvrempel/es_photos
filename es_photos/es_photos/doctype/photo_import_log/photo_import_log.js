// Copyright (c) 2026, Enterprise Systems Australia and contributors

frappe.ui.form.on("Photo Import Log", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!["Queued", "Running"].includes(frm.doc.status)) {
			const label = frm.doc.status === "Draft" ? __("Start import") : __("Run again");
			frm.add_custom_button(label, () => {
				frappe
					.call({
						method: "es_photos.es_photos.doctype.photo_import_log.photo_import_log.start_import",
						args: { name: frm.doc.name },
						freeze: true,
					})
					.then(() => {
						frappe.show_alert({ message: __("Import queued"), indicator: "blue" });
						frm.reload_doc();
					});
			}).addClass("btn-primary");
		} else {
			frm.dashboard.set_headline(__("Import is {0}. Refresh to see progress.", [frm.doc.status.toLowerCase()]));
			setTimeout(() => frm.reload_doc(), 8000);
		}
		frm.add_custom_button(__("Open gallery"), () => window.open("/social/gallery", "_blank"));
	},
});
