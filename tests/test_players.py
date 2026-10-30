import unittest
from unittest import mock

from rankings import demo, leagues, players

META = {
    "1": {"position": "WR", "full_name": "Ja'Marr Chase", "team": "CIN", "espn_id": 4362628},
    "2": {"position": "RB", "full_name": "Bijan Robinson", "team": "ATL", "injury_status": "Questionable"},
    "3": {"position": "WR", "full_name": "Injured Guy", "team": "NYJ"},
    "CIN": {"position": "DEF", "first_name": "Cincinnati", "last_name": "Bengals", "team": "CIN"},
    "9": {"position": "LB", "full_name": "Not Fantasy", "team": "CIN"},
}


def stat(pid, team, opp, player=None, **st):
    return {"player_id": pid, "team": team, "opponent": opp, "stats": st, "player": player}


def fake_stats(season, week):
    rows = [stat("9", "CIN", "BAL", gp=1, pts_ppr=3)]
    rows += [stat(f"x{i}", f"X{i}", "", gp=1) for i in range(20)]  # > 20 teams so byes are detected
    if week == 1:
        rows += [
            stat("1", "CIN", "BAL", gp=1, pts_ppr=21.4, off_snp=60, tm_off_snp=66, rec_tgt=11, rec=8, rec_yd=94, rec_td=1),
            stat("2", "ATL", "TB", gp=1, pts_ppr=18, off_snp=40, tm_off_snp=62, rush_att=19, rush_yd=88),
            stat("CIN", "CIN", "BAL", gp=1, pts_ppr=7),
        ]
    if week == 2:  # ATL on bye, Chase inactive
        rows += [stat("1", "CIN", "PIT", gms_active=0), stat("CIN", "CIN", "PIT", gp=1, pts_ppr=4)]
    return rows


def fake_proj(season, week):
    teams = ["CIN", "ATL"] + [f"X{i}" for i in range(20)]  # > 20 teams so byes are detected
    rows = [{"player_id": f"x{t}", "team": t, "stats": {"pts_ppr": 1}} for t in teams if not (week == 3 and t == "CIN")]
    if week == 3:
        rows.append({"player_id": "2", "team": "ATL", "stats": {"pts_ppr": 15.25}})
    return tuple(rows)


