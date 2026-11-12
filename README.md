# Mindforge — Daily Psychology Shorts Automation

Generates one complete 60-second YouTube Shorts video package every day, automatically:

- 🎯 Video idea + hook
- 📌 3 title options
- 🏷️ Tags & hashtags
- 📝 Copy-paste-ready YouTube description
- 🎬 A 5-scene **silent stickman visual script** with exact text overlays, timings (0:00–1:00), and styling notes for CapCut

Output lands in `content/` as both **Markdown** (human-friendly) and **JSON** (machine-friendly).
A `state.json` file tracks which topics have been used and which topic belongs to each date, so content never repeats within a cycle (the 48-topic bank cycles every ~7 weeks; rotating title/hook variants keep repeat topics feeling fresh).

## ✅ Requirements

- Python 3.8+ (nothing to install — stdlib only)

## 🏠 Run locally

```bash
cd mindforge
python generate.py
```

Today's files appear in `content/YYYY-MM-DD.md` and `content/YYYY-MM-DD.json`.

To regenerate the same day (overwrites today's files; the previously recorded topic is un-marked and a fresh one is picked):

```bash
python generate.py --force
```

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
| `generate.py` | The generator (idea bank + template engine + optional LLM) |
| `content/YYYY-MM-DD.md` | Daily package, human-readable |
| `content/YYYY-MM-DD.json` | Same package, machine-readable |
| `content/state.json` | Tracks used topics, per-date topic map and history (no repeats) |
| `.github/workflows/daily-content.yml` | The daily scheduler |

## 🎬 Using the output in CapCut

1. Open today's `content/YYYY-MM-DD.md`.
2. Create a 1080×1920 (9:16) project, black background.
3. Follow each scene: draw the stick figure as described, then add the exact overlay text at the listed timestamp.
4. The "CapCut Notes" section at the bottom lists font, export and style settings.
