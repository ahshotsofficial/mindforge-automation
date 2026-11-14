#!/usr/bin/env python3
"""
Mindforge - Phase 2 voiceover test suite.

Run:  python test_narrator.py

Offline tests use injected fake TTS engines (sine-tone WAVs) plus the local
imageio-ffmpeg binary - no network, no Microsoft/Google endpoints.
One integration test renders a real MP4 with an audio track and probes it.
"""

import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import narrator  # noqa: E402
from render import render_video  # noqa: E402

TOTAL_SAMPLES = int(narrator.TOTAL_SECONDS * narrator.SAMPLE_RATE)
TONE_FREQ = 523.0  # not a divisor-friendly frequency: avoids sine-phase zeros


def window_max(samples, t0, t1):
    """Loudest absolute sample in [t0, t1] seconds (robust vs single-sample zeros)."""
    a, b = int(t0 * narrator.SAMPLE_RATE), int(t1 * narrator.SAMPLE_RATE)
    return max(abs(v) for v in samples[a:b])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def write_tone(path, seconds, freq=TONE_FREQ, amp=9000, rate=narrator.SAMPLE_RATE):
    """Write a sine-tone WAV (real PCM audio, decodable by ffmpeg)."""
    path = Path(path)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate)))
        w.writeframes(bytes(frames))
    return path


def real_pkg(date="2026-11-14"):
    """The latest Actions-generated package (has top-level truth/mechanism/narration)."""
    p = ROOT / "content" / f"{date}.json"
    if not p.exists():
        for cand in sorted((ROOT / "content").glob("*.json")):
            if cand.stem != "state":
                return json.loads(cand.read_text(encoding="utf-8"))
        raise FileNotFoundError("no content JSON found")
    return json.loads(p.read_text(encoding="utf-8"))


def synthetic_pkg():
    """A legacy-style package: overlays carry the spoken content, but polluted
    with the production leftovers that must NEVER be narrated."""
    return {
        "date": "2026-11-14",
        "hook": "Your brain hides this from you every single day.",
        "truth": "",
        "mechanism": "",
        "titles": ["x"],
        "scenes": [
            {"role": "HOOK", "time": "0:00 - 0:03", "overlay": "YOUR BRAIN HIDES THIS."},
            {"role": "SETUP", "time": "0:03 - 0:15",
             "overlay": "✗ FEELINGS CONTROL YOU #mindset #psychology CapCut: zoom-in"},
            {"role": "MECHANISM", "time": "0:15 - 0:32",
             "overlay": "Naming an emotion calms the amygdala."},
            {"role": "PROOF", "time": "0:32 - 0:48",
             "overlay": "Bar chart: naming cuts amygdala activity 40% (UCLA fMRI)."},
            {"role": "PAYOFF", "time": "0:48 - 1:00",
             "overlay": "Name one feeling right now."},
        ],
    }


class FakeEngineFailure(Exception):
    pass


# ---------------------------------------------------------------------------
# Narration composition (text purity + cleanup)
# ---------------------------------------------------------------------------
class TestNarrationText(unittest.TestCase):
    def test_no_directions_or_hashtags_ever_spoken(self):
        lines = narrator.build_narration(synthetic_pkg())
        self.assertEqual(len(lines), 5)
        joined = " ".join(lines).lower()
        for banned in ("stickman", "capcut", "zoom", "split screen", "logo",
                       "#", "bar chart", "id:", "export:", "0:15"):
            self.assertNotIn(banned, joined)

    def test_all_lines_substantive(self):
        for line in narrator.build_narration(synthetic_pkg()):
            self.assertGreaterEqual(len(line.split()), 4, line)

    def test_citation_cleanup(self):
        out = narrator.clean_spoken("Proven by Gilovich et al. (2000) in real trials.")
        self.assertNotIn("et al.", out)
        self.assertNotIn("(2000)", out)
        self.assertIn("and colleagues", out.lower())
        self.assertIn("2000", out)

    def test_parentheticals_becomes_spoken(self):
        out = narrator.clean_spoken("A key fact (UCLA fMRI study) supports this.")
        self.assertNotIn("(", out)
        self.assertIn("UCLA fMRI study", out)

    def test_backward_compat_legacy_package(self):
        """2026-11-12 predates Phase 2: no narration/truth/mechanism fields."""
        legacy = ROOT / "content" / "2026-11-12.json"
        if not legacy.exists():
            self.skipTest("legacy sample not present")
        pkg = json.loads(legacy.read_text(encoding="utf-8"))
        self.assertNotIn("narration", pkg)
        lines = narrator.build_narration(pkg)
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(l.strip() for l in lines))

    def test_latest_package_narratable(self):
        """Latest Actions package must produce 5 lines - via its own narration
        field if generated post-Phase-2, or recomputed for legacy packages."""
        pkg = real_pkg()
        lines = pkg.get("narration") or narrator.build_narration(pkg)
        self.assertEqual(len(lines), 5)
        self.assertTrue(all(l.strip() for l in lines))


