"""NFL depth charts from ESPN, saved at build time.

ESPN's depth-chart feed with player names doesn't allow pages on other sites to read
it, so update.py fetches all 32 teams and the page shows what it saved (refreshed with
each daily update).
"""
from __future__ import annotations

import sys
import time

from .sources import ESPN_TEAMS, _get

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/depthcharts"


def _kind(group: dict) -> str:
    keys = set((group.get("positions") or {}).keys())
    if "qb" in keys:
        return "Offense"
    if keys & {"pk", "p", "ls"}:
        return "Special teams"
    return "Defense"


def team(espn_id: int) -> list:
    """[{"kind", "name", "pos": [[POS, [[name, espn id, injury or None], ...]]]}] for one team."""
    data = _get(URL.format(id=espn_id)).json()
    out = []
    for g in data.get("depthchart") or []:
        rows = []
        for key, slot in (g.get("positions") or {}).items():
            abbr = ((slot.get("position") or {}).get("abbreviation") or key).upper()
            players = []
            for a in slot.get("athletes") or []:
                inj = ((a.get("injuries") or [{}])[0] or {}).get("status")
                players.append([a.get("displayName"), a.get("id"), inj])
            if players:
                rows.append([abbr, players])
        if rows:
            out.append({"kind": _kind(g), "name": g.get("name"), "pos": rows})
    order = {"Offense": 0, "Defense": 1, "Special teams": 2}
    return sorted(out, key=lambda g: order[g["kind"]])


def build() -> dict:
    """{team abbreviation: depth chart} for every NFL team; teams that fail are left out."""
    out, failed = {}, []
    for espn_id, abbr in ESPN_TEAMS.items():
        try:
            out[abbr] = team(espn_id)
        except Exception as exc:
            failed.append(f"{abbr} ({type(exc).__name__})")
        time.sleep(0.1)
    if failed:
        print(f"  FAIL depth    {', '.join(failed)}", file=sys.stderr)
    return out
