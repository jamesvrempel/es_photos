// Copyright (c) 2026, Enterprise Systems Australia and contributors

frappe.ui.form.on("Photo Library Job", {
	refresh(frm) {
		const running = ["Queued", "Running"].includes(frm.doc.status);
		if (!frm.is_new() && !running) {
			frm.add_custom_button(frm.doc.status === "Draft" ? __("Start") : __("Run again"), () => {
				frappe
					.call("es_photos.es_photos.doctype.photo_library_job.photo_library_job.start", { name: frm.doc.name })
					.then(() => frm.reload_doc());
			}).addClass("btn-primary");
		}
		if (running) {
			frm.add_custom_button(__("Cancel"), () => {
				frappe
					.call("es_photos.es_photos.doctype.photo_library_job.photo_library_job.cancel", { name: frm.doc.name })
					.then(() => frappe.show_alert(__("Cancelling after the current photo…")));
			});
		}
		frm.add_custom_button(__("Open gallery"), () => window.open("/social/gallery", "_blank"));

		const total = frm.doc.total || 0;
		if (total) {
			const done = frm.doc.rendered || 0;
			frm.dashboard.show_progress(
				__("Photos processed"),
				Math.min(100, (done / total) * 100),
				__("{0} of {1}", [done, total])
			);
		}
		clearTimeout(frm._esp_timer);
		if (running) frm._esp_timer = setTimeout(() => frm.reload_doc(), 5000);
	},
});
