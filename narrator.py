#!/usr/bin/env python3
"""
Mindforge - AI voiceover pipeline (Phase 2)
===========================================
Turns a daily content package (JSON) into a synchronized 60-second narration
track and mixes it into the Phase 1 renderer.

  python narrator.py content/2026-11-14.json --outdir voice
  ->  voice/2026-11-14/scene_1.mp3 ... scene_5.mp3
      voice/2026-11-14/narration.wav   (exactly 60s, ready for render.py)
      voice/2026-11-14/report.json     (engine, durations, tempo, warnings)

What is spoken: ONLY the script itself (hook, misconception, truth, mechanism,
evidence, action, CTA). Scene directions, visual descriptions, CapCut notes,
hashtags and production metadata are never narrated.

TTS engines (configurable via MF_TTS_ENGINE env: auto | edge | gtts):
  edge - Microsoft Edge neural voices (free, no key, best quality).
         UNOFFICIAL service: known to occasionally 403 datacenter/CI IPs.
  gtts - Google Translate TTS fallback (free, no key, plainer voice).
Both fail -> pipeline FAILS LOUDLY. A video without narration is never
produced unless --engine none is passed explicitly.

Synchronization: each scene's narration starts ~0.25s after its scene begins.
If narration is longer than the scene window it is sped up with ffmpeg
`atempo` (max 1.45x). If still too long it BLEEDS into the next scene rather
than truncating words - and a warning is recorded in report.json.

Configuration (env or CLI):
  MF_TTS_VOICE   e.g. en-US-AndrewNeural (auto voice per language otherwise)
  MF_TTS_RATE    e.g. +8%  (default)
  MF_MUSIC_PATH  optional royalty-free audio file YOU provide (never downloaded)
  MF_MUSIC_GAIN  music volume, default 0.08, only used when path is set
"""

import asyncio
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOTAL_SECONDS = 60.0
SAMPLE_RATE = 24000
START_GAP = 0.25          # narration starts this long after scene start
END_GAP = 0.45            # narration should end this long before scene end
MAX_TEMPO = 1.45          # fastest safe speech speed-up
WORDS_PER_SECOND = 2.7    # planning estimate at default rate

# ---------------------------------------------------------------------------
# Language detection & voices
# ---------------------------------------------------------------------------
def detect_language(text):
    """Cheap unicode-range detection; content is authored, not user text."""
    if re.search(r"[\u0400-\u04FF]", text):
        return "ru"
    if re.search(r"[\u4E00-\u9FFF]", text):
        return "zh"
    if re.search(r"[\u3040-\u30FF]", text):
        return "ja"
    if re.search(r"[\uAC00-\uD7AF]", text):
        return "ko"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    if re.search(r"[\u00C0-\u024F]", text):
        return "es"
    return "en"


VOICES = {
    "en": "en-US-AndrewNeural",     # natural, engaging US male
    "ru": "ru-RU-DmitryNeural",
    "zh": "zh-CN-YunxiNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "ar": "ar-SA-HamedNeural",
    "hi": "hi-IN-MadhurNeural",
    "es": "es-ES-AlvaroNeural",
}


def resolve_voice(text, override=None):
    if override:
        return override
    return VOICES.get(detect_language(text), VOICES["en"])


# ---------------------------------------------------------------------------
# Narration text: composed ONLY from script fields - never from directions
# ---------------------------------------------------------------------------
def _strip_production(text):
    """Legacy packages derive narration from scene overlays, which may carry
    production leftovers. Strip everything that must never be spoken."""
    t = text
    t = re.sub(r"#[\w\-']+", "", t)                     # hashtags
    t = t.replace("✗", " ")                             # strike-through glyph
    t = re.sub(r"(?i)capcut\s*:.*", "", t)              # editor notes
    t = re.sub(r"(?im)^\s*(stickman|bar chart|split screen|export|canvas|logo)\s*:\s*", "", t)
    return t


