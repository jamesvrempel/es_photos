"""/social/gallery — the ES Photos gallery inside ES Social.

Routes (see hooks.website_route_rules):
  /social/gallery                       albums (home)
  /social/gallery/album/<slug>          album: sub-albums + photos
  /social/gallery/photo/<name>          single photo
  /social/gallery/keywords              keyword cloud
  /social/gallery/keyword/<slug>        photos with a keyword
  /social/gallery/recent                recent photos
  /social/gallery/recent-albums         recently updated albums
  /social/gallery/most-visited          most visited photos
  /social/gallery/random                random photos
  /social/gallery/calendar[/<y>[/<m>[/<d>]]]
  /social/gallery/search?q=
  /social/gallery/upload[?album=]       upload (members)
"""

import calendar as pycal
import json
import math
from datetime import date
from urllib.parse import unquote, urlencode

import frappe
from frappe import _
from frappe.utils import cint, format_datetime, get_url

from es_photos import gallery as G
from es_photos import social as S
from es_photos.api import REACTIONS, reaction_summary, register_view
from es_photos.integration import max_upload_bytes
from es_photos.utils import human_size, video_embed

no_cache = 1
sitemap = 0
BASE = "/social/gallery"


def get_context(context):
	parts = [p for p in (frappe.form_dict.get("gpath") or "").strip("/").split("/") if p]
	v = G.get_viewer()
	s = G.settings()

	# ES Social's page guard + shared context (brand, flags, sign-up, asset version)
	S.page_context(context, frappe.request.path if frappe.request else BASE)

	view = parts[0] if parts else "home"
	handler = VIEWS.get(view)
	if not handler:
		raise frappe.PageDoesNotExistError

	context.no_cache = 1
	context.no_breadcrumbs = 1
	context.show_sidebar = 0
	context.full_width = 1
	context.base = BASE
	context.view = view
	context.settings = s
	context.viewer = v
	context.me = G.profile_info(v.user) if not v.guest else None
	context.can_upload = v.can_upload()
	context.brand = context.es_brand
	context.login_url = "/login?" + urlencode({"redirect-to": frappe.request.path if frappe.request else BASE})
	context.gallery_title = s.gallery_title or _("Gallery")
	context.reaction_types = REACTIONS
	context.photo_src = G.photo_src
	context.profile = G.profile_info
	context.fmt_dt = lambda d: format_datetime(d, "d MMM yyyy") if d else ""
	context.human_size = human_size
	context.aside_keywords = G.keyword_cloud(v, limit=18)
	context.aside_albums = G.children(None, v)
	context.breadcrumbs_list = []
	context.metatags = {"og:site_name": context.brand}

	handler(context, parts[1:], v)

	context.title = context.get("page_title") or context.gallery_title
	context.metatags.setdefault("title", context.title)
	context.cfg_json = json.dumps(
		{
			"base": BASE,
			"csrf": frappe.sessions.get_csrf_token() if not v.guest else None,
			"is_guest": v.guest,
			"me": v.user if not v.guest else None,
			"login_url": context.login_url,
			"signup_url": context.signup_url,
			"reactions": REACTIONS,
			"album": context.get("album_name"),
			"photo": context.get("photo_name"),
			"keyword": context.get("keyword_name"),
			"sort": frappe.form_dict.get("sort"),
			"max_mb": context.get("max_mb"),
			"slideshow_seconds": min(cint(s.slideshow_seconds), 120) if cint(s.slideshow_seconds) >= 1 else 5,
		}
	)


# --------------------------------------------------------------------------- helpers


def _page(context, total):
	per = cint(context.settings.photos_per_page) or 48
	page = max(1, cint(frappe.form_dict.get("page")) or 1)
	pages = max(1, math.ceil((total or 0) / per))
	page = min(page, pages)
	path = frappe.request.path if frappe.request else BASE
	args = {k: v for k, v in (frappe.request.args.items() if frappe.request else []) if k not in ("page", "gpath")}

	def link(n):
		return path + "?" + urlencode({**args, "page": n}) if n != 1 else path + ("?" + urlencode(args) if args else "")

	context.pg = {
		"page": page,
		"pages": pages,
		"total": total,
		"per": per,
		"prev_url": link(page - 1) if page > 1 else None,
		"next_url": link(page + 1) if page < pages else None,
	}
	return (page - 1) * per, per


def _crumbs(context, *items):
	context.breadcrumbs_list = [{"label": context.gallery_title, "url": BASE}] + [
		{"label": label, "url": url} for label, url in items
	]


