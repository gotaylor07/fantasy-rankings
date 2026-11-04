"""Dynasty trade values: players and future draft picks on one scale.

Football blends FantasyCalc and KeepTradeCut, which both price players and picks. Each
market is scaled so its top player is 10,000, then the two are averaged and curved so
that two mid assets don't add up to a star. Neither market covers basketball, so its
values are this site's own estimate from the dynasty rankings (see `estimate`).
"""
from __future__ import annotations

import math
import re

from .players import player_key
from .sources import fantasycalc_raw, ktc_players

TOP = 10000
CURVE = 1.5        # higher = stars are worth more next to several mid assets
TIERS = ("early", "mid", "late")

# Estimates, for sports with no pick market: the dynasty rank each pick is treated as equal to,
# and how much a pick loses for each extra year away.
PICK_RANK = {1: (30, 50, 70), 2: (100, 120, 140), 3: (170, 190, 210), 4: (240, 260, 280)}
YEAR_DISCOUNT = 0.9
RANK_DECAY = 60    # value halves roughly every 42 dynasty ranks


def trade_value(market_value: float) -> int:
    return round(TOP * (max(0.0, market_value) / TOP) ** CURVE)


def parse_pick(name: str):
    """(year, round, tier or None) from "2027 1st (Early)", "2028 1st" or "2027 Early 1st"; None if not a pick."""
    m = re.match(r"(\d{4})\s+(?:(Early|Mid|Late)\s+)?(\d)(?:st|nd|rd|th)(?:\s+\((Early|Mid|Late)\))?$", name.strip())
    if not m:
        return None
    tier = m.group(2) or m.group(4)
    return m.group(1), int(m.group(3)), tier.lower() if tier else None


def _add_pick(table: dict, year: str, rnd: int, tier, value: float) -> None:
    """Record a price; one with no tier is kept under None and fills whichever tiers have no price of their own."""
    table.setdefault(year, {}).setdefault(str(rnd), {})[tier] = value


def football(keys: dict) -> dict:
    """Market values for players (by Sleeper id) and picks, from the raw market feeds."""
    players: dict[str, list] = {}
    picks: dict[str, dict] = {}

    fc = fantasycalc_raw(True)
    top = max((float(e.get("value") or 0) for e in fc), default=0) or 1
    fc_picks: dict = {}
    for e in fc:
        p = e.get("player") or {}
        scaled = TOP * float(e.get("value") or 0) / top
        parsed = parse_pick(p.get("name") or "") if p.get("position") == "PICK" else None
        if parsed:
            _add_pick(fc_picks, parsed[0], parsed[1], parsed[2], scaled)
        elif p.get("sleeperId"):
            players.setdefault(str(p["sleeperId"]), []).append(scaled)

    ktc = ktc_players()
    top = max((float((p.get("oneQBValues") or {}).get("value") or 0) for p in ktc), default=0) or 1
    ktc_picks: dict = {}
    for p in ktc:
        value = (p.get("oneQBValues") or {}).get("value")
        if value is None or not p.get("playerName"):
            continue
        scaled = TOP * float(value) / top
        parsed = parse_pick(p["playerName"]) if p.get("position") == "RDP" else None
        if parsed:
            _add_pick(ktc_picks, parsed[0], parsed[1], parsed[2], scaled)
        else:
            sid = keys.get(player_key(p["playerName"], p.get("position") or ""))
            if sid:
                players.setdefault(sid, []).append(scaled)

    for source in (fc_picks, ktc_picks):
        for year, rounds in source.items():
            for rnd, tiers in rounds.items():
                for tier in TIERS:
                    value = tiers.get(tier, tiers.get(None))
                    if value is not None:
                        picks.setdefault(year, {}).setdefault(rnd, {}).setdefault(tier, []).append(value)

    return {
        "players": {sid: trade_value(sum(v) / len(v)) for sid, v in players.items()},
        "picks": {y: {r: {t: trade_value(sum(v) / len(v)) for t, v in tiers.items()} for r, tiers in rounds.items()}
                  for y, rounds in sorted(picks.items())},
        "source": "FantasyCalc and KeepTradeCut",
        "estimated": False,
    }


def estimate(ranked_ids: list, season: int) -> dict:
    """Values from a dynasty ranking (best first): the site's own estimate, for sports with no pick market."""
    value = lambda rank: round(TOP * math.exp(-rank / RANK_DECAY))
    picks = {}
    for offset in (1, 2, 3):
        discount = YEAR_DISCOUNT ** (offset - 1)
        picks[str(season + offset)] = {
            str(rnd): {t: round(value(rank) * discount) for t, rank in zip(TIERS, ranks)} for rnd, ranks in PICK_RANK.items()
        }
    return {"players": {sid: value(i) for i, sid in enumerate(ranked_ids)}, "picks": picks,
            "source": "this site's estimate from the dynasty rankings", "estimated": True}
