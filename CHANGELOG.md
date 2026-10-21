# Changelog

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
