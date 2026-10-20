# ES Photos

A photo gallery app for Frappe v15 that lives inside **ES Social** at `/social/gallery`.
It recreates everything the Piwigo site at photos.tarrant-trading.com does — albums and
sub-albums, keywords, most visited / recent / random / calendar views, search, EXIF,
slideshow, downloads, videos — and plugs it into ES Social's people, privacy and feed.

## How it fits into ES Social

| ES Social piece | How ES Photos uses it |
|---|---|
| Page chrome | Gallery pages call ES Social's own `guard_page()` and `apply_guest_context()` and include its `es_social_nav.html`, so brand, guest browsing, sign-up buttons and the nav are exactly the same as every other `/social` page. |
| Top nav | **Gallery** is registered through the `es_social_nav_links` hook, which ES Social 0.9.7+ renders server-side (highlighted inside the gallery). On older ES Social a tiny fallback script adds the link. |
| Social graph | Connections, group membership, blocks and suspension come from ES Social's own cached helpers (`get_connection_ids`, `get_group_ids`, `get_block_ids`, `is_suspended`), so the gallery always agrees with the feed. |
| Social Profile | Owners, uploaders and commenters show their ES Social name and avatar and link to `/social/gallery/member/<profile slug>`, which links on to their `/u/<slug>` profile. |
| Moderation | Comments go through ES Social's `check_content()` keyword filter and `enforce_rate_limit()`; writes go through `require_login()` (logged in, not suspended). ES Social moderators/admins can remove any gallery comment. |
| Social Connection | Albums can be **Connections** only — visible to the owner's accepted connections. |
| Social Group / Group Member | Albums can be **Group** only — visible to active members of a chosen group. |
| Social Block | A block in either direction hides that person's albums and stops reactions/comments. |
| ES Social Settings | Guest browsing switch, brand name, blocked keywords + "Reject / Hold for review", comments-per-minute limit and max upload size are all honoured. |
| Feed | **Share to feed** (any photo) and **Post to feed** (whole album) create a real Social Post through `es_social.api.posts.create_post`, so ES Social's moderation, fan-out and notifications apply. Album pages then show **Discuss in feed**. |
| Social Album | ES Social's own member albums appear on the gallery home under "From the community". |
| Reactions | Same seven reaction types as ES Social posts. |

`es_social` is listed in `required_apps`, so bench installs it first.

## DocTypes (module "ES Photos")

* **Photo Album** — tree (nested set) so albums can contain albums; slug URL, owner, privacy
  (Public / Connections / Group / Only Me), cover photo, photo order, cached counts.
* **Photo** — image or YouTube/Vimeo video; renditions (thumb/medium/large/original);
  EXIF (camera, lens, focal length, aperture, exposure, ISO, GPS); keywords; "also show in"
  albums (Piwigo virtual albums); view/like/comment counts.
* **Photo Keyword**, **Photo Comment**, **Photo Reaction**
* **ES Photos Settings** — gallery title, page size, member uploads, downloads, EXIF,
  comments/reactions switches, Piwigo import options.
* **Photo Import Log** — one row per import run with counts and a log.

A **Gallery Manager** role is created on install (full desk access to all of the above and
sees every album). Members with the **Social User** role can create their own albums and
upload when "Members can create albums" is ticked.

## Pages

| URL | What it shows |
|---|---|
| `/social/gallery` | Album grid, recently added, community albums |
| `/social/gallery/album/<slug>` | Sub-albums, justified photo grid, sort, slideshow, owner tools |
| `/social/gallery/photo/<id>` | Photo/video, prev/next (← →), fullscreen, download, details + EXIF, keywords, reactions, comments, share |
| `/social/gallery/keywords`, `/keyword/<slug>` | Keyword cloud and keyword pages |
| `/social/gallery/recent`, `/recent-albums`, `/most-visited`, `/random` | Discover views |
| `/social/gallery/calendar[/<y>[/<m>[/<d>]]]` | Browse by date taken |
| `/social/gallery/search?q=` | Title, description, keyword and album search |
| `/social/gallery/member/<slug>` | One member's albums and uploads (what the viewer is allowed to see) |
| `/social/gallery/upload` | Drag-and-drop multi-upload (3 at a time), create album inline, add video |

Uploads get EXIF read and three JPEG renditions (720 / 1600 / 2560 px) written to
`/files/es_photos/`.

## Install

Needs ES Social. Upgrade ES Social to **0.9.7** first (adds the nav-links hook and a
phone-friendly nav), then install ES Photos:

```bash
cd ~/frappe-bench
bench get-app https://github.com/<you>/es_photos   # or copy this folder into apps/
bench --site erp.enterprisesystems.com.au install-app es_photos
bench --site erp.enterprisesystems.com.au migrate
bench build --app es_photos
bench restart
```

Then open **ES Photos Settings** in the desk to check the defaults.

## Importing photos.tarrant-trading.com

The Piwigo site's web API (`ws.php`) is public, so no credentials are needed for public albums.

1. ES Photos Settings → check **Piwigo site URL** and pick an **Import mode**:
   * **Link remote images** (default) — creates every album/photo record but images keep
     being served by Piwigo. Fast, no disk use.
   * **Download into this site** — copies each image (XX-Large ≈1656 px, or Original) into
     Frappe and makes local renditions, so Piwigo can be retired. 7,400+ photos take a while
     and need disk space.
2. Click **New Piwigo import**, optionally tick **Dry run** first, then **Start import**.
   It runs on the `long` queue; refresh the log to watch progress.

What comes across: the album tree (with descriptions and Piwigo order), every photo with title,
description, date taken/added and view count, album covers, virtual-album memberships
(e.g. the Videos album), keywords, and gvideo YouTube/Vimeo entries as playable videos.
Re-running is safe — records are matched by `source_ref`, so only new items are added.

Imported albums are owned by the **Import owner** user and get the default privacy
(Piwigo private albums come in as "Only Me").

## Notes

* Re-runnable imports use a savepoint per photo, so one bad item never discards the others.
* Piwigo with PHP `display_errors` on prints warnings ahead of its JSON; the importer skips
  them. On photos.tarrant-trading.com this happens for
  `galleries/Kosciuszko_National_Park_NSW_AU/Kosciuszko_National_Park_NSW_AU_Photos_1365.png`,
  which Piwigo can't read — worth checking on that server.

* Album and photo pages are server-rendered (good for sharing previews: Open Graph tags are set).
* View counts increment once per visitor per hour.
* A daily job recounts album totals; **Recount albums** in settings does it on demand.
