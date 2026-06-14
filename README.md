# Mercedes F1 Strategy Predictor — Self-Updating System

Predicts pit stop strategy, optimal lap windows, and position gain for
**George Russell** and **Kimi Antonelli** at every 2026 Grand Prix.
Automatically updates after every race using GitHub Actions.

---

## How it works

```
Every Sunday after the race
        │
        ▼
GitHub Actions runs update_data.py
        │
        ▼
Downloads f1db repo (open-source F1 database, updated within 24h of each race)
        │
        ▼
Extracts Mercedes pit stop + stint data for 2018–present
        │
        ▼
Rebuilds prediction model JSON → data/mercedes_strategy.json
        │
        ▼
Commits updated JSON back to this repo
        │
        ▼
The web app fetches the latest JSON on every page load
→ predictions always reflect the most recent race
```

---

## Repo structure

```
mercedes-f1-strategy/
├── .github/
│   └── workflows/
│       └── update-race-data.yml   ← GitHub Actions (runs every Sunday 22:00 UTC)
├── scripts/
│   └── update_data.py             ← Data pipeline (downloads, processes, writes JSON)
├── data/
│   └── mercedes_strategy.json     ← Auto-generated prediction model (DO NOT EDIT)
├── index.html                     ← The web app (open this in a browser)
├── requirements.txt
└── README.md
```

---

## Setup (one-time, ~5 minutes)

### 1. Create a GitHub repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `mercedes-f1-strategy` (or anything you like)
3. Make it **Public** (required for free GitHub Pages hosting)
4. Click **Create repository**

### 2. Push this code

```bash
cd mercedes-f1-strategy
git init
git add .
git commit -m "Initial setup"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mercedes-f1-strategy.git
git push -u origin main
```

### 3. Enable GitHub Pages (to host the web app)

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select `main` branch, `/ (root)` folder
3. Click **Save**
4. Your app will be live at:
   `https://YOUR_USERNAME.github.io/mercedes-f1-strategy/`

### 4. Run the first data update

1. Go to your repo → **Actions** tab
2. Click **"Update race data after each Grand Prix"**
3. Click **"Run workflow"** → **"Run workflow"**
4. Wait ~2 minutes for it to complete
5. The `data/mercedes_strategy.json` will be committed automatically

### 5. Done!

The app will now:
- Auto-update every Sunday at 22:00 UTC (after races)
- Also run every Monday at 06:00 UTC (catches Saturday races like Baku/Las Vegas)
- Be triggerable manually anytime via the Actions tab

---

## Local development

```bash
pip install -r requirements.txt
python scripts/update_data.py   # generates data/mercedes_strategy.json locally
open index.html                 # open in browser
```

---

## Data sources

| Source | What it provides |
|--------|-----------------|
| [f1db on GitHub](https://github.com/f1db/f1db) | Pit stop laps, race results, grid positions — updated within 24h of each race |
| Historical data | 2018–2026 Mercedes stint analysis (358+ race entries) |

### What the model predicts
- **Number of pit stops** — based on most common strategy at this circuit in recent seasons
- **Optimal pit laps** — from historical averages, adjusted for your starting grid position
- **Position gain** — average gain/loss for Mercedes using that strategy at this circuit, adjusted for weather and grid slot
- **Driver tendency** — per-driver historical preference at each circuit

### What it cannot predict
- Tire compound (Soft/Medium/Hard) — not in the f1db dataset; requires FastF1 access
- Safety car timing — random events that can flip strategy
- Real-time degradation — would need live telemetry

---

## After each race weekend

Nothing. GitHub Actions handles it automatically.

To **force** an immediate update (e.g. after a race you want to analyse right away):
1. Go to **Actions** → **"Update race data"** → **"Run workflow"**

---

## Updating the 2026 calendar

If races are added or cancelled, edit the `CALENDAR_2026` list in `scripts/update_data.py`.
The GitHub Actions workflow will use the updated calendar on its next run.

---

## License

Data from [f1db](https://github.com/f1db/f1db) is licensed under CC BY 4.0.
This code is MIT licensed.
