"""Past-season game logs for the player popup's season tabs.

Sleeper has weekly box scores back to 2009. A finished season never changes, so
each one is fetched once (about 17 requests) and cached in data/cache/history/.
The first run downloads every season the current players have been in the
league and takes a few minutes; later runs only read the cache.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .players import LOG_FIELDS, game_row
from .sources import CACHE_DIR, LINEUP_POSITIONS, sleeper_stats

FIRST_SEASON = 2009  # earliest season Sleeper has box scores for
HISTORY_DIR = CACHE_DIR / "history"


def weeks_in(season: int) -> int:
    return 18 if season >= 2021 else 17


def load_season(season: int, fetch=sleeper_stats) -> dict:
    """{"logs": {sid: [row...]}, "ranks": {sid: "WR5"}} for one finished season, from cache if possible."""
    path = HISTORY_DIR / f"{season}.json"
    if path.exists():
        return json.loads(path.read_text())
    logs: dict[str, list] = {}
    pos_of: dict[str, str] = {}
    for w in range(1, weeks_in(season) + 1):
        for e in fetch(season, w):
            st = e.get("stats") or {}
            if not st.get("gp") and not st.get("pts_ppr"):
                continue
            pos = (e.get("player") or {}).get("position")
            if pos not in LINEUP_POSITIONS:
                continue
            sid = str(e.get("player_id"))
            pos_of[sid] = pos
            logs.setdefault(sid, []).append(game_row(w, e.get("opponent"), st))
    # Season finish: rank by total PPR points within the position.
    ranks: dict[str, str] = {}
    for pos in LINEUP_POSITIONS:
        ids = sorted((s for s in logs if pos_of[s] == pos), key=lambda s: -sum(g[2] for g in logs[s]))
        for i, s in enumerate(ids, 1):
            ranks[s] = f"{pos}{i}"
    data = {"logs": logs, "ranks": ranks}
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")))  # only reached if every week fetched
    return data


def build(season: int, player_data: dict, meta: dict) -> dict:
    """{"fields", "seasons": {sid: {season: {"log": [...], "rank": "WR5"}}}} for the players on the site."""
    players = player_data.get("players", {})
    first = season
    for sid in players:
        exp = (meta.get(sid) or {}).get("years_exp")
        if isinstance(exp, int):
            first = min(first, season - exp)
    first = max(FIRST_SEASON, first)

    out: dict[str, dict] = {}
    failed = []
    for s in range(first, season):
        cached = (HISTORY_DIR / f"{s}.json").exists()
        try:
            data = load_season(s)
        except Exception as exc:  # a missing season just means one fewer tab
            failed.append(f"{s} ({type(exc).__name__})")
            continue
        if not cached:
            print(f"  ok   history  {s} season downloaded")
        for sid in players:
            log = data["logs"].get(sid)
            if log:
                out.setdefault(sid, {})[str(s)] = {"log": log, "rank": data["ranks"].get(sid)}
    for msg in failed:
        print(f"  FAIL history  {msg}", file=sys.stderr)
    return {"fields": LOG_FIELDS, "seasons": out, "failed": failed}
