"""Data + privacy layer for the gallery.

Privacy reuses ES Social's own graph:
  Public       anyone (guests too, if ES Social allows guest browsing)
  Connections  the owner's accepted Social Connections
  Group        active members of the chosen Social Group
  Only Me      the owner
Gallery Managers / System Managers see everything. Social Blocks in either
direction hide an owner's albums. An album is visible only if every
ancestor album is visible too.
"""

from urllib.parse import quote

import frappe
from frappe.utils import cint

from es_photos import social as S
from es_photos.utils import video_thumb

MANAGER_ROLES = {"System Manager", "Gallery Manager"}

PHOTO_FIELDS = (
	"p.name, p.title, p.album, p.media_type, p.thumb_url, p.medium_url, p.large_url, p.original_url, "
	"p.image, p.video_url, p.width, p.height, p.date_taken, p.date_added, p.view_count, "
	"p.like_count, p.comment_count, p.description, p.sort_order"
)

ORDERS = {
	"Date added (newest first)": "p.date_added DESC, p.name DESC",
	"Date added (oldest first)": "p.date_added ASC, p.name ASC",
	"Date taken (newest first)": "COALESCE(p.date_taken, p.date_added) DESC, p.name DESC",
	"Date taken (oldest first)": "COALESCE(p.date_taken, p.date_added) ASC, p.name ASC",
	"Title": "p.title ASC, p.name ASC",
	"Most viewed": "p.view_count DESC, p.name DESC",
	"Manual": "p.sort_order ASC, p.date_added ASC, p.name ASC",
}
SORT_KEYS = {
	"newest": "Date added (newest first)",
	"oldest": "Date added (oldest first)",
	"taken": "Date taken (newest first)",
	"taken-asc": "Date taken (oldest first)",
	"title": "Title",
	"views": "Most viewed",
	"manual": "Manual",
}


# --------------------------------------------------------------------------- settings


def settings():
	return frappe.get_cached_doc("ES Photos Settings")


FALLBACK_ORDER = "Date taken (newest first)"


def default_order() -> str:
	"""Gallery-wide photo order (ES Photos Settings → Default album sort)."""
	o = settings().get("default_album_order")
	return o if o in ORDERS else FALLBACK_ORDER


def album_order(row) -> str:
	"""An album's own Photo order, else the gallery default."""
	o = (row or {}).get("image_order") if row else None
	return o if o in ORDERS else default_order()


def social_settings():
	return S.social_settings()


def clear_gallery_cache():
	"""Forget the album tree and per-viewer visibility for this request."""
	for attr in ("esp_albums", "esp_visible"):
		if getattr(frappe.local, attr, None) is not None:
			setattr(frappe.local, attr, None)
	frappe.cache.delete_value("es_photos:albums")


def reset_request_cache():
	"""Also forget the current viewer and profile lookups (used by tests and
	background jobs that switch user mid-request)."""
	clear_gallery_cache()
	for attr in ("esp_viewer", "esp_profiles"):
		if getattr(frappe.local, attr, None) is not None:
			setattr(frappe.local, attr, None)


# --------------------------------------------------------------------------- viewer


