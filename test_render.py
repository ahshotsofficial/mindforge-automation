#!/usr/bin/env python3
"""
Mindforge renderer tests.

Run:  python test_render.py
Lightweight (stdlib unittest): fast unit tests + one small real-MP4
integration test (270x480 preview render, a few seconds of video).
"""

import json
import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import render  # noqa: E402


def is_valid_mp4_start(path):
    """A real MP4 starts with a box whose size>0 and type is 'ftyp'."""
    with open(path, "rb") as f:
        head = f.read(12)
    if len(head) < 12:
        return False
    size = struct.unpack(">I", head[:4])[0]
    return head[4:8] == b"ftyp" and size > 0


def load_sample_pkg():
    data = {
        "topic": "Test Topic",
        "scenes": [
            {"role": "HOOK", "time": "0:00 - 0:03", "overlay": "HOOK TEXT"},
            {"role": "SETUP", "time": "0:03 - 0:15", "overlay": "SETUP TEXT"},
            {"role": "MECHANISM", "time": "0:15 - 0:32", "overlay": "MECH TEXT"},
            {"role": "PROOF / CONTRAST", "time": "0:32 - 0:48", "overlay": "PROOF TEXT"},
            {"role": "PAYOFF / CTA", "time": "0:48 - 0:60", "overlay": "PAYOFF TEXT"},
        ],
    }
    return data


class TestParsing(unittest.TestCase):
    def test_parse_scenes_edges(self):
        edges = render.parse_scenes(load_sample_pkg())
        self.assertEqual(edges, [(0, 3), (3, 15), (15, 32), (32, 48), (48, 60)])

    def test_parse_scenes_bad_time_raises(self):
        pkg = {"scenes": [{"time": "whenever"}]}
        with self.assertRaises(ValueError):
            render.parse_scenes(pkg)

    def test_scene_window(self):
        edges = render.parse_scenes(load_sample_pkg())
        s, e, lt = render.scene_window(0, edges)
        self.assertEqual((s, e), (0, 3))
        s, e, lt = render.scene_window(47.9, edges)
        self.assertEqual((s, e), (32, 48))
        s, e, lt = render.scene_window(59.99, edges)
        self.assertEqual((s, e), (48, 60))


class TestText(unittest.TestCase):
    def setUp(self):
        self.img = render.Image.new("RGB", (render.W, render.H))
        self.d = render.ImageDraw.Draw(self.img)

    def test_font_found(self):
        self.assertNotEqual(render._find_font_path(), "")

    def test_wrap_respects_width(self):
        font = render.get_font(40)
        lines = render.wrap_line(self.d, "one two three four five six", font, 300)
        for ln in lines:
            self.assertLessEqual(render.text_w(self.d, ln, font), 300 + font.size)

    def test_fit_text_shrinks(self):
        font, lines, lh = render.fit_text(
            self.d, "THIS IS A VERY LONG SENTENCE THAT MUST SHRINK TO FIT THE BOX",
            600, 300, max_size=72)
        self.assertTrue(all(render.text_w(self.d, ln, font) <= 620 for ln in lines))

    def test_overlay_x_stripped(self):
        font, lines, _ = render.fit_text(self.d, "WRONG BELIEF. ✗", 500, 200)
        self.assertNotIn("✗", " ".join(lines))


class TestFrame(unittest.TestCase):
    def test_frame_dimensions_and_mode(self):
        pkg = load_sample_pkg()
        edges = render.parse_scenes(pkg)
        texts = [s["overlay"] for s in pkg["scenes"]]
        for t in (0.0, 5.0, 20.0, 40.0, 55.0):
            img = render.render_frame(pkg, edges, texts, t, size=(270, 480))
            self.assertEqual(img.size, (270, 480))
            self.assertEqual(img.mode, "RGB")

    def test_fade_frame_is_darker(self):
        from PIL import ImageStat
        pkg = load_sample_pkg()
        edges = render.parse_scenes(pkg)
        texts = [s["overlay"] for s in pkg["scenes"]]
        bright = render.render_frame(pkg, edges, texts, 1.5, size=(270, 480))
        dark = render.render_frame(pkg, edges, texts, 0.05, size=(270, 480))
        b_mean = sum(ImageStat.Stat(bright).mean)
        d_mean = sum(ImageStat.Stat(dark).mean)
        self.assertLess(d_mean, b_mean)


class TestIntegration(unittest.TestCase):
    def test_real_mp4_preview_render(self):
        """Renders a tiny real MP4 and checks its container signature."""
        with TemporaryDirectory() as td:
            out = Path(td) / "test_preview.mp4"
            pkg = load_sample_pkg()
            path, frames = render.render_video(
                pkg, out, width=270, height=480, fps=10, max_t=2.0,
                preset="ultrafast", crf="30")
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 2000, "MP4 suspiciously small")
            self.assertEqual(frames, 20)
            self.assertTrue(is_valid_mp4_start(path), "not a valid MP4 container")


if __name__ == "__main__":
    unittest.main(verbosity=2)
