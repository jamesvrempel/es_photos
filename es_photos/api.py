"""Whitelisted endpoints for the /social/gallery pages."""

import os

import frappe
from frappe import _
from frappe.utils import cint, escape_html, pretty_date

from es_photos import gallery as G
from es_photos import integration as I

REACTIONS = {"Like": "👍", "Love": "❤️", "Care": "🤗", "Haha": "😆", "Wow": "😮", "Sad": "😢", "Angry": "😠"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".heic"}


def _login():
	"""ES Social's write gate: logged in and not suspended."""
	I.require_login()


def _visible_photo(name):
	doc, album = G.photo_visible(name)
	if not doc:
		frappe.throw(_("Photo not found."), frappe.DoesNotExistError)
	return doc, album


def _editable_album(name):
	v = G.get_viewer()
	row = G.album_map().get(name)
	if not row or not v.can_edit_album(row):
		frappe.throw(_("You can't change this album."), frappe.PermissionError)
	return row


# --------------------------------------------------------------------------- browsing


@frappe.whitelist(allow_guest=True)
def slideshow(album: str | None = None, keyword: str | None = None, sort: str | None = None):
	"""Ordered list of photos for the fullscreen viewer."""
	v = G.get_viewer()
	albums = None
	order = "Date added (newest first)"
	if album:
		row = G.visible_albums(v).get(album)
		if not row:
			return []
		albums = [album]
		order = G.SORT_KEYS.get(sort) or row.image_order or order
	elif keyword:
		order = G.SORT_KEYS.get(sort) or order
	rows = G.photo_query(v, albums=albums, keyword=keyword, order=order, limit=2000)
	return [
		{
			"name": r.name,
			"title": r.title,
			"src": G.photo_src(r, "large"),
			"thumb": G.photo_src(r, "thumb"),
			"video": r.video_url if r.media_type == "Video" else None,
			"href": f"/social/gallery/photo/{r.name}",
		}
		for r in rows
	]


@frappe.whitelist(allow_guest=True)
def get_comments(photo: str):
	_visible_photo(photo)
	return [_comment_out(c) for c in _comments(photo)]


def _comments(photo):
	user = frappe.session.user
	return frappe.db.sql(
		"""SELECT name, author, content, posted_on, parent_comment, approval_status
		FROM `tabPhoto Comment` WHERE photo=%(p)s AND is_deleted=0
		AND (approval_status='Approved' OR author=%(u)s) ORDER BY posted_on ASC""",
		{"p": photo, "u": user},
		as_dict=True,
	)


def _comment_out(c):
	pf = G.profile_info(c.author)
	v = G.get_viewer()
	return {
		"name": c.name,
		"author": c.author,
		"author_name": pf.display_name,
		"author_image": pf.profile_image,
		"author_initials": pf.initials,
		"author_url": pf.photos_url,
		"content": escape_html(c.content or "").replace("\n", "<br>"),
		"when": pretty_date(c.posted_on),
		"pending": c.approval_status == "Pending",
		"can_delete": v.moderator or (not v.guest and c.author == v.user),
	}


# --------------------------------------------------------------------------- social actions


@frappe.whitelist(methods=["POST"])
def react(photo: str, reaction_type: str = "Like"):
	_login()
	if not cint(G.settings().enable_reactions):
		frappe.throw(_("Reactions are turned off."))
	if reaction_type not in REACTIONS:
		reaction_type = "Like"
	doc, album = _visible_photo(photo)
	I.assert_not_blocked(album.owner_user)
	existing = frappe.db.get_value(
		"Photo Reaction", {"photo": photo, "user": frappe.session.user}, ["name", "reaction_type"], as_dict=True
	)
	mine = None
	if existing and existing.reaction_type == reaction_type:
		frappe.delete_doc("Photo Reaction", existing.name, ignore_permissions=True)
	elif existing:
		frappe.db.set_value("Photo Reaction", existing.name, "reaction_type", reaction_type)
		mine = reaction_type
	else:
		frappe.get_doc(
			{"doctype": "Photo Reaction", "photo": photo, "user": frappe.session.user, "reaction_type": reaction_type}
		).insert(ignore_permissions=True)
		mine = reaction_type
	return reaction_summary(photo, mine)


def reaction_summary(photo, mine=None):
	rows = frappe.db.sql(
		"SELECT reaction_type, COUNT(*) n FROM `tabPhoto Reaction` WHERE photo=%s GROUP BY reaction_type ORDER BY n DESC",
		photo,
		as_dict=True,
	)
	return {
		"total": sum(r.n for r in rows),
		"top": [REACTIONS.get(r.reaction_type, "👍") for r in rows[:3]],
		"mine": mine,
		"mine_emoji": REACTIONS.get(mine) if mine else None,
	}


