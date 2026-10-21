# ES Photos

[![CI](https://github.com/jamesvrempel/es_photos/actions/workflows/ci.yml/badge.svg)](https://github.com/jamesvrempel/es_photos/actions/workflows/ci.yml)
![Frappe v15](https://img.shields.io/badge/Frappe-v15-0089FF)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A Piwigo-style photo library for Frappe v15 that lives inside **ES Social** at
`/social/gallery`: albums and sub-albums, keywords, most visited / recent / random /
calendar views, search, EXIF, slideshow, downloads and YouTube/Vimeo videos, plugged into
ES Social's people, privacy and feed. The gallery runs full screen (full browser width; the
site navbar and footer stay).

## Requirements

| | Version |
|---|---|
| Frappe | v15 (`version-15` branch) |
| Python | 3.10 – 3.12 |
| [ES Social](https://github.com/jamesvrempel/es_social) | 0.9.7 or later recommended (0.9.6 works; the Gallery nav link is then added by script) |
| Pillow | ships with Frappe |

No ERPNext dependency.

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

`required_apps = ["frappe", "jamesvrempel/es_social"]`, so `install-app es_photos` installs ES Social on the site first, and `bench get-app --resolve-deps` can fetch it from GitHub.

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
| `/social/gallery/album/<slug>` | Sub-albums, justified photo grid, sort, slideshow (adjustable seconds per photo), owner tools |
| `/social/gallery/photo/<id>` | Photo/video, prev/next (← →), fullscreen, download, details + EXIF, keywords, reactions, comments, share |
| `/social/gallery/keywords`, `/keyword/<slug>` | Keyword cloud and keyword pages |
| `/social/gallery/recent`, `/recent-albums`, `/most-visited`, `/random` | Discover views |
| `/social/gallery/calendar[/<y>[/<m>[/<d>]]]` | Browse by date taken |
| `/social/gallery/search?q=` | Title, description, keyword and album search |
| `/social/gallery/member/<slug>` | One member's albums and uploads (what the viewer is allowed to see) |
| `/social/gallery/upload` | Drag-and-drop multi-upload (3 at a time), create album inline, add video |

**Slideshow speed.** ES Photos Settings → *Slideshow seconds per photo* sets the default
(5 s; 1–120). In the slideshow toolbar the ⏱ selector changes it (1 s … 2 min) and the
visitor's browser remembers the choice; the `-` / `+` keys go faster / slower. Other
shortcuts: ← → next/previous, space play/pause, Esc close.

Uploads get EXIF read and three JPEG renditions (720 / 1600 / 2560 px) written to
`/files/es_photos/`.

## Install

ES Social must be in the bench first. It is a private repository, so fetch it with an
account (or deploy key / token) that can read it:

```bash
cd ~/frappe-bench

# 1. ES Social (skip if already installed; upgrade to 0.9.7+ if older)
bench get-app https://github.com/jamesvrempel/es_social --branch main

# 2. ES Photos
bench get-app https://github.com/jamesvrempel/es_photos --branch main

# 3. Install on the site (installs es_social first if it isn't yet)
bench --site <your-site> install-app es_photos
bench --site <your-site> migrate
bench build --app es_photos
bench restart          # or: sudo supervisorctl restart all
```

`bench get-app --resolve-deps https://github.com/jamesvrempel/es_photos` fetches ES Social
automatically when your git credentials can read it.

After installing:

1. Desk → **ES Photos** workspace → **Settings**: check gallery title, page size, upload
   size, downloads, EXIF, comments and reactions.
2. Give gallery admins the **Gallery Manager** role (created on install). Members with
   ES Social's **Social User** role can create albums and upload when
   "Members can create albums and upload" is ticked.
3. Open `/social/gallery`.

### Updating

```bash
cd ~/frappe-bench
bench update --apps es_photos --pull     # or: cd apps/es_photos && git pull
bench --site <your-site> migrate
bench build --app es_photos && bench restart
```

### Backups and the gallery

All gallery images live in one folder:

```
sites/<site>/public/files/es_photos/originals/   uploaded originals
sites/<site>/public/files/es_photos/             thumb / medium / large copies
```

**ES Photos Settings → Backups → "Exclude gallery photos from Google Drive backup"**
(on by default) makes Frappe's Google Drive backup — the nightly/weekly schedule and the
*Take Backup* button under Integrations → Google Drive — upload its files archive without
that folder. The database backup still includes every album, photo record, comment and
setting; only the image files are left out. Local `bench backup`, S3 and Dropbox backups are
not changed.

It works through Frappe v15's `before_job` / `after_job` hooks: only while the Google Drive
job runs, tar gets `--exclude <files>/es_photos`, and Google Drive is made to build fresh
archives instead of re-using a recent local backup (which would include the gallery). See
`es_photos/backup.py`.

Keep a copy of the gallery some other way if you need one, e.g. a nightly
`rsync -a sites/<site>/public/files/es_photos/ /backup/es_photos/`.

### Production notes

* Uploaded originals and renditions are public files under
  `sites/<site>/public/files/es_photos/` (see *Backups and the gallery*).
* Allow large uploads through nginx: `client_max_body_size` must be at least the
  configured max upload size (ES Photos Settings, or ES Social Settings when 0).
* Static assets are cache-busted with `?v=<app version / file mtime>`, so Cloudflare or a
  long nginx `max-age` will not serve stale CSS/JS after an update.
* The daily scheduler job `es_photos.gallery.recount_all` keeps album counts right; make
  sure the scheduler is enabled (`bench --site <site> enable-scheduler`).

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

## Development

```bash
cd ~/frappe-bench/apps/es_photos
pip install pre-commit && pre-commit install   # ruff + basic checks on commit
ruff check .

# tests need a throw-away site with es_social + es_photos installed
bench --site test.local set-config allow_tests true
bench --site test.local run-tests --app es_photos
```

Tests (`es_photos/tests/`) cover the privacy matrix (public / connections / group /
only me / nested albums / blocks / suspension), comment moderation, reactions, feed sharing
and the image helpers.

### CI

`.github/workflows/ci.yml` runs on pushes and pull requests to `main` / `develop`:

* **Lint** — ruff, compile check, JSON validity (always).
* **Server tests** — Frappe v15 bench with MariaDB 10.6 and Redis, installs ES Social and
  ES Photos and runs the test suite. Because ES Social is private, add a repository secret
  **`ES_SOCIAL_TOKEN`** (fine-grained personal access token with read-only *Contents* access
  to `jamesvrempel/es_social`). Without it the job is skipped with a notice.

## Notes

* Album and photo pages are server-rendered (good for sharing previews: Open Graph tags are set).
* View counts increment once per visitor per hour.
* A daily job recounts album totals; **Recount albums** in settings does it on demand.

## Licence

MIT — see [LICENSE](LICENSE).