def clean_spoken(text):
    """Make written-grammar fields comfortable to hear."""
    t = _strip_production(text)
    t = re.sub(r"\((\d{4})\)\s*:\s*", r" in \1, ", t)   # "Chen (2012): x" -> "Chen in 2012, x"
    t = re.sub(r"\((\d{4})\)", r", in \1,", t)          # remaining bare years
    t = re.sub(r"\(([^)]*)\)", r" \1", t)              # remaining parentheses -> spoken plain
    t = t.replace("et al.", "and colleagues")
    t = t.replace("e.g.", "for example").replace("i.e.", "that is")
    t = t.replace("~", "about ")
    t = t.replace("—", ", ").replace("–", " to ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.!?])", r"\1", t)               # no space before punctuation
    return t


def _cap_words(text, seconds, wps=WORDS_PER_SECOND):
    """Keep only whole sentences that plausibly fit the scene window.
    Never cuts mid-sentence: if the first sentence alone is too long it is
    kept in full and the tempo/bleed machinery handles the overrun."""
    limit = max(6, int(seconds * wps))
    words = text.split()
    if len(words) <= limit:
        return text
    kept, count = [], 0
    for sent in re.split(r"(?<=[.!?]) +", text):
        w = len(sent.split())
        if count + w <= limit or not kept:
            kept.append(sent)
            count += w
        else:
            break
    return " ".join(kept)


def build_narration(pkg):
    """Return a list of 5 spoken lines, one per scene (HOOK..PAYOFF).
    Backward compatible: works on any JSON that has the Phase 0 fields."""
    s = pkg["scenes"]
    hook = clean_spoken(pkg.get("hook", ""))
    misconception = clean_spoken(s[1].get("overlay", ""))
    # New packages carry dedicated top-level narration sources; legacy packages
    # fall back to the scene overlays (scene 3's overlay IS its content there).
    truth = clean_spoken(pkg.get("truth") or s[2].get("overlay", ""))
    mechanism = clean_spoken(pkg.get("mechanism") or "")
    evidence = clean_spoken(s[3].get("overlay", ""))
    action = clean_spoken(s[4].get("overlay", ""))

    windows = parse_windows(pkg)
    durs = [e - st for st, e in windows]

    n1 = _cap_words(hook, durs[0] - END_GAP)
    n2 = _cap_words(f"You probably believe this: {misconception} But that's not the full story.", durs[1] - END_GAP)
    n3 = _cap_words(f"{truth} Here's what's happening: {mechanism}".strip() if mechanism else truth,
                    durs[2] - END_GAP)
    n4 = _cap_words(evidence, durs[3] - END_GAP)
    n5 = _cap_words(f"{action} That's your Mindforge move for today. Follow for tomorrow's.", durs[4] - END_GAP)
    return [n1, n2, n3, n4, n5]


# ---------------------------------------------------------------------------
# Scene windows (same format as render.py, but standalone/stdlib)
# ---------------------------------------------------------------------------
def parse_windows(pkg):
    edges = []
    for sc in pkg["scenes"]:
        m = re.findall(r"(\d+):(\d+)", sc["time"])
        if len(m) != 2:
            raise ValueError(f"Unparseable scene time: {sc['time']!r}")
        edges.append((int(m[0][0]) * 60 + int(m[0][1]),
                      int(m[1][0]) * 60 + int(m[1][1])))
    edges.sort()
    return edges


# ---------------------------------------------------------------------------
# TTS engines
# ---------------------------------------------------------------------------
def _ffmpeg():
    exe = os.environ.get("MF_FFMPEG")
    if exe:
        return exe
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg not found (needed for audio processing)")


