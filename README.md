# Mindforge — Daily Psychology Shorts Automation

Generates one complete 60-second YouTube Shorts video package every day, automatically:

- 🎯 Video idea + hook
- 📌 3 title options
- 🏷️ Tags & hashtags
- 📝 Copy-paste-ready YouTube description
- 🎬 A 5-scene **silent stickman visual script** with exact text overlays, timings (0:00–1:00), and styling notes for CapCut

Output lands in `content/` as both **Markdown** (human-friendly) and **JSON** (machine-friendly).
A `state.json` file tracks which topics have been used and which topic belongs to each date, so content never repeats within a cycle (the 48-topic bank cycles every ~7 weeks; rotating title/hook variants keep repeat topics feeling fresh).

**Since Phase 1, the daily workflow also renders that package into a finished vertical video** (1080×1920 H.264 MP4, ~60s, 30fps) with animated stickman scenes, text overlays, transitions and a progress bar.

**Since Phase 2, every video ships with natural AI narration** (Microsoft Edge neural voice) synchronized to the five scenes. MP4s are saved as GitHub Actions **artifacts** (retained 30 days) — never committed to the repo (`output/` and `voice/` are gitignored).

## ✅ Requirements

- Python 3.8+ (the **generator** itself is stdlib-only)
- For **video rendering + voiceover**: `pip install -r requirements.txt` (Pillow, imageio-ffmpeg which bundles ffmpeg, edge-tts, gTTS — no system install or API keys needed). On GitHub Actions ubuntu runners, ffmpeg is already preinstalled.

## 🏠 Run locally

```bash
cd mindforge
python generate.py            # create today's content package (now includes per-scene narration)
python narrator.py content/2026-11-14.json --outdir voice   # TTS narration -> voice/<date>/narration.wav
python render.py              # render it to output/YYYY-MM-DD.mp4 (silent, 1080x1920, ~60s)
python render.py content/2026-11-14.json --audio=voice/2026-11-14/narration.wav   # with narration
python render.py --preview    # fast low-res test render (270x480, first 6s)
```

Render a specific package:

```bash
python render.py content/2026-11-12.json --out output/my.mp4
```

Run the test suites:

```bash
python test_render.py         # Phase 1: renderer unit tests + real-MP4 integration test
python test_narrator.py       # Phase 2: narration purity, sync/mix tests, audio-MP4 integration (offline; fake TTS engines)
```

The generator keeps its original flags: `python generate.py` (creates today's package, skips if it exists) and `python generate.py --force` (overwrites today's files; the previously recorded topic is un-marked and a fresh one is picked).

## ☁️ Set up the daily automation (GitHub Actions)

1. Create a new **public or private GitHub repository** named e.g. `mindforge`.
2. Copy this whole folder into it (keep the `.github/workflows/daily-content.yml` path intact):
   ```
   mindforge/
   ├── generate.py
   ├── README.md
   ├── content/            (created automatically)
   └── .github/
       └── workflows/
           └── daily-content.yml
   ```
3. Push it:
   ```bash
   git init
   git add .
   git commit -m "Mindforge daily content system"
   git remote add origin https://github.com/YOUR_USERNAME/mindforge.git
   git push -u origin main
   ```
4. Done. The workflow runs **every day at 06:00 UTC**, generates the package, and commits it to `content/`.

### Manual run / testing the workflow

- Go to your repo → **Actions** → **Daily Mindforge Content** → **Run workflow**.
- If nothing appears yet: enable Actions in repo **Settings → Actions → General** if needed.
- Note: scheduled workflows on repos inactive for 60 days get paused by GitHub — just re-enable or push occasionally.

### Optional: LLM-enhanced copy

Set a repository secret `OPENAI_API_KEY` (Settings → Secrets and variables → Actions) and the workflow will
automatically use GPT-4o-mini to punch up the overlays. Without the key, the built-in template engine is used — it needs no API and never fails.

## 🎙️ Phase 2 — AI voiceover

`narrator.py` turns a package into a synchronized 60-second narration track:

