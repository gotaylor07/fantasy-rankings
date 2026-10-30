"""Per-player data for the site: bios, this season's game logs, weekly projections and ownership.

Everything is keyed by Sleeper player id, because Sleeper supplies both the box
scores and the projections, and its player file also carries each player's
ESPN id, which is how ESPN league rosters are matched up.
"""
from __future__ import annotations

import re
import sys

from .aggregate import norm_name
from .sources import ESPN_TEAMS, LAST_WEEK, LINEUP_POSITIONS, sleeper_name, sleeper_players, sleeper_projections, sleeper_stats

# Box-score columns kept for each game, in this order after [week, opp, ppr, snap %].
LOG_FIELDS = [
    "pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int",
    "rush_att", "rush_yd", "rush_td",
    "rec_tgt", "rec", "rec_yd", "rec_td",
]


def player_key(name: str, pos: str) -> str:
    """Join key between rankings rows and player data (also built in the page's JS)."""
    return f"{norm_name(name)}|{pos}"


def _num(v):
    if v is None:
        return 0
    f = round(float(v), 1)
    return int(f) if f == int(f) else f


def game_row(week: int, opp, st: dict) -> list:
    """One game-log row: [week, opponent, PPR points, snap %, *LOG_FIELDS]."""
    team_snaps = st.get("tm_off_snp")
    snap_pct = round(100 * st["off_snp"] / team_snaps) if st.get("off_snp") and team_snaps else None
    return [week, opp or "", _num(st.get("pts_ppr")), snap_pct] + [_num(st.get(f)) for f in LOG_FIELDS]


# Sleeper sometimes names the same school two ways; use one name everywhere ("as listed": "use").
COLLEGES = {"North Carolina State": "NC State", "Gonzaga Bulldogs": "Gonzaga"}


def college(name):
    return COLLEGES.get(name, name) if name else name


def bio(info: dict) -> dict:
    """Profile fields from Sleeper's player file, short keys to keep the page small."""
    out = {
        "bd": info.get("birth_date"),
        "ht": info.get("height"),
        "wt": info.get("weight"),
        "col": college(info.get("college")),
        "exp": info.get("years_exp"),
        "num": info.get("number"),
        "inj": " ".join(x for x in (info.get("injury_body_part"), info.get("injury_notes")) if x) or None,
    }
    return {k: v for k, v in out.items() if v not in (None, "")}


def build(season: int, week: int) -> dict:
    """Game logs for weeks 1..week-1 and projections for week..18.

    A single failed week is skipped (and reported) rather than failing the lot.
    """
    meta = sleeper_players()
    players: dict[str, dict] = {}
    failed: list[str] = []

    def entry(pid: str, fallback: dict) -> dict | None:
        info = meta.get(pid) or fallback or {}
        pos = info.get("position")
        if pos not in LINEUP_POSITIONS:
            return None
        name = sleeper_name(info)
        if not name:
            return None
        if pid not in players:
            players[pid] = {
                "n": name,
                "p": pos,
                "t": info.get("team") or "",
                "i": info.get("injury_status") or None,
                "b": bio(info),
                "proj": {},
                "log": [],
            }
        return players[pid]

    teams_by_week: dict[int, set] = {}
    for w in range(1, week):
        try:
            rows = sleeper_stats(season, w)
        except Exception as exc:
            failed.append(f"stats week {w} ({type(exc).__name__})")
            continue
        teams = teams_by_week.setdefault(w, set())
        for e in rows:
            st = e.get("stats") or {}
            if st.get("gp") and e.get("team"):
                teams.add(e["team"])
            if not st.get("gp") and not st.get("pts_ppr"):
                continue  # inactive or didn't play
            p = entry(str(e.get("player_id")), e.get("player"))
            if p is None:
                continue
            p["log"].append(game_row(w, e.get("opponent"), st))

    games: dict[str, dict] = {}  # {team: {week: [opponent, date]}} for upcoming games
    for w in range(week, LAST_WEEK + 1):
        try:
            rows = sleeper_projections(season, w)
        except Exception as exc:
            failed.append(f"projections week {w} ({type(exc).__name__})")
            continue
        teams = teams_by_week.setdefault(w, set())
        for e in rows:
            pts = (e.get("stats") or {}).get("pts_ppr")
            if pts is None:
                continue
            if e.get("team"):
                teams.add(e["team"])
                if e.get("opponent"):
                    games.setdefault(e["team"], {})[str(w)] = [e["opponent"], e.get("date")]
            p = entry(str(e.get("player_id")), e.get("player"))
            if p is None:
                continue
            p["proj"][str(w)] = _num(pts)

    # A team with no box scores / projections in a week that has them for most teams is on bye.
    all_teams = {p["t"] for p in players.values() if p["t"]}
    byes = {}
    for w, teams in teams_by_week.items():
        if len(teams) > 20:
            for t in all_teams - teams:
                byes.setdefault(t, w)

    keys: dict[str, str] = {}
    espn_ids: dict[str, str] = {}
    for pid, p in players.items():
        keys.setdefault(player_key(p["n"], p["p"]), pid)
        espn = (meta.get(pid) or {}).get("espn_id")
        if espn:
            espn_ids[str(espn)] = pid

    for msg in failed:
        print(f"  FAIL players  {msg}", file=sys.stderr)
    return {
        "fields": LOG_FIELDS,
        "players": players,
        "keys": keys,
        "espn_ids": espn_ids,
        "byes": byes,
        "games": games,
        "failed": failed,
    }


