// Copyright (c) 2026, Enterprise Systems Australia and contributors

frappe.ui.form.on("Photo Album", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("View in gallery"), () =>
			window.open(`/social/gallery/album/${encodeURIComponent(frm.doc.name)}`, "_blank")
		);
		frm.set_query("cover_photo", () => ({ filters: { album: frm.doc.name, is_deleted: 0 } }));
		frm.set_query("parent_photo_album", () => ({ filters: { name: ["!=", frm.doc.name] } }));
	},
});
