# ES Photos

A photo gallery app for Frappe v15 that lives inside **ES Social** at `/social/gallery`.
A Piwigo-style photo library — albums and sub-albums, keywords, most visited / recent /
random / calendar views, search, EXIF, slideshow, downloads, videos — plugged into ES
Social's people, privacy and feed. The gallery runs full screen (full browser width; the
site navbar and footer stay).

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
  albums; view/like/comment counts.
* **Photo Keyword**, **Photo Comment**, **Photo Reaction**
* **ES Photos Settings** — gallery title, page size, member uploads, downloads, EXIF,
  comments/reactions switches.

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

## Desk workspace

**ES Photos** in the desk sidebar (Gallery Manager / System Manager) has shortcuts to open
the gallery, upload, the album tree, all photos (with a count), comments waiting for review
and settings; quick lists of recently added photos and recently updated albums; and cards
linking every ES Photos DocType plus ES Social Settings.

## Upgrading from 0.1.x

0.2.0 removes the Piwigo importer. `bench migrate` runs a patch that drops the
Photo Import Log DocType and table and clears only the Piwigo fields (URL, username,
password, import options) from ES Photos Settings — every other setting is kept as it is.
Albums and photos that were imported stay where they are.

## Notes


* Album and photo pages are server-rendered (good for sharing previews: Open Graph tags are set).
* View counts increment once per visitor per hour.
* A daily job recounts album totals; **Recount albums** in settings does it on demand.
