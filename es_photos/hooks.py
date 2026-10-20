from es_photos import __version__

app_name = "es_photos"
app_title = "ES Photos"
app_publisher = "Enterprise Systems Australia"
app_description = "Photo gallery for ES Social — albums, keywords, EXIF and slideshows"
app_email = "james.rempel@enterprisesystems.com.au"
app_license = "mit"

# The gallery lives inside ES Social (/social/gallery) and reuses its
# profiles, connections, groups, blocks, moderation settings and feed.
# "org/repo" lets `bench get-app --resolve-deps` fetch ES Social from GitHub;
# keep this on one line (bench reads it with a single-line regex).
required_apps = ["frappe", "jamesvrempel/es_social"]

# "Gallery" in the ES Social top nav. ES Social >= 0.9.7 renders links from
# this hook server-side; es_social_nav.js covers older ES Social versions.
es_social_nav_links = [
	{"label": "Gallery", "route": "/social/gallery"},
]
web_include_js = [f"/assets/es_photos/js/es_social_nav.js?v={__version__}"]

# /social/gallery/<anything> is handled by www/social/gallery.py
website_route_rules = [
	{"from_route": "/social/gallery/<path:gpath>", "to_route": "social/gallery"},
]

jinja = {
	"methods": [
		"es_photos.jinja.esp_asset",
	],
}

after_install = "es_photos.install.after_install"
after_migrate = "es_photos.install.after_migrate"

doc_events = {
	"Social Post": {
		# keep album/photo links clean if a feed post is removed in ES Social
		"on_trash": "es_photos.integration.on_social_post_trash",
	},
}

scheduler_events = {
	"daily": ["es_photos.gallery.recount_all"],
}
