"""Yahoo Fantasy leagues, fetched at update time.

Yahoo needs a sign-in for every league, public or not, and its API can't be called from a
web page, so Yahoo leagues work like private ESPN leagues: sign in once with

    python3 update.py --yahoo-login

and every update fetches the leagues and writes them into the page in the same shape as a
Sleeper league (the page reads both the same way). Your password goes only into Yahoo's own
sign-in page. What's kept in leagues.json is a Yahoo app's id and secret and a refresh token;
none of it is ever written into the page.

Yahoo may hand out a new refresh token when the old one is used, so the newest one is also
kept in data/yahoo_token.json, which GitHub's daily run carries over between runs.
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .sources import TIMEOUT, USER_AGENT

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2/"
REDIRECT = "oob"   # Yahoo shows the code on screen instead of sending it to a website
GAMES = {"football": "nfl", "basketball": "nba"}
TOKEN_CACHE = Path(__file__).resolve().parent.parent / "data" / "yahoo_token.json"

# Yahoo lineup slots -> the page's (Sleeper's) slot names.
SLOTS = {"W/R/T": "FLEX", "W/R": "WRRB_FLEX", "W/T": "REC_FLEX", "Q/W/R/T": "SUPER_FLEX", "Util": "UTIL",
         "BN": "BN", "IR": "IR", "IL": "IR", "IL+": "IR", "NA": "IR"}
# Yahoo team abbreviations that differ from Sleeper's (team defenses are keyed by abbreviation).
TEAM_FIX = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}


# ---------------------------------------------------------------- reading Yahoo's JSON

def flat(value) -> dict:
    """Yahoo wraps most objects as lists of one-key dicts (with empty lists mixed in); merge them into one dict."""
    if isinstance(value, dict):
        return value
    out: dict = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (list, dict)):
                out.update(flat(item))
    return out


def numbered(value) -> list:
    """Yahoo's collections: {"0": {...}, "1": {...}, "count": 2} -> [{...}, {...}]."""
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    return [value[k] for k in sorted((k for k in value if k.isdigit()), key=int)]


