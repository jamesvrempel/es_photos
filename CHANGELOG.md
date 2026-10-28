# Changelog

## 0.6.6 — 2026-10-28

### Added
- **Album order**: ES Photos Settings → Album order — Name (A to Z) (the default), Name (Z to A),
  Recently updated, Newest albums first, or Manual (each album's Sort order, the previous
  behaviour). Applies to the gallery home page, the sidebar album list, sub-albums and a
  member's albums. Names sort case-insensitively and naturally ("Trip 2" before "Trip 10").
- A **Sort albums** menu on the gallery home page lets visitors switch order (`?asort=`).
- The upload page's album list is always A to Z.

### Added (scripts)
- `scripts/fix_duplicate_import.py` — undoes an Import folder run that duplicated albums
  after Piwigo's folders were moved within the library.

## 0.6.5 — 2026-10-26

### Added
- Duplicate detection on upload: a photo whose content is identical to one already in the
  album (not deleted) isn't added again — its tile says **already in this album** and the
  summary counts it as skipped. Matched on file content (MD5), not file name, so a camera
  reusing names like `DSCF0001.jpg` still uploads, and re-uploading a folder after a partial
  batch only adds what's missing. The same photo in a different album is still added.
- Photo gets a hidden, indexed **Content hash** field (the file as uploaded). Photos uploaded
  before 0.6.5 are matched through their stored file's hash.

## 0.6.4 — 2026-10-26

### Fixed
- Upload page could stall on batches of large camera photos: it showed a full-size preview
  of every chosen file, and decoding dozens of 20–40 MP JPEGs in the page froze the browser.
  The queue now shows each file's name and size, and the server's thumbnail once uploaded.
- A photo whose connection dropped or never got an answer stayed on "uploading" forever.
  Uploads now time out after 10 minutes, are retried once automatically after a dropped
  connection or gateway timeout (502/503/504/52x), and a failed photo can be tapped to retry.
- Progress shows as a percentage, then "processing…" while the server makes the resized copies.
- Two uploads at a time instead of three, to go easier on slow upload links.

## 0.6.3 — 2026-10-24

### Fixed
- Uploads of photos over 25 MB failed with HTTP 413 even after raising System Settings →
  Max File Size. Frappe applies that setting only to its own `upload_file` endpoint; the
  gallery's upload is capped by the site config key **`max_file_size`** (bytes, default
  25 MB). The gallery's limit is now never higher than that cap, so an oversized photo is
  stopped in the browser with the real limit instead of failing on the server.

### Note
- To allow photos over 25 MB:
  `bench --site <site> set-config -p max_file_size 104857600` (100 MB), then
  `sudo supervisorctl restart all`. nginx (bench config: 50 MB) and Cloudflare (100 MB) also
  cap uploads.

## 0.6.2 — 2026-10-24

### Fixed
- Upload page: a failed photo now shows **why** on the photo itself (too large, web-server
  limit, session expired, server error) instead of only "failed"; a summary message appears
  when uploads fail.
- Photos over the upload limit are rejected in the browser before uploading, with the size
  and the limit.
- Photos whose browser-reported type is empty (some phones / cloud folders) are accepted by
  file extension instead of being silently ignored; non-photos are reported.

### Note
- The upload limit is **ES Photos Settings → Max upload size (MB)**; when 0 it uses
  **ES Social Settings → Max upload size**, whose default is only **5 MB** — too small for
  most camera photos. Set one of them to 50 or more.

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
