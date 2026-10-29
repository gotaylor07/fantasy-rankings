"""Render the rankings JSON into one self-contained HTML page (open it straight from disk)."""
from __future__ import annotations

import json
from pathlib import Path

from .aggregate import ALIASES, SUFFIXES

TEMPLATE_FILE = Path(__file__).resolve().parent / "template.html"


def render(data: dict, out_path: Path, history: dict | None = None) -> Path:
    """Write the page, plus <name>.history.js with past seasons' game logs.

    The history file is several MB, so the page only loads it when a player popup
    first opens. Returns the history file's path.
    """
    history_path = out_path.with_name(out_path.stem + ".history.js")
    # The page re-implements norm_name to match ESPN roster names, so it needs the same tables.
    page_data = dict(data, names={"aliases": ALIASES, "suffixes": sorted(SUFFIXES)}, history_file=history_path.name)
    payload = json.dumps(page_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(template.replace("__DATA__", payload), encoding="utf-8")
    if history is not None:
        js = json.dumps(history, ensure_ascii=False, separators=(",", ":"))
        history_path.write_text(f"window.PLAYER_HISTORY = {js};\n", encoding="utf-8")
    return history_path


def render_seasons(out_path: Path, seasons: dict) -> dict:
    """One <name>.<season>.js file per past season (basketball logs are too big for one file).

    Each file adds its season to window.SEASON_HISTORY; the page loads a file when its tab opens.
    Returns {season: file name}.
    """
    files = {}
    for season, players in seasons.items():
        path = out_path.with_name(f"{out_path.stem}.{season}.js")
        js = json.dumps(players, ensure_ascii=False, separators=(",", ":"))
        path.write_text(f"(window.SEASON_HISTORY = window.SEASON_HISTORY || {{}})[{json.dumps(season)}] = {js};\n",
                        encoding="utf-8")
        files[season] = path.name
    return files