class Viewer:
	"""Who is looking, resolved through ES Social's own (cached) social graph."""

	def __init__(self, user: str | None = None):
		self.user = user or frappe.session.user
		self.guest = self.user == "Guest"
		roles = set(frappe.get_roles(self.user)) if not self.guest else set()
		self.manager = self.user == "Administrator" or bool(roles & MANAGER_ROLES)
		self.roles = roles
		self._connections = None
		self._groups = None
		self._blocked = None
		self._suspended = None
		self._moderator = None

	@property
	def connections(self) -> set:
		if self._connections is None:
			self._connections = S.connection_ids(self.user)
		return self._connections

	@property
	def groups(self) -> set:
		if self._groups is None:
			self._groups = S.group_ids(self.user)
		return self._groups

	@property
	def blocked(self) -> set:
		if self._blocked is None:
			self._blocked = S.block_ids(self.user)
		return self._blocked

	@property
	def suspended(self) -> bool:
		if self._suspended is None:
			self._suspended = S.is_suspended(self.user)
		return self._suspended

	@property
	def moderator(self) -> bool:
		"""Gallery managers plus ES Social moderators/admins."""
		if self._moderator is None:
			self._moderator = self.manager or S.is_moderator(self.user)
		return self._moderator

	def can_upload(self) -> bool:
		if self.guest or self.suspended:
			return False
		if self.manager:
			return True
		return bool(cint(settings().allow_member_albums)) and "Social User" in self.roles

	def owns(self, album_row) -> bool:
		return not self.guest and album_row.owner_user == self.user

	def can_edit_album(self, album_row) -> bool:
		return self.manager or (self.owns(album_row) and not self.suspended)

	def album_allowed(self, row) -> bool:
		if self.manager or self.owns(row):
			return True
		if not cint(row.published):
			return False
		if row.owner_user in self.blocked:
			return False
		privacy = row.privacy or "Public"
		if privacy == "Public":
			return True
		if privacy == "Connections":
			return not self.guest and row.owner_user in self.connections
		if privacy == "Group":
			return bool(row.social_group) and row.social_group in self.groups
		return False


def get_viewer() -> Viewer:
	if not getattr(frappe.local, "esp_viewer", None) or frappe.local.esp_viewer.user != frappe.session.user:
		frappe.local.esp_viewer = Viewer()
	return frappe.local.esp_viewer


# --------------------------------------------------------------------------- albums


def all_albums() -> list:
	if getattr(frappe.local, "esp_albums", None) is None:
		frappe.local.esp_albums = frappe.get_all(
			"Photo Album",
			fields=[
				"name",
				"title",
				"slug",
				"parent_photo_album",
				"owner_user",
				"privacy",
				"social_group",
				"published",
				"cover_url",
				"cover_photo",
				"photo_count",
				"total_photo_count",
				"date_last",
				"description",
				"sort_order",
				"image_order",
				"social_post",
				"lft",
				"rgt",
				"creation",
			],
			order_by="lft ASC",
			limit_page_length=0,
		)
	return frappe.local.esp_albums


def album_map() -> dict:
	return {a.name: a for a in all_albums()}


def visible_albums(viewer: Viewer | None = None) -> dict:
	"""name -> row, in tree order, for albums this viewer may open."""
	viewer = viewer or get_viewer()
	store = getattr(frappe.local, "esp_visible", None)
	if store is None:
		store = frappe.local.esp_visible = {}
	cached = store.get(viewer.user)
	if cached is not None:
		return cached
	out = {}
	for a in all_albums():
		parent = a.parent_photo_album
		if parent and parent not in out:
			continue
		if viewer.album_allowed(a):
			out[a.name] = a
	store[viewer.user] = out
	return out


def ancestors(album_name: str) -> list:
	amap = album_map()
	chain, cur = [], amap.get(album_name)
	seen = set()
	while cur and cur.parent_photo_album and cur.parent_photo_album not in seen:
		seen.add(cur.parent_photo_album)
		cur = amap.get(cur.parent_photo_album)
		if cur:
			chain.append(cur)
	return list(reversed(chain))


def children(album_name: str | None, viewer: Viewer | None = None) -> list:
	vis = visible_albums(viewer)
	rows = [a for a in vis.values() if (a.parent_photo_album or None) == (album_name or None)]
	rows.sort(key=lambda a: (cint(a.sort_order), (a.title or "").lower()))
	return rows


def subtree_names(album_name: str, viewer: Viewer | None = None) -> list:
	vis = visible_albums(viewer)
	root = vis.get(album_name)
	if not root:
		return []
	return [a.name for a in vis.values() if a.lft >= root.lft and a.rgt <= root.rgt]


# --------------------------------------------------------------------------- photos