def _album_card(a):
	return frappe._dict(
		name=a.name,
		title=a.title,
		url=f"{BASE}/album/{a.name}",
		cover=a.cover_url,
		count=cint(a.total_photo_count),
		own=cint(a.photo_count),
		subs=len(G.children(a.name)),
		privacy=a.privacy,
		date_last=a.date_last,
		description=a.description,
	)


def _sort_key(default):
	key = frappe.form_dict.get("sort")
	return G.SORT_KEYS.get(key) or default


# --------------------------------------------------------------------------- views


def v_home(context, parts, v):
	context.page_title = context.gallery_title
	context.albums = [_album_card(a) for a in G.children(None, v)]
	context.total_photos = G.photo_query(v, count=True)
	context.recent = G.photo_query(v, limit=12)
	if cint(context.settings.show_community_albums):
		context.community = G.community_albums(v)
	context.metatags["description"] = context.settings.tagline or context.gallery_title
	if context.albums and context.albums[0].cover:
		context.metatags["image"] = get_url(context.albums[0].cover) if not context.albums[0].cover.startswith(
			"http"
		) else context.albums[0].cover


def v_album(context, parts, v):
	if not parts:
		raise frappe.PageDoesNotExistError
	vis = G.visible_albums(v)
	a = vis.get(parts[0])
	if not a:
		if frappe.db.exists("Photo Album", parts[0]) and v.guest:
			frappe.local.flags.redirect_location = context.login_url
			raise frappe.Redirect
		raise frappe.PageDoesNotExistError
	context.album = a
	context.album_name = a.name
	context.album_owner = G.profile_info(a.owner_user)
	context.can_edit = v.can_edit_album(a)
	context.default_order = G.default_order()
	context.subalbums = [_album_card(c) for c in G.children(a.name, v)]
	order = _sort_key(G.album_order(a))
	context.sort = frappe.form_dict.get("sort") or ""
	total = G.photo_query(v, albums=[a.name], count=True)
	start, per = _page(context, total)
	context.photos = G.photo_query(v, albums=[a.name], order=order, start=start, limit=per)
	context.page_title = a.title
	_crumbs(context, *[(x.title, f"{BASE}/album/{x.name}") for x in G.ancestors(a.name)], (a.title, None))
	context.metatags["description"] = a.description or _("{0} photos").format(total)
	if a.cover_url:
		context.metatags["image"] = a.cover_url if a.cover_url.startswith("http") else get_url(a.cover_url)
	context.groups_for_select = _my_groups(v) if context.can_edit else []


def v_photo(context, parts, v):
	if not parts:
		raise frappe.PageDoesNotExistError
	doc, album = G.photo_visible(parts[0], v)
	if not doc:
		raise frappe.PageDoesNotExistError
	# ?album= lets prev/next follow the album the visitor came from
	via = frappe.form_dict.get("album")
	vis = G.visible_albums(v)
	if via and via in vis and (via == doc.album or via in {r.album for r in doc.additional_albums}):
		album = vis[via]
	register_view(doc.name)
	context.photo = doc
	context.photo_name = doc.name
	context.album = album
	context.album_name = album.name
	context.album_owner = G.profile_info(album.owner_user)
	context.uploader = G.profile_info(doc.uploaded_by) if doc.uploaded_by else None
	context.can_edit = v.can_edit_album(album) or (not v.guest and doc.uploaded_by == v.user)
	context.can_set_cover = v.can_edit_album(album)
	order = G.album_order(album)
	prev, nxt, pos, total = G.neighbours(doc, album.name, order, v)
	context.prev, context.next, context.pos, context.count = prev, nxt, pos, total
	context.src = G.photo_src(doc, "medium")
	context.src_large = G.photo_src(doc, "large")
	context.src_original = G.photo_src(doc, "original")
	context.embed = video_embed(doc.video_url) if doc.media_type == "Video" else None
	kw = [r.keyword for r in doc.keywords]
	context.keywords = (
		frappe.get_all("Photo Keyword", filters={"name": ("in", kw)}, fields=["name", "slug"]) if kw else []
	)
	context.other_albums = [vis[r.album] for r in doc.additional_albums if r.album in vis] + (
		[vis[doc.album]] if doc.album in vis and doc.album != album.name else []
	)
	exif = [
		(_("Camera"), " ".join(x for x in [doc.camera_make, doc.camera_model] if x)),
		(_("Lens"), doc.lens),
		(_("Focal length"), doc.focal_length),
		(_("Aperture"), doc.aperture),
		(_("Exposure"), doc.exposure_time),
		(_("ISO"), doc.iso or None),
	]
	context.exif = [(k, val) for k, val in exif if val] if cint(context.settings.show_exif) else []
	mine = None
	if not v.guest:
		mine = frappe.db.get_value("Photo Reaction", {"photo": doc.name, "user": v.user}, "reaction_type")
	context.reactions = reaction_summary(doc.name, mine)
	from es_photos.api import _comment_out, _comments

	context.comments = [_comment_out(c) for c in _comments(doc.name)]
	context.page_title = doc.title or album.title
	_crumbs(
		context,
		*[(x.title, f"{BASE}/album/{x.name}") for x in G.ancestors(album.name)],
		(album.title, f"{BASE}/album/{album.name}"),
		(doc.title, None),
	)
	img = G.photo_src(doc, "large")
	context.metatags.update(
		{
			"description": (doc.description or f"{doc.title} — {album.title}")[:200],
			"image": img if (img or "").startswith("http") else get_url(img) if img else None,
			"og:type": "article",
		}
	)
	context.can_share = not v.guest and (album.privacy or "Public") != "Only Me"


