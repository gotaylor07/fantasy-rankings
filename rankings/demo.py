"""Synthetic data so the pipeline and site can be exercised without network access.

Names are deliberately fake ("Demo RB 07") so nobody mistakes this for real rankings.
"""
from __future__ import annotations

import random

from .aggregate import LIMITS

POOL = {"QB": 44, "RB": 84, "WR": 110, "TE": 44}
# Kickers and defenses: ranked for the week and rest of season only, like the live boards.
KD_POOL = {"K": 16, "DEF": 12}

DEMO_SOURCES = {
    "week": ["Sleeper", "FantasyPros"],
    "ros": ["Sleeper", "FantasyPros", "FantasyCalc"],
    "dynasty": ["FantasyCalc", "KeepTradeCut", "FantasyPros"],
}

RANK_BASED = {"FantasyPros"}


def generate(seed: int = 7) -> dict:
    rng = random.Random(seed)
    out: dict = {}
    for kind, sources in DEMO_SOURCES.items():
        out[kind] = {}
        for source in sources:
            rows = []
            pool = POOL if kind == "dynasty" else dict(POOL, **KD_POOL)
            for pos, count in pool.items():
                scored = []
                for i in range(1, count + 1):
                    if rng.random() < 0.06:  # source doesn't list this player
                        continue
                    strength = 320 / (i + 4)
                    noisy = strength * rng.uniform(0.75, 1.25)
                    scored.append((i, noisy))
                scored.sort(key=lambda t: -t[1])
                for rank, (i, noisy) in enumerate(scored, 1):
                    if pos == "DEF":
                        row = {"name": f"Demo T{i:02d} D/ST", "pos": pos, "team": f"T{i:02d}"}
                    else:
                        row = {"name": f"Demo {pos} {i:02d}", "pos": pos, "team": f"T{(i % 12) + 1:02d}"}
                    if source in RANK_BASED:
                        row["rank"] = rank
                    else:
                        row["score"] = round(noisy, 2)
                    rows.append(row)
            out[kind][source] = rows
    return out


assert all(LIMITS[p] <= POOL[p] for p in POOL)


# --------------------------------------------------------------------------
# Player game logs / projections and a demo league for the "My league" tab
# --------------------------------------------------------------------------

DEMO_TEAMS = [f"T{i:02d}" for i in range(1, 13)]
LAST_WEEK = 18


