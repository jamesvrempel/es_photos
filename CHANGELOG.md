# Changelog

## 0.6.1 — 2026-10-24

### Added
- **Copy linked photos in → Use files already on this server**: when the old site's folders
  (e.g. Piwigo's `galleries`, `upload`, `_data`) are on the server under the library folder,
  linked photos are switched to those files in place — no download or copy — using the old
  site's resized copies at once (`i.php?/…` derivatives map to `_data/i/…`), then ES Photos
  makes its own copies in the background. Photos whose file isn't found are left unchanged.

### Changed
- **Import folder** skips files that gallery photos already use (no duplicates after a
  relink) and ignores Piwigo's `_data` cache folders.
- Runbook: step 3a for a drive that already holds Piwigo's storage.

## 0.6.0 — 2026-10-22

### Added
- **Photo Library Job** (ES Photos → Library jobs) with two background jobs:
  - **Import folder** — folders under `public/files/es_photos/library/` become albums and
    sub-albums; images are used in place; re-runs only process new/changed files and can
    hide removed ones; dry run; cancel and resume. Tested with 1,200 photos in nested
    folders (0 errors, ~4 photos/s on 2 CPUs).
  - **Copy linked photos in** — downloads remotely-linked photos (Piwigo) into the server as
    originals or ≤1600 px JPEGs, keeping EXIF, albums, comments and reactions.
- `docs/STORAGE_AND_IMPORT.md` — runbook: dedicated drive (Proxmox passthrough, ext4,
  bind mount), copy-in, library import, retiring Piwigo, backups.

### Changed
- Faster resized copies: JPEGs decoded at reduced size, one rotation, cascaded
  large → medium → thumb; images read from disk without loading whole files into memory.
- Photos from a folder import stay hidden until their thumbnails exist.

## 0.5.0 — 2026-10-21

### Added
- **Default album sort** in ES Photos Settings (default *Date taken, newest first*), used by
  albums, keyword pages, photo-page next/previous and slideshows unless an album has its
  own Photo order. An album's Photo order can now be left blank ("Gallery default").

### Changed
- Patch `v0_5.default_album_sort` clears album orders nobody chose in ES Photos — the old
  auto-filled "Date added (newest first)" and orders copied from Piwigo on imported albums —
  so those albums follow the new default. Orders members picked themselves are kept.

### Fixed
- Keyword-page slideshows now play in the same order as the page.

## 0.4.0 — 2026-10-21

### Added
- **Exclude gallery photos from Google Drive backup** (ES Photos Settings → Backups, on by
  default). The Google Drive backup (scheduled or *Take Backup*) uploads the files archive
  without `public/files/es_photos`; database and all other files are still backed up.
  Other backups (local, S3, Dropbox) are unchanged. Uses Frappe's `before_job`/`after_job`
  hooks (`es_photos/backup.py`).

### Changed
- All gallery images now live under `public/files/es_photos/`: uploads and images attached
  in the desk are stored in `es_photos/originals/`. Patch
  `v0_4.gallery_files_to_own_folder` moves existing originals there (copying instead of
  moving any file another record also uses) and switches the new setting on.

## 0.3.0 — 2026-10-20

### Added
- Slideshow speed: **Slideshow seconds per photo** in ES Photos Settings (default 5,
  1–120) and a ⏱ seconds selector in the slideshow toolbar, remembered per browser;
  `-` / `+` keys change speed while viewing. The progress bar follows the chosen time.

## 0.2.0 — 2026-10-20

### Added
- **ES Photos** desk workspace: shortcuts (open gallery, upload, album tree, photos,
  comments to review, settings), quick lists and cards.
- GitHub-ready repository: `pyproject.toml` metadata, CI workflow (lint + Frappe v15
  server tests), pre-commit config, test suite.
- `gallery.reset_request_cache()`; per-viewer visibility cache is now cleared together with
  the album cache.

### Changed
- Gallery runs full screen (full browser width; site navbar and footer kept).
- `required_apps` uses `jamesvrempel/es_social` so bench can resolve it from GitHub.

### Removed
- Piwigo importer, **Photo Import Log** DocType and the Piwigo section of ES Photos
  Settings. Patch `v0_2.remove_piwigo_import` cleans existing sites and keeps every other
  setting.

## 0.1.0 — 2026-10-18

- First release: albums and sub-albums, photos and videos, keywords, discover views,
  calendar, search, EXIF, slideshow, uploads with renditions, reactions, comments,
  share to the ES Social feed, ES Social privacy and moderation, Piwigo importer.
