# Mindforge — Daily Psychology Shorts Automation

Generates one complete 60-second YouTube Shorts video package every day, automatically:

- 🎯 Video idea + hook
- 📌 3 title options
- 🏷️ Tags & hashtags
- 📝 Copy-paste-ready YouTube description
- 🎬 A 5-scene **silent stickman visual script** with exact text overlays, timings (0:00–1:00), and styling notes for CapCut

Output lands in `content/` as both **Markdown** (human-friendly) and **JSON** (machine-friendly).
A `state.json` file tracks which topics have been used and which topic belongs to each date, so content never repeats within a cycle (the 48-topic bank cycles every ~7 weeks; rotating title/hook variants keep repeat topics feeling fresh).

**Since Phase 1, the daily workflow also renders that package into a finished vertical video** (1080×1920 H.264 MP4, ~60s, 30fps) with animated stickman scenes, text overlays, transitions and a progress bar. MP4s are saved as GitHub Actions **artifacts** (retained 30 days) — never committed to the repo (`output/` is gitignored).

## ✅ Requirements

- Python 3.8+ (the **generator** itself is stdlib-only)
- For **video rendering**: `pip install -r requirements.txt` (Pillow + imageio-ffmpeg, which bundles ffmpeg — no system install needed). On GitHub Actions ubuntu runners, ffmpeg is already preinstalled.

## 🏠 Run locally

```bash
cd mindforge
python generate.py            # create today's content package
python render.py              # render it to output/YYYY-MM-DD.mp4 (1080x1920, ~60s)
python render.py --preview    # fast low-res test render (270x480, first 6s)
```

Render a specific package:

```bash
python render.py content/2026-11-12.json --out output/my.mp4
```

Run the test suite:

```bash
python test_render.py         # unit tests + one real-MP4 integration test
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

## 📁 File map

| Path | Purpose |
|---|---|
| `generate.py` | The daily content generator (idea bank + template engine + optional LLM) |
| `render.py` | Phase 1 renderer: JSON package → 1080×1920 stickman MP4 |
| `test_render.py` | Renderer test suite (`python test_render.py`) |
| `requirements.txt` | Rendering dependencies (Pillow, imageio-ffmpeg) |
| `content/YYYY-MM-DD.md` | Daily package, human-readable |
| `content/YYYY-MM-DD.json` | Same package, machine-readable |
| `content/state.json` | Tracks used topics, per-date topic map and history (no repeats) |
| `output/*.mp4` | Rendered videos (gitignored; uploaded as Actions artifacts) |
| `.github/workflows/daily-content.yml` | The daily scheduler: generate → render → artifact |

## 🎬 Using the output in CapCut

1. Open today's `content/YYYY-MM-DD.md`.
2. Create a 1080×1920 (9:16) project, black background.
3. Follow each scene: draw the stick figure as described, then add the exact overlay text at the listed timestamp.
4. The "CapCut Notes" section at the bottom lists font, export and style settings.
