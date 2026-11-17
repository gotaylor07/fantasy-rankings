import unittest
from datetime import date

from rankings import market


class HistoryTests(unittest.TestCase):
    def test_days_append_and_rerun_replaces(self):
        h = {}
        market.add_day(h, "redraft", date(2026, 11, 1), {"a": 100})
        market.add_day(h, "redraft", date(2026, 11, 2), {"a": 110, "b": 50})
        market.add_day(h, "redraft", date(2026, 11, 2), {"a": 120, "b": 50})
        self.assertEqual(h["redraft"]["dates"], ["2026-11-01", "2026-11-02"])
        self.assertEqual(h["redraft"]["series"], {"a": [100, 120], "b": [None, 50]})

    def test_earlier_point_seeds_only_missing_history(self):
        h = {}
        today = date(2026, 11, 30)
        market.add_day(h, "redraft", today, {"a": 100}, {"a": (date(2026, 10, 31), 80)})
        self.assertEqual(h["redraft"]["dates"], ["2026-10-31", "2026-11-30"])
        self.assertEqual(h["redraft"]["series"]["a"], [80, 100])
        # a later run doesn't overwrite real history with another seed
        market.add_day(h, "redraft", date(2026, 12, 1), {"a": 105}, {"a": (date(2026, 11, 1), 1)})
        self.assertNotIn("2026-11-01", h["redraft"]["dates"])

    def test_old_days_are_dropped(self):
        h = {}
        market.add_day(h, "site", date(2025, 1, 1), {"a": 1})
        market.add_day(h, "site", date(2026, 11, 1), {"b": 2})
        self.assertEqual(h["site"]["dates"], ["2026-11-01"])
        self.assertEqual(h["site"]["series"], {"b": [2]})

    def test_rank_values_fall_off(self):
        v = market.rank_values(["x", "y", "z"])
        self.assertEqual(v["x"], 10000)
        self.assertGreater(v["y"], v["z"])


if __name__ == "__main__":
    unittest.main()
