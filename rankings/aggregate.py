"""Turn per-source rows into one averaged ranking per position."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from statistics import mean

from .sources import LINEUP_POSITIONS

# How many players to publish per position.
LIMITS = {"QB": 36, "RB": 72, "WR": 96, "TE": 36, "K": 32, "DEF": 32}

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Add entries as you spot players that sources spell differently: {"as spelled": "canonical"}.
ALIASES = {
    "hollywood brown": "marquise brown",
    "gabe davis": "gabriel davis",
    "josh palmer": "joshua palmer",
}


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[.'`’-]", "", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    parts = [p for p in n.split() if p not in SUFFIXES]
    n = " ".join(parts)
    return ALIASES.get(n, n)


def position_ranks(rows: list[dict]) -> dict:
    """{(norm_name, pos): (rank_within_position, display_name, team)}"""
    by_pos: dict[str, list[dict]] = {}
    for r in rows:
        by_pos.setdefault(r["pos"], []).append(r)
    out: dict = {}
    for pos, items in by_pos.items():
        if all(i.get("rank") is not None for i in items):
            items = sorted(items, key=lambda i: i["rank"])
        else:
            items = sorted(items, key=lambda i: -float(i.get("score") or 0))
        rank = 0
        for it in items:
            key = (norm_name(it["name"]), pos)
            if key in out:
                continue
            rank += 1
            out[key] = (rank, it["name"], it.get("team") or "")
    return out


def aggregate(source_rows: dict[str, list[dict]], limits: dict = LIMITS, positions: list = LINEUP_POSITIONS) -> dict:
    """Average each player's position rank across the sources that list them.

    A player must appear in at least two sources (or one, if only one source
    returned data) so a single outlier source can't put an unknown player on
    the board.
    """
    per_source = {s: position_ranks(rows) for s, rows in source_rows.items() if rows}
    if not per_source:
        return {}
    min_sources = min(2, len(per_source))

    merged: dict = {}
    for source, ranks in per_source.items():
        for key, (rank, display, team) in ranks.items():
            m = merged.setdefault(key, {"name": display, "team": team, "ranks": {}})
            m["ranks"][source] = rank
            if not m["team"] and team:
                m["team"] = team

    result: dict[str, list[dict]] = {p: [] for p in positions}
    for (_, pos), m in merged.items():
        if pos not in result or len(m["ranks"]) < min_sources:
            continue
        vals = list(m["ranks"].values())
        result[pos].append(
            {
                "name": m["name"],
                "team": m["team"],
                "avg": round(mean(vals), 2),
                "best": min(vals),
                "worst": max(vals),
                "n": len(vals),
                "ranks": m["ranks"],
            }
        )
    for pos, rows in result.items():
        rows.sort(key=lambda r: (r["avg"], r["best"], r["name"]))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        result[pos] = rows[: limits.get(pos, 50)]
    return result


# --------------------------------------------------------------------------
# Season calendar
# --------------------------------------------------------------------------

def kickoff(season: int) -> date:
    """NFL opener: the Thursday after Labor Day (first Monday of September)."""
    d = date(season, 9, 1)
    labor_day = d + timedelta(days=(0 - d.weekday()) % 7)
    return labor_day + timedelta(days=3)


def upcoming_week(today: date, season: int) -> int:
    """The current NFL week. Weeks run Tuesday to Monday, so the site moves on to the
    next week on Tuesday morning, after Monday night's game (Tuesday after Week 7 -> 8,
    and it stays 8 through Monday night of Week 8)."""
    week_one_tuesday = kickoff(season) - timedelta(days=2)
    if today < week_one_tuesday:
        return 1
    return max(1, min(18, (today - week_one_tuesday).days // 7 + 1))
