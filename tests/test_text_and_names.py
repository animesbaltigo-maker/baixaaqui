import asyncio
import gc
import shutil
import uuid
from pathlib import Path
import unittest

from urluploader.database import PremiumStore
from urluploader.html_text import h, preserve
from urluploader.link_storage import LocalLinkStorage
from urluploader.names import extract_url, is_social_url, normalize_shared_url, sanitize_filename
from urluploader.premium_i18n import tx
from urluploader.social import SocialDownloader, SocialInfo, SocialMediaItem, _clean_progress, _friendly_gallery_error, _progressive_only_selector

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def make_local_tmp() -> Path:
    path = TEST_TMP_ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class TextAndNamesTest(unittest.TestCase):
    def test_html_escape(self):
        self.assertEqual(h("<b>oi</b>"), "&lt;b&gt;oi&lt;/b&gt;")

    def test_preserve_blank_lines(self):
        self.assertEqual(preserve("linha 1\n\nlinha 2"), "linha 1\n\nlinha 2")

    def test_i18n_escapes_values(self):
        rendered = tx("pt", "welcome", name="<Kayky>")
        self.assertIn("&lt;Kayky&gt;", rendered)

    def test_filename_sanitization(self):
        self.assertEqual(sanitize_filename("../video?.mp4"), "video_.mp4")

    def test_facebook_login_redirect_is_normalized(self):
        raw = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Fstory.php%3Fstory_fbid%3D1%26id%3D2"
        self.assertEqual(normalize_shared_url(raw), "https://www.facebook.com/story.php?story_fbid=1&id=2")

    def test_html_escaped_query_is_normalized(self):
        raw = "https://www.tiktok.com/@demo/photo/123?_r=1&amp;_t=abc"
        self.assertEqual(normalize_shared_url(raw), "https://www.tiktok.com/@demo/photo/123?_r=1&_t=abc")

    def test_tracking_params_are_removed_from_shared_url(self):
        raw = "https://youtu.be/abc?si=share&utm_source=telegram&v=keep&feature=share"
        self.assertEqual(normalize_shared_url(raw), "https://youtu.be/abc?v=keep")

    def test_extract_url_strips_sentence_punctuation(self):
        raw = 'baixa esse: https://www.youtube.com/watch?v=abc&utm_medium=x).'
        self.assertEqual(extract_url(raw), "https://www.youtube.com/watch?v=abc")

    def test_crunchyroll_is_social_url(self):
        self.assertTrue(is_social_url("https://www.crunchyroll.com/watch/ABC123/demo"))

    def test_social_url_rejects_lookalike_host(self):
        self.assertFalse(is_social_url("https://youtube.com.evil.example/watch?v=abc"))

    def test_link_storage_quotes_filename(self):
        root = make_local_tmp()
        try:
            source = root / "arquivo com espaço.png"
            source.write_bytes(b"abc")
            storage = LocalLinkStorage(root / "public", "https://example.com/files", 24)
            stored = asyncio.run(storage.store(source))
            self.assertIn("arquivo%20com%20espa%C3%A7o.png", stored.public_url)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_link_storage_store_bytes_supports_ephemeral_payload(self):
        root = make_local_tmp()
        try:
            storage = LocalLinkStorage(root / "public", "https://example.com/files", 24)
            stored = asyncio.run(storage.store_bytes(b"abc", "imagem.png", mime_type="image/png", ttl_seconds=120))
            self.assertEqual(stored.size, 3)
            self.assertEqual(stored.mime_type, "image/png")
            self.assertTrue(stored.internal_path.exists())
            self.assertIn("/imagem.png", stored.public_url)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_i18n_translates_new_buttons(self):
        self.assertEqual(tx("en", "btn_back"), "⬅️ Back")
        self.assertIn("portada", tx("es", "btn_set_thumb").lower())

    def test_social_progress_cleanup(self):
        text = _clean_progress("[download]  71.2% of 142.00MiB at 13.46MiB/s ETA 00:12")
        self.assertEqual(text, "71.20%\n[▪▪▪▪▪▪▪▫▫▫]\n101.1 MB / 142.0 MB • 13.46MiB/s • ETA 00:12")

    def test_progressive_only_selector_removes_merge_formats(self):
        selector = (
            "best[height=720][ext=mp4][acodec!=none][vcodec!=none]/"
            "bestvideo[height=720][ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo[height<=720]+bestaudio/"
            "best[height<=720][ext=mp4]/best"
        )
        self.assertEqual(
            _progressive_only_selector(selector),
            "best[height=720][ext=mp4][acodec!=none][vcodec!=none]/best[height<=720][ext=mp4]/best",
        )

    def test_social_downloader_uses_progressive_fallback_without_ffprobe(self):
        downloader = SocialDownloader(1024 * 1024 * 200, "best[ext=mp4][acodec!=none]/bestvideo+bestaudio/best")
        downloader.ffmpeg = None
        downloader.ffprobe = None
        downloader.can_postprocess = False
        cmd = downloader._build_command(
            "https://www.youtube.com/watch?v=abc",
            TEST_TMP_ROOT,
            "video",
            "best[ext=mp4][acodec!=none]/bestvideo+bestaudio/best",
        )
        joined = " ".join(cmd)
        self.assertNotIn("--merge-output-format", joined)
        self.assertIn("-f best[ext=mp4][acodec!=none]/best", joined)

    def test_social_downloader_keeps_audio_download_without_ffmpeg(self):
        downloader = SocialDownloader(1024 * 1024 * 200, "best[ext=mp4][acodec!=none]/best")
        downloader.ffmpeg = None
        downloader.ffprobe = None
        downloader.can_postprocess = False
        cmd = downloader._build_command("https://music.youtube.com/watch?v=abc", TEST_TMP_ROOT, "audio")
        joined = " ".join(cmd)
        self.assertNotIn(" --audio-format mp3", joined)
        self.assertNotIn(" -x ", f" {joined} ")
        self.assertIn("bestaudio[ext=m4a]", joined)

    def test_social_downloader_uses_crunchyroll_cookie_file(self):
        root = make_local_tmp()
        try:
            cookie_file = root / "crunchyroll.txt"
            cookie_file.write_text(
                "# Netscape HTTP Cookie File\n"
                ".crunchyroll.com\tTRUE\t/\tTRUE\t1893456000\tetp_rt\tsecret\n",
                encoding="utf-8",
            )
            downloader = SocialDownloader(
                1024 * 1024 * 200,
                "best[ext=mp4][acodec!=none]/best",
                platform_cookies={"crunchyroll": str(cookie_file)},
            )
            cmd = downloader._build_command("https://www.crunchyroll.com/watch/ABC123/demo", root, "video")
            self.assertIn("--cookies", cmd)
            self.assertIn(str(cookie_file), cmd)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_social_downloader_passes_proxy_to_ytdlp(self):
        downloader = SocialDownloader(
            1024 * 1024 * 200,
            "best[ext=mp4][acodec!=none]/best",
            proxy="http://127.0.0.1:8080",
        )
        cmd = downloader._build_command("https://www.youtube.com/watch?v=abc", TEST_TMP_ROOT, "video")
        self.assertIn("--proxy", cmd)
        self.assertIn("http://127.0.0.1:8080", cmd)

    def test_social_info_round_trips_gallery_items(self):
        info = SocialInfo(
            url="https://x.com/test/status/1",
            title="Fotos",
            author="Autor",
            duration=None,
            media_type="album",
            item_count=2,
            quality=None,
            description="Legenda",
            thumbnail=None,
            provider="gallery_dl",
            media_items=(
                SocialMediaItem(url="https://cdn.example.com/a.jpg", filename="a.jpg", mime_type="image/jpeg", kind="image"),
                SocialMediaItem(url="https://cdn.example.com/b.jpg", filename="b.jpg", mime_type="image/jpeg", kind="image"),
            ),
        )
        rebuilt = SocialInfo.from_dict(info.to_dict())
        self.assertEqual(rebuilt.provider, "gallery_dl")
        self.assertEqual(len(rebuilt.media_items), 2)
        self.assertEqual(rebuilt.media_items[0].filename, "a.jpg")

    def test_gallery_auth_error_is_humanized_for_instagram(self):
        message = _friendly_gallery_error(
            "https://www.instagram.com/stories/demo/123",
            "401 Unauthorized for https://www.instagram.com/web/search/topsearch/?query=demo",
        )
        self.assertEqual(message, "[instagram-auth-required]")

    def test_cleanup_expired_links_marks_deleted(self):
        tmp = make_local_tmp()
        try:
            store = PremiumStore(tmp / "bot.sqlite3")
            store.record_link(
                link_id="abc",
                user_id=1,
                public_url="https://example.com/a.png",
                internal_path=str(tmp / "public" / "a.png"),
                filename="a.png",
                mime_type="image/png",
                size=123,
                sha256="hash",
                expires_at=1,
            )
            expired = store.cleanup_expired_links()
            self.assertEqual(len(expired), 1)
            self.assertTrue(expired[0].endswith("a.png"))
            del store
            gc.collect()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
