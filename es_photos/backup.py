"""Leave the gallery out of Google Drive backups.

Frappe's Google Drive integration uploads tar archives of the whole
public/private files folders. When ES Photos Settings → "Exclude gallery
photos from Google Drive backup" is ticked, the Google Drive job (nightly /
weekly schedule, or "Take Backup" in the desk) gets archives built without
the gallery folder (public/files/es_photos — originals and renditions).

How: Frappe v15 runs `before_job` / `after_job` hooks around every background
job. For the Google Drive job only, `before_job` sets a flag and makes sure
three small wrappers are in place (each runs Frappe's original code untouched
unless the flag is set):

* BackupGenerator.backup_files — adds `--exclude <files>/es_photos` to tar;
* google_drive.new_backup — forces a fresh backup (Frappe would otherwise
  re-use a local backup made in the last 6 hours, which includes the gallery);
* google_drive.get_latest_backup_file — Google Drive re-uses the newest local
  backup when the database dump is over 1 GB; with the flag set it gets that
  database dump plus freshly built file archives without the gallery.

If backup encryption is on (System Settings), the fresh archives are encrypted
the same way Frappe encrypts its own.

Local `bench backup`, the scheduled local backups, S3 and Dropbox are not
affected.
"""

import os

import click
import frappe
from frappe.utils import cint

GOOGLE_DRIVE = "frappe.integrations.doctype.google_drive.google_drive"
GD_METHODS = {
	f"{GOOGLE_DRIVE}.upload_system_backup_to_google_drive",
	f"{GOOGLE_DRIVE}.daily_backup",
	f"{GOOGLE_DRIVE}.weekly_backup",
}
SCHEDULED_JOB_RUNNER = "frappe.core.doctype.scheduled_job_type.scheduled_job_type.run_scheduled_job"
FLAG = "esp_exclude_gallery_from_backup"


# --------------------------------------------------------------------------- job hooks


def is_google_drive_job(method: str | None, kwargs: dict | None) -> bool:
	if method in GD_METHODS:
		return True
	if method == SCHEDULED_JOB_RUNNER:
		return (kwargs or {}).get("job_type") in GD_METHODS
	return False


def exclusion_enabled() -> bool:
	try:
		return bool(cint(frappe.db.get_single_value("ES Photos Settings", "exclude_from_google_drive")))
	except Exception:
		return False


def before_job(method=None, kwargs=None, transaction_type=None):
	if is_google_drive_job(method, kwargs) and exclusion_enabled():
		install()
		frappe.flags[FLAG] = True


def after_job(method=None, kwargs=None, result=None):
	if frappe.flags.get(FLAG):
		frappe.flags[FLAG] = False


def active() -> bool:
	return bool(frappe.flags.get(FLAG))


# --------------------------------------------------------------------------- wrappers


def install():
	"""Put the two wrappers in place (idempotent, per worker process)."""
	from frappe.utils.backups import BackupGenerator

	if not getattr(BackupGenerator.backup_files, "_esp_wrapped", False):
		original = BackupGenerator.backup_files

		def backup_files(self, *args, **kwargs):
			if active():
				return backup_files_without_gallery(self)
			return original(self, *args, **kwargs)

		backup_files._esp_wrapped = True
		backup_files._esp_original = original
		BackupGenerator.backup_files = backup_files

	try:
		gd = frappe.get_module(GOOGLE_DRIVE)
	except Exception:
		return
	if not getattr(gd.new_backup, "_esp_wrapped", False):
		original_new = gd.new_backup

		def new_backup(*args, **kwargs):
			if active():
				kwargs["force"] = True
			return original_new(*args, **kwargs)

		new_backup._esp_wrapped = True
		gd.new_backup = new_backup
	if not getattr(gd.get_latest_backup_file, "_esp_wrapped", False):
		original_latest = gd.get_latest_backup_file

		def get_latest_backup_file(with_files=False):
			if active() and with_files:
				return latest_db_with_fresh_files(original_latest)
			return original_latest(with_files=with_files)

		get_latest_backup_file._esp_wrapped = True
		gd.get_latest_backup_file = get_latest_backup_file


def backup_files_without_gallery(gen):
	"""Frappe's BackupGenerator.backup_files, with the gallery folder excluded."""
	from es_photos.storage import gallery_path

	excluded = gallery_path()
	for folder in ("public", "private"):
		files_path = frappe.get_site_path(folder, "files")
		backup_path = gen.backup_path_files if folder == "public" else gen.backup_path_private_files
		exclude = f"--exclude={_q(excluded)} " if folder == "public" else ""

		if gen.compress_files:
			cmd = f"set -o pipefail; tar {exclude}-cf - {_q(files_path)} | gzip > {_q(backup_path)}"
		else:
			cmd = f"tar {exclude}-cf {_q(backup_path)} {_q(files_path)}"
		try:
			frappe.utils.execute_in_shell(cmd, verbose=gen.verbose, low_priority=True, check_exit_code=True)
		except frappe.CommandFailedError as e:
			if e.err and "file changed as we read it" in e.err:
				click.secho("Ignoring `tar: file changed as we read it` to prevent backup failure", fg="red")
			else:
				raise
	note = f"ES Photos: gallery folder {excluded} left out of the Google Drive files backup"
	if gen.verbose:
		click.secho(note, fg="yellow")
	frappe.logger("es_photos").info(note)


def latest_db_with_fresh_files(original_latest):
	"""Newest database/config backup + newly built file archives (gallery excluded)."""
	from frappe.utils.backups import BackupGenerator

	database, config = original_latest(with_files=False)
	gen = BackupGenerator(
		frappe.conf.db_name,
		frappe.conf.db_name,
		frappe.conf.db_password,
		db_socket=frappe.conf.db_socket,
		db_host=frappe.conf.db_host,
		db_port=frappe.conf.db_port,
		db_type=frappe.conf.db_type,
	)
	gen.set_backup_file_name()
	backup_files_without_gallery(gen)
	if frappe.get_system_settings("encrypt_backup"):
		gen.backup_path_db = ""  # the database dump is re-used as is; encrypt only the new archives
		gen.backup_encryption()
	return database, config, gen.backup_path_files, gen.backup_path_private_files


def _q(path: str) -> str:
	import shlex

	return shlex.quote(os.fspath(path))
