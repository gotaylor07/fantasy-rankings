"""Fantasy basketball data: players, game logs, projections, schedule, ranking boards, past seasons.

Same shapes as the football side where it can be, so the page code is shared. The
differences that matter:

- Scoring is fantasy *points*, computed from stat lines. The boards use ESPN's
  standard points scoring; league tabs re-score every stat line with that
  league's own settings in the page.
- Lineups are set daily, so a week's value depends on how many games a team plays.
  Every remaining game has its own Sleeper projection.
- Seasons are named by the year they start (Sleeper's convention): 2026 = 2026-27.
  ESPN names them by the year they end.
"""
from __future__ import annotations

import functools
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

from ..aggregate import norm_name
from ..sources import CACHE_DIR, _get, _json_after

POSITIONS = ["PG", "SG", "SF", "PF", "C"]
BOARD_POSITIONS = ["ALL"] + POSITIONS
LIMITS = {"ALL": 200, "PG": 60, "SG": 60, "SF": 60, "PF": 60, "C": 50}
FIRST_HISTORY_SEASON = 2017  # earliest season Sleeper has NBA box scores for

# Stat line kept for every game and projection, in this order.
FIELDS = ["min", "pts", "reb", "ast", "stl", "blk", "to", "tpm", "tpa", "fgm", "fga", "ftm", "fta", "oreb", "dd", "td"]

# ESPN's standard points scoring: what the ranking boards use.
DEFAULT_SCORING = {"pts": 1, "tpm": 1, "fgm": 2, "fga": -1, "ftm": 1, "fta": -1,
                   "reb": 1, "ast": 2, "stl": 4, "blk": 4, "to": -2}

ESPN_TEAMS = {1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GSW", 10: "HOU",
              11: "IND", 12: "LAC", 13: "LAL", 14: "MIA", 15: "MIL", 16: "MIN", 17: "BKN", 18: "NYK", 19: "ORL",
              20: "PHI", 21: "PHX", 22: "POR", 23: "SAC", 24: "SAS", 25: "OKC", 26: "UTA", 27: "WAS", 28: "TOR",
              29: "MEM", 30: "CHA"}
ESPN_INJURY_STATUS = {"Out": "Out", "Day-To-Day": "DTD", "Questionable": "Questionable", "Doubtful": "Doubtful",
                      "Probable": "Probable", "Suspension": "Sus"}
HISTORY_DIR = CACHE_DIR / "nba_history"


def espn_season(season: int) -> int:
    return season + 1


def season_label(season: int) -> str:
    return f"{season}-{str(season + 1)[-2:]}"


def player_key(name: str) -> str:
    return norm_name(name)


def _num(v):
    if v is None:
        return 0
    f = round(float(v), 2)
    return int(f) if f == int(f) else f


def line_of(st: dict, projected: bool = False) -> list:
    """Stat line in FIELDS order. Minutes come as seconds ("sp") in projections."""
    line = dict(st)
    if "min" not in line and line.get("sp"):
        line["min"] = line["sp"] / 60
    if not projected:  # actual games: count double- and triple-doubles ourselves
        tens = sum(1 for k in ("pts", "reb", "ast", "stl", "blk") if (line.get(k) or 0) >= 10)
        line["dd"], line["td"] = int(tens >= 2), int(tens >= 3)
    if "tpm" not in line and line.get("tpa") is not None and line.get("tpmi") is not None:
        line["tpm"] = line["tpa"] - line["tpmi"]
    return [round(_num(line.get(f)), 1) if projected else _num(line.get(f)) for f in FIELDS]


def fantasy_points(line: list, scoring: dict = DEFAULT_SCORING) -> float:
    d = dict(zip(FIELDS, line))
    d["fgmi"], d["ftmi"] = d["fga"] - d["fgm"], d["fta"] - d["ftm"]
    return round(sum(scoring.get(k, 0) * v for k, v in d.items()), 2)


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------

def sleeper_players() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / "sleeper_players_nba.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        return json.loads(cache.read_text())
    data = _get("https://api.sleeper.app/v1/players/nba").json()
    cache.write_text(json.dumps(data))
    return data


@functools.lru_cache(maxsize=None)
def schedule(season: int) -> tuple:
    return tuple(_get(f"https://api.sleeper.com/schedule/nba/regular/{season}").json())


