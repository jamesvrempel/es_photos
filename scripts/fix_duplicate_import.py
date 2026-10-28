"""Undo an "Import folder" run that duplicated the relinked Piwigo albums.

Situation this fixes: Piwigo's folders were moved from
    es_photos/library/piwigo/galleries/<Album>/...   (where the gallery's photos point)
to  es_photos/library/<Album>/...
and an Import folder job then created a second copy of every album and photo.

What it does
 1. Points each original gallery photo at its file's new place (original / large /
    medium / thumb URLs). Comments, reactions, views, keywords, album links stay.
 2. Deletes the duplicate photo that the import made for the same file, and its
    resized copies.
 3. Links each original album to its folder, so future Import folder runs add new
    files from that folder to the ORIGINAL album. Photos in the folder that the
    original album didn't have are moved into it.
 4. Deletes the now-empty duplicate albums and the albums made from the old
    piwigo/... folder structure (only when they hold no visible photos).
 5. Recounts all albums.

Albums with no original (e.g. new folders) are left alone.

Run from the bench's sites folder (dry run first, then --apply):
    cd ~/frappe-bench/sites
    ../env/bin/python /path/to/fix_duplicate_import.py erp.enterprisesystems.com.au
    ../env/bin/python /path/to/fix_duplicate_import.py erp.enterprisesystems.com.au --apply
"""

import os
import sys
from collections import Counter, defaultdict
from urllib.parse import unquote

import frappe

OLD = "/files/es_photos/library/piwigo/galleries/"


def disk_path(url):
	return frappe.get_site_path("public", *unquote(url.lstrip("/")).split("/"))


def main(site, apply):
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	try:
		run(apply)
	finally:
		frappe.destroy()


