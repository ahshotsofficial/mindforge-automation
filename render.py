#!/usr/bin/env python3
"""
Mindforge - Automated stickman Shorts renderer
==============================================
Renders a daily 5-scene video package (JSON from generate.py) into a vertical
1080x1920 H.264 MP4 (~60s, 30fps), fully automatic:

  python render.py content/2026-11-12.json --out output/2026-11-12.mp4

Design notes:
  - Frames are drawn with Pillow and piped as rawvideo straight into ffmpeg
    (no intermediate PNG files, low disk usage).
  - ffmpeg resolution order: system PATH  ->  imageio_ffmpeg bundled binary.
    GitHub's ubuntu runners ship ffmpeg; locally `pip install imageio-ffmpeg`
    provides one.
  - No secrets, no network, no voiceover, no upload - pure offline rendering.

Preview mode for quick tests:
  python render.py <json> --preview
    -> 270x480 @ 10fps, first 6 seconds only (renders in seconds).
"""

import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Canvas / palette
# ---------------------------------------------------------------------------
BG = (10, 10, 14)
WHITE = (245, 245, 245)
GRAY = (150, 150, 155)
RED = (229, 57, 53)
YELLOW = (255, 214, 64)
DIM = (70, 70, 80)

W, H = 1080, 1920
FPS = 30
STROKE = 16            # stickman line thickness at scale 1
MAX_SECONDS = 60.0

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
_FONT_CACHE = {}
_FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    r"C:\Windows\Fonts\ariblk.ttf",
    # Linux (GitHub Actions runners)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_FONT_PATH = None


def _find_font_path():
    global _FONT_PATH
    if _FONT_PATH is None:
        for c in _FONT_CANDIDATES:
            if Path(c).exists():
                _FONT_PATH = c
                break
        else:
            _FONT_PATH = ""  # fall back to PIL default bitmap font
    return _FONT_PATH


def get_font(size):
    key = size
    if key not in _FONT_CACHE:
        path = _find_font_path()
        if path:
            _FONT_CACHE[key] = ImageFont.truetype(path, size)
        else:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def text_w(draw, s, font):
    return draw.textlength(s, font=font)


def wrap_line(draw, line, font, max_w):
    words, out, cur = line.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if text_w(draw, trial, font) <= max_w or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out or [""]


def fit_text(draw, text, box_w, box_h, max_size=72, min_size=26):
    """Wrap text and shrink until it fits the box. Existing line breaks are
    treated as spaces - the renderer re-wraps optimally for the frame."""
    text = " ".join(text.split()).replace("✗", "").strip()  # red X drawn as graphic
    for size in range(max_size, min_size - 1, -2):
        font = get_font(size)
        lines = []
        for raw in text.split("\n"):
            lines.extend(wrap_line(draw, raw, font, box_w))
        line_h = int(size * 1.3)
        if len(lines) * line_h <= box_h and all(text_w(draw, ln, font) <= box_w for ln in lines):
            return font, lines, line_h
    font = get_font(min_size)
    lines = []
    for raw in text.split("\n"):
        lines.extend(wrap_line(draw, raw, font, box_w))
    return font, lines, int(min_size * 1.3)