def _run_ffmpeg(args, timeout=120):
    subprocess.run([_ffmpeg(), "-y", *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                   timeout=timeout, check=True)


def synth_edge(text, voice, out_path, rate, timeout=90, retries=3):
    """Microsoft Edge neural TTS. Unofficial - may 403 from datacenter IPs."""
    import edge_tts

    async def _once():
        com = edge_tts.Communicate(text, voice, rate=rate)
        await asyncio.wait_for(com.save(str(out_path)), timeout=timeout)

    last = None
    for attempt in range(retries):
        try:
            asyncio.run(_once())
            if Path(out_path).stat().st_size > 1000:
                return "edge"
        except Exception as e:  # noqa: BLE001 - report any failure to caller
            last = e
            import time
            time.sleep([3, 7, 15][min(attempt, 2)])
    raise RuntimeError(f"edge-tts failed after {retries} attempts: {last}")


def synth_gtts(text, voice, out_path, rate, **_):
    """Google Translate TTS fallback. `voice` is ignored (lang from prefix)."""
    from gtts import gTTS
    lang = voice.split("-")[0] if "-" in voice else "en"
    gTTS(text=text, lang=lang if lang in {"en", "ru", "zh", "ja", "ko", "ar", "hi", "es"} else "en").save(str(out_path))
    return "gtts"


def synth_none(text, voice, out_path, rate, **_):
    """Explicit silent mode (--engine none): writes a header-only track."""
    Path(out_path).write_bytes(b"")
    return "none"


ENGINES = {"edge": synth_edge, "gtts": synth_gtts, "none": synth_none}


def synth_with_fallback(text, voice, out_path, engine="auto", rate=None):
    """Try engines in order until one produces audio. Raises if all fail."""
    rate = rate or os.environ.get("MF_TTS_RATE", "+8%")
    if engine in ENGINES:
        order = [engine]                      # explicit engine (incl. test fakes)
    else:
        order = ["edge", "gtts"]              # auto: quality first, fallback second
    errors = []
    for name in order:
        try:
            used = ENGINES[name](text, voice, out_path, rate)
            return used
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
    raise RuntimeError("All TTS engines failed -> " + " | ".join(errors))


# ---------------------------------------------------------------------------
# Audio measurement / tempo / mixing (stdlib `wave` + ffmpeg decode)
# ---------------------------------------------------------------------------
def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def decode_to_wav(src, dst, tempo=None):
    """Decode any audio to 24kHz mono 16-bit PCM wav (optionally tempo-scaled)."""
    args = ["-i", str(src)]
    if tempo and abs(tempo - 1.0) > 0.01:
        args += ["-filter:a", f"atempo={tempo:.4f}"]
    args += ["-ar", str(SAMPLE_RATE), "-ac", "1", str(dst)]
    _run_ffmpeg(args)


def wav_samples(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    n = len(raw) // 2
    return [struct.unpack("<h", raw[i * 2:i * 2 + 2])[0] for i in range(n)]


def normalize(samples, peak=0.82):
    m = max(1, max(abs(x) for x in samples) if samples else 1)
    if m <= int(peak * 32767):
        return samples, 1.0
    gain = peak * 32767 / m
    return [int(x * gain) for x in samples], gain


def mix_track(scene_audio, windows, out_path, music_path=None, music_gain=0.08):
    """Place each scene's samples on a 60s track; music (optional) underneath.
    Words are never truncated: narration may bleed past a scene end (warning
    is returned in the report)."""
    total = int(TOTAL_SECONDS * SAMPLE_RATE)
    track = [0] * total
    report = []
    for i, (path, (start, end)) in enumerate(zip(scene_audio, windows), 1):
        if not path or not Path(path).exists() or Path(path).stat().st_size == 0:
            raise RuntimeError(f"Scene {i} narration audio missing: {path}")
        samples = wav_samples(path)
        offset = int((start + (START_GAP if start > 0 else 0.15)) * SAMPLE_RATE)
        overflow = (offset + len(samples)) / SAMPLE_RATE - end
        if overflow > 0.05:
            report.append(f"scene {i}: narration bleeds {overflow:.2f}s past scene end (words preserved)")
        for j, v in enumerate(samples):
            p = offset + j
            if p >= total:
                report.append(f"scene {i}: narration exceeded the 60s track - TAIL TRIMMED at master track")
                break
            track[p] += v
    if music_path:
        mg, _tmp = _decode_loop_music(music_path, total)
        if mg:
            for p in range(total):
                track[p] += int(mg[p] * music_gain)
    # master saturation + normalization
    peak = max(1, max(abs(x) for x in track))
    scale = 1.0 if peak <= 32700 else 32700 / peak
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for v in track:
            x = int(v * scale)
            frames += struct.pack("<h", max(-32768, min(32767, x)))
        w.writeframes(bytes(frames))
    return report


def _decode_loop_music(music_path, total_samples):
    tmp = Path(music_path).with_suffix(".loop.wav")
    decode_to_wav(music_path, tmp)
    samples = wav_samples(tmp)
    try:
        tmp.unlink()
    except OSError:
        pass
    if not samples:
        return [0] * total_samples, None
    repeats = math.ceil(total_samples / len(samples))
    return (samples * repeats)[:total_samples], None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def generate_voiceover(pkg, outdir, engine="auto", voice_override=None, rate=None):
    """Full pipeline: narration text -> TTS -> tempo-fit -> mixed 60s track."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = pkg.get("narration") or build_narration(pkg)
    if not lines or len(lines) != 5:
        raise RuntimeError("narration fields missing/invalid and could not be composed")
    for i, ln in enumerate(lines, 1):
        if not ln or len(ln.split()) < 2:
            raise RuntimeError(f"Scene {i} narration is empty or invalid: {ln!r}")

    voice = resolve_voice(" ".join(lines), voice_override)
    windows = parse_windows(pkg)
    durs = [e - st for st, e in windows]

    scene_files, report = [], {"engine_order": engine, "voice": voice, "scenes": []}
    for i, (line, (start, end)) in enumerate(zip(lines, windows), 1):
        mp3 = outdir / f"scene_{i}.mp3"
        used = synth_with_fallback(line, voice, mp3, engine, rate)
        if used == "none":
            scene_files.append(None)
            report["scenes"].append({"scene": i, "engine": "none", "audio": None})
            continue
        raw = outdir / f"scene_{i}_raw.wav"
        decode_to_wav(mp3, raw)
        dur = wav_duration(raw)
        max_len = (end - start) - END_GAP
        tempo = 1.0
        if dur > max_len > 0:
            tempo = min(MAX_TEMPO, dur / max_len)
        fitted = raw
        if tempo > 1.001:
            fitted = outdir / f"scene_{i}_fitted.wav"
            decode_to_wav(mp3, fitted, tempo=tempo)
            fitted_dur = wav_duration(fitted)
        else:
            fitted_dur = dur
        scene_files.append(fitted)
        report["scenes"].append({
            "scene": i, "engine": used, "text_words": len(line.split()),
            "raw_duration": round(dur, 2), "tempo": round(tempo, 2),
            "fitted_duration": round(fitted_dur, 2), "window": round(end - start, 2),
        })

    narration_path = outdir / "narration.wav"
    music = os.environ.get("MF_MUSIC_PATH")
    warnings = mix_track(scene_files, windows, narration_path,
                         music_path=music if music else None,
                         music_gain=float(os.environ.get("MF_MUSIC_GAIN", "0.08")))
    report["warnings"] = warnings
    report["narration_wav"] = str(narration_path)
    (outdir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return narration_path, report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a.split("=", 1)[0] for a in argv[1:] if a.startswith("--")}
    opts = dict(a.split("=", 1) for a in argv[1:] if a.startswith("--") and "=" in a)
    json_path = Path(args[0]) if args else ROOT / "content" / f"{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%d')}.json"
    if not json_path.exists():
        print(f"[error] JSON not found: {json_path}", file=sys.stderr)
        return 1
    pkg = json.loads(json_path.read_text(encoding="utf-8"))
    engine = opts.get("engine", os.environ.get("MF_TTS_ENGINE", "auto"))
    outdir = Path(opts.get("outdir", ROOT / "voice" / pkg.get("date", "out")))
    try:
        narration, report = generate_voiceover(pkg, outdir, engine=engine,
                                               voice_override=os.environ.get("MF_TTS_VOICE"))
    except Exception as e:  # noqa: BLE001
        print(f"[error] voiceover generation FAILED: {e}", file=sys.stderr)
        print("        A silent video will NOT be produced. Fix TTS access or rerun.", file=sys.stderr)
        return 1
    dur = wav_duration(narration)
    print(f"[ok] narration: {narration} ({dur:.2f}s, engine={report['scenes'][0]['engine'] if report['scenes'] else '?'})")
    for w in report["warnings"]:
        print(f"[warn] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