def run(apply):
	from es_photos import gallery as G
	from es_photos.imaging import delete_renditions
	from es_photos.library import url_for

	say = print
	say(("APPLYING CHANGES" if apply else "DRY RUN — nothing is changed") + f" on {frappe.local.site}\n")

	originals = frappe.db.sql(
		"""SELECT name, album, original_url, large_url, medium_url, thumb_url FROM `tabPhoto`
		WHERE IFNULL(source_ref, '') NOT LIKE 'library:%%' AND original_url LIKE %s""",
		(OLD + "%",),
		as_dict=True,
	)
	imported = {
		r.source_ref: r
		for r in frappe.db.sql(
			"SELECT name, album, source_ref, is_deleted FROM `tabPhoto` WHERE source_ref LIKE 'library:%%'",
			as_dict=True,
		)
	}

	repointed, missing, to_delete = 0, [], []
	album_votes = defaultdict(Counter)  # duplicate album -> original albums
	for o in originals:
		rest = unquote(o.original_url[len(OLD) :])
		new_url = url_for(rest)
		if not os.path.isfile(disk_path(new_url)):
			missing.append(o.original_url)
			continue
		changes = {}
		for f in ("original_url", "large_url", "medium_url", "thumb_url"):
			v = o.get(f)
			if v and v.startswith(OLD):
				changes[f] = url_for(unquote(v[len(OLD) :]))
		if apply:
			frappe.db.set_value("Photo", o.name, changes, update_modified=False)
		repointed += 1
		d = imported.pop("library:" + rest, None)
		if d:
			to_delete.append(d.name)
			album_votes[d.album][o.album] += 1

	say(f"Original photos pointed at the moved files: {repointed}")
	if missing:
		say(f"  {len(missing)} originals left unchanged — file not found at the new place, e.g.:")
		for m in missing[:10]:
			say("   ", m)
	say(f"Duplicate photos to delete: {len(to_delete)}")

	# duplicate album -> original album (only when unambiguous)
	album_map = {}
	for dup_album, votes in album_votes.items():
		(target, n), *others = votes.most_common()
		if others:
			say(f"  ! {dup_album}: its photos belong to several albums {dict(votes)} — left alone")
			continue
		album_map[dup_album] = target

	children = {}
	for meta_df in frappe.get_meta("Photo").get_table_fields():
		children[meta_df.options] = True

	def delete_photo(name):
		if not apply:
			return
		delete_renditions(name)
		for dt in ("Photo Reaction", "Photo Comment"):
			frappe.db.delete(dt, {"photo": name})
		for child in children:
			frappe.db.delete(child, {"parent": name, "parenttype": "Photo"})
		frappe.db.delete("Photo", name)

	for i, name in enumerate(to_delete, 1):
		delete_photo(name)
		if apply and i % 500 == 0:
			frappe.db.commit()
			say(f"  … {i} deleted")

	# link original albums to their folders; move extra photos across; drop duplicates
	moved, albums_deleted, kept = 0, [], []
	for dup_album, target in sorted(album_map.items()):
		dup = frappe.db.get_value("Photo Album", dup_album, ["name", "title", "source_ref"], as_dict=True)
		if not dup:
			continue
		remaining = frappe.get_all(
			"Photo", filters={"album": dup_album}, fields=["name", "is_deleted"]
		)
		live = [r.name for r in remaining if not r.is_deleted]
		extra_live = [n for n in live if n not in to_delete]
		extra_hidden = [r.name for r in remaining if r.is_deleted and r.name not in to_delete]
		say(f"  {dup.title}: duplicate '{dup_album}' -> original '{target}'"
			+ (f", moving {len(extra_live)} extra photo(s) into it" if extra_live else ""))
		if apply:
			for n in extra_live:
				frappe.db.set_value("Photo", n, "album", target, update_modified=False)
			for n in extra_hidden:
				delete_photo(n)
			frappe.db.set_value("Photo Album", dup_album, "source_ref", None, update_modified=False)
			frappe.db.set_value("Photo Album", target, "source_ref", dup.source_ref, update_modified=False)
		moved += len(extra_live)
		albums_deleted.append(dup_album)

	# albums made from the old piwigo/... folders
	junk = frappe.db.sql(
		"""SELECT name, title FROM `tabPhoto Album` WHERE source_ref LIKE 'library:dir:piwigo%%'
		ORDER BY rgt - lft ASC""",
		as_dict=True,
	)
	for a in junk:
		live = frappe.db.count("Photo", {"album": a.name, "is_deleted": 0})
		if live:
			kept.append(f"{a.name} ({live} visible photos)")
			continue
		if apply:
			for n in frappe.get_all("Photo", filters={"album": a.name}, pluck="name"):
				delete_photo(n)
		albums_deleted.append(a.name)

	if apply:
		# delete leaves first so nested albums go cleanly
		order = frappe.db.sql_list(
			"SELECT name FROM `tabPhoto Album` WHERE name IN %(n)s ORDER BY rgt - lft ASC",
			{"n": tuple(albums_deleted) or ("",)},
		)
		for name in order:
			if frappe.db.exists("Photo", {"album": name}):
				kept.append(f"{name} (still has photos)")
				continue
			frappe.delete_doc("Photo Album", name, ignore_permissions=True, force=True)

	say(f"Extra photos moved into original albums: {moved}")
	say(f"Albums deleted: {len(albums_deleted)}")
	if kept:
		say("Albums left in place: " + ", ".join(kept))
	untouched = Counter(r.album for r in imported.values() if not r.is_deleted and r.album not in album_map)
	if untouched:
		say("Imported albums with no original, left as they are: "
			+ ", ".join(f"{a} ({n})" for a, n in sorted(untouched.items())))

	if apply:
		say("Recounting albums …")
		G.recount_all()
		frappe.db.commit()
		G.clear_gallery_cache()
		say("Done.")
	else:
		frappe.db.rollback()
		say("\nDry run finished. Run again with --apply to make these changes.")


if __name__ == "__main__":
	if len(sys.argv) < 2:
		sys.exit(__doc__)
	main(sys.argv[1], "--apply" in sys.argv[2:])