@frappe.whitelist(methods=["POST"])
def add_comment(photo: str, content: str, parent_comment: str | None = None):
	_login()
	v = G.get_viewer()
	if not cint(G.settings().enable_comments):
		frappe.throw(_("Comments are turned off."))
	content = (content or "").strip()
	if not content:
		frappe.throw(_("Write something first."))
	if len(content) > 2000:
		frappe.throw(_("Comments are limited to 2000 characters."))
	doc, album = _visible_photo(photo)
	I.assert_not_blocked(album.owner_user)
	I.rate_limit_comments(v.user)
	status = I.check_text(content)
	c = frappe.get_doc(
		{
			"doctype": "Photo Comment",
			"photo": photo,
			"author": v.user,
			"content": content,
			"parent_comment": parent_comment
				if parent_comment and frappe.db.get_value("Photo Comment", parent_comment, "photo") == photo
				else None,
			"approval_status": status,
		}
	).insert(ignore_permissions=True)
	return _comment_out(c)


@frappe.whitelist(methods=["POST"])
def delete_comment(name: str):
	_login()
	c = frappe.get_doc("Photo Comment", name)
	v = G.get_viewer()
	album_owner = frappe.db.get_value("Photo Album", frappe.db.get_value("Photo", c.photo, "album"), "owner_user")
	if not (v.moderator or c.author == v.user or album_owner == v.user):
		frappe.throw(_("Not allowed."), frappe.PermissionError)
	c.is_deleted = 1
	c.save(ignore_permissions=True)
	return "ok"


@frappe.whitelist(methods=["POST"])
def share_to_feed(photo: str, message: str = ""):
	_login()
	doc, album = _visible_photo(photo)
	post = I.share_photo(doc, album, (message or "").strip()[:2000])
	return {"post": post, "feed_url": "/social"}


@frappe.whitelist(methods=["POST"])
def post_album_to_feed(album: str, message: str = ""):
	_login()
	row = _editable_album(album)
	n = cint(G.settings().feed_preview_photos) or 4
	photos = G.photo_query(albums=G.subtree_names(album), order=row.image_order or "Date added (newest first)", limit=n)
	if not photos:
		frappe.throw(_("Add some photos first."))
	post = I.post_album(row, photos, (message or "").strip()[:2000])
	return {"post": post, "feed_url": "/social"}


# --------------------------------------------------------------------------- managing


@frappe.whitelist(methods=["POST"])
def save_album(
	title: str,
	name: str | None = None,
	description: str | None = None,
	privacy: str | None = None,
	social_group: str | None = None,
	parent_photo_album: str | None = None,
	image_order: str | None = None,
):
	_login()
	v = G.get_viewer()
	title = (title or "").strip()
	if not title:
		frappe.throw(_("Give the album a title."))
	if privacy not in (None, "", "Public", "Connections", "Group", "Only Me"):
		frappe.throw(_("Unknown privacy setting."))
	if privacy == "Group" and social_group and not v.manager and social_group not in v.groups:
		frappe.throw(_("You're not a member of that group."))
	if parent_photo_album:
		parent = G.album_map().get(parent_photo_album)
		if not parent or not v.can_edit_album(parent):
			frappe.throw(_("You can only add sub-albums to your own albums."))
	if name:
		_editable_album(name)
		doc = frappe.get_doc("Photo Album", name)
	else:
		if not v.can_upload():
			frappe.throw(_("You can't create albums."), frappe.PermissionError)
		doc = frappe.new_doc("Photo Album")
		doc.owner_user = v.user
	doc.title = title
	doc.description = (description or "").strip()
	if privacy:
		doc.privacy = privacy
	doc.social_group = social_group or None
	doc.parent_photo_album = parent_photo_album or None
	if image_order in G.ORDERS:
		doc.image_order = image_order
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "url": f"/social/gallery/album/{doc.name}"}