1. **Narration text** — composed ONLY from the script itself (hook, misconception, truth, mechanism, evidence, action + CTA). Scene directions, animation notes, CapCut notes and hashtags are never spoken (the generator emits a dedicated `narration` field; older packages are recomputed on the fly and sanitized).
2. **TTS** — Microsoft **edge-tts** neural voices (free, no API key). If edge-tts fails (it uses an *unofficial* Microsoft endpoint that occasionally 403s datacenter/CI IPs), it automatically falls back to **gTTS**. If both fail, the pipeline **fails loudly** — a silent video is never produced.
3. **Sync** — each scene's narration starts 0.25s after the scene begins (0.15s for scene 1). Overlong lines are sped up via ffmpeg `atempo` (capped at 1.45×); if still too long, narration **bleeds** into the next scene rather than cutting words, and the bleed is recorded as a warning in `voice/<date>/report.json`.
4. **Mix** — all scenes are placed onto an exact 60.00s 24 kHz mono track (peak-normalized, never clipping), then muxed into the MP4 (AAC 160k). Output stays 1080×1920, H.264, yuv420p, 30fps, exactly 60s.

### Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `MF_TTS_ENGINE` | `auto` | `auto` (edge → gtts fallback), `edge`, or `gtts` |
| `MF_TTS_VOICE` | auto per language | Any edge voice id, e.g. `en-US-AndrewNeural` |
| `MF_TTS_RATE` | `+8%` | Speech rate, e.g. `+15%` (faster) / `-10%` (slower) |
| `MF_MUSIC_PATH` | _(unset = off)_ | Path to a **royalty-free** audio file YOU provide. Never downloaded; disabled by default. |
| `MF_MUSIC_GAIN` | `0.08` | Music volume under the narration (only used when `MF_MUSIC_PATH` is set) |
| `MF_FFMPEG` | auto-detect | Explicit ffmpeg binary path |

The language of the content is auto-detected (English, Russian, Chinese, Japanese, Korean, Arabic, Hindi, Spanish) and a matching neural voice is chosen automatically.

### Troubleshooting

| Symptom | Cause & fix |
|---|---|
| `edge-tts failed after 3 attempts` | Unofficial endpoint blocked your IP (403) or network down. The workflow falls back to gTTS automatically; locally you can retry, force `MF_TTS_ENGINE=gtts`, or set up a VPN/proxy. |
| All TTS engines failed → workflow step red | Intentional fail-loud behavior. No silent video is produced; re-run the workflow. |
| Narration sounds rushed | Raise `MF_TTS_RATE` speed or let it bleed (words are never cut; bleeds are listed in `report.json`). |
| Mixed voice quality in one video | One scene fell back to gTTS (edge flaked for that scene only). Retry, or pin `MF_TTS_ENGINE=edge`. |
| ffmpeg not found | Set `MF_FFMPEG` to your ffmpeg path (imageio-ffmpeg is bundled via requirements). |

## 📁 File map

| Path | Purpose |
|---|---|
| `generate.py` | The daily content generator (idea bank + template engine + optional LLM) |
| `render.py` | Phase 1 renderer: JSON package → 1080×1920 stickman MP4 (silent or `--audio` muxed) |
| `narrator.py` | Phase 2 voiceover: package → synchronized 60s narration track (edge-tts + gTTS fallback) |
| `test_render.py` | Phase 1 test suite (`python test_render.py`) |
| `test_narrator.py` | Phase 2 test suite (`python test_narrator.py`) |
| `requirements.txt` | Dependencies (Pillow, imageio-ffmpeg, edge-tts, gTTS) |
| `content/YYYY-MM-DD.md` | Daily package, human-readable |
| `content/YYYY-MM-DD.json` | Same package, machine-readable (includes per-scene `narration`) |
| `content/state.json` | Tracks used topics, per-date topic map and history (no repeats) |
| `output/*.mp4` | Rendered videos (gitignored; uploaded as Actions artifacts) |
| `voice/<date>/` | TTS audio, fitted scene tracks, `narration.wav`, `report.json` (gitignored) |
| `.github/workflows/daily-content.yml` | The daily scheduler: generate → voiceover → render → artifact |

## 🎬 Using the output in CapCut

1. Open today's `content/YYYY-MM-DD.md`.
2. Create a 1080×1920 (9:16) project, black background.
3. Follow each scene: draw the stick figure as described, then add the exact overlay text at the listed timestamp.
4. The "CapCut Notes" section at the bottom lists font, export and style settings.
