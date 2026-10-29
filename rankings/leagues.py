"""Private ESPN leagues, fetched at update time.

A browser page can't send ESPN's login cookies (espn_s2 / SWID) to espn.com, so
private leagues are listed in leagues.json and fetched here instead. Public ESPN
leagues and all Sleeper leagues are connected from the page itself.

The cookies stay in leagues.json; only the league data is written into the page.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

from .sources import TIMEOUT, USER_AGENT

ESPN_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/{game}/seasons/{season}/segments/0/leagues/{league_id}"
# ESPN's game codes; leagues.json entries say which sport with "sport" (football if left out).
ESPN_GAMES = {"football": "ffl", "basketball": "fba"}
# Same views the page requests for public leagues.
ESPN_VIEWS = ["mSettings", "mTeam", "mRoster", "mMatchupScore"]


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def fetch_espn(league_id: str, season: int, espn_s2: str = "", swid: str = "", game: str = "ffl") -> dict:
    cookies = {}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    if swid:
        cookies["SWID"] = swid
    resp = requests.get(
        ESPN_URL.format(game=game, season=season, league_id=league_id),
        params=[("view", v) for v in ESPN_VIEWS],
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        cookies=cookies,
        timeout=TIMEOUT,
    )
    if resp.status_code in (401, 403):
        raise PermissionError("ESPN refused access: check espn_s2 and swid in leagues.json")
    resp.raise_for_status()
    return trim_espn(resp.json())


def trim_espn(raw: dict) -> dict:
    """Keep only the fields the page reads, in ESPN's own shape (the page parses both the same way)."""
    settings = raw.get("settings") or {}
    sched = settings.get("scheduleSettings") or {}
    teams = []
    for t in raw.get("teams") or []:
        entries = []
        for e in (t.get("roster") or {}).get("entries") or []:
            pl = ((e.get("playerPoolEntry") or {}).get("player")) or {}
            entries.append(
                {
                    "playerId": e.get("playerId"),
                    "lineupSlotId": e.get("lineupSlotId"),
                    "playerPoolEntry": {
                        "player": {
                            k: pl.get(k)
                            for k in ("fullName", "defaultPositionId", "proTeamId", "injuryStatus", "eligibleSlots")
                        }
                    },
                }
            )
        teams.append(
            {
                **{k: t.get(k) for k in ("id", "name", "location", "nickname", "abbrev", "owners", "primaryOwner")},
                "roster": {"entries": entries},
            }
        )
    return {
        "id": raw.get("id"),
        "seasonId": raw.get("seasonId"),
        "scoringPeriodId": raw.get("scoringPeriodId"),
        "settings": {
            "name": settings.get("name"),
            "rosterSettings": {"lineupSlotCounts": (settings.get("rosterSettings") or {}).get("lineupSlotCounts")},
            "scoringSettings": {"scoringItems": [
                {"statId": i.get("statId"), "points": i.get("points")}
                for i in (settings.get("scoringSettings") or {}).get("scoringItems") or []
            ]},
            "scheduleSettings": {
                k: sched.get(k) for k in ("matchupPeriodCount", "playoffTeamCount", "matchupPeriods")
            },
        },
        "members": [{"id": m.get("id"), "displayName": m.get("displayName")} for m in raw.get("members") or []],
        "teams": teams,
        "schedule": [
            {
                "matchupPeriodId": m.get("matchupPeriodId"),
                "winner": m.get("winner"),
                "home": {k: (m.get("home") or {}).get(k) for k in ("teamId", "totalPoints")},
                "away": {k: (m.get("away") or {}).get(k) for k in ("teamId", "totalPoints")},
            }
            for m in raw.get("schedule") or []
        ],
    }


def fetch_configured(config: dict, season: int, sport: str = "football", espn_season: int | None = None) -> list[dict]:
    """[{league_id, my_team, data | error}] for every ESPN league of one sport in the config."""
    out = []
    for entry in config.get("espn") or []:
        if (entry.get("sport") or "football") != sport:
            continue
        league_id = str(entry.get("league_id") or "").strip()
        if not league_id:
            continue
        swid = entry.get("swid") or ""
        item = {"league_id": league_id, "my_team": None}
        try:
            item["data"] = fetch_espn(league_id, int(entry.get("season") or espn_season or season),
                                      entry.get("espn_s2") or "", swid, ESPN_GAMES[sport])
            item["my_team"] = next(
                (t["id"] for t in item["data"]["teams"] if swid and swid in (t.get("owners") or [])), None
            )
            print(f"  ok   league   ESPN {league_id}  {len(item['data']['teams'])} teams")
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  FAIL league   ESPN {league_id}  {item['error']}", file=sys.stderr)
        out.append(item)
    return out
