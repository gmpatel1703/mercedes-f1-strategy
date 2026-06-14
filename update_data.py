"""
Mercedes F1 Strategy Predictor — Auto-Updater
==============================================
Runs after each race weekend (triggered by GitHub Actions).
Fetches the latest race data from f1db (open-source F1 database on GitHub),
extracts Mercedes stint/pit-stop data, rebuilds the prediction model JSON,
and writes it to data/mercedes_strategy.json.

The JSON is then read live by the frontend app.

Data sources:
  - Historical stints (2018-2025): f1db GitHub repo YAML files
  - 2026 results: f1db GitHub repo YAML files (updated within ~24h of each race)
"""

import requests
import zipfile
import io
import yaml
import json
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────────────

F1DB_ZIP_URL = "https://codeload.github.com/f1db/f1db/zip/refs/heads/main"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mercedes_strategy.json")

MERCEDES_ID = "mercedes"
TARGET_SEASONS = list(range(2018, 2027))  # 2018 through current

DRIVER_NAMES = {
    "lewis-hamilton":        "Lewis Hamilton",
    "valtteri-bottas":       "Valtteri Bottas",
    "george-russell":        "George Russell",
    "andrea-kimi-antonelli": "Kimi Antonelli",
    "nico-rosberg":          "Nico Rosberg",
}

# 2026 full calendar (locked in at season start)
CALENDAR_2026 = [
    {"round": 1,  "name": "Australia",    "date": "2026-03-08", "circuit": "Melbourne"},
    {"round": 2,  "name": "China",        "date": "2026-03-15", "circuit": "Shanghai",    "sprint": True},
    {"round": 3,  "name": "Japan",        "date": "2026-03-29", "circuit": "Suzuka"},
    {"round": 4,  "name": "Miami",        "date": "2026-05-03", "circuit": "Miami Gardens"},
    {"round": 5,  "name": "Canada",       "date": "2026-05-25", "circuit": "Montreal"},
    {"round": 6,  "name": "Monaco",       "date": "2026-06-07", "circuit": "Monaco"},
    {"round": 7,  "name": "Spain",        "date": "2026-06-14", "circuit": "Barcelona"},
    {"round": 8,  "name": "Austria",      "date": "2026-06-28", "circuit": "Red Bull Ring"},
    {"round": 9,  "name": "Great Britain","date": "2026-07-05", "circuit": "Silverstone",  "sprint": True},
    {"round": 10, "name": "Belgium",      "date": "2026-07-19", "circuit": "Spa-Francorchamps"},
    {"round": 11, "name": "Hungary",      "date": "2026-07-26", "circuit": "Hungaroring"},
    {"round": 12, "name": "Netherlands",  "date": "2026-08-23", "circuit": "Zandvoort",   "sprint": True},
    {"round": 13, "name": "Italy",        "date": "2026-09-06", "circuit": "Monza"},
    {"round": 14, "name": "Madrid",       "date": "2026-09-13", "circuit": "Madrid"},
    {"round": 15, "name": "Azerbaijan",   "date": "2026-09-27", "circuit": "Baku"},
    {"round": 16, "name": "Singapore",    "date": "2026-10-11", "circuit": "Marina Bay",  "sprint": True},
    {"round": 17, "name": "United States","date": "2026-10-25", "circuit": "COTA"},
    {"round": 18, "name": "Mexico",       "date": "2026-11-01", "circuit": "Mexico City"},
    {"round": 19, "name": "Sao Paulo",    "date": "2026-11-08", "circuit": "Interlagos"},
    {"round": 20, "name": "Las Vegas",    "date": "2026-11-21", "circuit": "Las Vegas Strip"},
    {"round": 21, "name": "Qatar",        "date": "2026-11-29", "circuit": "Lusail"},
    {"round": 22, "name": "Abu Dhabi",    "date": "2026-12-06", "circuit": "Yas Marina"},
]

