# Copyright (c) 2026, Enterprise Systems Australia and contributors
"""Pure helpers: slugs, video links, EXIF and renditions."""

import io

from frappe.tests.utils import FrappeTestCase
from PIL import Image

from es_photos.imaging import make_renditions, read_exif
from es_photos.tests.helpers import jpeg
from es_photos.utils import human_size, slugify, video_embed, video_thumb


class TestUtils(FrappeTestCase):
	def test_slugify(self):
		self.assertEqual(slugify("Walpole WA AU — October 2026!"), "walpole-wa-au-october-2026")
		self.assertEqual(slugify(""), "item")
		self.assertTrue(len(slugify("x" * 500)) <= 120)

	def test_video_links(self):
		self.assertEqual(
			video_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
			"https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0",
		)
		self.assertEqual(video_embed("https://youtu.be/dQw4w9WgXcQ"), video_embed("https://youtube.com/shorts/dQw4w9WgXcQ"))
		self.assertEqual(video_embed("https://vimeo.com/76979871"), "https://player.vimeo.com/video/76979871")
		self.assertIsNone(video_embed("https://example.com/clip.mp4"))
		self.assertEqual(video_thumb("https://youtu.be/dQw4w9WgXcQ"), "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")

	def test_human_size(self):
		self.assertEqual(human_size(512), "512 B")
		self.assertEqual(human_size(2048), "2.0 KB")

	def test_exif(self):
		ex = read_exif(Image.open(io.BytesIO(jpeg())))
		self.assertEqual(ex["camera_model"], "X-T5")
		self.assertEqual(ex["aperture"], "f/5.6")
		self.assertEqual(ex["exposure_time"], "1/250 s")
		self.assertEqual(ex["iso"], 200)
		self.assertEqual(ex["date_taken"].year, 2026)

	def test_renditions(self):
		urls = make_renditions(Image.open(io.BytesIO(jpeg(3000, 2000))), "esptestrend")
		self.assertEqual(set(urls), {"thumb_url", "medium_url", "large_url"})
		small = make_renditions(Image.open(io.BytesIO(jpeg(1000, 600))), "esptestrend2")
		self.assertNotIn("large_url", small)  # no upscaled "large" for small images
		from es_photos.imaging import delete_renditions

		delete_renditions("esptestrend")
		delete_renditions("esptestrend2")