def find(value, key: str):
    """Every value stored under `key` anywhere inside a Yahoo response, in order."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key:
                yield v
            yield from find(v, key)
    elif isinstance(value, list):
        for item in value:
            yield from find(item, key)


def _team(entry) -> tuple[dict, dict]:
    """A Yahoo "team" value -> (its details, everything after them: roster, points...)."""
    parts = entry if isinstance(entry, list) else [entry]
    return flat(parts[0]), flat(parts[1:])


def _player(entry) -> tuple[dict, str]:
    """A Yahoo "player" value -> (its details, the lineup slot it's in)."""
    parts = entry if isinstance(entry, list) else [entry]
    meta = flat(parts[0])
    selected = flat(flat(parts[1:]).get("selected_position"))
    return meta, selected.get("position") or "BN"


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- turning a league into the page's shape

def to_bundle(settings_raw: dict, teams_raw: dict, scoreboards: dict, sid_of) -> dict:
    """Yahoo's league settings, team rosters and weekly scoreboards -> a Sleeper-shaped league bundle.

    sid_of(player_details) gives the site's player id for a Yahoo player, or None if it's not one the site knows.
    """
    league = flat(next(find(settings_raw, "league"), []))
    settings = flat(league.get("settings"))
    slots = []
    for rp in find(settings.get("roster_positions") or [], "roster_position"):
        rp = flat(rp)
        slots += [SLOTS.get(rp.get("position"), rp.get("position"))] * _int(rp.get("count"), 1)
    start_slots = [s for s in slots if s not in ("BN", "IR")]

    start_week = _int(league.get("start_week"), 1)
    end_week = _int(league.get("end_week"), 17)
    playoff_start = _int(settings.get("playoff_start_week"), end_week + 1) if _int(settings.get("uses_playoff"), 1) else end_week + 1

    users, rosters, me, missing = [], [], None, 0
    team_ids = {}
    for i, entry in enumerate(find(teams_raw, "team"), 1):
        meta, rest = _team(entry)
        team_key = meta.get("team_key") or str(i)
        team_ids[team_key] = i
        manager = flat(next(find(meta.get("managers") or [], "manager"), {}))
        user_id = manager.get("guid") or f"yahoo-{i}"
        users.append({"user_id": user_id, "display_name": manager.get("nickname") or "",
                      "metadata": {"team_name": meta.get("name") or f"Team {i}"}})
        if _int(meta.get("is_owned_by_current_login")):
            me = user_id
        players, by_slot = [], {}
        for p in find(rest.get("roster") or {}, "player"):
            details, slot = _player(p)
            sid = sid_of(details)
            if not sid:
                missing += 1
                continue
            players.append(sid)
            by_slot.setdefault(SLOTS.get(slot, slot), []).append(sid)
        starters = [by_slot[s].pop(0) if by_slot.get(s) else "0" for s in start_slots]
        rosters.append({"roster_id": i, "owner_id": user_id, "players": players, "starters": starters, "settings": {}})

    matchups = {}
    for week, raw in scoreboards.items():
        rows = []
        for m_id, matchup in enumerate(find(raw, "matchup"), 1):
            for entry in find(matchup, "team"):
                meta, rest = _team(entry)
                points = flat(rest.get("team_points")).get("total")
                if meta.get("team_key") in team_ids:
                    rows.append({"roster_id": team_ids[meta["team_key"]], "matchup_id": m_id, "points": _float(points)})
        matchups[str(week)] = rows

    return {
        "league": {"league_id": league.get("league_key"), "name": league.get("name") or "Yahoo league",
                   "season": str(league.get("season") or ""), "total_rosters": len(rosters),
                   "roster_positions": slots,
                   "settings": {"start_week": start_week, "playoff_week_start": playoff_start,
                                "playoff_teams": _int(settings.get("num_playoff_teams"), 4)}},
        "users": users, "rosters": rosters, "matchups": matchups, "me": me, "traded": [],
        "unmatched": missing,
    }


def football_ids(player_data: dict):
    """Yahoo player -> Sleeper id, by name and position (team defenses by team abbreviation)."""
    from .players import player_key
    keys, known = player_data.get("keys", {}), player_data.get("players", {})

    def sid_of(p: dict):
        pos = (p.get("primary_position") or p.get("display_position") or "").split(",")[0]
        if pos in ("DEF", "DST", "D/ST"):
            team = str(p.get("editorial_team_abbr") or "").upper()
            team = TEAM_FIX.get(team, team)
            return team if team in known else None
        name = flat(p.get("name")).get("full") or ""
        return keys.get(player_key(name, pos))
    return sid_of


def basketball_ids(pd: dict):
    """Yahoo player -> the basketball page's player id, by name."""
    from .nba.build import player_key
    keys = pd.get("keys", {})
    return lambda p: keys.get(player_key(flat(p.get("name")).get("full") or ""))


# ---------------------------------------------------------------- talking to Yahoo

def _token_request(app: dict, **data) -> dict:
    resp = requests.post(TOKEN_URL, auth=(app["client_id"], app["client_secret"]),
                         data={"redirect_uri": REDIRECT, **data},
                         headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    if resp.status_code in (400, 401):
        raise PermissionError("Yahoo refused the sign-in: run python3 update.py --yahoo-login again")
    resp.raise_for_status()
    return resp.json()


def access_token(app: dict, config_path: Path | None = None) -> str:
    """A fresh access token. Yahoo may rotate the refresh token, so the newest one is saved for next time."""
    cached = json.loads(TOKEN_CACHE.read_text()) if TOKEN_CACHE.exists() else {}
    refresh = cached.get(app["client_id"]) or app["refresh_token"]
    try:
        tokens = _token_request(app, grant_type="refresh_token", refresh_token=refresh)
    except PermissionError:
        if refresh == app["refresh_token"]:
            raise
        tokens = _token_request(app, grant_type="refresh_token", refresh_token=app["refresh_token"])
    new = tokens.get("refresh_token")
    if new and new != refresh:
        TOKEN_CACHE.parent.mkdir(exist_ok=True)
        TOKEN_CACHE.write_text(json.dumps({**cached, app["client_id"]: new}))
        os.chmod(TOKEN_CACHE, 0o600)
        if config_path and config_path.exists():   # on your computer, keep leagues.json current too
            config = json.loads(config_path.read_text())
            config.setdefault("yahoo", {})["refresh_token"] = new
            config_path.write_text(json.dumps(config, indent=2) + "\n")
    return tokens["access_token"]


def get(path: str, token: str) -> dict:
    resp = requests.get(API + path, params={"format": "json"}, timeout=TIMEOUT,
                        headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT, "Accept": "application/json"})
    if resp.status_code in (401, 403):
        raise PermissionError(f"Yahoo refused access to {path.split('/')[1] if '/' in path else path}")
    resp.raise_for_status()
    return resp.json()


def fetch_league(league_key: str, token: str, sid_of) -> dict:
    settings = get(f"league/{league_key}/settings", token)
    league = flat(next(find(settings, "league"), []))
    teams = get(f"league/{league_key}/teams/roster", token)
    end = _int(flat(league.get("settings")).get("playoff_start_week"), _int(league.get("end_week"), 17) + 1) - 1
    # Every regular-season week: weeks not played yet have no points, but their pairings drive projected records.
    scoreboards = {week: get(f"league/{league_key}/scoreboard;week={week}", token)
                   for week in range(_int(league.get("start_week"), 1), end + 1)}
    return to_bundle(settings, teams, scoreboards, sid_of)


def fetch_configured(config: dict, sport: str, sid_of, config_path: Path | None = None) -> list[dict]:
    """[{league_key, name, data | error}] for every Yahoo league of one sport in leagues.json."""
    yahoo = config.get("yahoo") or {}
    wanted = [lg for lg in yahoo.get("leagues") or [] if (lg.get("sport") or "football") == sport]
    if not wanted:
        return []
    try:
        token = access_token(yahoo, config_path)
    except Exception as exc:
        print(f"  FAIL league   Yahoo sign-in  {type(exc).__name__}: {exc}", file=sys.stderr)
        return [{"league_key": lg["league_key"], "name": lg.get("name"), "error": f"{type(exc).__name__}: {exc}"} for lg in wanted]
    out = []
    for lg in wanted:
        item = {"league_key": lg["league_key"], "name": lg.get("name")}
        try:
            item["data"] = fetch_league(lg["league_key"], token, sid_of)
            item["name"] = item["data"]["league"]["name"]
            unmatched = item["data"].pop("unmatched", 0)
            print(f"  ok   league   Yahoo {lg['league_key']}  {len(item['data']['rosters'])} teams"
                  + (f", {unmatched} players not matched" if unmatched else ""))
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
            print(f"  FAIL league   Yahoo {lg['league_key']}  {item['error']}", file=sys.stderr)
        out.append(item)
    return out


# ---------------------------------------------------------------- python3 update.py --yahoo-login

APP_HELP = """Yahoo only lets registered apps read fantasy leagues, so you need your own (free, two minutes):
  1. Go to https://developer.yahoo.com/apps/create/ and sign in.
  2. Application Name: anything (e.g. "My fantasy site"). Application Type: Installed Application.
  3. Redirect URI(s): oob   API Permissions: tick Fantasy Sports (Read).
  4. Create App, then copy the Client ID and Client Secret shown.
"""


def find_leagues(token: str) -> list[dict]:
    """Your current Yahoo football and basketball leagues: [{league_key, name, season, sport}]."""
    raw = get("users;use_login=1/games;game_keys=nfl,nba/leagues", token)
    out = []
    for game in find(raw, "game"):
        meta = flat(game[0] if isinstance(game, list) else game)
        sport = {v: k for k, v in GAMES.items()}.get(meta.get("code"))
        if not sport:
            continue
        for lg in find(game, "league"):
            info = flat(lg)
            if info.get("league_key"):
                out.append({"league_key": info["league_key"], "name": info.get("name") or info["league_key"],
                            "season": info.get("season"), "sport": sport})
    return out


def run(path: Path) -> None:
    config = json.loads(path.read_text()) if path.exists() else {}
    yahoo = config.get("yahoo") or {}
    if not (yahoo.get("client_id") and yahoo.get("client_secret")):
        print(APP_HELP)
        yahoo["client_id"] = input("Client ID: ").strip()
        yahoo["client_secret"] = input("Client Secret: ").strip()
        if not (yahoo["client_id"] and yahoo["client_secret"]):
            raise SystemExit("Both the Client ID and Client Secret are needed.")
    url = AUTH_URL + "?" + urlencode({"client_id": yahoo["client_id"], "redirect_uri": REDIRECT,
                                       "response_type": "code", "language": "en-us"})
    print("\nOpening Yahoo's sign-in page. Sign in, press Agree, and Yahoo shows a code.")
    print(f"If no browser opens, go to:\n  {url}\n")
    webbrowser.open(url)
    typed = input("Paste the code (or the whole address Yahoo sent you to): ").strip()
    code = parse_qs(urlparse(typed).query).get("code", [typed])[0] if "code=" in typed else typed
    tokens = _token_request(yahoo, grant_type="authorization_code", code=code)
    yahoo["refresh_token"] = tokens["refresh_token"]
    if TOKEN_CACHE.exists():   # a fresh sign-in replaces any token saved by earlier updates
        cached = json.loads(TOKEN_CACHE.read_text())
        cached.pop(yahoo["client_id"], None)
        TOKEN_CACHE.write_text(json.dumps(cached))
    print("Signed in.")

    found = find_leagues(tokens["access_token"])
    have = {lg["league_key"] for lg in yahoo.get("leagues") or []}
    if found:
        print("Your Yahoo leagues:")
        for i, lg in enumerate(found, 1):
            print(f"  {i}. {lg['name']}  [{lg['sport']}, {lg['league_key']}]{'  (already added)' if lg['league_key'] in have else ''}")
        picked = input("Which ones should the site show? Numbers separated by commas, or Enter for all: ").strip()
        chosen = found if not picked else [found[int(p) - 1] for p in picked.replace(" ", "").split(",")
                                          if p.isdigit() and 1 <= int(p) <= len(found)]
    else:
        print("No current Yahoo football or basketball leagues found on this account.")
        chosen = []
    leagues = yahoo.setdefault("leagues", [])
    for lg in chosen:
        if lg["league_key"] not in have:
            leagues.append({"league_key": lg["league_key"], "sport": lg["sport"], "name": lg["name"]})
    config["yahoo"] = yahoo
    path.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(path, 0o600)   # it holds your Yahoo app secret and sign-in token
    print(f"Saved to {path.name}: {len(leagues)} Yahoo league(s).")