def photo_src(p, size: str = "medium") -> str | None:
	if not p:
		return None
	g = p.get
	if size == "thumb":
		return g("thumb_url") or g("medium_url") or g("large_url") or g("image") or g("original_url") or (
			video_thumb(g("video_url")) if g("video_url") else None
		)
	if size == "large":
		return g("large_url") or g("medium_url") or g("original_url") or g("image") or g("thumb_url")
	if size == "original":
		return g("original_url") or g("image") or g("large_url") or g("medium_url")
	return g("medium_url") or g("large_url") or g("image") or g("original_url") or g("thumb_url")


def _album_condition(albums) -> tuple[str, dict]:
	return (
		"""(p.album IN %(albums)s OR EXISTS (SELECT 1 FROM `tabPhoto Album Membership` m
		WHERE m.parent=p.name AND m.parenttype='Photo' AND m.album IN %(albums)s))""",
		{"albums": tuple(albums)},
	)


def photo_query(
	viewer: Viewer | None = None,
	albums: list | None = None,
	keyword: str | None = None,
	order: str = "Date added (newest first)",
	start: int = 0,
	limit: int = 48,
	where: str = "",
	values: dict | None = None,
	count: bool = False,
	random_order: bool = False,
):
	"""Photos visible to viewer. albums=None means all visible albums."""
	viewer = viewer or get_viewer()
	vis = visible_albums(viewer)
	scope = [a for a in (albums if albums is not None else vis.keys()) if a in vis]
	if not scope:
		return 0 if count else []
	cond, params = _album_condition(scope)
	params.update(values or {})
	sql_where = f"p.is_deleted=0 AND {cond}"
	if keyword:
		sql_where += """ AND EXISTS (SELECT 1 FROM `tabPhoto Keyword Link` k
			WHERE k.parent=p.name AND k.parenttype='Photo' AND k.keyword=%(kw)s)"""
		params["kw"] = keyword
	if where:
		sql_where += f" AND ({where})"
	if count:
		return frappe.db.sql(f"SELECT COUNT(*) FROM `tabPhoto` p WHERE {sql_where}", params)[0][0]
	order_sql = "RAND()" if random_order else ORDERS.get(order, ORDERS["Date added (newest first)"])
	params.update({"start": cint(start), "limit": cint(limit) or 48})
	return frappe.db.sql(
		f"SELECT {PHOTO_FIELDS} FROM `tabPhoto` p WHERE {sql_where} ORDER BY {order_sql} "
		"LIMIT %(start)s, %(limit)s",
		params,
		as_dict=True,
	)


def neighbours(photo, album: str, order: str, viewer: Viewer | None = None):
	"""(prev, next, position, total) of photo inside album using album order."""
	viewer = viewer or get_viewer()
	cond, params = _album_condition([album])
	order_sql = ORDERS.get(order, ORDERS["Date added (newest first)"])
	names = frappe.db.sql_list(
		f"SELECT p.name FROM `tabPhoto` p WHERE p.is_deleted=0 AND {cond} ORDER BY {order_sql} LIMIT 5000",
		params,
	)
	if photo.name not in names:
		return None, None, 0, len(names)
	i = names.index(photo.name)
	prev_name = names[i - 1] if i > 0 else None
	next_name = names[i + 1] if i < len(names) - 1 else None

	def row(n):
		if not n:
			return None
		return frappe.db.get_value(
			"Photo",
			n,
			["name", "title", "thumb_url", "medium_url", "large_url", "image", "original_url", "video_url"],
			as_dict=True,
		)

	return row(prev_name), row(next_name), i + 1, len(names)


def photo_visible(photo_name: str, viewer: Viewer | None = None):
	"""Return (photo doc, album row it is being shown in) or (None, None)."""
	viewer = viewer or get_viewer()
	if not frappe.db.exists("Photo", photo_name):
		return None, None
	doc = frappe.get_doc("Photo", photo_name)
	if cint(doc.is_deleted) and not viewer.manager:
		return None, None
	vis = visible_albums(viewer)
	if doc.album in vis:
		return doc, vis[doc.album]
	for r in doc.additional_albums:
		if r.album in vis:
			return doc, vis[r.album]
	return None, None


