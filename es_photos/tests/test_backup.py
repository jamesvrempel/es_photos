# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Gallery files are kept in one folder and left out of Google Drive backups."""

import os
import tarfile
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from es_photos import backup as B
from es_photos import storage
from es_photos.tests.helpers import album, jpeg, photo, user

GD = B.GOOGLE_DRIVE


def members(path):
	with tarfile.open(path) as t:
		return t.getnames()


class TestBackup(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		owner = user("esp_b_owner@example.com")
		cls.album = album(owner, "ESP B Album")
		cls.photo = photo(cls.album, "backup test", owner)
		cls.file = storage.save_original(cls.photo, "My Holiday (1).JPG", jpeg())
		# an ordinary site file that must stay in every backup
		cls.other = frappe.get_doc(
			{"doctype": "File", "file_name": "esp_b_keep.txt", "content": b"keep me", "is_private": 0}
		).insert(ignore_permissions=True)
		frappe.db.set_single_value("ES Photos Settings", "exclude_from_google_drive", 1)

	def tearDown(self):
		frappe.flags[B.FLAG] = False

	# ---------------------------------------------------------------- storage

	def test_original_saved_in_gallery_folder(self):
		self.assertTrue(self.file.file_url.startswith("/files/es_photos/originals/"))
		top_level = os.listdir(frappe.get_site_path("public", "files"))
		self.assertNotIn(os.path.basename(self.file.file_url), top_level)  # no stray copy
		self.assertTrue(self.file.file_url.endswith(f"/{self.photo}-My_Holiday_1.jpg"), self.file.file_url)
		self.assertTrue(os.path.isfile(frappe.get_site_path("public", self.file.file_url.lstrip("/"))))

	def test_relocate_moves_unshared_file(self):
		p = photo(self.album, "relocate")
		f = frappe.get_doc(
			{"doctype": "File", "file_name": "esp_b_loose.jpg", "content": jpeg(1100, 700), "is_private": 0,
			 "attached_to_doctype": "Photo", "attached_to_name": p, "attached_to_field": "image"}
		).insert(ignore_permissions=True)
		old_path = frappe.get_site_path("public", f.file_url.lstrip("/"))
		new = storage.relocate_original(p, f.file_url)
		self.assertTrue(new.startswith("/files/es_photos/originals/"))
		self.assertFalse(os.path.exists(old_path))
		self.assertEqual(frappe.db.get_value("File", f.name, "file_url"), new)
		self.assertEqual(frappe.db.get_value("Photo", p, "image"), new)

	def test_relocate_copies_shared_file(self):
		p = photo(self.album, "shared")
		shared = frappe.get_doc(
			{"doctype": "File", "file_name": "esp_b_shared.jpg", "content": jpeg(640, 480), "is_private": 0}
		).insert(ignore_permissions=True)
		new = storage.relocate_original(p, shared.file_url)
		self.assertTrue(os.path.exists(frappe.get_site_path("public", shared.file_url.lstrip("/"))))  # still there
		self.assertTrue(os.path.exists(frappe.get_site_path("public", new.lstrip("/"))))
		self.assertEqual(frappe.db.get_value("File", shared.name, "file_url"), shared.file_url)

	# ---------------------------------------------------------------- job detection

	def test_google_drive_jobs_detected(self):
		self.assertTrue(B.is_google_drive_job(f"{GD}.upload_system_backup_to_google_drive", {}))
		self.assertTrue(B.is_google_drive_job(B.SCHEDULED_JOB_RUNNER, {"job_type": f"{GD}.daily_backup"}))
		self.assertTrue(B.is_google_drive_job(B.SCHEDULED_JOB_RUNNER, {"job_type": f"{GD}.weekly_backup"}))
		self.assertFalse(B.is_google_drive_job(B.SCHEDULED_JOB_RUNNER, {"job_type": "frappe.utils.backups.backup"}))
		self.assertFalse(B.is_google_drive_job("frappe.integrations.doctype.s3_backup_settings.s3_backup_settings.take_backups_s3", {}))

	def test_setting_off_means_no_flag(self):
		frappe.db.set_single_value("ES Photos Settings", "exclude_from_google_drive", 0)
		try:
			B.before_job(method=f"{GD}.upload_system_backup_to_google_drive", kwargs={})
			self.assertFalse(B.active())
		finally:
			frappe.db.set_single_value("ES Photos Settings", "exclude_from_google_drive", 1)

	# ---------------------------------------------------------------- end to end

	def _run_google_drive(self, create_new_backup=True):
		"""Run Frappe's real Google Drive upload with the Google API mocked out;
		return the local archive paths it tried to upload."""
		gd = frappe.get_module(GD)
		account = MagicMock(file_backup=1, backup_folder_id="folder")
		uploaded = []

		def fake_media(path, **kw):
			uploaded.append(path)
			return MagicMock()

		def fake_validate():
			frappe.flags.create_new_backup = create_new_backup

		B.before_job(method=f"{GD}.upload_system_backup_to_google_drive", kwargs={})
		with patch.object(gd, "get_google_drive_object", return_value=(MagicMock(), account)), patch.object(
			gd, "check_for_folder_in_google_drive"
		), patch.object(gd, "validate_file_size", fake_validate), patch.object(
			gd, "MediaFileUpload", fake_media
		), patch.object(gd, "send_email"), patch.object(gd, "set_progress"):
			gd.upload_system_backup_to_google_drive()
		B.after_job(method=f"{GD}.upload_system_backup_to_google_drive")
		return uploaded

	def _public_archive(self, uploaded):
		files = [p for p in uploaded if "-files" in os.path.basename(p) and "private" not in os.path.basename(p)]
		self.assertEqual(len(files), 1, uploaded)
		return members(files[0])

	def test_google_drive_upload_leaves_gallery_out(self):
		names = self._public_archive(self._run_google_drive())
		self.assertFalse([n for n in names if "/files/es_photos" in n], "gallery files were uploaded")
		self.assertTrue([n for n in names if n.endswith("/esp_b_keep.txt")], "ordinary files are missing")
		self.assertFalse(B.active())  # flag cleared after the job

	def test_reused_backup_path_also_leaves_gallery_out(self):
		# a fresh local backup with files exists (it includes the gallery) ...
		from frappe.utils.backups import new_backup

		local = new_backup(ignore_files=False, force=True)
		self.assertTrue([n for n in members(local.backup_path_files) if "/files/es_photos/" in n])
		# ... but when Google Drive re-uses backups, it gets new archives without the gallery
		names = self._public_archive(self._run_google_drive(create_new_backup=False))
		self.assertFalse([n for n in names if "/files/es_photos" in n])
		self.assertTrue([n for n in names if n.endswith("/esp_b_keep.txt")])

	def test_local_backups_unchanged(self):
		from frappe.utils.backups import new_backup

		B.install()  # wrappers in place, but no Google Drive job running
		local = new_backup(ignore_files=False, force=True)
		names = members(local.backup_path_files)
		self.assertTrue([n for n in names if "/files/es_photos/originals/" in n])
