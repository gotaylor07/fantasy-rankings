import unittest

from rankings import yahoo


def team(key, name, nick, mine=False, roster=None, points=None):
    meta = [{"team_key": key}, {"team_id": key[-1]}, {"name": name}, [],
            {"is_owned_by_current_login": 1} if mine else {},
            {"managers": [{"manager": {"manager_id": key[-1], "nickname": nick, "guid": "G" + key[-1]}}]}]
    extra = {}
    if roster is not None:
        players = {str(i): {"player": [[{"player_key": f"p{i}"}, {"name": {"full": n}}, {"editorial_team_abbr": abbr},
                                        {"primary_position": pos}],
                                       {"selected_position": [{"coverage_type": "week"}, {"position": slot}]}]}
                   for i, (n, pos, abbr, slot) in enumerate(roster)}
        players["count"] = len(roster)
        extra["roster"] = {"coverage_type": "week", "0": {"players": players}}
    if points is not None:
        extra["team_points"] = {"coverage_type": "week", "total": str(points)}
    return {"team": [meta, extra]}


SETTINGS = {"fantasy_content": {"league": [
    {"league_key": "449.l.1", "name": "Yahoo Test", "season": "2026", "start_week": "1", "end_week": "17", "current_week": "2"},
    {"settings": [{"uses_playoff": "1", "playoff_start_week": "3", "num_playoff_teams": "4",
                   "roster_positions": [{"roster_position": {"position": "QB", "count": 1}},
                                        {"roster_position": {"position": "WR", "count": 2}},
                                        {"roster_position": {"position": "W/R/T", "count": 1}},
                                        {"roster_position": {"position": "DEF", "count": 1}},
                                        {"roster_position": {"position": "BN", "count": 2}}]}]}]}}

TEAMS = {"fantasy_content": {"league": [{"league_key": "449.l.1"}, {"teams": {
    "0": team("449.l.1.t.1", "Mine", "me", mine=True, roster=[
        ("Josh Allen", "QB", "Buf", "QB"), ("Puka Nacua", "WR", "LAR", "WR"), ("Nobody Known", "WR", "NYJ", "WR"),
        ("Bijan Robinson", "RB", "Atl", "W/R/T"), ("Seattle", "DEF", "Sea", "DEF"), ("Bench Guy", "RB", "Chi", "BN")]),
    "1": team("449.l.1.t.2", "Theirs", "them", roster=[("Ja'Marr Chase", "WR", "Cin", "WR")]),
    "count": 2}}]}}


def scoreboard(week, a, b):
    return {"fantasy_content": {"league": [{"league_key": "449.l.1"}, {"scoreboard": {"week": str(week), "0": {"matchups": {
        "0": {"matchup": {"week": str(week), "0": {"teams": {"0": team("449.l.1.t.1", "Mine", "me", points=a),
                                                             "1": team("449.l.1.t.2", "Theirs", "them", points=b),
                                                             "count": 2}}}},
        "count": 1}}}}]}}


IDS = {"josh allen|QB": "17", "puka nacua|WR": "9493", "bijan robinson|RB": "9509", "jamarr chase|WR": "7564",
       "bench guy|RB": "1"}


class YahooTests(unittest.TestCase):
    def setUp(self):
        sid_of = yahoo.football_ids({"keys": IDS, "players": {"SEA": {}}})
        self.b = yahoo.to_bundle(SETTINGS, TEAMS, {1: scoreboard(1, 101.5, 99), 2: scoreboard(2, 0, 0)}, sid_of)

    def test_lineup_slots_use_the_pages_names(self):
        self.assertEqual(self.b["league"]["roster_positions"], ["QB", "WR", "WR", "FLEX", "DEF", "BN", "BN"])
        self.assertEqual(self.b["league"]["settings"]["playoff_week_start"], 3)

    def test_rosters_starters_and_owner(self):
        mine = self.b["rosters"][0]
        self.assertEqual(mine["players"], ["17", "9493", "9509", "SEA", "1"])   # the unknown player is left out
        self.assertEqual(mine["starters"], ["17", "9493", "0", "9509", "SEA"])  # his WR slot shows as empty
        self.assertEqual(self.b["me"], "G1")
        self.assertEqual(self.b["users"][1]["metadata"]["team_name"], "Theirs")
        self.assertEqual(self.b["unmatched"], 1)

    def test_weekly_scores(self):
        self.assertEqual(self.b["matchups"]["1"], [{"roster_id": 1, "matchup_id": 1, "points": 101.5},
                                                  {"roster_id": 2, "matchup_id": 1, "points": 99.0}])
        self.assertEqual([r["points"] for r in self.b["matchups"]["2"]], [0.0, 0.0])

    def test_flat_merges_yahoos_lists(self):
        self.assertEqual(yahoo.flat([{"a": 1}, [], [{"b": 2}]]), {"a": 1, "b": 2})


if __name__ == "__main__":
    unittest.main()