def keyword_cloud(viewer: Viewer | None = None, limit: int = 0) -> list:
	viewer = viewer or get_viewer()
	vis = list(visible_albums(viewer).keys())
	if not vis:
		return []
	cond, params = _album_condition(vis)
	rows = frappe.db.sql(
		f"""SELECT k.keyword AS name, kw.slug, COUNT(DISTINCT p.name) AS n
		FROM `tabPhoto Keyword Link` k
		JOIN `tabPhoto` p ON p.name=k.parent AND k.parenttype='Photo'
		JOIN `tabPhoto Keyword` kw ON kw.name=k.keyword
		WHERE p.is_deleted=0 AND {cond}
		GROUP BY k.keyword, kw.slug ORDER BY n DESC, k.keyword ASC {"LIMIT %(lim)s" if limit else ""}""",
		dict(params, lim=cint(limit)),
		as_dict=True,
	)
	if rows:
		hi = max(r.n for r in rows)
		lo = min(r.n for r in rows)
		for r in rows:
			r.level = 1 if hi == lo else 1 + round(4 * (r.n - lo) / (hi - lo))
	return sorted(rows, key=lambda r: r.name.lower()) if not limit else rows


def calendar_counts(viewer, year: int | None = None, month: int | None = None) -> list:
	vis = list(visible_albums(viewer).keys())
	if not vis:
		return []
	cond, params = _album_condition(vis)
	d = "COALESCE(p.date_taken, p.date_added)"
	if year and month:
		grp, extra = f"DAY({d})", f" AND YEAR({d})=%(y)s AND MONTH({d})=%(m)s"
	elif year:
		grp, extra = f"MONTH({d})", f" AND YEAR({d})=%(y)s"
	else:
		grp, extra = f"YEAR({d})", ""
	params.update({"y": cint(year), "m": cint(month)})
	return frappe.db.sql(
		f"""SELECT {grp} AS k, COUNT(*) AS n FROM `tabPhoto` p
		WHERE p.is_deleted=0 AND {cond} AND {d} IS NOT NULL {extra}
		GROUP BY k ORDER BY k {"DESC" if not year else "ASC"}""",
		params,
		as_dict=True,
	)


# --------------------------------------------------------------------------- people (ES Social)


def profile_info(user: str) -> frappe._dict:
	cache = getattr(frappe.local, "esp_profiles", None)
	if cache is None:
		cache = frappe.local.esp_profiles = {}
	if user in cache:
		return cache[user]
	p = frappe.db.get_value(
		"Social Profile", {"user": user}, ["display_name", "profile_image", "profile_slug"], as_dict=True
	) or frappe._dict()
	if not p.get("display_name"):
		p.display_name = frappe.db.get_value("User", user, "full_name") or user
	if not p.get("profile_image"):
		p.profile_image = frappe.db.get_value("User", user, "user_image")
	p.user = user
	p.slug = p.get("profile_slug") or user
	# gallery page for this member; their ES Social profile lives at /u/<slug>
	p.photos_url = f"/social/gallery/member/{quote(p.slug, safe='@.')}"
	p.profile_url = f"/u/{quote(p.profile_slug)}" if p.get("profile_slug") else None
	p.initials = "".join(w[0] for w in (p.display_name or "?").split()[:2]).upper()
	cache[user] = p
	return p