class BuildTests(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(players, "sleeper_players", return_value=META),
            mock.patch.object(players, "sleeper_stats", side_effect=fake_stats),
            mock.patch.object(players, "sleeper_projections", side_effect=fake_proj),
            mock.patch.object(players, "LAST_WEEK", 3),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.data = players.build(2026, 3)

    def test_game_log_rows(self):
        chase = self.data["players"]["1"]
        self.assertEqual(len(chase["log"]), 1)  # inactive week 2 left out
        g = chase["log"][0]
        F = {f: i + 4 for i, f in enumerate(self.data["fields"])}
        self.assertEqual(g[:4], [1, "BAL", 21.4, 91])
        self.assertEqual((g[F["rec_tgt"]], g[F["rec"]], g[F["rec_yd"]]), (11, 8, 94))

    def test_positions_and_names(self):
        P = self.data["players"]
        self.assertNotIn("9", P)  # IDP players are skipped
        self.assertEqual(P["CIN"]["n"], "Cincinnati Bengals D/ST")
        self.assertIsNone(P["CIN"]["log"][0][3])  # no snap share for a defense
        self.assertEqual(P["2"]["i"], "Questionable")
        self.assertEqual(P["2"]["proj"], {"3": 15.2})

    def test_byes_from_box_scores_and_projections(self):
        self.assertEqual(self.data["byes"]["ATL"], 2)
        self.assertEqual(self.data["byes"]["CIN"], 3)

    def test_lookups(self):
        self.assertEqual(self.data["keys"]["jamarr chase|WR"], "1")
        self.assertEqual(self.data["espn_ids"], {"4362628": "1"})

    def test_attach_ids(self):
        types = {"dynasty": {"rankings": {"WR": [{"name": "Ja'Marr Chase"}, {"name": "Injured Guy"}, {"name": "Nobody"}]}}}
        players.attach_ids(types, self.data, META)
        rows = types["dynasty"]["rankings"]["WR"]
        self.assertEqual(rows[0]["sid"], "1")
        self.assertEqual(rows[1]["sid"], "3")  # found in the Sleeper file, given an empty log
        self.assertEqual(self.data["players"]["3"]["log"], [])
        self.assertNotIn("sid", rows[2])


class EspnTrimTests(unittest.TestCase):
    def test_keeps_page_fields_and_drops_the_rest(self):
        raw = {
            "id": 7, "seasonId": 2026, "scoringPeriodId": 8,
            "settings": {"name": "L", "rosterSettings": {"lineupSlotCounts": {"0": 1}, "x": 1},
                         "scheduleSettings": {"matchupPeriodCount": 14, "playoffTeamCount": 6, "y": 2}},
            "members": [{"id": "{A}", "displayName": "a", "email": "secret@example.com"}],
            "teams": [{"id": 1, "name": "T", "owners": ["{A}"], "roster": {"entries": [
                {"playerId": 5, "lineupSlotId": 0, "playerPoolEntry": {"player": {
                    "fullName": "Q B", "defaultPositionId": 1, "proTeamId": 3, "injuryStatus": "ACTIVE", "stats": [1, 2]}}}]}}],
            "schedule": [{"matchupPeriodId": 1, "winner": "HOME", "home": {"teamId": 1, "totalPoints": 100, "rosterForMatchupPeriod": {}},
                          "away": {"teamId": 2, "totalPoints": 90}}],
        }
        t = leagues.trim_espn(raw)
        self.assertNotIn("email", t["members"][0])
        self.assertNotIn("stats", t["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"])
        self.assertEqual(t["settings"]["scheduleSettings"]["playoffTeamCount"], 6)
        self.assertEqual(t["schedule"][0]["home"], {"teamId": 1, "totalPoints": 100})

    def test_config_team_lookup_and_errors(self):
        data = {"teams": [{"id": 1, "owners": ["{A}"]}, {"id": 2, "owners": ["{B}"]}]}
        cfg = {"espn": [{"league_id": "11", "swid": "{B}", "espn_s2": "x"}, {"league_id": "12"}]}

        def fetch(league_id, season, s2, swid, game="ffl"):
            if league_id == "12":
                raise PermissionError("private")
            return data

        with mock.patch.object(leagues, "fetch_espn", side_effect=fetch):
            out = leagues.fetch_configured(cfg, 2026)
        self.assertEqual(out[0]["my_team"], 2)
        self.assertNotIn("swid", out[0])  # cookies never reach the page
        self.assertIn("PermissionError", out[1]["error"])


class DemoTests(unittest.TestCase):
    def test_demo_league_is_consistent(self):
        pd = demo.players(8)
        lg = demo.league(pd, 8)
        ids = {r["roster_id"] for r in lg["rosters"]}
        for w, rows in lg["matchups"].items():
            self.assertEqual({r["roster_id"] for r in rows}, ids)
            self.assertEqual(all(r["points"] > 0 for r in rows), int(w) < 8)
        for r in lg["rosters"]:
            self.assertTrue(set(r["starters"]) <= set(r["players"]))
            self.assertTrue(all(s in pd["players"] for s in r["players"]))


if __name__ == "__main__":
    unittest.main()


class KickerDefenseTests(unittest.TestCase):
    def test_defense_names_match_across_sources(self):
        from rankings.sources import def_name, sleeper_name
        self.assertEqual(def_name("Chicago Bears"), "Chicago Bears D/ST")
        self.assertEqual(def_name("Chicago Bears DST"), "Chicago Bears D/ST")
        self.assertEqual(sleeper_name(META["CIN"]), def_name("Cincinnati Bengals"))

    def test_fantasypros_urls(self):
        from rankings.sources import _fp_url
        self.assertTrue(_fp_url("week", "K").endswith("/k.php"))
        self.assertTrue(_fp_url("ros", "DEF").endswith("/ros-dst.php"))
        self.assertTrue(_fp_url("week", "RB").endswith("/ppr-rb.php"))

    def test_aggregate_keeps_kickers(self):
        from rankings.aggregate import aggregate
        rows = [{"name": n, "pos": "K", "team": "X", "rank": i} for i, n in enumerate(["A K", "B K"], 1)]
        out = aggregate({"S1": rows, "S2": list(reversed(rows))})
        self.assertEqual(len(out["K"]), 2)
        self.assertEqual(out["DEF"], [])


class CollegeTests(unittest.TestCase):
    def test_one_name_per_school(self):
        self.assertEqual(players.bio({"college": "North Carolina State"})["col"], "NC State")
        self.assertEqual(players.bio({"college": "NC State"})["col"], "NC State")
        self.assertEqual(players.bio({"college": "Clemson"})["col"], "Clemson")


class HistoryTests(unittest.TestCase):
    def test_season_is_ranked_and_cached(self):
        import tempfile
        from pathlib import Path
        from rankings import history

        def fetch(season, week):
            return [
                stat("1", "CIN", "BAL", gp=1, pts_ppr=20, rec_tgt=9, player={"position": "WR"}),
                stat("3", "NYJ", "MIA", gp=1, pts_ppr=5, player={"position": "WR"}),
                stat("9", "CIN", "BAL", gp=1, pts_ppr=9, player={"position": "LB"}),
            ]

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(history, "HISTORY_DIR", Path(tmp)):
            data = history.load_season(2020, fetch)
            self.assertEqual(len(data["logs"]["1"]), 17)  # 17-week season before 2021
            self.assertEqual((data["ranks"]["1"], data["ranks"]["3"]), ("WR1", "WR2"))
            self.assertNotIn("9", data["logs"])
            # Second load comes from the cache: a fetch that fails proves it isn't called.
            again = history.load_season(2020, lambda s, w: 1 / 0)
            self.assertEqual(again["ranks"], data["ranks"])

    def test_failed_week_is_not_cached(self):
        import tempfile
        from pathlib import Path
        from rankings import history

        def flaky(season, week):
            if week == 9:
                raise ConnectionError("down")
            return []

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(history, "HISTORY_DIR", Path(tmp)):
            with self.assertRaises(ConnectionError):
                history.load_season(2022, flaky)
            self.assertFalse((Path(tmp) / "2022.json").exists())


class OwnershipTests(unittest.TestCase):
    def test_matches_by_espn_id_name_and_team(self):
        data = {"players": {"1": {}, "2": {}, "CIN": {}}, "espn_ids": {"4362628": "1"},
                "keys": {"bijan robinson|RB": "2"}}
        rows = [
            {"name": "Ja'Marr Chase", "pos": "WR", "team": "CIN", "espn_id": 4362628, "owned": 99.9, "started": 98.0},
            {"name": "Bijan Robinson", "pos": "RB", "team": "ATL", "espn_id": 1, "owned": 99.8, "started": 97.1},
            {"name": "Bengals D/ST", "pos": "DEF", "team": "CIN", "espn_id": -16004, "owned": 40.0, "started": 20.0},
            {"name": "Nobody", "pos": "WR", "team": "", "espn_id": 2, "owned": 0.1, "started": 0.0},
        ]
        self.assertEqual(players.attach_ownership(data, rows), 3)
        self.assertEqual(data["players"]["1"]["own"], [99.9, 98.0])
        self.assertEqual(data["players"]["CIN"]["own"], [40.0, 20.0])


class EspnLoginTests(unittest.TestCase):
    def test_save_merges_and_refreshes_cookies(self):
        import json, os, stat, tempfile
        from pathlib import Path
        from rankings import espn_login
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leagues.json"
            path.write_text(json.dumps({"espn": [{"league_id": "11", "espn_s2": "old", "swid": "{OLD}"}]}))
            espn_login.save(path, {"espn_s2": "new", "swid": "{NEW}"}, ["11", "22"])
            cfg = json.loads(path.read_text())
            self.assertEqual([e["league_id"] for e in cfg["espn"]], ["11", "22"])
            self.assertTrue(all(e["espn_s2"] == "new" and e["swid"] == "{NEW}" for e in cfg["espn"]))
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_choose(self):
        from rankings import espn_login
        leagues = [{"league_id": "11", "name": "A"}, {"league_id": "22", "name": "B"}]
        leagues = [dict(lg, sport="football") for lg in leagues]
        with mock.patch("builtins.input", return_value=""), mock.patch("builtins.print"):
            self.assertEqual(espn_login.choose(leagues, set()), [("11", "football"), ("22", "football")])
        with mock.patch("builtins.input", return_value="2, 9"), mock.patch("builtins.print"):
            self.assertEqual(espn_login.choose(leagues, set()), [("22", "football")])
        with mock.patch("builtins.input", side_effect=["12345", "basketball"]):
            self.assertEqual(espn_login.choose([], set()), [("12345", "basketball")])

    def test_find_leagues_reads_football_entries(self):
        from rankings import espn_login
        body = {"preferences": [
            {"metaData": {"entry": {"gameId": 1, "seasonId": 2026, "groups": [{"groupId": 777, "groupName": "Work League"}]}}},
            {"metaData": {"entry": {"gameId": 2, "groups": [{"groupId": 888, "groupName": "Baseball"}]}}},
            {"metaData": {"entry": {"gameId": 3, "seasonId": 2027, "groups": [{"groupId": 999, "groupName": "Hoops"}]}}},
        ]}
        resp = mock.Mock(); resp.json.return_value = body; resp.raise_for_status.return_value = None
        with mock.patch.object(espn_login.requests, "get", return_value=resp):
            self.assertEqual(espn_login.find_leagues({"espn_s2": "x", "swid": "{A}"}),
                             [{"league_id": "777", "name": "Work League", "season": 2026, "sport": "football"},
                              {"league_id": "999", "name": "Hoops", "season": 2027, "sport": "basketball"}])
