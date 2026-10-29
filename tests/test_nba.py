import unittest
from datetime import date
from unittest import mock

from rankings import leagues
from rankings.aggregate import aggregate
from rankings.nba import build as nb
from rankings.nba import demo


class ScoringTests(unittest.TestCase):
    def test_espn_standard_points(self):
        line = nb.line_of({"min": 34, "pts": 30, "reb": 10, "ast": 5, "stl": 2, "blk": 1, "to": 3,
                           "tpm": 3, "fgm": 11, "fga": 20, "ftm": 5, "fta": 6})
        # 30 + 3 + 22 - 20 + 5 - 6 + 10 + 10 + 8 + 4 - 6
        self.assertEqual(nb.fantasy_points(line), 60)

    def test_double_doubles_and_seconds(self):
        line = dict(zip(nb.FIELDS, nb.line_of({"sp": 1800, "pts": 12, "reb": 11, "ast": 10})))
        self.assertEqual((line["min"], line["dd"], line["td"]), (30, 1, 1))
        # projections keep Sleeper's own (fractional) double-double odds
        proj = dict(zip(nb.FIELDS, nb.line_of({"pts": 12, "reb": 11, "dd": 0.4}, projected=True)))
        self.assertEqual(proj["dd"], 0.4)

    def test_threes_from_misses(self):
        line = dict(zip(nb.FIELDS, nb.line_of({"min": 20, "tpa": 7, "tpmi": 4})))
        self.assertEqual(line["tpm"], 3)


class CalendarTests(unittest.TestCase):
    def test_weeks_run_monday_to_sunday(self):
        games = [{"date": "2026-10-20", "week": 1, "home": {"team": "DET"}, "away": {"team": "CHI"}},
                 {"date": "2026-10-27", "week": 2, "home": {"team": "CHI"}, "away": {"team": "BOS"}}]
        with mock.patch.object(nb, "schedule", return_value=tuple(games)):
            cal = nb.calendar(2099)
        self.assertEqual(cal["weeks"]["1"], ["2026-10-19", "2026-10-25"])
        self.assertEqual(cal["games"]["CHI"], [["2026-10-20", "DET", 0], ["2026-10-27", "BOS", 1]])
        self.assertEqual(nb.current_week(cal, date(2026, 10, 26)), 2)


class InjuryTests(unittest.TestCase):
    def test_chance_to_play(self):
        self.assertEqual(nb.chance_to_play("DTD", "", None, None), 55)
        self.assertEqual(nb.chance_to_play("DTD", "He's expected to play Friday.", None, None), 85)
        self.assertEqual(nb.chance_to_play("Questionable", "He will miss Friday's game.", None, None), 1)
        self.assertEqual(nb.chance_to_play("DTD", "", "2026-11-05", "2026-11-01"), 5)
        self.assertEqual(nb.chance_to_play("Out", "", None, None), 0)


class HistoryTests(unittest.TestCase):
    def test_team_totals_are_not_ranked(self):
        logs = {"1658": [["10-22", "OKC"] + nb.line_of({"min": 35, "pts": 30, "reb": 12, "ast": 10})],
                "TEAM_DEN": [["10-22", "OKC"] + nb.line_of({"min": 240, "pts": 120, "reb": 45, "ast": 30})]}
        out = nb._ranked(logs)
        self.assertEqual(out["ranks"], {"1658": 1})


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 28)
        self.pd = demo.players(self.today)

    def test_boards_cover_every_position(self):
        src = demo.boards(self.pd, self.today)
        for kind, sources in src.items():
            out = aggregate({k: f() for k, f in sources.items()}, nb.LIMITS, nb.BOARD_POSITIONS)
            self.assertTrue(all(out[p] for p in nb.BOARD_POSITIONS), kind)

    def test_demo_league(self):
        lg = demo.league(self.pd, self.today)
        ids = {r["roster_id"] for r in lg["rosters"]}
        for w, rows in lg["matchups"].items():
            self.assertEqual({r["roster_id"] for r in rows}, ids)
            self.assertEqual(all(r["points"] > 0 for r in rows), int(w) < self.pd["week"])
        self.assertTrue(all(s in self.pd["players"] for r in lg["rosters"] for s in r["players"]))


class ConfigTests(unittest.TestCase):
    def test_leagues_are_split_by_sport(self):
        cfg = {"espn": [{"league_id": "1"}, {"league_id": "2", "sport": "basketball"}]}
        calls = []

        def fetch(league_id, season, s2, swid, game):
            calls.append((league_id, season, game))
            return {"teams": []}

        with mock.patch.object(leagues, "fetch_espn", side_effect=fetch), mock.patch("builtins.print"):
            leagues.fetch_configured(cfg, 2026, "basketball", 2027)
            leagues.fetch_configured(cfg, 2026)
        self.assertEqual(calls, [("2", 2027, "fba"), ("1", 2026, "ffl")])


if __name__ == "__main__":
    unittest.main()
