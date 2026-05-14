import unittest
import uuid
from pathlib import Path
import shutil

from urluploader.content import profile_for_direct, profile_for_social, profile_for_telegram
from urluploader.database import PremiumStore
from urluploader.models import RemoteFileInfo
from urluploader.names import normalize_mode
from urluploader.social import SocialInfo, SocialMediaItem

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def make_local_tmp() -> Path:
    path = TEST_TMP_ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class ContentProfilesTest(unittest.TestCase):
    def test_normalize_mode_supports_photo(self):
        self.assertEqual(normalize_mode("foto"), "photo")
        self.assertEqual(normalize_mode("image"), "photo")

    def test_direct_image_profile_is_contextual(self):
        profile = profile_for_direct(
            RemoteFileInfo(
                url="https://cdn.example.com/poster.jpg",
                filename="poster.jpg",
                size=123,
                mime_type="image/jpeg",
            )
        )
        self.assertEqual(profile.kind, "image")
        self.assertTrue(profile.can_send_photo)
        self.assertTrue(profile.can_generate_link)
        self.assertFalse(profile.can_send_audio)

    def test_social_video_profile_exposes_audio_and_quality(self):
        profile = profile_for_social(
            SocialInfo(
                url="https://www.youtube.com/watch?v=abc",
                title="Clip",
                author="Channel",
                duration=12.0,
                media_type="video",
                item_count=1,
                quality="at\u00e9 1080p",
                description=None,
                thumbnail=None,
                qualities=(1080, 720),
            )
        )
        self.assertEqual(profile.platform, "youtube")
        self.assertTrue(profile.can_extract_audio)
        self.assertTrue(profile.can_choose_quality)

    def test_crunchyroll_profile_is_detected(self):
        profile = profile_for_social(
            SocialInfo(
                url="https://www.crunchyroll.com/watch/ABC123/demo",
                title="Episode",
                author="Crunchyroll",
                duration=1200.0,
                media_type="video",
                item_count=1,
                quality="ate 1080p",
                description=None,
                thumbnail=None,
                qualities=(1080, 720),
            )
        )
        self.assertEqual(profile.platform, "crunchyroll")
        self.assertTrue(profile.can_choose_quality)

    def test_social_image_album_profile_stays_contextual(self):
        profile = profile_for_social(
            SocialInfo(
                url="https://x.com/test/status/1",
                title="Album",
                author="Autor",
                duration=None,
                media_type="album",
                item_count=4,
                quality=None,
                description=None,
                thumbnail=None,
                provider="gallery_dl",
                media_items=(
                    SocialMediaItem(url="https://cdn.example.com/1.jpg", filename="1.jpg", mime_type="image/jpeg", kind="image"),
                    SocialMediaItem(url="https://cdn.example.com/2.jpg", filename="2.jpg", mime_type="image/jpeg", kind="image"),
                ),
            )
        )
        self.assertEqual(profile.kind, "album")
        self.assertFalse(profile.can_choose_quality)
        self.assertFalse(profile.can_extract_audio)

    def test_telegram_photo_profile_prefers_photo_and_link(self):
        profile = profile_for_telegram("imagem.png", "image/png", is_image_message=True)
        self.assertEqual(profile.kind, "image")
        self.assertTrue(profile.can_send_photo)
        self.assertTrue(profile.can_generate_link)

    def test_document_profile_can_set_thumb(self):
        profile = profile_for_telegram("arquivo.pdf", "application/pdf", is_image_message=False)
        self.assertEqual(profile.kind, "document")
        self.assertTrue(profile.can_set_thumb)

    def test_recent_jobs_returns_latest_items(self):
        tmp = make_local_tmp()
        try:
            store = PremiumStore(tmp / "bot.sqlite3")
            store.create_job("a1", 10, "direct", "primeiro")
            store.update_job("a1", "running")
            store.create_job("a2", 10, "social", "segundo")
            store.update_job("a2", "done")
            jobs = store.recent_jobs(10, limit=2)
            self.assertEqual(len(jobs), 2)
            self.assertEqual(jobs[0]["job_id"], "a2")
            self.assertEqual(jobs[1]["job_id"], "a1")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