def v_keywords(context, parts, v):
	context.page_title = _("Keywords")
	context.cloud = G.keyword_cloud(v)
	_crumbs(context, (_("Keywords"), None))


def v_keyword(context, parts, v):
	if not parts:
		raise frappe.PageDoesNotExistError
	kw = frappe.db.get_value("Photo Keyword", {"slug": parts[0]}, ["name", "keyword_name", "description"], as_dict=True)
	if not kw:
		raise frappe.PageDoesNotExistError
	context.keyword = kw
	context.keyword_name = kw.name
	total = G.photo_query(v, keyword=kw.name, count=True)
	start, per = _page(context, total)
	context.photos = G.photo_query(
		v, keyword=kw.name, order=_sort_key(G.default_order()), start=start, limit=per
	)
	context.sort = frappe.form_dict.get("sort") or ""
	context.page_title = kw.keyword_name
	context.heading = kw.keyword_name
	context.subheading = kw.description or _("{0} photos tagged with this keyword").format(total)
	_crumbs(context, (_("Keywords"), f"{BASE}/keywords"), (kw.keyword_name, None))


def _list_view(context, v, title, sub, order=None, random_order=False, where="", values=None, cap=None):
	total = G.photo_query(v, count=True, where=where, values=values)
	if cap:
		total = min(total, cap)
	start, per = _page(context, total) if not random_order else (0, cint(context.settings.photos_per_page) or 48)
	context.photos = G.photo_query(
		v, order=order or "Date added (newest first)", start=start, limit=per, where=where, values=values,
		random_order=random_order,
	)
	context.page_title = context.heading = title
	context.subheading = sub
	_crumbs(context, (title, None))


def v_recent(context, parts, v):
	_list_view(context, v, _("Recent photos"), _("The newest additions to the gallery"), cap=480)


def v_most_visited(context, parts, v):
	_list_view(context, v, _("Most visited"), _("The photos people look at most"), order="Most viewed", cap=480)


def v_random(context, parts, v):
	_list_view(context, v, _("Random photos"), _("A fresh selection every time"), random_order=True)
	context.random = True


def v_member(context, parts, v):
	"""/social/gallery/member/<profile slug or user id>: one member's albums and uploads."""
	if not parts:
		raise frappe.PageDoesNotExistError
	key = unquote(parts[0])
	user = frappe.db.get_value("Social Profile", {"profile_slug": key}, "user") or (
		key if frappe.db.exists("User", key) and key not in ("Guest", "Administrator") else None
	)
	if not user or user in v.blocked:
		raise frappe.PageDoesNotExistError
	person = G.profile_info(user)
	vis = G.visible_albums(v)
	owned = [a for a in vis.values() if a.owner_user == user]
	owned_names = {a.name for a in owned}
	# top of each of their trees only (sub-albums are reached from the parent)
	context.albums = [_album_card(a) for a in owned if a.parent_photo_album not in owned_names]
	_list_view(
		context, v, person.display_name, None, where="p.uploaded_by=%(mu)s", values={"mu": user},
	)
	context.subheading = _("{0} albums · {1} photos").format(len(owned), context.pg["total"])
	context.member = person
	context.metatags["description"] = _("Photos by {0}").format(person.display_name)
	if person.profile_image:
		context.metatags["image"] = get_url(person.profile_image) if not person.profile_image.startswith("http") else person.profile_image


def v_recent_albums(context, parts, v):
	rows = sorted(
		[a for a in G.visible_albums(v).values() if a.date_last],
		key=lambda a: a.date_last,
		reverse=True,
	)[:24]
	context.albums = [_album_card(a) for a in rows]
	context.page_title = context.heading = _("Recently updated albums")
	_crumbs(context, (context.heading, None))