def attach_ownership(player_data: dict, rows: list[dict]) -> int:
    """Add ESPN's rostered/started percentages ("own": [rostered, started]) to each player. Returns matches."""
    players = player_data.get("players", {})
    espn_ids = player_data.get("espn_ids", {})
    keys = player_data.get("keys", {})
    matched = 0
    for r in rows:
        if r["pos"] == "DEF":
            sid = r["team"] if r["team"] in players else None
        else:
            sid = espn_ids.get(str(r["espn_id"])) or keys.get(player_key(r["name"], r["pos"]))
        if sid and sid in players:
            players[sid]["own"] = [r["owned"], r["started"]]
            matched += 1
    return matched


def attach_ids(types: dict, player_data: dict, meta: dict | None = None) -> None:
    """Give each ranking row the Sleeper id of the player it refers to (for the game-log popup).

    Ranked players with no games or projections this season (injured, rookies) are looked up in
    `meta`, Sleeper's player file, and get an entry with an empty log.
    """
    keys = player_data.get("keys", {})
    players = player_data.get("players", {})
    meta_keys = None
    for t in types.values():
        for pos, rows in (t.get("rankings") or {}).items():
            for r in rows:
                key = player_key(r["name"], pos)
                sid = keys.get(key)
                if not sid and meta:
                    if meta_keys is None:
                        meta_keys = {
                            player_key(sleeper_name(m), m["position"]): pid
                            for pid, m in meta.items()
                            if m.get("position") in LINEUP_POSITIONS and sleeper_name(m)
                        }
                    sid = meta_keys.get(key)
                    if sid:
                        m = meta[sid]
                        players[sid] = {"n": sleeper_name(m), "p": pos, "t": m.get("team") or "",
                                        "i": m.get("injury_status") or None, "b": bio(m), "proj": {}, "log": []}
                        keys[key] = sid
                if sid:
                    r["sid"] = sid


# Chance to play this week. Nobody publishes this, so it's an estimate: a base rate for the
# designation, moved by the latest practice report, and capped when ESPN's expected return
# date is after the game.
PLAY_BASE = {"Questionable": 70, "Doubtful": 15}
PRACTICE = [  # (pattern in the practice note, adjustment); first match wins
    (r"\bfull(y)? (participa|practic)|practiced fully|full go|full participant", +15),
    (r"\blimited\b", 0),
    (r"did not practice|didn't practice|not practice|did not participate|didn't participate|\bDNP\b|sat out|absent|sidelined|missed practice", -20),
]


def chance_to_play(status: str, note: str, return_date: str | None, game_date: str | None) -> int | None:
    if status not in PLAY_BASE:
        return 0 if status in ("Out", "IR", "PUP", "Sus") else None
    pct = PLAY_BASE[status]
    for pattern, adj in PRACTICE:
        if re.search(pattern, note or "", re.I):
            pct += adj
            break
    if return_date and game_date and return_date > game_date:
        pct = min(pct, 5)
    return int(max(1, min(95, round(pct / 5) * 5)))


def attach_injuries(player_data: dict, rows: list[dict], week: int) -> int:
    """Add ESPN injury details ("inj") to each player and make ESPN's status the current one. Returns matches."""
    players = player_data.get("players", {})
    espn_ids = player_data.get("espn_ids", {})
    keys = player_data.get("keys", {})
    games = player_data.get("games", {})
    matched = 0
    for r in rows:
        sid = espn_ids.get(str(r["espn_id"])) or keys.get(player_key(r["name"], r["pos"]))
        if not sid or sid not in players:
            continue
        p = players[sid]
        game = (games.get(p.get("t") or r["team"]) or {}).get(str(week))
        p["i"] = r["status"]
        p["inj"] = {
            "s": r["status"], "ret": r["return"], "type": r["type"], "note": r["note"], "upd": r["updated"],
            # Only the short note: the long write-up often discusses teammates' practice status too.
            "play": chance_to_play(r["status"], r["note"], r["return"], game[1] if game else None),
        }
        matched += 1
    return matched
