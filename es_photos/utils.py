import re

import frappe

_YT = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_VIMEO = re.compile(r"vimeo\.com/(?:video/)?(\d+)")


def slugify(text: str) -> str:
	text = (text or "").lower()
	text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
	return text[:120] or "item"


def unique_slug(doctype: str, field: str, text: str) -> str:
	base = slugify(text)
	slug, i = base, 2
	while frappe.db.exists(doctype, {field: slug}) or frappe.db.exists(doctype, slug):
		slug = f"{base}-{i}"
		i += 1
	return slug


def youtube_id(url: str | None) -> str | None:
	m = _YT.search(url or "")
	return m.group(1) if m else None


def vimeo_id(url: str | None) -> str | None:
	m = _VIMEO.search(url or "")
	return m.group(1) if m else None


def video_embed(url: str | None) -> str | None:
	if yt := youtube_id(url):
		return f"https://www.youtube-nocookie.com/embed/{yt}?rel=0"
	if vm := vimeo_id(url):
		return f"https://player.vimeo.com/video/{vm}"
	return None


def video_thumb(url: str | None) -> str | None:
	if yt := youtube_id(url):
		return f"https://i.ytimg.com/vi/{yt}/hqdefault.jpg"
	return None


def strip_html(text: str | None) -> str:
	if not text:
		return ""
	from frappe.utils import strip_html as _strip

	return _strip(text).strip()


def human_size(n) -> str:
	n = float(n or 0)
	for unit in ("B", "KB", "MB", "GB"):
		if n < 1024 or unit == "GB":
			return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
		n /= 1024
	return ""