def draw_text_block(draw, lines, font, line_h, cx, cy, fill=WHITE, stroke=6):
    """Centered text block with black outline."""
    total = line_h * len(lines)
    y = cy - total // 2
    for ln in lines:
        tw = text_w(draw, ln, font)
        draw.text((cx - tw / 2, y), ln, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------
def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def pulse(t, freq=2.0):
    return (math.sin(t * freq * math.pi * 2) + 1) / 2


def scene_window(t, edges=None):
    """Return (start, end, local_t) for the scene containing t."""
    if edges is None:
        edges = SCENE_EDGES
    for s, e in edges:
        if s <= t < e or (e == MAX_SECONDS and t >= s):
            return s, e, t - s
    return edges[-1][0], edges[-1][1], t - edges[-1][0]


# ---------------------------------------------------------------------------
# Stickman
# ---------------------------------------------------------------------------
def draw_stickman(d, cx, cy, s, pose="idle", t=0.0, emotion="neutral", color=WHITE):
    """cx, cy = head center; s = head radius (scale unit)."""
    bob = math.sin(t * 2.2) * s * 0.08
    hx, hy = cx, cy + bob
    neck = (hx, hy + s * 1.35)
    hip = (hx, neck[1] + s * 2.1)
    shoulder = (hx, neck[1] + s * 0.35)
    lw = max(6, int(STROKE * s / 40))

    # legs
    if pose == "walk":
        sw = math.sin(t * 5)
        l_leg = (hx - s * 0.9 + sw * s * 0.5, hip[1] + s * 2.3)
        r_leg = (hx + s * 0.9 - sw * s * 0.5, hip[1] + s * 2.3)
    else:
        l_leg = (hx - s * 0.75, hip[1] + s * 2.3)
        r_leg = (hx + s * 0.75, hip[1] + s * 2.3)
    d.line([hip, l_leg], fill=color, width=lw)
    d.line([hip, r_leg], fill=color, width=lw)

    # arms
    if pose == "point":
        d.line([shoulder, (hx - s * 1.5, shoulder[1] + s * 1.6)], fill=color, width=lw)
        d.line([shoulder, (hx + s * 2.6, shoulder[1] - s * 0.1)], fill=color, width=lw)
    elif pose == "shrug":
        d.line([shoulder, (hx - s * 1.6, shoulder[1] - s * 1.1)], fill=color, width=lw)
        d.line([shoulder, (hx + s * 1.6, shoulder[1] - s * 1.1)], fill=color, width=lw)
    elif pose == "think":
        d.line([shoulder, (hx - s * 1.4, shoulder[1] + s * 1.4)], fill=color, width=lw)
        d.line([shoulder, (hx + s * 1.2, shoulder[1] - s * 1.5)], fill=color, width=lw)
    else:  # idle / walk / wave
        d.line([shoulder, (hx - s * 1.5, shoulder[1] + s * 1.7)], fill=color, width=lw)
        d.line([shoulder, (hx + s * 1.5, shoulder[1] + s * 1.7)], fill=color, width=lw)

    # body + head
    d.line([neck, hip], fill=color, width=lw)
    d.ellipse([hx - s, hy - s, hx + s, hy + s], outline=color, width=lw)

    # face
    ex, ey = hx + s * 0.35, hy - s * 0.15
    eye = max(2, int(s * 0.14))
    if emotion == "happy":
        d.line([(hx - s * 0.45, ey - s * 0.25), (hx - s * 0.15, ey - s * 0.35)], fill=color, width=max(2, eye - 1))
        d.line([(hx - s * 0.15, ey - s * 0.35), (hx + s * 0.15, ey - s * 0.35)], fill=color, width=max(2, eye - 1))
        d.line([(hx - s * 0.3, ey + s * 0.45), (hx + s * 0.3, ey + s * 0.45)], fill=color, width=max(2, eye - 1))
    else:
        d.ellipse([ex - s * 0.1, ey - s * 0.1, ex + s * 0.1, ey + s * 0.1], fill=color)
        d.ellipse([hx - s * 0.1, ey - s * 0.1, hx + s * 0.1, ey + s * 0.1], fill=color)
        if emotion == "confused":
            d.arc([hx - s * 0.35, ey + s * 0.25, hx + s * 0.35, ey + s * 0.75], 20, 160, fill=color, width=max(2, eye - 1))
        else:
            d.line([(hx - s * 0.3, ey + s * 0.45), (hx + s * 0.3, ey + s * 0.45)], fill=color, width=max(2, eye - 1))


def draw_question_mark(d, cx, cy, s, alpha):
    """Pulsing '?' above the stickman (HOOK scene)."""
    f = get_font(int(s * 3.2 * (0.8 + 0.25 * alpha)))
    tw = text_w(d, "?", f)
    d.text((cx - tw / 2, cy), "?", font=f, fill=YELLOW, stroke_width=6, stroke_fill=(0, 0, 0))


def draw_speech_bubble(d, box, text, scale=1.0):
    """Rounded speech bubble with tail, pointing left-down."""
    x0, y0, x1, y1 = box
    r = int(48 * scale)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, outline=WHITE, width=6, fill=(22, 22, 28))
    tail = [(x0 + 40, y1 - 4), (x0 - 10, y1 + 90), (x0 + 150, y1 - 4)]
    d.polygon(tail, fill=(22, 22, 28))
    d.line([tail[0], tail[1]], fill=WHITE, width=6)
    d.line([tail[1], tail[2]], fill=WHITE, width=6)
    font, lines, lh = fit_text(d, text, (x1 - x0) - 80, (y1 - y0) - 60, max_size=52)
    total = lh * len(lines)
    y = (y0 + y1) / 2 - total / 2
    for ln in lines:
        tw = text_w(d, ln, font)
        d.text(((x0 + x1) / 2 - tw / 2, y), ln, font=font, fill=WHITE)
        y += lh