# GP name normaliser: maps f1db grandPrixId → our display name
GP_NAME_MAP = {
    "australia": "Australia", "china": "China", "japan": "Japan",
    "bahrain": "Bahrain", "saudi-arabia": "Saudi Arabia",
    "miami": "Miami", "emilia-romagna": "Emilia Romagna",
    "monaco": "Monaco", "spain": "Spain", "canada": "Canada",
    "great-britain": "Great Britain", "austria": "Austria",
    "hungary": "Hungary", "belgium": "Belgium",
    "netherlands": "Netherlands", "italy": "Italy",
    "singapore": "Singapore", "japan": "Japan",
    "united-states": "United States", "mexico-city": "Mexico",
    "sao-paulo": "Sao Paulo", "las-vegas": "Las Vegas",
    "qatar": "Qatar", "abu-dhabi": "Abu Dhabi",
    "azerbaijan": "Azerbaijan", "portugal": "Portugal",
    "france": "France", "russia": "Russia", "turkey": "Turkey",
    "germany": "Germany", "sakhir": "Sakhir", "tuscany": "Tuscany",
    "styria": "Styria", "eifel": "Eifel",
    "70th-anniversary": "70Th Anniversary",
    "brazil": "Sao Paulo",
    "madrid": "Madrid",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def download_f1db():
    print("Downloading f1db repo zip …")
    r = requests.get(F1DB_ZIP_URL, timeout=120, stream=True)
    r.raise_for_status()
    content = b""
    for chunk in r.iter_content(chunk_size=32768):
        content += chunk
        if len(content) > 80 * 1024 * 1024:
            break
    print(f"  Downloaded {len(content)/1024/1024:.1f} MB")
    return zipfile.ZipFile(io.BytesIO(content))


def read_yaml(z, path):
    try:
        return yaml.safe_load(z.read(path).decode("utf-8")) or []
    except Exception:
        return []


def safe_float(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def normalise_gp_name(grand_prix_id):
    return GP_NAME_MAP.get(grand_prix_id, grand_prix_id.replace("-", " ").title())


# ── Core extraction ──────────────────────────────────────────────────────────

def extract_all_races(z):
    """
    Walk f1db YAML source files and extract every Mercedes race entry
    for seasons 2018–present.
    Returns: list of race-level dicts, list of stint-level dicts.
    """
    all_files = z.namelist()

    # Build race metadata (race.yml per round)
    race_meta = {}
    for f in all_files:
        if "/races/" in f and f.endswith("/race.yml") and "/seasons/" in f:
            parts = f.split("/")
            try:
                si = parts.index("seasons")
                season = int(parts[si + 1])
                if season not in TARGET_SEASONS:
                    continue
                race_dir = parts[si + 3]
                data = yaml.safe_load(z.read(f).decode("utf-8")) or {}
                gp_id = data.get("grandPrixId", "")
                race_meta[(season, race_dir)] = {
                    "grand_prix": normalise_gp_name(gp_id),
                    "gp_id": gp_id,
                    "official_name": data.get("officialName", ""),
                    "circuit_id": data.get("circuitId", ""),
                    "date": str(data.get("date", "")),
                    "total_laps": data.get("laps"),
                    "round": data.get("round"),
                }
            except Exception:
                continue

    race_rows = []   # one row per driver per race
    stint_rows = []  # one row per stint per driver per race

    for season in TARGET_SEASONS:
        race_dirs = set()
        for f in all_files:
            key = f"seasons/{season}/races/"
            if key in f:
                parts = f.split("/")
                try:
                    ri = parts.index("races")
                    if ri + 1 < len(parts):
                        race_dirs.add(parts[ri + 1])
                except ValueError:
                    pass

        for race_dir in sorted(race_dirs):
            meta = race_meta.get((season, race_dir), {})
            if not meta:
                continue

            base = f"f1db-main/src/data/seasons/{season}/races/{race_dir}"

            pit_stops = read_yaml(z, f"{base}/pit-stops.yml")
            results   = read_yaml(z, f"{base}/race-results.yml")

            total_laps = meta.get("total_laps")
            merc_results = {}

            for res in results:
                if res.get("constructorId") != MERCEDES_ID:
                    continue
                drv = res.get("driverId", "")
                laps = res.get("laps")
                if laps and not total_laps:
                    total_laps = laps
                merc_results[drv] = {
                    "finish_position": res.get("position"),
                    "laps_completed": laps,
                    "grid_position": res.get("gridPosition"),
                    "points_scored": res.get("points"),
                }

            if not merc_results:
                continue

            # Collect pit stops per Mercedes driver
            merc_pits = [p for p in pit_stops if p.get("constructorId") == MERCEDES_ID]
            pits_by_driver = defaultdict(list)
            for p in merc_pits:
                drv = p.get("driverId", "")
                pits_by_driver[drv].append({
                    "stop": int(p.get("stop", 0)),
                    "lap": int(p.get("lap", 0)),
                    "duration": str(p.get("time", "")),
                })

            for drv_id, res in merc_results.items():
                laps_done = res.get("laps_completed") or total_laps
                driver_name = DRIVER_NAMES.get(drv_id, drv_id)
                driver_pits = sorted(pits_by_driver.get(drv_id, []), key=lambda x: x["stop"])
                num_stops = len(driver_pits)
                pit_laps = [p["lap"] for p in driver_pits]

                # One race-level summary row
                race_rows.append({
                    "season": season,
                    "round": meta.get("round"),
                    "date": meta.get("date"),
                    "grand_prix": meta.get("grand_prix"),
                    "gp_id": meta.get("gp_id"),
                    "circuit": meta.get("circuit_id"),
                    "driver": driver_name,
                    "driver_id": drv_id,
                    "total_pit_stops": num_stops,
                    "strategy_type": f"{num_stops}-stop",
                    "total_race_laps": laps_done,
                    "finish_position": res.get("finish_position"),
                    "grid_position": res.get("grid_position"),
                    "points_scored": res.get("points_scored"),
                })

                # Stint rows
                for i, pit in enumerate(driver_pits):
                    stint_start = (pit_laps[i - 1] + 1) if i > 0 else 1
                    stint_end = pit["lap"]
                    stint_len = stint_end - stint_start + 1

                    dur = pit.get("duration", "")
                    dur_clean = dur if ":" not in str(dur) or str(dur).count(":") == 1 else None

                    stint_rows.append({
                        "season": season, "round": meta.get("round"),
                        "grand_prix": meta.get("grand_prix"),
                        "driver": driver_name,
                        "stint_number": i + 1,
                        "stint_start_lap": stint_start,
                        "stint_end_lap": stint_end,
                        "stint_length_laps": stint_len,
                        "pit_stop_on_lap": pit["lap"],
                        "stop_number": pit["stop"],
                        "pit_duration_sec": dur_clean,
                        "finish_position": res.get("finish_position"),
                        "grid_position": res.get("grid_position"),
                        "total_race_laps": laps_done,
                    })

                # Final stint
                if laps_done and pit_laps:
                    final_start = pit_laps[-1] + 1
                    final_len = laps_done - pit_laps[-1]
                    stint_rows.append({
                        "season": season, "round": meta.get("round"),
                        "grand_prix": meta.get("grand_prix"),
                        "driver": driver_name,
                        "stint_number": num_stops + 1,
                        "stint_start_lap": final_start,
                        "stint_end_lap": laps_done,
                        "stint_length_laps": final_len,
                        "pit_stop_on_lap": None,
                        "stop_number": None,
                        "pit_duration_sec": None,
                        "finish_position": res.get("finish_position"),
                        "grid_position": res.get("grid_position"),
                        "total_race_laps": laps_done,
                    })

    return race_rows, stint_rows


# ── Model building ───────────────────────────────────────────────────────────

def build_gp_model(race_rows, stint_rows):
    """
    For each Grand Prix, compute:
      - strategy distribution (% per stop count)
      - pit timing per stop number (avg, std, min, max)
      - avg position gain per strategy
      - recent form (last 3 seasons weighted 2x)
      - per-driver recent tendency
    """
    from math import sqrt

    gp_model = {}

    # Group by grand prix
    gps = set(r["grand_prix"] for r in race_rows)

    for gp in gps:
        gp_races = [r for r in race_rows if r["grand_prix"] == gp]
        gp_stints = [s for s in stint_rows if s["grand_prix"] == gp and s["pit_stop_on_lap"] is not None]

        if not gp_races:
            continue

        total_laps_vals = [r["total_race_laps"] for r in gp_races if r["total_race_laps"]]
        total_laps = int(max(total_laps_vals)) if total_laps_vals else 60

        # ── Strategy distribution ──────────────────────────────────────────
        strat_counts = defaultdict(int)
        recent_strat_counts = defaultdict(int)
        latest_season = max(r["season"] for r in gp_races)

        for r in gp_races:
            key = r["strategy_type"]
            strat_counts[key] += 1
            # Weight recent 3 seasons double
            if r["season"] >= latest_season - 2:
                recent_strat_counts[key] += 2
            else:
                recent_strat_counts[key] += 1

        total = sum(strat_counts.values())
        strat_dist = {
            k: {"count": v, "pct": round(v / total * 100)}
            for k, v in sorted(strat_counts.items())
        }

        # Most common overall vs recent
        most_common = max(strat_counts, key=strat_counts.get)
        recent_most_common = max(recent_strat_counts, key=recent_strat_counts.get)

        # ── Pit stop timing ────────────────────────────────────────────────
        pit_timing = {}
        for stop_n in range(1, 6):
            laps = [s["pit_stop_on_lap"] for s in gp_stints
                    if s["stop_number"] == stop_n and s["pit_stop_on_lap"]]
            if not laps:
                continue
            avg = sum(laps) / len(laps)
            variance = sum((x - avg) ** 2 for x in laps) / len(laps)
            std = sqrt(variance)
            pit_timing[stop_n] = {
                "avg": round(avg, 1),
                "std": round(std, 1),
                "min": min(laps),
                "max": max(laps),
                "count": len(laps),
            }

        # ── Position gain by strategy ──────────────────────────────────────
        gain_by_strat = defaultdict(list)
        for r in gp_races:
            try:
                g = int(r["grid_position"])
                f = int(r["finish_position"])
                gain_by_strat[r["strategy_type"]].append(g - f)
            except (TypeError, ValueError):
                pass

        avg_gain = {
            k: round(sum(v) / len(v), 1)
            for k, v in gain_by_strat.items() if v
        }

        # ── Per-driver recent tendency (last 2 seasons) ────────────────────
        driver_tendency = {}
        drivers_seen = set(r["driver"] for r in gp_races)
        for drv in drivers_seen:
            drv_races = [r for r in gp_races
                         if r["driver"] == drv and r["season"] >= latest_season - 1]
            if drv_races:
                dc = defaultdict(int)
                for r in drv_races:
                    dc[r["strategy_type"]] += 1
                driver_tendency[drv] = max(dc, key=dc.get)

        # ── 2026-specific data ─────────────────────────────────────────────
        races_2026 = [r for r in gp_races if r["season"] == 2026]
        result_2026 = None
        if races_2026:
            result_2026 = [{
                "driver": r["driver"],
                "grid": r["grid_position"],
                "finish": r["finish_position"],
                "strategy": r["strategy_type"],
                "points": r["points_scored"],
            } for r in races_2026]

        gp_model[gp] = {
            "total_laps": total_laps,
            "strategy_distribution": strat_dist,
            "most_common_strategy": most_common,
            "recent_most_common": recent_most_common,
            "pit_timing": {str(k): v for k, v in pit_timing.items()},
            "avg_position_gain_by_strategy": avg_gain,
            "driver_tendency": driver_tendency,
            "data_points": len(gp_races),
            "latest_season": latest_season,
            "result_2026": result_2026,
        }

    return gp_model


# ── 2026 calendar enrichment ─────────────────────────────────────────────────

def enrich_calendar(calendar, race_rows):
    """
    Mark each 2026 race as done/live/upcoming and attach results.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    enriched = []

    for race in calendar:
        status = "upcoming"
        results_2026 = None

        race_date = race["date"]
        if race_date < today:
            status = "done"
        elif race_date == today:
            status = "live"

        # Look for actual 2026 results in our data
        gp_results = [r for r in race_rows
                      if r["season"] == 2026 and r["grand_prix"] == race["name"]]
        if gp_results:
            status = "done"
            results_2026 = {r["driver"]: r["finish_position"] for r in gp_results}

        entry = dict(race)
        entry["status"] = status
        if results_2026:
            entry["results_2026"] = results_2026
        enriched.append(entry)

    return enriched


# ── Driver season stats ──────────────────────────────────────────────────────

def build_driver_stats(race_rows):
    """
    Build 2026 season stats per driver: wins, podiums, points, avg finish.
    """
    rows_2026 = [r for r in race_rows if r["season"] == 2026]
    drivers = set(r["driver"] for r in rows_2026)
    stats = {}

    for drv in drivers:
        drv_rows = [r for r in rows_2026 if r["driver"] == drv]
        finishes = []
        wins = pods = pts = 0
        for r in drv_rows:
            try:
                f = int(r["finish_position"])
                finishes.append(f)
                if f == 1: wins += 1
                if f <= 3: pods += 1
            except (TypeError, ValueError):
                pass
            try:
                pts += float(r["points_scored"] or 0)
            except (TypeError, ValueError):
                pass

        avg_finish = round(sum(finishes) / len(finishes), 1) if finishes else None
        stats[drv] = {
            "races": len(drv_rows),
            "wins": wins,
            "podiums": pods,
            "points": int(pts),
            "avg_finish": avg_finish,
        }

    return stats


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Mercedes F1 Strategy — Data Updater")
    print(f"Running at {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # 1. Download f1db
    try:
        z = download_f1db()
    except Exception as e:
        print(f"ERROR downloading f1db: {e}")
        sys.exit(1)

    # 2. Extract race data
    print("Extracting race data …")
    race_rows, stint_rows = extract_all_races(z)
    print(f"  Found {len(race_rows)} race entries, {len(stint_rows)} stint rows")

    # 3. Build GP model
    print("Building prediction model …")
    gp_model = build_gp_model(race_rows, stint_rows)
    print(f"  Built model for {len(gp_model)} circuits")

    # 4. Enrich 2026 calendar
    calendar = enrich_calendar(CALENDAR_2026, race_rows)

    # 5. Driver stats
    driver_stats = build_driver_stats(race_rows)

    # 6. Determine current season state
    today = datetime.now(timezone.utc).date().isoformat()
    completed = [r for r in calendar if r["status"] == "done"]
    upcoming = [r for r in calendar if r["status"] in ("upcoming", "live")]
    current_round = len(completed)
    next_race = upcoming[0] if upcoming else None

    # 7. Assemble output
    output = {
        "meta": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "generated_by": "update_data.py",
            "current_season": 2026,
            "current_round": current_round,
            "total_rounds": len(CALENDAR_2026),
            "next_race": next_race,
            "data_seasons": f"2018–{max(r['season'] for r in race_rows)}",
            "total_race_entries": len(race_rows),
        },
        "gp_model": gp_model,
        "calendar_2026": calendar,
        "driver_stats_2026": driver_stats,
    }

    # 8. Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"\nWrote {OUTPUT_PATH} ({size_kb:.1f} KB)")
    print("Done!")


if __name__ == "__main__":
    main()
