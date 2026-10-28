// Copyright (c) 2026, Enterprise Systems Australia and contributors

frappe.ui.form.on("Photo", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("View in gallery"), () =>
			window.open(`/social/gallery/photo/${encodeURIComponent(frm.doc.name)}`, "_blank")
		);
		const src = frm.doc.thumb_url || frm.doc.medium_url || frm.doc.image;
		if (src) {
			frm.dashboard.add_section(
				`<img src="${frappe.utils.escape_html(src)}" style="max-height:220px;border-radius:8px">`,
				__("Preview")
			);
		}
	},
});