def community_albums(viewer: Viewer, limit: int = 12) -> list:
	"""ES Social's own member albums (Social Album) this viewer may see."""
	if not frappe.db.table_exists("Social Album"):
		return []
	rows = frappe.get_all(
		"Social Album",
		filters={"photo_count": (">", 0)},
		fields=["name", "title", "slug", "owner_user", "privacy", "cover_image", "photo_count", "posted_on"],
		order_by="posted_on desc",
		limit_page_length=200,
	)
	out = []
	for r in rows:
		if r.owner_user in viewer.blocked:
			continue
		priv = r.privacy or "Public"
		ok = (
			viewer.manager
			or (not viewer.guest and r.owner_user == viewer.user)
			or priv == "Public"
			or (priv == "Connections" and r.owner_user in viewer.connections)
		)
		if ok:
			if not r.cover_image:
				r.cover_image = frappe.db.get_value(
					"Social Photo", {"album": r.name, "media_type": "Image"}, "image", order_by="sort_order asc"
				)
			r.owner = profile_info(r.owner_user)
			out.append(r)
		if len(out) >= limit:
			break
	return out


# --------------------------------------------------------------------------- counts


def recount_album(name: str):
	if not frappe.db.exists("Photo Album", name):
		return
	lft, rgt, cover_photo = frappe.db.get_value("Photo Album", name, ["lft", "rgt", "cover_photo"])
	own_cond, own_params = _album_condition([name])
	own = frappe.db.sql(
		f"SELECT COUNT(*), MAX(p.date_added) FROM `tabPhoto` p WHERE p.is_deleted=0 AND {own_cond}",
		own_params,
	)[0]
	sub = frappe.db.sql_list(
		"SELECT name FROM `tabPhoto Album` WHERE lft>=%s AND rgt<=%s", (lft, rgt)
	) or [name]
	sub_cond, sub_params = _album_condition(sub)
	total = frappe.db.sql(
		f"SELECT COUNT(DISTINCT p.name), MAX(p.date_added) FROM `tabPhoto` p WHERE p.is_deleted=0 AND {sub_cond}",
		sub_params,
	)[0]
	cover_url = None
	if cover_photo:
		p = frappe.db.get_value(
			"Photo", cover_photo, ["thumb_url", "medium_url", "large_url", "image", "original_url", "video_url"],
			as_dict=True,
		)
		cover_url = photo_src(p, "thumb")
	if not cover_url:
		first = frappe.db.sql(
			f"""SELECT {PHOTO_FIELDS} FROM `tabPhoto` p WHERE p.is_deleted=0 AND {sub_cond}
			ORDER BY p.media_type='Video', p.date_added DESC LIMIT 1""",
			sub_params,
			as_dict=True,
		)
		cover_url = photo_src(first[0], "thumb") if first else None
	frappe.db.set_value(
		"Photo Album",
		name,
		{
			"photo_count": own[0] or 0,
			"total_photo_count": total[0] or 0,
			"date_last": total[1] or own[1],
			"cover_url": cover_url,
		},
		update_modified=False,
	)


def recount_album_and_ancestors(name: str | None):
	if not name or not frappe.db.exists("Photo Album", name):
		return
	recount_album(name)
	lft, rgt = frappe.db.get_value("Photo Album", name, ["lft", "rgt"])
	for a in frappe.db.sql_list(
		"SELECT name FROM `tabPhoto Album` WHERE lft<%s AND rgt>%s ORDER BY lft DESC", (lft, rgt)
	):
		recount_album(a)
	clear_gallery_cache()


def recount_for_photo(photo, old_album: str | None = None):
	targets = {photo.album} | {r.album for r in photo.additional_albums}
	if old_album:
		targets.add(old_album)
	for a in targets:
		recount_album_and_ancestors(a)


def recount_keywords():
	frappe.db.sql(
		"""UPDATE `tabPhoto Keyword` kw SET photo_count = (
			SELECT COUNT(DISTINCT k.parent) FROM `tabPhoto Keyword Link` k
			JOIN `tabPhoto` p ON p.name=k.parent WHERE k.keyword=kw.name AND p.is_deleted=0)"""
	)


def recount_all():
	for name in frappe.db.sql_list("SELECT name FROM `tabPhoto Album` ORDER BY rgt - lft ASC"):
		recount_album(name)
	recount_keywords()
	clear_gallery_cache()
