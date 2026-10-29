"""This week's games and betting lines from ESPN's public scoreboard, saved at build time.

The page refreshes scores live from the same scoreboard, but ESPN drops the betting
lines once a game starts, so the pre-game lines are kept here and shown all week.
"""
from __future__ import annotations

from .sources import _get

BASE = "https://site.api.espn.com/apis/site/v2/sports/{sport}/scoreboard"
SPORTS = {"football": "football/nfl", "basketball": "basketball/nba"}


def _odds(comp: dict) -> dict | None:
    o = (comp.get("odds") or [None])[0]
    if not o:
        return None
    ml = o.get("moneyline") or {}

    def price(side):
        s = ml.get(side) or {}
        return ((s.get("close") or {}).get("odds")) or ((s.get("open") or {}).get("odds"))

    return {"details": o.get("details"), "ou": o.get("overUnder"), "mlHome": price("home"), "mlAway": price("away"),
            "provider": (o.get("provider") or {}).get("name")}


def build(sport: str, season: int, week: int | None = None, dates: tuple[str, str] | None = None) -> dict:
    """{"odds": {event id: lines}} for football week `week`, or basketball dates (first, last) as YYYY-MM-DD."""
    if sport == "football":
        events = _get(BASE.format(sport=SPORTS[sport]), params={"seasontype": 2, "week": week, "dates": season}).json().get("events", [])
    else:
        # The basketball scoreboard takes one day at a time.
        from datetime import date, timedelta
        day, last, events = date.fromisoformat(dates[0]), date.fromisoformat(dates[1]), []
        while day <= last:
            events += _get(BASE.format(sport=SPORTS[sport]), params={"dates": day.strftime("%Y%m%d")}).json().get("events", [])
            day += timedelta(days=1)
    odds = {}
    for e in events:
        lines = _odds((e.get("competitions") or [{}])[0])
        if lines:
            odds[str(e["id"])] = lines
    return {"odds": odds, "events": len(events)}