@frappe.whitelist(methods=["POST"])
def upload_photo(album: str, title: str | None = None):
	"""multipart: file=<image> album=<name>. Returns the new photo."""
	_login()
	v = G.get_viewer()
	row = _editable_album(album)
	if not v.can_upload():
		frappe.throw(_("You can't upload photos."), frappe.PermissionError)
	f = frappe.request.files.get("file") if frappe.request else None
	if not f:
		frappe.throw(_("No file received."))
	fname = os.path.basename(f.filename or "photo.jpg")
	ext = os.path.splitext(fname)[1].lower()
	if ext not in IMAGE_EXT:
		frappe.throw(_("{0} isn't an image file.").format(escape_html(fname)))
	content = f.stream.read()
	if len(content) > I.max_upload_bytes():
		frappe.throw(_("{0} is too large.").format(escape_html(fname)))

	photo = frappe.new_doc("Photo")
	photo.album = row.name
	photo.title = (title or "").strip() or os.path.splitext(fname)[0].replace("_", " ").replace("-", " ")
	photo.uploaded_by = v.user
	photo.media_type = "Image"
	photo.original_url = "pending"  # satisfies validate until the file is attached
	photo.flags.esp_skip_recount = True
	photo.insert(ignore_permissions=True)

	# originals live in /files/es_photos/originals with the renditions (see storage.py)
	from es_photos.storage import save_original

	file_doc = save_original(photo.name, fname, content)

	try:
		from es_photos.imaging import process_image_bytes

		values = process_image_bytes(photo, content)
	except Exception:
		frappe.log_error(title=f"ES Photos: could not read {fname}")
		values = {}
	values["image"] = file_doc.file_url
	values["original_url"] = file_doc.file_url
	frappe.db.set_value("Photo", photo.name, values, update_modified=False)
	G.recount_album_and_ancestors(row.name)
	return {
		"name": photo.name,
		"title": photo.title,
		"thumb": values.get("thumb_url") or file_doc.file_url,
		"url": f"/social/gallery/photo/{photo.name}",
	}


@frappe.whitelist(methods=["POST"])
def add_video(album: str, video_url: str, title: str | None = None):
	_login()
	row = _editable_album(album)
	doc = frappe.get_doc(
		{
			"doctype": "Photo",
			"album": row.name,
			"media_type": "Video",
			"video_url": (video_url or "").strip(),
			"title": (title or "").strip() or _("Video"),
		}
	).insert(ignore_permissions=True)
	return {"name": doc.name, "url": f"/social/gallery/photo/{doc.name}"}


@frappe.whitelist(methods=["POST"])
def update_photo(name: str, title: str | None = None, description: str | None = None, keywords: str | None = None):
	_login()
	doc, _album = _visible_photo(name)
	row = G.album_map()[doc.album]
	v = G.get_viewer()
	if not (v.can_edit_album(row) or doc.uploaded_by == v.user):
		frappe.throw(_("You can't edit this photo."), frappe.PermissionError)
	if title is not None:
		doc.title = title.strip()[:140]
	if description is not None:
		doc.description = description.strip()
	if keywords is not None:
		names = [k.strip() for k in keywords.split(",") if k.strip()][:30]
		doc.keywords = []
		for k in names:
			if not frappe.db.exists("Photo Keyword", k):
				frappe.get_doc({"doctype": "Photo Keyword", "keyword_name": k}).insert(ignore_permissions=True)
			doc.append("keywords", {"keyword": k})
	doc.save(ignore_permissions=True)
	return "ok"


@frappe.whitelist(methods=["POST"])
def set_cover(album: str, photo: str):
	_login()
	_editable_album(album)
	doc = frappe.get_doc("Photo Album", album)
	doc.cover_photo = photo
	doc.save(ignore_permissions=True)
	return "ok"


@frappe.whitelist(methods=["POST"])
def delete_photo(name: str):
	_login()
	doc = frappe.get_doc("Photo", name)
	row = G.album_map().get(doc.album)
	v = G.get_viewer()
	if not (row and v.can_edit_album(row)) and doc.uploaded_by != v.user:
		frappe.throw(_("You can't delete this photo."), frappe.PermissionError)
	album = doc.album
	frappe.delete_doc("Photo", name, ignore_permissions=True)
	return {"album_url": f"/social/gallery/album/{album}"}


@frappe.whitelist()
def recount():
	frappe.only_for(("System Manager", "Gallery Manager"))
	G.recount_all()
	return "ok"


def register_view(photo_name: str):
	"""Count one view per visitor per hour (called from the photo page)."""
	who = frappe.session.user if frappe.session.user != "Guest" else (frappe.local.request_ip or "anon")
	key = f"es_photos:view:{photo_name}:{who}"
	if frappe.cache.get_value(key):
		return
	frappe.cache.set_value(key, 1, expires_in_sec=3600)
	try:
		frappe.db.sql("UPDATE `tabPhoto` SET view_count=view_count+1 WHERE name=%s", photo_name)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()

