"""Source adapters.

Every adapter returns a list of dicts:

    {"name": str, "pos": "QB"|"RB"|"WR"|"TE", "team": str,
     "score": float}   # higher is better (projected points, trade value)
  or
     "rank": int}      # lower is better, already within the position

The aggregator turns both shapes into position ranks, so adding a source only
means writing one function and registering it in `source_registry`.

All of these use public but UNOFFICIAL endpoints/pages. They can change without
notice, so each source is wrapped in a try/except by update.py and a failure in
one never takes down the others.
"""
from __future__ import annotations

import functools
import json
import re
import subprocess
import time
from pathlib import Path

import requests

POSITIONS = ["QB", "RB", "WR", "TE"]
# Kickers and defenses are ranked for the week and rest of season only (no dynasty sources).
LINEUP_POSITIONS = POSITIONS + ["K", "DEF"]


def def_name(team_name: str) -> str:
    """One spelling for team defenses across sources: "Chicago Bears D/ST"."""
    base = re.sub(r"\s*(D/ST|DST|Defense)$", "", team_name.strip(), flags=re.I)
    return f"{base} D/ST"


def sleeper_name(info: dict) -> str:
    if info.get("position") == "DEF":
        return def_name(f"{info.get('first_name', '')} {info.get('last_name', '')}")
    return info.get("full_name") or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
