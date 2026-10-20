import os

import frappe


def esp_asset(path: str) -> str:
	"""Return an /assets URL stamped with the file's mtime (?v=...).

	Same idea as ES Social's es_asset(): Cloudflare + nginx's one-year max-age
	otherwise pin stale unversioned assets. Works for any installed app,
	e.g. esp_asset("/assets/es_social/css/es_social.css").
	"""
	if not path.startswith("/assets/"):
		return path
	rest = path[len("/assets/") :]
	app, _, rel = rest.partition("/")
	try:
		full = frappe.get_app_path(app, "public", rel)
		version = int(os.path.getmtime(full))
	except Exception:
		version = frappe.get_attr(f"{app}.__version__") if app else "0"
	return f"{path}?v={version}"
