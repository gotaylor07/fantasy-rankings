"""Synthetic basketball data so the basketball page can be tried without network access.

Names are deliberately fake ("Demo PG 07") so nobody mistakes them for real rankings.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .build import FIELDS, POSITIONS, fantasy_points, player_key

TEAMS = [f"T{i:02d}" for i in range(1, 31)]
SEASON_START = date(2026, 10, 20)
WEEKS = 25
POOL = {"PG": 40, "SG": 40, "SF": 40, "PF": 40, "C": 34}
SECOND_POS = {"PG": "SG", "SG": "SF", "SF": "PF", "PF": "C", "C": "PF"}
# Sleeper-style points scoring for the demo league, different from the boards' ESPN scoring on purpose.
DEMO_LEAGUE_SCORING = {"pts": 1, "reb": 1.2, "ast": 1.5, "stl": 3, "blk": 3, "to": -1, "tpm": 0.5, "dd": 1.5, "td": 3}


def calendar(seed: int = 3) -> dict:
    rng = random.Random(seed)
    weeks, games = {}, {t: [] for t in TEAMS}
    monday = SEASON_START - timedelta(days=SEASON_START.weekday())
    for w in range(1, WEEKS + 1):
        start = monday + timedelta(days=7 * (w - 1))
        weeks[str(w)] = [start.isoformat(), (start + timedelta(days=6)).isoformat()]
        for day in range(7):
            d = start + timedelta(days=day)
            if d < SEASON_START:
                continue
            playing = rng.sample(TEAMS, 2 * rng.randint(3, 7))
            for a, b in zip(playing[::2], playing[1::2]):
                games[a].append([d.isoformat(), b, 1])
                games[b].append([d.isoformat(), a, 0])
    return {"weeks": weeks, "games": games}


def _line(rng: random.Random, pos: str, fp_target: float, projected: bool) -> list:
    """A box score that roughly scores fp_target under ESPN standard points."""
    pts = max(0.0, fp_target * rng.uniform(0.45, 0.6))
    reb = fp_target * (0.22 if pos in ("PF", "C") else 0.1) * rng.uniform(0.7, 1.3)
    ast = fp_target * (0.12 if pos in ("PG", "SG") else 0.05) * rng.uniform(0.7, 1.3)
    stl, blk = rng.uniform(0.3, 1.8), rng.uniform(0.1, 2.2 if pos == "C" else 0.8)
    fga = pts / 2.2
    fgm = fga * rng.uniform(0.4, 0.56)
    fta = pts * 0.2
    ftm = fta * 0.78
    tpa = fga * (0.2 if pos == "C" else 0.42)
    tpm = tpa * 0.36
    line = {"min": rng.uniform(22, 37), "pts": pts, "reb": reb, "ast": ast, "stl": stl, "blk": blk,
            "to": rng.uniform(0.8, 3.5), "tpm": tpm, "tpa": tpa, "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta,
            "oreb": reb * 0.25, "dd": 0, "td": 0}
    if not projected:
        line = {k: round(v) for k, v in line.items()}
        tens = sum(1 for k in ("pts", "reb", "ast", "stl", "blk") if line[k] >= 10)
        line["dd"], line["td"] = int(tens >= 2), int(tens >= 3)
    return [round(line[f], 1) for f in FIELDS]


def players(today: date, seed: int = 11) -> dict:
    rng = random.Random(seed)
    cal = calendar()
    t = today.isoformat()
    week = next((int(w) for w, (a, b) in sorted(cal["weeks"].items(), key=lambda x: int(x[0])) if b >= t), WEEKS)
    week_end_next = cal["weeks"].get(str(week + 1), cal["weeks"][str(week)])[1]
    out, remaining = {}, {}
    for pos, count in POOL.items():
        for i in range(1, count + 1):
            sid = f"demo-{pos}-{i:02d}"
            team = TEAMS[(i * 7 + POSITIONS.index(pos)) % 30]
            strength = 48 * (1.1 - 0.85 * (i - 1) / count)
            el = [pos] + ([SECOND_POS[pos]] if i % 3 == 0 else [])
            log = [[d, opp] + _line(rng, pos, max(5.0, rng.gauss(strength, strength * 0.3)), False)
                   for d, opp, _ in cal["games"][team] if d < t and rng.random() > 0.06]
            rem = [(d, _line(rng, pos, strength * rng.uniform(0.9, 1.1), True)) for d, _, _ in cal["games"][team] if d >= t]
            injury = rng.choice(["DTD", "Out", "Questionable"]) if rng.random() < 0.07 else None
            p = {"n": f"Demo {pos} {i:02d}", "p": pos, "el": el, "t": team, "i": injury, "log": log,
                 "nx": {d: line for d, line in rem if d <= week_end_next},
                 "pg": _line(rng, pos, strength, True), "adp": round(i * 5 + rng.uniform(-6, 6), 1),
                 "b": {"bd": f"{rng.randint(1992, 2006)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                       "ht": str(rng.randint(73, 86)), "wt": str(rng.randint(180, 270)), "col": "Demo State",
                       "exp": rng.randint(0, 12), "num": rng.randint(0, 99)},
                 "own": [round(max(0.0, min(100.0, 102 - 2.6 * i + rng.uniform(-6, 6))), 1), None]}
            if injury:
                back = (today + timedelta(days={"DTD": 2, "Questionable": 1, "Out": 12}[injury])).isoformat()
                p["inj"] = {"s": injury, "ret": back, "type": rng.choice(["Ankle", "Knee", "Hamstring"]),
                            "note": "Demo note: listed as day-to-day after the last game.", "upd": t,
                            "play": {"DTD": 55, "Questionable": 50, "Out": 0}[injury]}
            out[sid] = p
            remaining[sid] = rem
    return {"fields": FIELDS, "players": out, "keys": {player_key(p["n"]): sid for sid, p in out.items()},
            "calendar": cal, "week": week, "remaining": remaining, "failed": []}


def boards(pd: dict, today: date, seed: int = 9) -> dict:
    """Stand-ins for the network sources: Sleeper-like values plus a noisy 'expert' ranking."""
    from .build import board_sources

    rng = random.Random(seed)
    src = board_sources(pd, today)

    def expert(kind):
        def make():
            scored = sorted(pd["players"].values(), key=lambda p: -fantasy_points(p["pg"]) * rng.uniform(0.85, 1.15))
            return [{"name": p["n"], "team": p["t"], "el": p["el"], "rank": i} for i, p in enumerate(scored, 1)]
        return make

    def with_eligibility(make):
        def run():
            out = []
            for r in make():
                for pos in ["ALL"] + r["el"]:
                    out.append({"name": r["name"], "pos": pos, "team": r["team"], "rank": r["rank"]})
            return out
        return run

    src["ros"]["FantasyPros"] = with_eligibility(expert("ros"))
    src["dynasty"]["FantasyPros"] = with_eligibility(expert("dynasty"))
    return src


def league(pd: dict, today: date, seed: int = 5) -> dict:
    """A 10-team points league in the shape of Sleeper's NBA API responses."""
    rng = random.Random(seed)
    P, cal = pd["players"], pd["calendar"]
    slots = ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "UTIL", "UTIL"] + ["BN"] * 3
    n_teams, reg_weeks = 10, 19
    pool = sorted(P, key=lambda s: -fantasy_points(P[s]["pg"]))
    rosters = [[] for _ in range(n_teams)]
    for rnd in range(13):
        order = range(n_teams) if rnd % 2 == 0 else reversed(range(n_teams))
        for t in order:
            rosters[t].append(pool.pop(rng.randrange(min(4, len(pool)))))

    def week_points(roster, w):
        """Rough actual score: each day, the 10 best performers among players who played."""
        start, end = cal["weeks"][str(w)]
        total = 0.0
        days = {}
        for sid in roster:
            for g in P[sid]["log"]:
                if start <= g[0] <= end:
                    days.setdefault(g[0], []).append(fantasy_points(g[2:], DEMO_LEAGUE_SCORING))
        for scores in days.values():
            total += sum(sorted(scores, reverse=True)[:10])
        return round(total, 2)

    names = ["Pick and Pop", "Fast Break", "Triple Threat", "Full Court Press", "Splash Zone",
             "Glass Cleaners", "Euro Steppers", "Zone Defense", "Alley Oops", "Buzzer Beaters"]
    users = [{"user_id": f"u{i}", "display_name": "you" if i == 0 else f"manager{i}",
              "metadata": {"team_name": names[i]}} for i in range(n_teams)]
    roster_objs = [{"roster_id": i + 1, "owner_id": f"u{i}", "players": r, "starters": r[:10], "settings": {}}
                   for i, r in enumerate(rosters)]
    teams = list(range(1, n_teams + 1))
    matchups = {}
    for w in range(1, reg_weeks + 1):
        rot = teams[:1] + teams[1:][(w - 1) % (n_teams - 1):] + teams[1:][: (w - 1) % (n_teams - 1)]
        rows = []
        for mid in range(n_teams // 2):
            for rid in (rot[mid], rot[-1 - mid]):
                pts = week_points(rosters[rid - 1], w) if w < pd["week"] else 0
                rows.append({"roster_id": rid, "matchup_id": mid + 1, "points": pts})
        matchups[str(w)] = rows
    return {
        "league": {"league_id": "demo-nba", "name": "Demo Hoops League", "season": "demo", "total_rosters": n_teams,
                   "roster_positions": slots, "scoring_settings": DEMO_LEAGUE_SCORING,
                   "settings": {"playoff_week_start": reg_weeks + 1, "playoff_teams": 6, "start_week": 1}},
        "users": users, "rosters": roster_objs, "matchups": matchups, "me": "u0",
    }


def history(pd: dict, season: int, seed: int = 13) -> dict:
    rng = random.Random(seed)
    out: dict = {}
    for sid, p in pd["players"].items():
        years = min(4, (p.get("b") or {}).get("exp", 0))
        for y in range(season - years, season):
            log = []
            day = date(y, 10, 22)
            for _ in range(rng.randint(55, 78)):
                day += timedelta(days=rng.choice([1, 2, 2, 3]))
                log.append([day.isoformat()[5:], rng.choice(TEAMS)] + _line(rng, p["p"], rng.uniform(15, 50), False))
            out.setdefault(str(y), {})[sid] = {"log": log, "rank": rng.randint(1, 300)}
            p.setdefault("hs", {})[str(y)] = out[str(y)][sid]["rank"]
    return out