@functools.lru_cache(maxsize=None)
def projections(season: int, week: int) -> tuple:
    """One entry per player per game that week."""
    rows = _get(f"https://api.sleeper.com/projections/nba/{season}/{week}", params={"season_type": "regular"}).json()
    time.sleep(0.2)
    return tuple(rows)


@functools.lru_cache(maxsize=None)
def season_projections(season: int) -> tuple:
    return tuple(_get(f"https://api.sleeper.com/projections/nba/{season}", params={"season_type": "regular"}).json())


def stats(season: int, week: int) -> list:
    """One entry per player per game that week."""
    rows = _get(f"https://api.sleeper.com/stats/nba/{season}/{week}", params={"season_type": "regular"}).json()
    time.sleep(0.2)
    return rows


def fantasypros(kind: str) -> list[dict]:
    page = {"ros": "ros-overall", "dynasty": "dynasty-overall"}[kind]
    data = _json_after(_get(f"https://www.fantasypros.com/nba/rankings/{page}.php").text, "var ecrData", "{")
    players = [p for p in data.get("players", []) if p.get("player_name")]
    players.sort(key=lambda p: float(p.get("rank_ecr") or 9999))
    return [{"name": p["player_name"], "team": p.get("player_team_id") or "",
             "el": [x for x in (p.get("player_positions") or "").split(",") if x in POSITIONS], "rank": i}
            for i, p in enumerate(players, 1)]


ESPN_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}"


