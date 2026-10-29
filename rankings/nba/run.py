"""Build the basketball page: python3 update.py --sport basketball (update.py builds both by default)."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime

from .. import leagues, site, slate
from . import build as nb
from . import demo

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "data" / "nba.json"
SITE_FILE = ROOT / "site" / "basketball.html"
DEMO_DATA_FILE = ROOT / "data" / "demo-nba.json"
DEMO_SITE_FILE = ROOT / "site" / "demo-basketball.html"


def default_season(today: date) -> int:
    """NBA seasons start in October; the 2026-27 season is "2026" until the next one starts."""
    return today.year if today.month >= 8 else today.year - 1


def run(args, today: date) -> int:
    import update  # the shared helpers live next to the football pipeline

    season = args.season or default_season(today)
    if args.demo:
        pd = demo.players(today)
        registry = demo.boards(pd, today)
    else:
        try:
            pd = nb.build(season, today)
        except Exception as exc:
            print(f"  FAIL nba      players {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        registry = nb.board_sources(pd, today)
    week = pd["week"]
    print(f"Basketball: {nb.season_label(season)} season, week {week}{' (demo data)' if args.demo else ''}")
    print(f"  ok   nba      Sleeper       {len(pd['players'])} players")

    fetched = update.fetch_all(registry)
    data_file = DEMO_DATA_FILE if args.demo else DATA_FILE
    site_file = DEMO_SITE_FILE if args.demo else SITE_FILE
    previous = {} if args.demo else update.load_previous(DATA_FILE)
    types = update.build_boards(fetched, lambda kind: nb.describe(kind, week), previous.get("types", {}),
                                limits=nb.LIMITS, positions=nb.BOARD_POSITIONS)
    nb.attach_ids(types, pd)

    espn_periods = {}
    if args.demo:
        seasons = demo.history(pd, season)
        league_data = {"espn": [], "demo": demo.league(pd, today)}
    else:
        for label, fn in (("ESPN own %", lambda: nb.attach_ownership(pd, nb.espn_ownership(season))),
                          ("ESPN injuries", lambda: nb.attach_injuries(pd, nb.espn_injuries(), today))):
            try:
                print(f"  ok   nba      {label:13s} {fn()} players")
            except Exception as exc:
                print(f"  FAIL nba      {label} {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            espn_periods = nb.espn_periods(season)
        except Exception as exc:  # only ESPN leagues need it, to turn scoring days into dates
            print(f"  FAIL nba      ESPN schedule {type(exc).__name__}: {exc}", file=sys.stderr)
        seasons = nb.history(season, pd, nb.sleeper_players())
        print(f"  ok   nba      history       {len(seasons)} past seasons")
        league_data = {"espn": leagues.fetch_configured(update.load_leagues_config(), season, "basketball",
                                                        nb.espn_season(season))}

    slate_data = {}
    if not args.demo:
        try:
            span = pd["calendar"]["weeks"].get(str(week))
            slate_data = slate.build("basketball", season, dates=tuple(span))
            print(f"  ok   slate    ESPN          {slate_data['events']} games, {len(slate_data['odds'])} with lines")
        except Exception as exc:
            print(f"  FAIL slate    ESPN {type(exc).__name__}: {exc}", file=sys.stderr)
    pd.pop("remaining", None)  # only needed for the boards; too big for the page
    data = {
        "sport": "basketball",
        "slate": slate_data,
        "links": update.DEMO_LINKS if args.demo else update.LINKS,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "season": season,
        "season_label": nb.season_label(season),
        "espn_season": nb.espn_season(season),
        "week": week,
        "today": today.isoformat(),
        "demo": args.demo,
        "scoring": nb.DEFAULT_SCORING,
        "espn_periods": espn_periods,
        "types": types,
        "players": pd,
        "leagues": league_data,
    }
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(data, separators=(",", ":")))
    files = site.render_seasons(site_file, seasons)
    data["history_files"] = files
    site.render(data, site_file)
    print(f"Wrote {site_file.relative_to(ROOT)} and {len(files)} past-season files")
    return 1 if any(not t.get("rankings") for t in types.values()) else 0
