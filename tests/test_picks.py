import unittest
from unittest import mock

from rankings import picks


class ParseTests(unittest.TestCase):
    def test_both_market_formats(self):
        self.assertEqual(picks.parse_pick("2027 1st (Early)"), ("2027", 1, "early"))
        self.assertEqual(picks.parse_pick("2028 2nd"), ("2028", 2, None))
        self.assertEqual(picks.parse_pick("2029 Late 3rd"), ("2029", 3, "late"))
        self.assertIsNone(picks.parse_pick("Jahmyr Gibbs"))


class ValueTests(unittest.TestCase):
    def test_two_mid_assets_are_worth_less_than_a_star(self):
        self.assertLess(2 * picks.trade_value(5000), picks.trade_value(10000))

    def test_football_blends_both_markets_on_one_scale(self):
        fc = ({"value": 10000, "player": {"name": "Star", "position": "RB", "sleeperId": "1"}},
              {"value": 5000, "player": {"name": "2027 1st (Early)", "position": "PICK"}},
              {"value": 4000, "player": {"name": "2027 1st", "position": "PICK"}},
              {"value": 3000, "player": {"name": "2028 1st", "position": "PICK"}})
        ktc = ({"playerName": "Star", "position": "RB", "oneQBValues": {"value": 5000}},
               {"playerName": "2027 Early 1st", "position": "RDP", "oneQBValues": {"value": 3000}})
        with mock.patch.object(picks, "fantasycalc_raw", return_value=fc), mock.patch.object(picks, "ktc_players", return_value=ktc):
            out = picks.football({"star|RB": "1"})
        self.assertEqual(out["players"]["1"], 10000)                 # each market's top player scales to 10,000
        self.assertEqual(out["picks"]["2027"]["1"]["early"], picks.trade_value(5500))   # 5,000 and 6,000 averaged
        self.assertEqual(out["picks"]["2027"]["1"]["mid"], picks.trade_value(4000))     # generic price fills the other tiers
        self.assertEqual(out["picks"]["2028"]["1"]["late"], picks.trade_value(3000))
        self.assertFalse(out["estimated"])

    def test_estimate_discounts_later_years_and_orders_tiers(self):
        out = picks.estimate(["a", "b"], 2026)
        self.assertTrue(out["estimated"])
        self.assertGreater(out["players"]["a"], out["players"]["b"])
        first = out["picks"]["2027"]["1"]
        self.assertGreater(first["early"], first["mid"])
        self.assertGreater(first["mid"], first["late"])
        self.assertLess(out["picks"]["2028"]["1"]["mid"], first["mid"])
        self.assertLess(out["picks"]["2027"]["2"]["early"], first["late"])


if __name__ == "__main__":
    unittest.main()