USER_AGENT = "Mozilla/5.0 (compatible; fantasy-rankings-local/1.0)"
TIMEOUT = 30
LAST_WEEK = 18
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def _get(url: str, **kwargs) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/html,*/*"}
    headers.update(kwargs.pop("headers", {}))
    resp = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


def _get_text(url: str) -> str:
    # Some hosts (KeepTradeCut) require TLS 1.3, which the LibreSSL bundled
    # with Apple's Python can't negotiate; fall back to the system curl.
    try:
        return _get(url).text
    except requests.exceptions.SSLError:
        out = subprocess.run(
            ["curl", "-sSfL", "--max-time", str(TIMEOUT), "-A", USER_AGENT, url],
            capture_output=True, text=True, check=True,
        )
        return out.stdout


def _json_after(text: str, marker: str, opener: str) -> object:
    """Decode the JSON value that follows `marker` (e.g. `var ecrData =`)."""
    idx = text.find(marker)
    if idx == -1:
        raise ValueError(f"'{marker}' not found in page")
    start = text.find(opener, idx)
    if start == -1:
        raise ValueError(f"no JSON found after '{marker}'")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    return value


# --------------------------------------------------------------------------
# Sleeper: projected PPR points (week and rest of season)
# --------------------------------------------------------------------------

def sleeper_players() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "sleeper_players.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        return json.loads(cache.read_text())
    data = _get("https://api.sleeper.app/v1/players/nfl").json()
    cache.write_text(json.dumps(data))
    return data


@functools.lru_cache(maxsize=None)
def sleeper_projections(season: int, week: int) -> tuple:
    """Raw Sleeper projection entries for one week (cached: the week and ROS boards share them)."""
    params = [("season_type", "regular"), ("order_by", "pts_ppr")]
    params += [("position[]", p) for p in LINEUP_POSITIONS]
    entries = _get(f"https://api.sleeper.app/projections/nfl/{season}/{week}", params=params).json()
    time.sleep(0.3)
    return tuple(entries)


def sleeper_stats(season: int, week: int) -> list:
    """Raw Sleeper box-score entries for one completed week."""
    params = [("season_type", "regular")] + [("position[]", p) for p in LINEUP_POSITIONS]
    entries = _get(f"https://api.sleeper.com/stats/nfl/{season}/{week}", params=params).json()
    time.sleep(0.3)
    return entries


def _sleeper_points(season: int, weeks) -> list[dict]:
    meta = sleeper_players()
    totals: dict[str, dict] = {}
    for week in weeks:
        for e in sleeper_projections(season, week):
            pts = (e.get("stats") or {}).get("pts_ppr")
            if pts is None:
                continue
            pid = str(e.get("player_id"))
            info = meta.get(pid) or e.get("player") or {}
            pos = info.get("position")
            if pos not in LINEUP_POSITIONS:
                continue
            name = sleeper_name(info)
            if not name:
                continue
            row = totals.setdefault(
                pid,
                {"name": name, "pos": pos, "team": info.get("team") or e.get("team") or "", "score": 0.0},
            )
            row["score"] += float(pts)
    return [r for r in totals.values() if r["score"] > 0]


def sleeper_week(season: int, week: int) -> list[dict]:
    return _sleeper_points(season, [week])


def sleeper_ros(season: int, week: int) -> list[dict]:
    return _sleeper_points(season, range(week, LAST_WEEK + 1))


# --------------------------------------------------------------------------
# FantasyPros: expert consensus rankings (week, ROS, dynasty), PPR where it exists
# --------------------------------------------------------------------------

FP_BASE = "https://www.fantasypros.com/nfl/rankings"


def _fp_url(kind: str, pos: str) -> str:
    p = "dst" if pos == "DEF" else pos.lower()
    scoring = "" if pos in ("QB", "K", "DEF") else "ppr-"  # PPR doesn't change these
    if kind == "week":
        return f"{FP_BASE}/{scoring}{p}.php"
    if kind == "ros":
        return f"{FP_BASE}/ros-{scoring}{p}.php"
    if kind == "dynasty":
        return f"{FP_BASE}/dynasty-{p}.php"
    raise ValueError(kind)


def fantasypros(kind: str) -> list[dict]:
    rows: list[dict] = []
    for pos in POSITIONS if kind == "dynasty" else LINEUP_POSITIONS:
        html = _get(_fp_url(kind, pos)).text
        data = _json_after(html, "var ecrData", "{")
        players = data.get("players", []) if isinstance(data, dict) else []
        players = [p for p in players if p.get("player_name")]
        players.sort(key=lambda p: float(p.get("rank_ecr") or 9999))
        for i, p in enumerate(players, 1):
            name = def_name(p["player_name"]) if pos == "DEF" else p["player_name"]
            rows.append({"name": name, "pos": pos, "team": p.get("player_team_id") or "", "rank": i})
        time.sleep(1.0)  # be polite
    return rows


# --------------------------------------------------------------------------
# FantasyCalc: trade values (dynasty) and redraft values (used for ROS)
# --------------------------------------------------------------------------

def fantasycalc(dynasty: bool) -> list[dict]:
    data = _get(
        "https://api.fantasycalc.com/values/current",
        params={"isDynasty": str(dynasty).lower(), "numQbs": 1, "numTeams": 12, "ppr": 1},
    ).json()
    rows = []
    for e in data:
        p = e.get("player") or {}
        if p.get("position") not in POSITIONS or not p.get("name"):
            continue
        rows.append(
            {
                "name": p["name"],
                "pos": p["position"],
                "team": p.get("maybeTeam") or "",
                "score": float(e.get("value") or 0),
            }
        )
    return rows


# --------------------------------------------------------------------------
# KeepTradeCut: dynasty values (1QB)
# --------------------------------------------------------------------------

def keeptradecut() -> list[dict]:
    html = _get_text("https://keeptradecut.com/dynasty-rankings")
    # Player data now lives in <script type="application/json" id="ktc-players">;
    # older pages assigned it inline to `var playersArray`.
    m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', html, re.S)
    players = json.loads(m.group(1)) if m else _json_after(html, "var playersArray", "[")
    rows = []
    for p in players:
        pos = p.get("position")
        value = (p.get("oneQBValues") or {}).get("value")
        if pos not in POSITIONS or value is None or not p.get("playerName"):
            continue
        rows.append(
            {"name": p["playerName"], "pos": pos, "team": p.get("team") or "", "score": float(value)}
        )
    return rows


# --------------------------------------------------------------------------
# ESPN: share of ESPN leagues each player is rostered / started in
# --------------------------------------------------------------------------

ESPN_TEAMS = {1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN",
              11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
              21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR",
              30: "JAX", 33: "BAL", 34: "HOU"}
ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}


def espn_ownership(season: int) -> list[dict]:
    # players_wl is the light view (about 0.3 MB); kona_player_info carries the same numbers in 20+ MB.
    flt = {"players": {"limit": 1500, "sortPercOwned": {"sortAsc": False, "sortPriority": 1},
                       "filterSlotIds": {"value": [0, 2, 4, 6, 16, 17]}}}
    data = _get(
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3",
        params={"view": "players_wl"},
        headers={"x-fantasy-filter": json.dumps(flt)},
    ).json()
    rows = []
    for p in data.get("players", []) if isinstance(data, dict) else data:
        pl = p.get("player", p)
        own = pl.get("ownership") or {}
        pos = ESPN_POSITIONS.get(pl.get("defaultPositionId"))
        if not pos or not pl.get("fullName") or own.get("percentOwned") is None:
            continue
        rows.append({
            "name": pl["fullName"], "pos": pos, "team": ESPN_TEAMS.get(pl.get("proTeamId"), ""),
            "espn_id": pl.get("id"), "owned": round(own["percentOwned"], 1),
            # players_wl only carries percentOwned; percentStarted needs the 20+ MB view.
            "started": round(own["percentStarted"], 1) if own.get("percentStarted") is not None else None,
        })
    return rows


ESPN_INJURY_STATUS = {"Questionable": "Questionable", "Doubtful": "Doubtful", "Out": "Out",
                      "Injured Reserve": "IR", "Suspension": "Sus", "Physically Unable to Perform": "PUP"}
ESPN_INJURY_POS = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "PK": "K", "K": "K"}


def espn_injuries() -> list[dict]:
    """League-wide injury report: status, ESPN's expected return date and the latest practice note."""
    data = _get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries").json()
    rows = []
    for team in data.get("injuries", []):
        abbr = ESPN_TEAMS.get(int(team.get("id") or 0), "")
        for inj in team.get("injuries", []):
            status = ESPN_INJURY_STATUS.get(inj.get("status"))
            a = inj.get("athlete") or {}
            pos = ESPN_INJURY_POS.get((a.get("position") or {}).get("abbreviation"))
            if not status or not pos or not a.get("displayName"):
                continue  # "Active" means cleared; defenders and linemen aren't on the site
            link = next((l.get("href", "") for l in a.get("links", [])), "")
            m = re.search(r"/id/(\d+)", link)
            details = inj.get("details") or {}
            rows.append({
                "name": a["displayName"], "pos": pos, "team": abbr, "espn_id": m.group(1) if m else None,
                "status": status, "return": details.get("returnDate"), "type": details.get("type"),
                "note": inj.get("shortComment") or "", "detail": inj.get("longComment") or "",
                "updated": (inj.get("date") or "")[:10],
            })
    return rows


# --------------------------------------------------------------------------
# Registry: which sources feed which ranking
# --------------------------------------------------------------------------

def source_registry(season: int, week: int) -> dict:
    return {
        "week": {
            "Sleeper": lambda: sleeper_week(season, week),
            "FantasyPros": lambda: fantasypros("week"),
        },
        "ros": {
            "Sleeper": lambda: sleeper_ros(season, week),
            "FantasyPros": lambda: fantasypros("ros"),
            "FantasyCalc": lambda: fantasycalc(False),
        },
        "dynasty": {
            "FantasyCalc": lambda: fantasycalc(True),
            "KeepTradeCut": keeptradecut,
            "FantasyPros": lambda: fantasypros("dynasty"),
        },
    }
