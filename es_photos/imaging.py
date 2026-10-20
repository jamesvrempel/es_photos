"""Renditions (thumb / medium / large) and EXIF extraction with Pillow."""

import io
import os
from datetime import datetime

import frappe
from PIL import ExifTags, Image, ImageOps

RENDITIONS = {"thumb": (720, "th"), "medium": (1600, "md"), "large": (2560, "lg")}
FOLDER = "es_photos"

Image.MAX_IMAGE_PIXELS = 200_000_000


def _folder() -> str:
	path = frappe.get_site_path("public", "files", FOLDER)
	os.makedirs(path, exist_ok=True)
	return path


def local_path(file_url: str) -> str | None:
	if not file_url or not file_url.startswith("/files/"):
		return None
	path = frappe.get_site_path("public", file_url.lstrip("/"))
	return path if os.path.exists(path) else None


def _ratio(v):
	try:
		return float(v)
	except Exception:
		try:
			return v[0] / v[1]
		except Exception:
			return None


def read_exif(img: Image.Image) -> dict:
	out = {}
	try:
		exif = img.getexif()
	except Exception:
		return out
	if not exif:
		return out
	base = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
	try:
		sub = {ExifTags.TAGS.get(k, k): v for k, v in exif.get_ifd(0x8769).items()}
	except Exception:
		sub = {}
	tags = {**base, **sub}

	def clean(v):
		return str(v).strip("\x00 ").strip() if v else None

	out["camera_make"] = clean(tags.get("Make"))
	out["camera_model"] = clean(tags.get("Model"))
	out["lens"] = clean(tags.get("LensModel"))
	if (f := _ratio(tags.get("FocalLength"))) is not None:
		out["focal_length"] = f"{f:g} mm"
	if (a := _ratio(tags.get("FNumber"))) is not None:
		out["aperture"] = f"f/{a:.1f}".replace(".0", "")
	if (e := _ratio(tags.get("ExposureTime"))) is not None and e > 0:
		out["exposure_time"] = f"1/{round(1 / e)} s" if e < 1 else f"{e:g} s"
	iso = tags.get("ISOSpeedRatings") or tags.get("PhotographicSensitivity")
	if isinstance(iso, (list, tuple)):
		iso = iso[0] if iso else None
	if iso:
		try:
			out["iso"] = int(iso)
		except Exception:
			pass
	dt = tags.get("DateTimeOriginal") or tags.get("DateTime")
	if dt:
		try:
			out["date_taken"] = datetime.strptime(str(dt).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
		except Exception:
			pass
	try:
		gps = exif.get_ifd(0x8825)
		if gps and 2 in gps and 4 in gps:

			def deg(vals, ref):
				d, m, s = (_ratio(x) or 0 for x in vals)
				v = d + m / 60 + s / 3600
				return -v if ref in ("S", "W") else v

			out["latitude"] = round(deg(gps[2], gps.get(1)), 6)
			out["longitude"] = round(deg(gps[4], gps.get(3)), 6)
	except Exception:
		pass
	return {k: v for k, v in out.items() if v not in (None, "")}


def make_renditions(img: Image.Image, photo_name: str) -> dict:
	img = ImageOps.exif_transpose(img)
	if img.mode not in ("RGB", "L"):
		bg = Image.new("RGB", img.size, (255, 255, 255))
		try:
			bg.paste(img, mask=img.convert("RGBA").split()[-1])
		except Exception:
			bg.paste(img.convert("RGB"))
		img = bg
	folder = _folder()
	urls = {}
	longest = max(img.size)
	for key, (edge, suffix) in RENDITIONS.items():
		if key == "large" and longest <= RENDITIONS["medium"][0]:
			continue
		r = img.copy()
		r.thumbnail((edge, edge), Image.LANCZOS)
		fname = f"{photo_name}-{suffix}.jpg"
		r.save(os.path.join(folder, fname), "JPEG", quality=85 if key != "thumb" else 80, optimize=True,
		       progressive=True)
		urls[f"{key}_url"] = f"/files/{FOLDER}/{fname}"
	return urls


def process_image_bytes(photo, content: bytes) -> dict:
	img = Image.open(io.BytesIO(content))
	values = {"width": img.size[0], "height": img.size[1], "filesize": len(content)}
	for k, v in read_exif(img).items():
		if not photo.get(k):
			values[k] = v
	# exif orientation swaps dimensions
	t = ImageOps.exif_transpose(img)
	values["width"], values["height"] = t.size
	values.update(make_renditions(img, photo.name))
	return values


def process_local_image(photo):
	path = local_path(photo.image)
	if not path:
		return
	try:
		with open(path, "rb") as fh:
			values = process_image_bytes(photo, fh.read())
		values["original_url"] = photo.image
		for k, v in values.items():
			photo.set(k, v)
		frappe.db.set_value("Photo", photo.name, values, update_modified=False)
	except Exception:
		frappe.log_error(title=f"ES Photos: could not process {photo.name}")


def delete_renditions(photo_name: str):
	folder = frappe.get_site_path("public", "files", FOLDER)
	for _edge, suffix in RENDITIONS.values():
		p = os.path.join(folder, f"{photo_name}-{suffix}.jpg")
		if os.path.exists(p):
			try:
				os.remove(p)
			except OSError:
				pass
