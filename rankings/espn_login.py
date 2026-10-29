"""Sign in to ESPN in a real browser window and save the login cookies to leagues.json.

    python3 update.py --espn-login

You type your password into ESPN's own sign-in page (captchas and email codes work
as usual); this script never sees it. Once you're signed in it reads the two
cookies ESPN uses for private leagues (espn_s2 and SWID), finds your football and
basketball leagues, and adds the ones you pick to leagues.json.

Needs Playwright, once:
    python3 -m pip install --user playwright && python3 -m playwright install chromium
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from .sources import TIMEOUT, USER_AGENT

LOGIN_URL = "https://www.espn.com/fantasy/football/"
FAN_API = "https://fan.api.espn.com/apis/v2/fans/{swid}"
GAME_IDS = {1: "football", 3: "basketball"}  # ESPN's fantasy game ids
WAIT_SECONDS = 10 * 60
INSTALL_HINT = "python3 -m pip install --user playwright && python3 -m playwright install chromium"


def sign_in() -> dict:
    """Open a browser window and wait until ESPN has set espn_s2 and SWID. Returns {espn_s2, swid}."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(f"Playwright isn't installed. Install it once with:\n    {INSTALL_HINT}")

    print("Opening an ESPN window. Sign in there (use 'Log In' at the top right); this window closes by itself.")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=False)
        except Exception as exc:
            raise SystemExit(f"Couldn't start the browser ({exc}). Try:\n    python3 -m playwright install chromium")
        try:
            context = browser.new_context(viewport={"width": 1100, "height": 850})
            page = context.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            deadline = time.time() + WAIT_SECONDS
            while time.time() < deadline:
                if not browser.is_connected() or all(p.is_closed() for p in context.pages):
                    raise SystemExit("The ESPN window was closed before you finished signing in.")
                found = {c["name"]: c["value"] for c in context.cookies("https://www.espn.com")}
                # SWID exists for signed-out visitors too; espn_s2 only appears after signing in.
                if found.get("espn_s2") and found.get("SWID"):
                    print("Signed in.")
                    return {"espn_s2": found["espn_s2"], "swid": found["SWID"]}
                page.wait_for_timeout(1000)
            raise SystemExit("Timed out after 10 minutes waiting for you to sign in.")
        finally:
            browser.close()


def find_leagues(cookies: dict) -> list[dict]:
    """Your ESPN football and basketball leagues as [{league_id, name, season, sport}], from ESPN's fan profile."""
    try:
        resp = requests.get(
            FAN_API.format(swid=cookies["swid"]),
            params={"displayHiddenPrefs": "true", "context": "fantasy", "useCookieAuth": "true"},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            cookies={"espn_s2": cookies["espn_s2"], "SWID": cookies["swid"]},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        prefs = resp.json().get("preferences") or []
    except Exception:
        return []
    out, seen = [], set()
    for pref in prefs:
        entry = ((pref.get("metaData") or {}).get("entry")) or {}
        try:
            sport = GAME_IDS.get(int(entry.get("gameId")))
        except (TypeError, ValueError):
            sport = None
        if not sport:
            continue
        for group in entry.get("groups") or []:
            league_id = str(group.get("groupId") or "")
            if league_id and (league_id, sport) not in seen:
                seen.add((league_id, sport))
                out.append({"league_id": league_id, "name": group.get("groupName") or f"League {league_id}",
                            "season": entry.get("seasonId"), "sport": sport})
    return out


def choose(leagues: list[dict], existing: set) -> list[tuple]:
    """[(league_id, sport)] the user wants on the site."""
    if not leagues:
        typed = input("Couldn't list your leagues automatically. Enter your league ID (the number after leagueId= in the URL): ").strip()
        if not typed.isdigit():
            return []
        sport = input("Is it a football or basketball league? [football]: ").strip().lower() or "football"
        return [(typed, "basketball" if sport.startswith("b") else "football")]
    print("Your ESPN leagues:")
    for i, lg in enumerate(leagues, 1):
        mark = "  (already added)" if (lg["league_id"], lg["sport"]) in existing else ""
        print(f"  {i}. {lg['name']}  [{lg['sport']}, {lg['league_id']}{', ' + str(lg['season']) if lg.get('season') else ''}]{mark}")
    picked = input("Which ones should the site show? Numbers separated by commas, or Enter for all: ").strip()
    if not picked:
        return [(lg["league_id"], lg["sport"]) for lg in leagues]
    out = []
    for part in picked.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= len(leagues):
            lg = leagues[int(part) - 1]
            out.append((lg["league_id"], lg["sport"]))
    return out


def _key(entry: dict) -> tuple:
    return str(entry.get("league_id")), entry.get("sport") or "football"


def save(path: Path, cookies: dict, picked: list) -> None:
    """Merge into leagues.json: new leagues are added, and every ESPN league gets the fresh cookies.

    picked is [(league_id, sport)]; a bare league id means football.
    """
    config = json.loads(path.read_text()) if path.exists() else {}
    espn = config.setdefault("espn", [])
    have = {_key(e) for e in espn}
    for item in picked:
        lid, sport = (item, "football") if isinstance(item, str) else item
        if (lid, sport) not in have:
            espn.append({"league_id": lid, "sport": sport} if sport != "football" else {"league_id": lid})
            have.add((lid, sport))
    for entry in espn:
        entry["espn_s2"] = cookies["espn_s2"]
        entry["swid"] = cookies["swid"]
    path.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(path, 0o600)  # it holds your ESPN login


def run(path: Path) -> None:
    cookies = sign_in()
    config = json.loads(path.read_text()) if path.exists() else {}
    existing = {_key(e) for e in config.get("espn") or []}
    picked = choose(find_leagues(cookies), existing)
    save(path, cookies, picked)
    added = [p for p in picked if p not in existing]
    total = len(json.loads(path.read_text()).get("espn") or [])
    print(f"Saved to {path.name}: {len(added)} new league(s), {total} ESPN league(s) in all, cookies refreshed.")