def draw_red_x(d, cx, cy, s, grow):
    """Big red X strike-through (SETUP scene)."""
    g = max(0.05, grow)
    arm = s * g
    w = max(8, int(22 * g))
    d.line([(cx - arm, cy - arm), (cx + arm, cy + arm)], fill=RED, width=w)
    d.line([(cx - arm, cy + arm), (cx + arm, cy - arm)], fill=RED, width=w)


def draw_gear(d, cx, cy, r, angle, color=GRAY):
    teeth = 8
    for i in range(teeth):
        a = angle + i * (2 * math.pi / teeth)
        x0, y0 = cx + math.cos(a) * r * 0.78, cy + math.sin(a) * r * 0.78
        x1, y1 = cx + math.cos(a) * r * 1.15, cy + math.sin(a) * r * 1.15
        d.line([x0, y0, x1, y1], fill=color, width=10)
    d.ellipse([cx - r * 0.78, cy - r * 0.78, cx + r * 0.78, cy + r * 0.78], outline=color, width=10)
    d.ellipse([cx - r * 0.22, cy - r * 0.22, cx + r * 0.22, cy + r * 0.22], outline=color, width=8)


def draw_lightbulb(d, cx, cy, r, glow, color=YELLOW):
    if glow > 0:
        g = int(r * (1.7 + glow * 0.6))
        d.ellipse([cx - g, cy - g, cx + g, cy + g], outline=(90, 80, 30), width=6)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=10)
    d.line([(cx - r * 0.35, cy + r), (cx - r * 0.35, cy + r * 1.35)], fill=color, width=8)
    d.line([(cx + r * 0.35, cy + r), (cx + r * 0.35, cy + r * 1.35)], fill=color, width=8)
    d.line([(cx - r * 0.35, cy + r * 1.35), (cx + r * 0.35, cy + r * 1.35)], fill=color, width=8)
    for i in range(3):
        a = -math.pi / 2 + (i - 1) * 0.5
        d.line([(cx + math.cos(a) * r * 1.25, cy + math.sin(a) * r * 1.25),
                (cx + math.cos(a) * r * 1.5, cy + math.sin(a) * r * 1.5)], fill=color, width=5)


def draw_bars_chart(d, x, y, w, h, t):
    """Two contrasting bars + rising line (PROOF scene)."""
    axis_y = y + h
    d.line([(x, axis_y), (x + w, axis_y)], fill=GRAY, width=6)
    d.line([(x, axis_y), (x, y)], fill=GRAY, width=6)
    b1 = h * (0.35 + 0.05 * math.sin(t * 1.5))
    b2 = h * 0.85
    d.rectangle([x + w * 0.15, axis_y - b1, x + w * 0.4, axis_y], outline=GRAY, width=8)
    d.rectangle([x + w * 0.6, axis_y - b2, x + w * 0.85, axis_y], outline=YELLOW, width=10)
    pts = []
    for i in range(5):
        px = x + w * (0.15 + 0.16 * i)
        py = axis_y - b1 - (b2 - b1) * ease(i / 4) * 0.9 - 20
        pts.append((px, py))
    d.line(pts, fill=YELLOW, width=8)


