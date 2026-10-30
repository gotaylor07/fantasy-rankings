#!/usr/bin/env python3
"""Fetch every source, average the rankings, write data/rankings.json and site/index.html.

    python3 update.py            # live data
    python3 update.py --demo     # fake players, no network needed
    python3 update.py --week 9   # override the detected upcoming week
    python3 update.py --espn-login   # sign in to ESPN in a browser window, add private leagues, then update

Private ESPN leagues listed in leagues.json are fetched too (see README).
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Apple's bundled Python links LibreSSL; urllib3 warns about it on every run but works.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from rankings import demo, history, leagues, players, site, slate
from rankings.aggregate import aggregate, upcoming_week
from rankings.sources import espn_injuries, espn_ownership, sleeper_players, source_registry

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "rankings.json"
SITE_FILE = ROOT / "site" / "index.html"
# Demo runs write to their own files so they never overwrite real data.
DEMO_DATA_FILE = ROOT / "data" / "demo.json"
DEMO_SITE_FILE = ROOT / "site" / "demo.html"
LEAGUES_FILE = ROOT / "leagues.json"
# The two pages link to each other with the sport switch at the top.
LINKS = {"football": "index.html", "basketball": "basketball.html"}
DEMO_LINKS = {"football": "demo.html", "basketball": "demo-basketball.html"}


def default_season(today: date) -> int:
    return today.year if today.month >= 3 else today.year - 1


def describe(kind: str, week: int) -> dict:
    return {
        "week": {"tab": f"Week {week}", "description": f"Projected full PPR value for Week {week}."},
        "ros": {"tab": "Rest of season", "description": f"Full PPR value from Week {week} through Week 18."},
        "dynasty": {"tab": "Dynasty", "description": "Long-term dynasty value (1QB, full PPR)."},
    }[kind]


def fetch_all(registry: dict) -> dict:
    """{kind: {source: rows}} plus per-source errors."""
    results: dict = {}
    for kind, sources in registry.items():
        rows_by_source: dict = {}
        failed: dict = {}
        for name, fn in sources.items():
            try:
                rows = fn()
                if not rows:
                    raise ValueError("returned no players")
                rows_by_source[name] = rows
                print(f"  ok   {kind:8s} {name:13s} {len(rows)} players")
            except Exception as exc:  # one bad source must not stop the run
                failed[name] = f"{type(exc).__name__}: {exc}"
                print(f"  FAIL {kind:8s} {name:13s} {failed[name]}", file=sys.stderr)
        results[kind] = {"rows": rows_by_source, "failed": failed}
    return results


def build_boards(fetched: dict, describe_fn, previous: dict, **aggregate_args) -> dict:
    """Average each board's sources; keep the previous board if every source for it failed."""
    types: dict = {}
    for kind, result in fetched.items():
        rankings = aggregate(result["rows"], **aggregate_args)
        entry = describe_fn(kind)
        if rankings:
            entry.update(rankings=rankings, sources=sorted(result["rows"]), failed=result["failed"], stale=False)
        elif previous.get(kind, {}).get("rankings"):
            # Every source failed: keep last week's board rather than publishing an empty one.
            entry = dict(previous[kind], failed=result["failed"], stale=True)
        else:
            entry.update(rankings={}, sources=[], failed=result["failed"], stale=False)
        types[kind] = entry
    return types


def load_previous(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def load_leagues_config() -> dict:
    try:
        return leagues.load_config(LEAGUES_FILE)
    except (OSError, ValueError) as exc:
        print(f"  FAIL league   leagues.json unreadable: {exc}", file=sys.stderr)
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="use synthetic data (no network)")
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int, help="upcoming week (default: detected from the date)")
    ap.add_argument("--espn-login", action="store_true",
                    help="sign in to ESPN in a browser window to add private leagues (then updates as usual)")
    ap.add_argument("--sport", choices=["all", "football", "basketball"], default="all",
                    help="which page to build (default: both)")
    args = ap.parse_args()

    if args.espn_login:
        from rankings import espn_login
        espn_login.run(LEAGUES_FILE)

    # GitHub's servers run on UTC, which is already "tomorrow" on US evenings; use Eastern time.
    today = datetime.now(ZoneInfo("America/New_York")).date()
    status = 0
    if args.sport in ("all", "football"):
        status |= run_football(args, today)
    if args.sport in ("all", "basketball"):
        from rankings.nba import run as nba_run
        status |= nba_run.run(args, today)
    return status


def run_football(args, today: date) -> int:
    season = args.season or default_season(today)
    week = args.week or upcoming_week(today, season)
    print(f"Football: season {season}, upcoming week {week}{' (demo data)' if args.demo else ''}")

    if args.demo:
        fetched = {k: {"rows": v, "failed": {}} for k, v in demo.generate().items()}
    else:
        fetched = fetch_all(source_registry(season, week))

    data_file = DEMO_DATA_FILE if args.demo else DATA_FILE
    site_file = DEMO_SITE_FILE if args.demo else SITE_FILE
    previous_data = {} if args.demo else load_previous(DATA_FILE)
    types = build_boards(fetched, lambda kind: describe(kind, week), previous_data.get("types", {}))

    if args.demo:
        player_data = demo.players(week)
        league_data = {"espn": [], "demo": demo.league(player_data, week)}
    else:
        try:
            player_data = players.build(season, week)
            print(f"  ok   players  Sleeper       {len(player_data['players'])} players")
        except Exception as exc:
            print(f"  FAIL players  {type(exc).__name__}: {exc}", file=sys.stderr)
            player_data = previous_data.get("players") or {}
            player_data["failed"] = [f"{type(exc).__name__}: {exc}"]
        league_data = {"espn": leagues.fetch_configured(load_leagues_config(), season)}
    meta = None
    if not args.demo:
        try:
            meta = sleeper_players()
        except Exception:
            meta = None  # only used to link players who haven't played; not worth failing over
    players.attach_ids(types, player_data, meta)

    if args.demo:
        player_history = demo.history(player_data, season)
    else:
        try:
            matched = players.attach_ownership(player_data, espn_ownership(season))
            print(f"  ok   players  ESPN own %    {matched} players")
        except Exception as exc:  # the popup just leaves ownership out
            print(f"  FAIL players  ESPN ownership {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            matched = players.attach_injuries(player_data, espn_injuries(), week)
            print(f"  ok   players  ESPN injuries {matched} players")
        except Exception as exc:  # falls back to Sleeper's injury status, without details
            print(f"  FAIL players  ESPN injuries {type(exc).__name__}: {exc}", file=sys.stderr)
        player_history = history.build(season, player_data, meta or {})
        print(f"  ok   history  {len(player_history['seasons'])} players with past seasons")

    slate_data = {}
    if not args.demo:
        try:
            slate_data = slate.build("football", season, week)
            print(f"  ok   slate    ESPN          {slate_data['events']} games, {len(slate_data['odds'])} with lines")
        except Exception as exc:  # the page still loads scores live
            print(f"  FAIL slate    ESPN {type(exc).__name__}: {exc}", file=sys.stderr)

    data = {
        "sport": "football",
        "slate": slate_data,
        "links": DEMO_LINKS if args.demo else LINKS,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "season": season,
        "week": week,
        "demo": args.demo,
        "types": types,
        "players": player_data,
        "leagues": league_data,
    }
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(data, indent=1))
    history_file = site.render(data, site_file, player_history)
    print(f"Wrote {site_file.relative_to(ROOT)} and {history_file.relative_to(ROOT)}")

    empty = [k for k, t in types.items() if not t.get("rankings")]
    return 1 if empty else 0


if __name__ == "__main__":
    sys.exit(main())