def espn_ownership(season: int) -> list[dict]:
    flt = {"players": {"limit": 1200, "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}
    data = _get(ESPN_BASE.format(season=espn_season(season)) + "/segments/0/leaguedefaults/1",
                params={"view": "players_wl"}, headers={"x-fantasy-filter": json.dumps(flt)}).json()
    rows = []
    for p in data.get("players", []):
        pl = p.get("player", p)
        own = (pl.get("ownership") or {}).get("percentOwned")
        if pl.get("fullName") and own is not None:
            rows.append({"name": pl["fullName"], "team": ESPN_TEAMS.get(pl.get("proTeamId"), ""), "owned": round(own, 1)})
    return rows


def espn_injuries() -> list[dict]:
    data = _get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries").json()
    rows = []
    for team in data.get("injuries", []):
        abbr = ESPN_TEAMS.get(int(team.get("id") or 0), "")
        for inj in team.get("injuries", []):
            status = ESPN_INJURY_STATUS.get(inj.get("status"))
            a = inj.get("athlete") or {}
            if not status or not a.get("displayName"):
                continue
            details = inj.get("details") or {}
            rows.append({"name": a["displayName"], "team": abbr, "status": status, "return": details.get("returnDate"),
                         "type": details.get("type"), "note": inj.get("shortComment") or "",
                         "updated": (inj.get("date") or "")[:10]})
    return rows


def espn_periods(season: int) -> dict:
    """ESPN scores basketball by day ("scoring periods"); map each one to its date (US Eastern)."""
    from zoneinfo import ZoneInfo

    data = _get(ESPN_BASE.format(season=espn_season(season)), params={"view": "proTeamSchedules_wl"}).json()
    eastern = ZoneInfo("America/New_York")
    out: dict[str, str] = {}
    for team in (data.get("settings") or {}).get("proTeams") or []:
        for period, games in (team.get("proGamesByScoringPeriod") or {}).items():
            for g in games:
                if g.get("date"):
                    d = datetime.fromtimestamp(g["date"] / 1000, eastern).date().isoformat()
                    out[period] = min(out.get(period, d), d)
    return out


# --------------------------------------------------------------------------
# Season calendar
# --------------------------------------------------------------------------

def calendar(season: int) -> dict:
    """{"weeks": {week: [first date, last date]}, "games": {team: [[date, opp, home]]}}."""
    weeks: dict[str, list] = {}
    games: dict[str, list] = {}
    for g in schedule(season):
        d, w = g.get("date"), g.get("week")
        home, away = (g.get("home") or {}).get("team"), (g.get("away") or {}).get("team")
        if not d or not w or not home or not away:
            continue
        span = weeks.setdefault(str(w), [d, d])
        span[0], span[1] = min(span[0], d), max(span[1], d)
        games.setdefault(home, []).append([d, away, 1])
        games.setdefault(away, []).append([d, home, 0])
    for lst in games.values():
        lst.sort()
    # Fantasy weeks run Monday to Sunday; widen each week's span to the whole calendar week.
    for span in weeks.values():
        start = date.fromisoformat(span[0])
        monday = start - timedelta(days=start.weekday())
        span[0], span[1] = monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    return {"weeks": weeks, "games": games}


def current_week(cal: dict, today: date) -> int:
    """The week containing today, or the next one with games."""
    t = today.isoformat()
    for w in sorted(cal["weeks"], key=int):
        if cal["weeks"][w][1] >= t:
            return int(w)
    return max(int(w) for w in cal["weeks"]) if cal["weeks"] else 1


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

def bio(info: dict) -> dict:
    out = {"bd": info.get("birth_date"), "ht": info.get("height"), "wt": info.get("weight"),
           "col": info.get("college"), "exp": info.get("years_exp"), "num": info.get("number"),
           "inj": " ".join(x for x in (info.get("injury_body_part"), info.get("injury_notes")) if x) or None}
    return {k: v for k, v in out.items() if v not in (None, "")}


def build(season: int, today: date) -> dict:
    meta = sleeper_players()
    cal = calendar(season)
    week = current_week(cal, today)
    last_week = max(int(w) for w in cal["weeks"])
    t = today.isoformat()
    players: dict[str, dict] = {}
    failed: list[str] = []

    def entry(pid: str, fallback: dict | None) -> dict | None:
        info = meta.get(pid) or fallback or {}
        el = [p for p in (info.get("fantasy_positions") or [info.get("position")]) if p in POSITIONS]
        name = info.get("full_name") or f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
        if not el or not name:
            return None
        if pid not in players:
            players[pid] = {"n": name, "p": el[0], "el": el, "t": info.get("team") or "",
                            "i": info.get("injury_status") or None, "b": bio(info), "nx": {}, "log": []}
        return players[pid]

    # This season's games so far
    for w in range(1, week + 1):
        try:
            rows = stats(season, w)
        except Exception as exc:
            failed.append(f"stats week {w} ({type(exc).__name__})")
            continue
        for e in rows:
            st = e.get("stats") or {}
            if not st or not (st.get("min") or st.get("pts")) or not e.get("date") or e["date"] >= t:
                continue
            p = entry(str(e.get("player_id")), e.get("player"))
            if p is not None:
                p["log"].append([e["date"], e.get("opponent") or ""] + line_of(st))
    for p in players.values():
        p["log"].sort()

    # Per-game projections for every remaining game. The page keeps the next two weeks' lines;
    # later games use the season per-game line.
    remaining: dict[str, list] = {}   # sid -> [(date, line)]
    for w in range(week, last_week + 1):
        try:
            rows = projections(season, w)
        except Exception as exc:
            failed.append(f"projections week {w} ({type(exc).__name__})")
            continue
        for e in rows:
            d = e.get("date")
            if not d or d < t or not e.get("stats"):
                continue
            p = entry(str(e.get("player_id")), e.get("player"))
            if p is None:
                continue
            line = line_of(e["stats"], projected=True)
            remaining.setdefault(str(e["player_id"]), []).append((d, line))
            if w <= week + 1:
                p["nx"][d] = line
    try:
        for e in season_projections(season):
            p = players.get(str(e.get("player_id")))
            if p is not None and e.get("stats"):
                p["pg"] = line_of(e["stats"], projected=True)
                p["adp"] = (e["stats"] or {}).get("adp_dynasty")
    except Exception as exc:
        failed.append(f"season projections ({type(exc).__name__})")

    # Only players who matter for fantasy: on a team and projected or playing this season.
    players = {sid: p for sid, p in players.items() if p["t"] and (p["log"] or remaining.get(sid))}
    keys = {}
    for sid, p in players.items():
        keys.setdefault(player_key(p["n"]), sid)
    for msg in failed:
        print(f"  FAIL nba      {msg}", file=sys.stderr)
    return {"fields": FIELDS, "players": players, "keys": keys, "calendar": cal, "week": week,
            "remaining": remaining, "failed": failed}


# --------------------------------------------------------------------------
# Ranking boards
# --------------------------------------------------------------------------

def _rows(name: str, team: str, el: list, **value) -> list[dict]:
    """One row for the overall board and one for each position the player is eligible at."""
    return [dict(name=name, pos=pos, team=team, **value) for pos in ["ALL"] + el]


def board_sources(pd: dict, today: date) -> dict:
    """{kind: {source: rows | callable}} for the three boards."""
    players, cal, week = pd["players"], pd["calendar"], pd["week"]
    t = today.isoformat()
    week_end = cal["weeks"].get(str(week), [t, t])[1]
    games_left = {team: [g for g in gl if g[0] >= t] for team, gl in cal["games"].items()}
    two_weeks_ago = (today - timedelta(days=14)).isoformat()

    def avg_fp(log):
        return mean(fantasy_points(g[2:]) for g in log) if log else None

    def sleeper_week():
        out = []
        for sid, p in players.items():
            pts = sum(fantasy_points(line) for d, line in pd["remaining"].get(sid, []) if d <= week_end)
            if pts > 0:
                out += _rows(p["n"], p["t"], p["el"], score=pts)
        return out

    def recent_form():
        out = []
        for p in players.values():
            recent = avg_fp([g for g in p["log"] if g[0] >= two_weeks_ago])
            n = sum(1 for g in games_left.get(p["t"], []) if g[0] <= week_end)
            if recent and n:
                out += _rows(p["n"], p["t"], p["el"], score=recent * n)
        return out

    def sleeper_ros():
        out = []
        for sid, p in players.items():
            pts = sum(fantasy_points(line) for _, line in pd["remaining"].get(sid, []))
            if pts > 0:
                out += _rows(p["n"], p["t"], p["el"], score=pts)
        return out

    def season_pace():
        out = []
        for p in players.values():
            avg = avg_fp(p["log"])
            if avg and len(p["log"]) >= 2:
                out += _rows(p["n"], p["t"], p["el"], score=avg * len(games_left.get(p["t"], [])))
        return out

    def with_eligibility(rows):
        # Use Sleeper's position eligibility for every source, so the position boards line up.
        out = []
        for r in rows:
            sid = pd["keys"].get(player_key(r["name"]))
            el = players[sid]["el"] if sid else r["el"]
            if el:
                out += _rows(r["name"], r["team"], el, rank=r["rank"])
        return out

    def sleeper_dynasty():
        ranked = sorted((p for p in players.values() if p.get("adp")), key=lambda p: p["adp"])
        out = []
        for i, p in enumerate(ranked, 1):
            out += _rows(p["n"], p["t"], p["el"], rank=i)
        return out

    return {
        "week": {"Sleeper": sleeper_week, "Recent form": recent_form},
        "ros": {"Sleeper": sleeper_ros, "Season pace": season_pace,
                "FantasyPros": lambda: with_eligibility(fantasypros("ros"))},
        "dynasty": {"FantasyPros": lambda: with_eligibility(fantasypros("dynasty")),
                    "Sleeper ADP": sleeper_dynasty},
    }


def describe(kind: str, week: int) -> dict:
    return {
        "week": {"tab": f"Week {week}", "description": f"Projected fantasy points for the rest of Week {week}, so players with more games rank higher (ESPN standard points scoring)."},
        "ros": {"tab": "Rest of season", "description": "Projected fantasy points for every remaining game (ESPN standard points scoring)."},
        "dynasty": {"tab": "Dynasty", "description": "Long-term value: expert dynasty rankings and Sleeper dynasty draft position."},
    }[kind]


def attach_ids(types: dict, pd: dict) -> None:
    for t in types.values():
        for rows in (t.get("rankings") or {}).values():
            for r in rows:
                sid = pd["keys"].get(player_key(r["name"]))
                if sid:
                    r["sid"] = sid
                    r["name"] = pd["players"][sid]["n"]  # Sleeper's spelling, accents included


# --------------------------------------------------------------------------
# Ownership and injuries
# --------------------------------------------------------------------------

def attach_ownership(pd: dict, rows: list[dict]) -> int:
    matched = 0
    for r in rows:
        sid = pd["keys"].get(player_key(r["name"]))
        if sid in pd["players"]:
            pd["players"][sid]["own"] = [r["owned"], None]
            matched += 1
    return matched


# Chance to play the next game. Nobody publishes this; it's an estimate from the designation,
# moved by what the latest note says.
PLAY_BASE = {"Probable": 90, "DTD": 55, "Questionable": 50, "Doubtful": 15}
NOTE_HINTS = [
    (r"\b(won't play|will not play|ruled out|will miss|out for|sidelined)\b", -100),
    (r"\bdoubtful\b", -35),
    (r"\bprobable\b|expected to play|should play|will play|cleared", +30),
    (r"game-time decision|gametime decision", -5),
]


def chance_to_play(status: str, note: str, return_date: str | None, next_game: str | None) -> int | None:
    if status in ("Out", "Sus"):
        return 0
    if status not in PLAY_BASE:
        return None
    pct = PLAY_BASE[status]
    for pattern, adj in NOTE_HINTS:
        if re.search(pattern, note or "", re.I):
            pct += adj
            break
    if return_date and next_game and return_date > next_game:
        pct = min(pct, 5)
    return int(max(1, min(95, round(pct / 5) * 5)))


def attach_injuries(pd: dict, rows: list[dict], today: date) -> int:
    t = today.isoformat()
    matched = 0
    for r in rows:
        sid = pd["keys"].get(player_key(r["name"]))
        if sid not in pd["players"]:
            continue
        p = pd["players"][sid]
        nxt = next((g[0] for g in pd["calendar"]["games"].get(p["t"], []) if g[0] >= t), None)
        p["i"] = r["status"]
        p["inj"] = {"s": r["status"], "ret": r["return"], "type": r["type"], "note": r["note"], "upd": r["updated"],
                    "play": chance_to_play(r["status"], r["note"], r["return"], nxt)}
        matched += 1
    return matched


# --------------------------------------------------------------------------
# Past seasons (one file per season, loaded when its tab is opened)
# --------------------------------------------------------------------------

def load_season(season: int, fetch=stats) -> dict:
    """{"logs": {sid: [[MM-DD, opp, *line]]}, "ranks": {sid: overall rank}} for a finished season, cached."""
    path = HISTORY_DIR / f"{season}.json"
    if path.exists():
        return _ranked(json.loads(path.read_text())["logs"])
    logs: dict[str, list] = {}
    empty = 0
    for w in range(1, 31):
        rows = fetch(season, w)
        # Older seasons record playing time as seconds ("sp") rather than minutes.
        got = [e for e in rows if (e.get("stats") or {}).get("min") or (e.get("stats") or {}).get("sp")]
        if not got:
            empty += 1
            if empty >= 2 and w > 20:
                break  # past the end of the regular season
            continue
        empty = 0
        for e in got:
            logs.setdefault(str(e["player_id"]), []).append([e["date"][5:], e.get("opponent") or ""] + line_of(e["stats"]))
    if not logs:
        raise ValueError(f"no box scores for {season}")
    data = _ranked(logs)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")))
    return data


def _ranked(logs: dict) -> dict:
    """Season finish by total fantasy points. Sleeper also lists whole-team totals ("TEAM_PHI"); drop them."""
    logs = {sid: games for sid, games in logs.items() if not sid.startswith("TEAM_")}
    order = sorted(logs, key=lambda s: -sum(fantasy_points(g[2:]) for g in logs[s]))
    return {"logs": logs, "ranks": {s: i for i, s in enumerate(order, 1)}}


def history(season: int, pd: dict, meta: dict) -> dict:
    """{season: {sid: {"log", "rank"}}} for the site's players, plus each player's list of seasons ("hs")."""
    first = season
    for sid in pd["players"]:
        exp = (meta.get(sid) or {}).get("years_exp")
        if isinstance(exp, int):
            first = min(first, season - exp)
    out: dict[str, dict] = {}
    for s in range(max(FIRST_HISTORY_SEASON, first), season):
        cached = (HISTORY_DIR / f"{s}.json").exists()
        try:
            data = load_season(s)
        except Exception as exc:
            print(f"  FAIL nba      history {s} ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        if not cached:
            print(f"  ok   nba      {season_label(s)} season downloaded")
        chunk = {}
        for sid, p in pd["players"].items():
            if sid in data["logs"]:
                chunk[sid] = {"log": data["logs"][sid], "rank": data["ranks"].get(sid)}
                p.setdefault("hs", {})[str(s)] = data["ranks"].get(sid)
        out[str(s)] = chunk
    return out