def _demo_line(rng: random.Random, pos: str, pts: float) -> dict:
    """Plausible-looking box score for a given point total."""
    z = {f: 0 for f in ("pass_cmp", "pass_att", "pass_yd", "pass_td", "pass_int",
                        "rush_att", "rush_yd", "rush_td", "rec_tgt", "rec", "rec_yd", "rec_td")}
    if pos == "QB":
        z.update(pass_att=rng.randint(26, 42), pass_td=int(pts // 7), pass_int=rng.randint(0, 2),
                 rush_att=rng.randint(1, 8), rush_yd=rng.randint(0, 45))
        z.update(pass_cmp=int(z["pass_att"] * rng.uniform(0.58, 0.72)), pass_yd=int(pts * 12))
    elif pos == "RB":
        z.update(rush_att=rng.randint(8, 24), rush_yd=int(pts * 4), rush_td=int(pts // 14),
                 rec_tgt=rng.randint(1, 7))
        z.update(rec=max(0, z["rec_tgt"] - rng.randint(0, 2)), rec_yd=rng.randint(0, 40))
    elif pos in ("WR", "TE"):
        z.update(rec_tgt=max(1, int(pts / 2.2) + rng.randint(-1, 2)), rec_td=int(pts // 13))
        z.update(rec=max(0, z["rec_tgt"] - rng.randint(0, 3)), rec_yd=int(pts * 5))
    return z


def players(week: int, seed: int = 11) -> dict:
    """Same shape as rankings.players.build(), for the demo players."""
    from .players import LOG_FIELDS, player_key

    rng = random.Random(seed)
    byes = {t: 5 + i for i, t in enumerate(DEMO_TEAMS)}
    pool = dict(POOL, **KD_POOL)
    base = {"QB": 24, "RB": 20, "WR": 19, "TE": 14, "K": 9, "DEF": 8}
    out: dict = {}
    for pos, count in pool.items():
        for i in range(1, count + 1):
            team = DEMO_TEAMS[i - 1] if pos == "DEF" else f"T{(i % 12) + 1:02d}"
            sid = team if pos == "DEF" else f"demo-{pos}-{i:02d}"
            name = f"Demo {team} D/ST" if pos == "DEF" else f"Demo {pos} {i:02d}"
            mean = base[pos] * (1.15 - 0.85 * (i - 1) / count)
            log = []
            for w in range(1, week):
                if byes[team] == w or rng.random() < 0.05:
                    continue
                pts = round(max(0.0, rng.gauss(mean, mean * 0.4)), 1)
                snap = None if pos in ("K", "DEF") else int(min(100, max(20, rng.gauss(85 - i, 10))))
                line = _demo_line(rng, pos, pts)
                log.append([w, rng.choice([t for t in DEMO_TEAMS if t != team]), pts, snap]
                           + [line[f] for f in LOG_FIELDS])
            proj = {str(w): round(mean * rng.uniform(0.85, 1.15), 1)
                    for w in range(week, LAST_WEEK + 1) if byes[team] != w}
            injury = rng.choice(["Questionable", "Out", "IR"]) if rng.random() < 0.06 else None
            out[sid] = {"n": name, "p": pos, "t": team, "i": injury, "proj": proj, "log": log}
            if injury:
                back = {"Questionable": 0, "Out": 7, "IR": 35}[injury]
                out[sid]["inj"] = {"s": injury, "ret": f"2026-11-{min(28, 1 + back):02d}" if back < 30 else "2026-12-06",
                                   "type": rng.choice(["Hamstring", "Ankle", "Knee"]), "upd": "2026-10-28",
                                   "note": "Demo note: limited participant at practice Wednesday." if injury == "Questionable" else "",
                                   "play": rng.choice([55, 70, 85]) if injury == "Questionable" else 0}
            if pos != "DEF":
                out[sid]["b"] = {"bd": f"{rng.randint(1990, 2003)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                                 "ht": str(rng.randint(68, 78)), "wt": str(rng.randint(180, 250)),
                                 "col": "Demo State", "exp": rng.randint(0, 9), "num": rng.randint(1, 99)}
            owned = round(max(0.0, min(100.0, 105 - 2.2 * i + rng.uniform(-8, 8))), 1)
            out[sid]["own"] = [owned, round(owned * rng.uniform(0.3, 0.95), 1)]
    games: dict = {}
    for w in range(week, LAST_WEEK + 1):
        teams = [t for t in DEMO_TEAMS if byes[t] != w]
        rng.shuffle(teams)
        for a, b in zip(teams[::2], teams[1::2]):
            games.setdefault(a, {})[str(w)] = [b, None]
            games.setdefault(b, {})[str(w)] = [a, None]
    return {
        "games": games,
        "fields": LOG_FIELDS,
        "players": out,
        "keys": {player_key(p["n"], p["p"]): sid for sid, p in out.items()},
        "espn_ids": {},
        "byes": byes,
        "failed": [],
    }


def league(player_data: dict, week: int, seed: int = 5) -> dict:
    """A 10-team demo league in the shape of Sleeper's API responses."""
    rng = random.Random(seed)
    P = player_data["players"]
    n_teams, reg_weeks = 10, 14
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"] + ["BN"] * 6

    def avg_proj(sid):
        proj = P[sid]["proj"].values()
        return sum(proj) / max(1, len(proj))

    by_pos = {pos: sorted([s for s, p in P.items() if p["p"] == pos], key=lambda s: -avg_proj(s))
              for pos in ("QB", "RB", "WR", "TE", "K", "DEF")}
    need = {"QB": 2, "RB": 5, "WR": 5, "TE": 1, "K": 1, "DEF": 1}
    rosters = [[] for _ in range(n_teams)]
    for pos, k in need.items():
        for r in range(k):
            order = range(n_teams) if r % 2 == 0 else reversed(range(n_teams))
            for t in order:
                if by_pos[pos]:
                    rosters[t].append(by_pos[pos].pop(rng.randrange(min(3, len(by_pos[pos])))))

    def starters_for(roster):
        """A plausible but not always optimal lineup, so the suggestions have something to fix."""
        picks, left = [], list(roster)
        for slot in slots:
            if slot == "BN":
                continue
            ok = [s for s in left if P[s]["p"] in ({"RB", "WR", "TE"} if slot == "FLEX" else {slot})]
            ok.sort(key=lambda s: -(avg_proj(s) * rng.uniform(0.8, 1.2)))
            if ok:
                picks.append(ok[0])
                left.remove(ok[0])
        return picks

    names = ["Gridiron Gurus", "Waiver Wire Warriors", "Fourth and Long", "End Zone Elite",
             "Blitz Brigade", "Hail Mary Heroes", "Red Zone Rebels", "Pocket Passers",
             "Turf Toes", "Two Point Conversion"]
    users = [{"user_id": f"u{i}", "display_name": "you" if i == 0 else f"manager{i}",
              "metadata": {"team_name": names[i]}} for i in range(n_teams)]
    roster_objs = [{"roster_id": i + 1, "owner_id": f"u{i}", "players": r, "starters": starters_for(r),
                    "settings": {}} for i, r in enumerate(rosters)]

    # Round-robin schedule; completed weeks scored from the demo game logs.
    teams = list(range(1, n_teams + 1))
    matchups = {}
    for w in range(1, reg_weeks + 1):
        rot = teams[:1] + teams[1:][(w - 1) % (n_teams - 1):] + teams[1:][: (w - 1) % (n_teams - 1)]
        pairs = [(rot[i], rot[-1 - i]) for i in range(n_teams // 2)]
        week_rows = []
        for mid, (a, b) in enumerate(pairs, 1):
            for rid in (a, b):
                pts = 0.0
                if w < week:
                    ro = roster_objs[rid - 1]
                    for sid in starters_for(ro["players"]):
                        pts += next((g[2] for g in P[sid]["log"] if g[0] == w), 0)
                week_rows.append({"roster_id": rid, "matchup_id": mid, "points": round(pts, 2)})
        matchups[str(w)] = week_rows

    return {
        "league": {"league_id": "demo", "name": "Demo League", "season": "demo", "total_rosters": n_teams,
                   "roster_positions": slots,
                   "settings": {"playoff_week_start": reg_weeks + 1, "playoff_teams": 4, "start_week": 1}},
        "users": users,
        "rosters": roster_objs,
        "matchups": matchups,
        "me": "u0",
    }


def history(player_data: dict, season: int, seed: int = 13) -> dict:
    """Past seasons for the demo players, same shape as rankings.history.build()."""
    from .players import LOG_FIELDS

    rng = random.Random(seed)
    seasons: dict = {}
    for sid, p in player_data["players"].items():
        years = (p.get("b") or {}).get("exp", rng.randint(0, 6))
        for y in range(season - years, season):
            games = []
            for w in range(1, 18):
                if rng.random() < 0.12:
                    continue
                pts = round(max(0.0, rng.gauss(12, 6)), 1)
                line = _demo_line(rng, p["p"], pts)
                snap = None if p["p"] in ("K", "DEF") else rng.randint(40, 95)
                games.append([w, rng.choice(DEMO_TEAMS), pts, snap] + [line[f] for f in LOG_FIELDS])
            seasons.setdefault(sid, {})[str(y)] = {"log": games, "rank": f"{p['p']}{rng.randint(1, 60)}"}
    return {"fields": LOG_FIELDS, "seasons": seasons, "failed": []}
