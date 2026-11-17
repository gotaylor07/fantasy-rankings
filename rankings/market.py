"""Player trade values over time, for the Market tab.

No source publishes a cheap day-by-day value history, so the site keeps its own: every update
adds today's value for each player. The history is written next to the page as
<page>.market.js (loaded when the Market tab opens) and kept in data/ between runs. If data/ is
missing (GitHub's cache was cleared), the last published copy is read back from the live site.

Football values are FantasyCalc's trade values (redraft and dynasty); FantasyCalc's 30-day trend
gives each player one earlier point, so charts have a shape from the first day. Basketball has no
trade market, so its value comes from the consensus rest-of-season ranking.
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

from .sources import TIMEOUT, USER_AGENT, fantasycalc_raw

SITE_URL = "https://gotaylor07.github.io/fantasy-rankings/"
KEEP_DAYS = 400


def _empty() -> dict:
    return {"dates": [], "series": {}}


def load(data_path: Path, published_name: str) -> dict:
    """The kept history: data/ first, else the copy published with the live site."""
    try:
        if data_path.exists():
            return json.loads(data_path.read_text())
    except (OSError, ValueError):
        pass
    try:
        text = requests.get(SITE_URL + published_name, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT).text
        m = re.match(r"\s*window\.MARKET\s*=\s*(\{.*\});?\s*$", text, re.S)
        if m:
            return json.loads(m.group(1))["history"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return {}


def add_day(history: dict, kind: str, day: date, values: dict, earlier: dict | None = None) -> dict:
    """Record today's values for one kind ("redraft", "dynasty", "site").

    history[kind] = {"dates": [...], "series": {player id: [value or None per date]}}. Re-running on the
    same day replaces that day. `earlier` ({player id: (date, value)}) seeds one older point for players
    whose history doesn't reach back that far yet.
    """
    h = history.setdefault(kind, _empty())
    dates, series = h["dates"], h["series"]

    def column(d: str) -> int:
        if d in dates:
            return dates.index(d)
        at = sum(1 for x in dates if x < d)
        dates.insert(at, d)
        for vals in series.values():
            vals.insert(at, None)
        return at

    for sid, (d, value) in (earlier or {}).items():
        if value is None or value <= 0:
            continue
        known = series.get(sid)
        if known and any(v is not None for v in known[: sum(1 for x in dates if x <= d.isoformat())]):
            continue   # real history already reaches back that far
        i = column(d.isoformat())
        series.setdefault(sid, [None] * len(dates))[i] = round(value)

    i = column(day.isoformat())
    for sid, value in values.items():
        if value is None:
            continue
        series.setdefault(sid, [None] * len(dates))[i] = round(value)

    # Keep the last KEEP_DAYS days, and drop players with nothing left.
    cut = (day - timedelta(days=KEEP_DAYS)).isoformat()
    drop = sum(1 for d in dates if d < cut)
    if drop:
        del dates[:drop]
        for sid in list(series):
            del series[sid][:drop]
    for sid in [s for s, vals in series.items() if all(v is None for v in vals)]:
        del series[sid]
    return history


def football_values(day: date) -> dict:
    """{kind: (values, earlier)} from FantasyCalc, redraft and dynasty, keyed by Sleeper id."""
    out = {}
    for kind, dynasty in (("redraft", False), ("dynasty", True)):
        values, earlier = {}, {}
        for e in fantasycalc_raw(dynasty):
            p = e.get("player") or {}
            sid = p.get("sleeperId")
            if not sid or p.get("position") == "PICK" or not e.get("value"):
                continue
            values[str(sid)] = e["value"]
            if e.get("trend30Day") is not None:
                earlier[str(sid)] = (day - timedelta(days=30), e["value"] - e["trend30Day"])
        out[kind] = (values, earlier)
    return out


def rank_values(ranked_ids: list) -> dict:
    """A value from a ranking, best first: falls off steeply like a trade market (top player 10,000)."""
    return {sid: round(10000 * math.exp(-i / 60)) for i, sid in enumerate(ranked_ids)}


def demo_history(day: date, base: dict, kind: str, seed: int = 21, days: int = 90) -> dict:
    """A made-up random walk ending at today's values, so the demo page has charts to look at."""
    rng = random.Random(seed)
    h = {kind: _empty()}
    dates = [(day - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    h[kind]["dates"] = dates
    for sid, end in base.items():
        drift = rng.gauss(0, 0.004)
        walk = [float(end)]
        for _ in range(days - 1):
            walk.append(walk[-1] / (1 + drift + rng.gauss(0, 0.02)))
        h[kind]["series"][sid] = [round(v) for v in reversed(walk)]
    return h


def write(out_path: Path, history: dict, labels: dict) -> str:
    """Write <page>.market.js next to the page; returns its file name."""
    path = out_path.with_name(out_path.stem + ".market.js")
    path.parent.mkdir(parents=True, exist_ok=True)   # written before the page, so site/ may not exist yet
    js = json.dumps({"history": history, "labels": labels}, separators=(",", ":"))
    path.write_text(f"window.MARKET = {js};\n", encoding="utf-8")
    return path.name


def build(site_file: Path, data_dir: Path, today: date, demo: bool, current: dict, labels: dict) -> str:
    """Add today to the kept history and write <page>.market.js. Returns its file name.

    current: {kind: callable returning (values, earlier)}; for the demo page only its values are used,
    to make up a history.
    """
    published = site_file.stem + ".market.js"
    if demo:
        history = {}
        for i, (kind, fetch) in enumerate(current.items()):
            history.update(demo_history(today, fetch()[0], kind, seed=21 + i))
        return write(site_file, history, labels)
    path = data_dir / f"market-{site_file.stem}.json"
    history = load(path, published)
    for kind, fetch in current.items():
        try:
            values, earlier = fetch()
            add_day(history, kind, today, values, earlier)
            print(f"  ok   market   {kind:<12}  {len(values)} players, {len(history[kind]['dates'])} days kept")
        except Exception as exc:
            print(f"  FAIL market   {kind} {type(exc).__name__}: {exc}", file=sys.stderr)
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, separators=(",", ":")))
    return write(site_file, history, labels)