def draw_label(d, cx, cy, text, color=GRAY, size=40):
    f = get_font(size)
    tw = text_w(d, text, f)
    d.text((cx - tw / 2, cy), text, font=f, fill=color)


# ---------------------------------------------------------------------------
# Scene renderers: each returns nothing; draws onto the frame at local time lt
# ---------------------------------------------------------------------------
def scene_hook(d, pkg, lt, dur, t):
    s = 70
    cx, cy = W // 2, 1250
    draw_stickman(d, cx, cy, s, pose="idle", t=t, emotion="neutral")
    draw_question_mark(d, cx, cy - s * 3.4, s, pulse(lt, 1.2))


def scene_setup(d, pkg, lt, dur, t):
    s = 70
    cx, cy = 330, 1250
    draw_stickman(d, cx, cy, s, pose="shrug" if lt < dur * 0.7 else "think",
                  t=t, emotion="confused" if lt > 1.0 else "neutral")
    box = (430, 420, 1010, 760)
    draw_speech_bubble(d, box, pkg["scenes"][1]["overlay"])
    strike = ease((lt - dur * 0.4) / 1.2)          # X grows in at 40% of scene
    if strike > 0:
        draw_red_x(d, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, 210, strike)


def scene_mechanism(d, pkg, lt, dur, t):
    s = 62
    # split screen
    d.line([(W // 2, 330), (W // 2, 1700)], fill=DIM, width=5)
    draw_stickman(d, 270, 1150, s, pose="idle", t=t, emotion="neutral")
    draw_stickman(d, W - 270, 1150, s, pose="point", t=t, emotion="happy")
    # left: auto-pilot gears
    draw_gear(d, 190, 800, 64, t * 1.6)
    draw_gear(d, 330, 720, 46, -t * 2.2)
    draw_label(d, 260, 600, "AUTO-PILOT")
    # right: insight lightbulb
    draw_lightbulb(d, W - 270, 770, 56, pulse(lt, 0.8))
    draw_label(d, W - 270, 580, "INSIGHT", color=YELLOW)
    # dashed synapse between the two halves
    for k in range(5):
        x = 420 + k * 58
        d.line([(x, 890), (x + 30, 890)], fill=DIM, width=6)


def scene_proof(d, pkg, lt, dur, t):
    s = 66
    cx, cy = 300, 1280
    draw_stickman(d, cx, cy, s, pose="point", t=t, emotion="happy")
    draw_bars_chart(d, 460, 480, 480, 420, t)
    draw_label(d, 700, 420, "THE EVIDENCE", color=YELLOW)


def scene_payoff(d, pkg, lt, dur, t):
    s = 70
    cx, cy = W // 2, 1150
    draw_stickman(d, cx, cy, s, pose="idle", t=t, emotion="happy")
    # prop: phone in hand (right side)
    ph = (cx + s * 1.9, cy + s * 1.4)
    d.rounded_rectangle([ph[0] - 22, ph[1] - 46, ph[0] + 22, ph[1] + 46], radius=12,
                        outline=WHITE, width=8)
    # MINDFORGE logo fade-in during last 5s
    fade = ease((lt - (dur - 5)) / 2.5)
    if fade > 0:
        f = get_font(int(88 * (0.7 + 0.3 * fade)))
        tw = text_w(d, "MINDFORGE", f)
        a = int(255 * fade)
        col = (255, 214, 64, ) if a > 200 else (150, 130, 60)
        d.text(((W - tw) / 2, 1660), "MINDFORGE", font=f, fill=YELLOW,
               stroke_width=6, stroke_fill=(0, 0, 0))


SCENE_FUNCS = [scene_hook, scene_setup, scene_mechanism, scene_proof, scene_payoff]
SCENE_EDGES = []  # set by render_video(); used only as a fallback default

# ---------------------------------------------------------------------------
# Frame rendering
# ---------------------------------------------------------------------------
def parse_scenes(pkg):
    """Read 'time': '0:15 - 0:32' entries -> [(start, end), ...] in seconds."""
    edges = []
    for sc in pkg["scenes"]:
        m = re.findall(r"(\d+):(\d+)", sc["time"])
        if len(m) != 2:
            raise ValueError(f"Unparseable scene time: {sc['time']!r}")
        start = int(m[0][0]) * 60 + int(m[0][1])
        end = int(m[1][0]) * 60 + int(m[1][1])
        edges.append((float(start), float(end)))
    edges.sort()
    if edges[0][0] != 0:
        edges.insert(0, (0.0, edges[0][1]))
    return edges


def render_frame(pkg, edges, scene_texts, t, size=(W, H), layouts=None):
    """Draw one complete frame at global time t (drawn at full res, then
    downscaled if a smaller preview size is requested)."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    start, end, lt = scene_window(t, edges)
    dur = end - start

    # overall fade at scene edges (crossfade-to-black transitions)
    fade_in = ease(lt / 0.4)
    fade_out = 1 - ease((lt - (dur - 0.4)) / 0.4)
    fade = min(fade_in, fade_out)

    SCENE_FUNCS[edges.index((start, end))](d, pkg, lt, dur, t)

    # overlay text for the active scene (scene 2 shows it inside the speech
    # bubble instead - drawing both would duplicate the same words)
    idx = edges.index((start, end))
    text = scene_texts[idx]
    if text and idx != 1:
        if layouts is not None:
            font, lines, lh = layouts[idx]
        else:
            font, lines, lh = fit_text(d, text, int(W * 0.86), int(H * 0.26), max_size=66)
        draw_text_block(d, lines, font, lh, W // 2, int(H * 0.16))

    # progress bar
    prog = min(1.0, t / MAX_SECONDS)
    d.rectangle([int(W * 0.08), H - 30, int(W * 0.08 + (W * 0.84) * prog), H - 18], fill=GRAY)

    if fade < 1.0:
        img = Image.blend(Image.new("RGB", (W, H), BG), img, max(0.05, fade))
    if size != (W, H):
        img = img.resize(size, Image.LANCZOS)
    return img


def resolve_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError(
            "ffmpeg not found. On GitHub Actions it is preinstalled; "
            "locally run: pip install imageio-ffmpeg"
        )


def render_video(pkg, out_path, width=W, height=H, fps=FPS, max_t=None, preset="medium", crf="20"):
    global SCENE_EDGES
    edges = parse_scenes(pkg)
    SCENE_EDGES = edges
    scene_texts = [sc.get("overlay", "") for sc in pkg["scenes"]]
    # Precompute per-scene text layouts once (huge speedup: no per-frame
    # font-size search or word wrapping).
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    layouts = [
        fit_text(probe, txt, int(W * 0.86), int(H * 0.26), max_size=66) if txt else None
        for txt in scene_texts
    ]
    total = min(max_t if max_t is not None else MAX_SECONDS, MAX_SECONDS)
    frames = int(total * fps)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        resolve_ffmpeg(), "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-an", "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            img = render_frame(pkg, edges, scene_texts, i / fps, size=(width, height), layouts=layouts)
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
    stderr = proc.stderr.read().decode(errors="replace")
    proc.stderr.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed:\n{stderr[-2000:]}")
    return out_path, frames


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def default_json_path():
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return ROOT / "content" / f"{date}.json"


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    json_path = Path(args[0]) if args else default_json_path()
    if not json_path.exists():
        print(f"[error] JSON not found: {json_path}", file=sys.stderr)
        return 1
    pkg = json.loads(json_path.read_text(encoding="utf-8"))

    preview = "--preview" in flags
    if preview:
        out = ROOT / "output" / f"preview_{json_path.stem}.mp4"
        render_video(pkg, out, width=270, height=480, fps=10, max_t=6.0,
                     preset="ultrafast", crf="28")
    else:
        out = Path(args[1]) if len(args) > 1 else ROOT / "output" / f"{json_path.stem}.mp4"
        render_video(pkg, out)

    print(f"[ok] rendered {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