# ---------------------------------------------------------------------------
# Language & voice resolution
# ---------------------------------------------------------------------------
class TestLanguage(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(narrator.detect_language("Как работает ваш мозг?"), "ru")
        self.assertEqual(narrator.detect_language("大脑如何工作"), "zh")
        self.assertEqual(narrator.detect_language("How your brain works?"), "en")

    def test_voice_override(self):
        self.assertEqual(narrator.resolve_voice("hello", "en-GB-SoniaNeural"),
                         "en-GB-SoniaNeural")

    def test_auto_voice_by_language(self):
        self.assertEqual(narrator.resolve_voice("Как дела?"), "ru-RU-DmitryNeural")
        self.assertEqual(narrator.resolve_voice("Hello there"), "en-US-AndrewNeural")


# ---------------------------------------------------------------------------
# Scene windows
# ---------------------------------------------------------------------------
class TestWindows(unittest.TestCase):
    def test_parse_real_package(self):
        self.assertEqual(narrator.parse_windows(real_pkg()),
                         [(0, 3), (3, 15), (15, 32), (32, 48), (48, 60)])

    def test_bad_time_raises(self):
        with self.assertRaises(ValueError):
            narrator.parse_windows({"scenes": [{"time": "nope"}]})


# ---------------------------------------------------------------------------
# Audio: decoding, tempo, mixing
# ---------------------------------------------------------------------------
class TestAudioOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mf_narr_"))

    def test_atempo_shortens_duration(self):
        src = write_tone(self.tmp / "t.wav", 4.0)
        out = self.tmp / "t_fast.wav"
        narrator.decode_to_wav(src, out, tempo=1.45)
        self.assertAlmostEqual(narrator.wav_duration(out), 4.0 / 1.45, delta=0.1)

    def test_mix_track_exactly_60s(self):
        win = narrator.parse_windows(real_pkg())
        files = [write_tone(self.tmp / f"s{i}.wav", 2.0) for i in range(1, 6)]
        out = self.tmp / "narr.wav"
        narrator.mix_track(files, win, out)
        self.assertEqual(narrator.wav_duration(out), 60.0)

    def test_mix_track_samples_count_exact(self):
        win = narrator.parse_windows(real_pkg())
        files = [write_tone(self.tmp / f"s{i}.wav", 1.0) for i in range(1, 6)]
        out = self.tmp / "narr.wav"
        narrator.mix_track(files, win, out)
        self.assertEqual(len(narrator.wav_samples(out)), TOTAL_SAMPLES)

    def test_mix_track_no_clipping(self):
        win = narrator.parse_windows(real_pkg())
        files = [write_tone(self.tmp / f"s{i}.wav", 5.0, amp=30000) for i in range(1, 6)]
        out = self.tmp / "narr.wav"
        narrator.mix_track(files, win, out)
        peak = max(abs(v) for v in narrator.wav_samples(out))
        self.assertLessEqual(peak, 32767)

    def test_narration_starts_after_scene_start_not_silently_at_zero(self):
        """Scene 1 (window 0-3) must begin at 0.15s, scene 2 at 3.25s."""
        win = narrator.parse_windows(real_pkg())
        files = [write_tone(self.tmp / f"s{i}.wav", 1.5) for i in range(1, 6)]
        out = self.tmp / "narr.wav"
        narrator.mix_track(files, win, out)
        s = narrator.wav_samples(out)
        self.assertEqual(window_max(s, 0.0, 0.10), 0)                # head gap
        self.assertGreater(window_max(s, 0.3, 1.4), 0)               # scene 1 talking
        self.assertEqual(window_max(s, 2.0, 3.0), 0)                 # gap after scene 1
        self.assertGreater(window_max(s, 3.4, 4.4), 0)               # scene 2 talking

    def test_bleed_preserves_words(self):
        """Overlong narration bleeds past the window instead of being cut."""
        win = narrator.parse_windows(real_pkg())
        files = [
            write_tone(self.tmp / "s1.wav", 4.0),   # scene 1: 3s window -> 4s overflows
            write_tone(self.tmp / "s2.wav", 2.0),
            write_tone(self.tmp / "s3.wav", 2.0),
            write_tone(self.tmp / "s4.wav", 2.0),
            write_tone(self.tmp / "s5.wav", 2.0),
        ]
        out = self.tmp / "narr.wav"
        warnings = narrator.mix_track(files, win, out)
        self.assertTrue(any("scene 1" in w and "bleeds" in w for w in warnings),
                        warnings)
        s = narrator.wav_samples(out)
        # Scene 2's own narration starts at 3.25s, but scene 1's tail must still
        # be audible at ~3.1s (inside scene 2) -> words were NOT truncated.
        self.assertGreater(window_max(s, 3.05, 3.2), 0)

    def test_missing_audio_fails_loudly(self):
        win = narrator.parse_windows(real_pkg())
        files = [write_tone(self.tmp / f"s{i}.wav", 2.0) for i in range(1, 6)]
        files[2] = self.tmp / "missing.wav"
        with self.assertRaises(RuntimeError):
            narrator.mix_track(files, win, self.tmp / "narr.wav")


# ---------------------------------------------------------------------------
# Pipeline (fake engines - offline)
# ---------------------------------------------------------------------------
class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mf_pipe_"))
        self._orig = dict(narrator.ENGINES)

    def tearDown(self):
        narrator.ENGINES.clear()
        narrator.ENGINES.update(self._orig)

    def test_engine_failure_fails_loudly(self):
        def boom(*a, **k):
            raise FakeEngineFailure("network 403")
        narrator.ENGINES["edge"] = boom
        narrator.ENGINES["gtts"] = boom
        with self.assertRaises(RuntimeError):
            narrator.synth_with_fallback("text", "en-US-X", self.tmp / "a.mp3")

    def test_overlong_narration_sped_up_and_reported(self):
        def fake(text, voice, out_path, rate, **_):
            write_tone(out_path, 8.0)   # too long even for the 15-17s scenes
            return "fake"
        narrator.ENGINES["fake"] = fake
        path, report = narrator.generate_voiceover(
            real_pkg(), self.tmp, engine="fake")
        self.assertEqual(narrator.wav_duration(path), 60.0)
        tempos = {sc["scene"]: sc["tempo"] for sc in report["scenes"]}
        # Scene 1's 3s window cannot hold an 8s tone -> max safe speed-up;
        # longer windows don't need speed-up at all.
        self.assertGreaterEqual(tempos[1], 1.4, tempos)
        self.assertLessEqual(max(tempos.values()), narrator.MAX_TEMPO)
        self.assertTrue(report["warnings"], "8s tone must overflow some window")

    def test_narration_field_used_directly(self):
        seen = []

        def fake(text, voice, out_path, rate, **_):
            seen.append(text)
            write_tone(out_path, 1.0)
            return "fake"
        narrator.ENGINES["fake"] = fake
        pkg = real_pkg()
        pkg["narration"] = [f"custom line {i} for phase two test" for i in range(1, 6)]
        narrator.generate_voiceover(pkg, self.tmp, engine="fake")
        self.assertEqual(seen[0], pkg["narration"][0])

    def test_invalid_narration_rejected(self):
        pkg = real_pkg()
        pkg["narration"] = ["", "ok words here", "more words", "even more", "final one"]
        with self.assertRaises(RuntimeError):
            narrator.generate_voiceover(pkg, self.tmp, engine="fake")


# ---------------------------------------------------------------------------
# Integration: real MP4 WITH an audio track
# ---------------------------------------------------------------------------
class TestRenderWithAudio(unittest.TestCase):
    def test_mp4_has_audio_stream(self):
        pkg = real_pkg()
        tmp = Path(tempfile.mkdtemp(prefix="mf_av_"))
        audio = write_tone(tmp / "narration.wav", 60.0)
        out = tmp / "av.mp4"
        render_video(pkg, out, width=270, height=480, fps=10, max_t=6.0,
                     preset="ultrafast", crf="28", audio_path=audio)
        ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
        probe = subprocess.run([ff, "-i", str(out)], capture_output=True,
                               text=True, timeout=60)
        blob = probe.stderr
        self.assertIn("Audio:", blob, "muxed MP4 must contain an audio stream")
        self.assertIn("Video:", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