def v_calendar(context, parts, v):
	y = cint(parts[0]) if len(parts) > 0 else 0
	m = cint(parts[1]) if len(parts) > 1 else 0
	d = cint(parts[2]) if len(parts) > 2 else 0
	context.cal_year, context.cal_month, context.cal_day = y, m, d
	crumbs = [(_("Calendar"), f"{BASE}/calendar" if y else None)]
	if not y:
		context.cal_items = [
			{"label": str(r.k), "url": f"{BASE}/calendar/{r.k}", "n": r.n} for r in G.calendar_counts(v)
		]
		context.photos = []
	elif not m:
		context.cal_items = [
			{"label": pycal.month_name[r.k], "url": f"{BASE}/calendar/{y}/{r.k}", "n": r.n}
			for r in G.calendar_counts(v, y)
		]
		crumbs.append((str(y), None))
	else:
		counts = {r.k: r.n for r in G.calendar_counts(v, y, m)}
		first_wd, ndays = pycal.monthrange(y, m)
		context.month_grid = {"lead": first_wd, "days": [
			{"day": i, "n": counts.get(i, 0), "url": f"{BASE}/calendar/{y}/{m}/{i}"} for i in range(1, ndays + 1)
		]}
		crumbs += [(str(y), f"{BASE}/calendar/{y}"), (pycal.month_name[m], f"{BASE}/calendar/{y}/{m}" if d else None)]
		if d:
			crumbs.append((str(d), None))
	if y:
		dexpr = "COALESCE(p.date_taken, p.date_added)"
		where = f"YEAR({dexpr})=%(cy)s" + (f" AND MONTH({dexpr})=%(cm)s" if m else "") + (
			f" AND DAY({dexpr})=%(cd)s" if d else ""
		)
		vals = {"cy": y, "cm": m, "cd": d}
		total = G.photo_query(v, count=True, where=where, values=vals)
		start, per = _page(context, total)
		context.photos = G.photo_query(
			v, order="Date taken (oldest first)", start=start, limit=per, where=where, values=vals
		)
	label = " ".join(x for x in [str(d) if d else "", pycal.month_name[m] if m else "", str(y) if y else ""] if x)
	context.page_title = context.heading = label or _("Calendar")
	context.subheading = _("Photos by the date they were taken")
	_crumbs(context, *crumbs)
	context.today = date.today()


def v_search(context, parts, v):
	q = (frappe.form_dict.get("q") or "").strip()[:100]
	context.q = q
	context.photos, context.albums = [], []
	if q:
		like = f"%{q}%"
		where = """(p.title LIKE %(q)s OR p.description LIKE %(q)s
			OR EXISTS (SELECT 1 FROM `tabPhoto Keyword Link` k WHERE k.parent=p.name AND k.keyword LIKE %(q)s)
			OR EXISTS (SELECT 1 FROM `tabPhoto Album` a WHERE a.name=p.album AND a.title LIKE %(q)s))"""
		total = G.photo_query(v, count=True, where=where, values={"q": like})
		start, per = _page(context, total)
		context.photos = G.photo_query(v, where=where, values={"q": like}, start=start, limit=per)
		ql = q.lower()
		context.albums = [
			_album_card(a)
			for a in G.visible_albums(v).values()
			if ql in (a.title or "").lower() or ql in (a.description or "").lower()
		][:12]
		context.subheading = _("{0} photos match “{1}”").format(total, q)
	context.page_title = context.heading = _("Search")
	_crumbs(context, (_("Search"), None))


def v_upload(context, parts, v):
	if v.guest:
		frappe.local.flags.redirect_location = context.login_url
		raise frappe.Redirect
	if not v.can_upload():
		raise frappe.PermissionError(_("You can't upload to the gallery."))
	context.my_albums = [
		a for a in G.visible_albums(v).values() if v.can_edit_album(a)
	]
	context.selected_album = frappe.form_dict.get("album")
	context.groups_for_select = _my_groups(v)
	context.page_title = context.heading = _("Upload photos")
	context.max_mb = round(max_upload_bytes() / 1048576)
	_crumbs(context, (context.heading, None))


def _my_groups(v):
	filters = {} if v.manager else {"name": ("in", list(v.groups) or [""])}
	return frappe.get_all(
		"Social Group", filters=filters, fields=["name", "group_name as title"], order_by="group_name asc",
		limit_page_length=500,
	)


VIEWS = {
	"home": v_home,
	"member": v_member,
	"album": v_album,
	"photo": v_photo,
	"keywords": v_keywords,
	"keyword": v_keyword,
	"recent": v_recent,
	"most-visited": v_most_visited,
	"random": v_random,
	"recent-albums": v_recent_albums,
	"calendar": v_calendar,
	"search": v_search,
	"upload": v_upload,
}
