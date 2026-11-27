#!/usr/bin/env python3
"""
Mindforge - Phase 3 YouTube uploader test suite.

Run:  python test_uploader.py

ALL YouTube interactions are mocked (fake service objects) - no network, no
real uploads, no real tokens. Secrets used in tests are obviously fake strings
and never touch a real endpoint.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import youtube_uploader as yu  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

FAKE_CLIENT_ID = "fake-client-id.apps.googleusercontent.com"
FAKE_SECRET = "fake-client-secret"
FAKE_REFRESH = "fake-refresh-token"


class FakeResp:
    def __init__(self, status):
        self.status = status
        self.reason = "fake"


def http_error(status):
    return HttpError(resp=FakeResp(status), content=b'{"error": {"code": %d}}' % status)


class FakeChunkRequest:
    """Emulates videos().insert(...).next_chunk() with a scripted sequence."""

    def __init__(self, script):
        self._script = list(script)   # items: ("err", status) | ("resp", dict)

    def next_chunk(self):
        if not self._script:
            return None, None
        kind, val = self._script.pop(0)
        if kind == "err":
            raise http_error(val)
        return None, val


class FakeVideos:
    def __init__(self, insert_script):
        self._insert_script = insert_script
        self.inserted_parts = []
        self.inserted_bodies = []

    def insert(self, part=None, body=None, media_body=None):
        self.inserted_parts.append(part)
        self.inserted_bodies.append(body)
        return FakeChunkRequest(self._insert_script)


class FakeService:
    def __init__(self, videos):
        self._videos = videos
        self.videos_api = videos

    def videos(self):
        return self._videos


def tiny_mp4(path):
    Path(path).write_bytes(b"\x00\x00\x00\x18ftypisom" + b"0" * 2048)
    return Path(path)


SAMPLE_PKG = {
    "date": "2026-11-14",
    "title": "The Dark Truth About Self-Compassion",
    "description": "Self-Compassion Beats Self-Criticism explained in 60 seconds.",
    "tags": ["psychology", "mindset"],
    "scenes": [],
}


# ---------------------------------------------------------------------------
# Metadata & scope
# ---------------------------------------------------------------------------
class TestMetadata(unittest.TestCase):
    def test_privacy_is_always_private(self):
        body = yu.metadata_from_pkg(SAMPLE_PKG)
        self.assertEqual(body["status"]["privacyStatus"], "private")
        self.assertEqual(yu.PRIVACY_STATUS, "private")

    def test_title_description_tags_category(self):
        body = yu.metadata_from_pkg(SAMPLE_PKG)
        self.assertEqual(body["snippet"]["title"], SAMPLE_PKG["title"])
        self.assertEqual(body["snippet"]["description"], SAMPLE_PKG["description"])
        self.assertEqual(body["snippet"]["tags"], ["psychology", "mindset"])
        self.assertEqual(body["snippet"]["categoryId"], yu.CATEGORY_ID)

    def test_title_capped_at_100_chars(self):
        pkg = dict(SAMPLE_PKG, title="x" * 250)
        self.assertEqual(len(yu.metadata_from_pkg(pkg)["snippet"]["title"]), 100)

    def test_minimum_scope_only(self):
        self.assertEqual(yu.SCOPE, "https://www.googleapis.com/auth/youtube.upload")


# ---------------------------------------------------------------------------
# Deduplication ledger
# ---------------------------------------------------------------------------
class TestDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mf_up_"))
        self.ledger = self.tmp / "uploads.json"

    def test_no_tokens_ever_stored(self):
        entry = yu.record_upload("2026-11-14", "abc123xyz", "T", self.ledger)
        data = json.loads(self.ledger.read_text(encoding="utf-8"))
        # No secret-like values and no credential-shaped keys anywhere.
        self.assertNotIn(FAKE_REFRESH, self.ledger.read_text(encoding="utf-8"))
        for key in data.get("uploads", {})["2026-11-14"]:
            self.assertNotIn("token", key.lower())
        self.assertIn("abc123xyz", self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(entry["privacy"], "private")
        self.assertEqual(entry["url"], "https://www.youtube.com/watch?v=abc123xyz")

    def test_dedup_by_date(self):
        yu.record_upload("2026-11-14", "abc123", "T", self.ledger)
        self.assertTrue(yu.already_uploaded("2026-11-14", path=self.ledger))
        self.assertFalse(yu.already_uploaded("2026-11-15", path=self.ledger))

    def test_corrupt_ledger_tolerated(self):
        self.ledger.write_text("{not json", encoding="utf-8")
        self.assertEqual(yu.load_uploads(self.ledger), {})


# ---------------------------------------------------------------------------
# Upload flow (fake service)
# ---------------------------------------------------------------------------
class TestUploadFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mf_up2_"))
        self.mp4 = tiny_mp4(self.tmp / "v.mp4")

    def _pkg(self, date="2026-11-14"):
        return dict(SAMPLE_PKG, date=date)

    def test_successful_resumable_upload(self):
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos(
            [("resp", {"id": "vid_1",
                       "status": {"privacyStatus": "private"},
                       "snippet": {"title": "T"}})]))
        with mock.patch.object(yu.time, "sleep"):
            entry = yu.upload_video(self._pkg(), self.mp4, svc,
                                    date_str="2026-11-14", uploads_path=ledger,
                                    on_progress=lambda p: None)
        self.assertEqual(entry["video_id"], "vid_1")
        recorded = json.loads(ledger.read_text(encoding="utf-8"))["uploads"]["2026-11-14"]
        self.assertEqual(recorded["video_id"], "vid_1")

    def test_insert_body_sent_private(self):
        """The actual insert request must carry privacyStatus=private."""
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos(
            [("resp", {"id": "vid_1b",
                       "status": {"privacyStatus": "private"}})]))
        with mock.patch.object(yu.time, "sleep"):
            yu.upload_video(self._pkg(), self.mp4, svc,
                            date_str="2026-11-22", uploads_path=ledger)
        self.assertEqual(svc.videos_api.inserted_bodies[0]["status"]["privacyStatus"],
                         "private")

    def test_retries_transient_5xx(self):
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos(
            [("err", 500), ("err", 503),
             ("resp", {"id": "vid_2", "status": {"privacyStatus": "private"}})]))
        with mock.patch.object(yu.time, "sleep") as slept:
            entry = yu.upload_video(self._pkg(), self.mp4, svc, "2026-11-15",
                                    uploads_path=ledger)
        self.assertEqual(entry["video_id"], "vid_2")
        self.assertTrue(slept.called, "exponential backoff must kick in")

    def test_non_retryable_error_fails_loudly(self):
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos([("err", 403)]))
        with self.assertRaises(RuntimeError) as ctx:
            yu.upload_video(self._pkg(), self.mp4, svc, "2026-11-16",
                            uploads_path=ledger)
        self.assertIn("403", str(ctx.exception))

    def test_gives_up_after_max_retries(self):
        ledger = self.tmp / "uploads.json"
        script = [("err", 500)] * 7
        svc = FakeService(FakeVideos(script))
        with mock.patch.object(yu.time, "sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                yu.upload_video(self._pkg(), self.mp4, svc, "2026-11-17",
                                uploads_path=ledger)
        self.assertIn("failed", str(ctx.exception).lower())

    def test_stalled_session_fails_loudly(self):
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos([]))   # endless (None, None)
        with self.assertRaises(RuntimeError) as ctx:
            yu.upload_video(self._pkg(), self.mp4, svc, "2026-11-21",
                            uploads_path=ledger)
        self.assertIn("stalled", str(ctx.exception))

    def test_dedup_skips_service_entirely(self):
        ledger = self.tmp / "uploads.json"
        yu.record_upload("2026-11-18", "old_id", "T", ledger)
        svc = FakeService(FakeVideos([]))
        entry = yu.upload_video(self._pkg("2026-11-18"), self.mp4, svc,
                                date_str="2026-11-18", uploads_path=ledger)
        self.assertIsNone(entry)              # skipped, nothing uploaded
        self.assertEqual(svc.videos_api.inserted_bodies, [])

    def test_missing_video_file_fails(self):
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos([]))
        with self.assertRaises(RuntimeError):
            yu.upload_video(self._pkg(), self.tmp / "nope.mp4", svc, "d",
                            uploads_path=ledger)

    def test_insert_response_not_private_fails_loudly(self):
        """Verification must FAIL if the created video somehow isn't private."""
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos(
            [("resp", {"id": "vid_9", "status": {"privacyStatus": "public"}})]))
        with self.assertRaises(RuntimeError) as ctx:
            yu.upload_video(self._pkg(), self.mp4, svc, "2026-11-19",
                            uploads_path=ledger)
        self.assertIn("privacyStatus", str(ctx.exception))

    def test_missing_status_recorded_with_warning(self):
        """Google always echoes status; if it ever doesn't, record + warn
        instead of breaking dedup (which would cause duplicate uploads)."""
        ledger = self.tmp / "uploads.json"
        svc = FakeService(FakeVideos([("resp", {"id": "vid_11"})]))
        with mock.patch.object(yu.time, "sleep"):
            entry = yu.upload_video(self._pkg(), self.mp4, svc, "2026-11-23",
                                    uploads_path=ledger)
        self.assertEqual(entry["video_id"], "vid_11")
        self.assertIn("vid_11", ledger.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CLI behavior
# ---------------------------------------------------------------------------
class TestCLI(unittest.TestCase):
    def test_skips_cleanly_without_secrets(self):
        env = {k: "" for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET",
                               "YOUTUBE_REFRESH_TOKEN")}
        with mock.patch.dict(yu.os.environ, env, clear=True):
            self.assertEqual(yu.main(["prog"]), 0)   # [skip] message, exit 0

    def test_runs_with_secrets(self):
        pkg_path = ROOT / "content" / "2026-11-14.json"
        if not pkg_path.exists():
            self.skipTest("sample content missing")
        video = tiny_mp4(Path(tempfile.mkdtemp()) / "v.mp4")
        entry = {"video_id": "cli_1", "url": "u", "title": "t"}
        env = {k: v for k, v in [
            ("YOUTUBE_CLIENT_ID", FAKE_CLIENT_ID),
            ("YOUTUBE_CLIENT_SECRET", FAKE_SECRET),
            ("YOUTUBE_REFRESH_TOKEN", FAKE_REFRESH)]}
        with mock.patch.dict(yu.os.environ, env, clear=True), \
             mock.patch.object(yu, "build_credentials", return_value=object()), \
             mock.patch.object(yu, "refresh_access_token"), \
             mock.patch.object(yu, "build_service", return_value=object()), \
             mock.patch.object(yu, "upload_video", return_value=entry) as up:
            rc = yu.main(["prog", str(pkg_path), f"--video={video}"])
        self.assertEqual(rc, 0)
        self.assertTrue(up.called)

    def test_bad_refresh_token_message(self):
        pkg_path = ROOT / "content" / "2026-11-14.json"
        env = {k: v for k, v in [
            ("YOUTUBE_CLIENT_ID", FAKE_CLIENT_ID),
            ("YOUTUBE_CLIENT_SECRET", FAKE_SECRET),
            ("YOUTUBE_REFRESH_TOKEN", FAKE_REFRESH)]}
        err = RuntimeError("Token refresh failed: invalid_grant bad token")
        with mock.patch.dict(yu.os.environ, env, clear=True), \
             mock.patch.object(yu, "build_credentials", return_value=object()), \
             mock.patch.object(yu, "refresh_access_token", side_effect=err):
            rc = yu.main(["prog", str(pkg_path), "--video=x.mp4"])
        self.assertEqual(rc, 1)   # clear error, no crash, no silent success


if __name__ == "__main__":
    import faulthandler
    faulthandler.dump_traceback_later(240, exit=True)  # surface any hang
    unittest.main(verbosity=2)
