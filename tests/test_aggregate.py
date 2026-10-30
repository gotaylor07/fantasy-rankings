import unittest
from datetime import date

from rankings.aggregate import aggregate, kickoff, norm_name, position_ranks, upcoming_week


def rows(pos, names, key):
    """names listed best-first; key is 'rank' or 'score'."""
    out = []
    for i, n in enumerate(names, 1):
        row = {"name": n, "pos": pos, "team": "XX"}
        if key == "rank":
            row["rank"] = i
        else:
            row["score"] = 100 - i
        out.append(row)
    return out


class NameTests(unittest.TestCase):
    def test_suffixes_and_punctuation(self):
        self.assertEqual(norm_name("Kenneth Walker III"), norm_name("Kenneth Walker"))
        self.assertEqual(norm_name("Amon-Ra St. Brown"), norm_name("Amon-Ra St Brown"))
        self.assertEqual(norm_name("D'Andre Swift"), norm_name("DAndre Swift"))
        self.assertEqual(norm_name("Marvin Harrison Jr."), "marvin harrison")

    def test_alias(self):
        self.assertEqual(norm_name("Hollywood Brown"), norm_name("Marquise Brown"))


class RankTests(unittest.TestCase):
    def test_score_and_rank_sources_agree(self):
        by_score = position_ranks(rows("RB", ["A One", "B Two", "C Three"], "score"))
        by_rank = position_ranks(rows("RB", ["A One", "B Two", "C Three"], "rank"))
        self.assertEqual({k: v[0] for k, v in by_score.items()}, {k: v[0] for k, v in by_rank.items()})

    def test_ranks_are_per_position(self):
        mixed = rows("RB", ["R One"], "score") + rows("WR", ["W One"], "score")
        ranks = position_ranks(mixed)
        self.assertEqual(ranks[(norm_name("R One"), "RB")][0], 1)
        self.assertEqual(ranks[(norm_name("W One"), "WR")][0], 1)


class AggregateTests(unittest.TestCase):
    def test_average_and_order(self):
        src = {
            "S1": rows("RB", ["Alpha", "Bravo", "Charlie"], "score"),
            "S2": rows("RB", ["Bravo", "Alpha", "Charlie"], "rank"),
            "S3": rows("RB", ["Alpha", "Charlie", "Bravo"], "score"),
        }
        rb = aggregate(src)["RB"]
        by_name = {r["name"]: r for r in rb}
        self.assertAlmostEqual(by_name["Alpha"]["avg"], (1 + 2 + 1) / 3, places=2)
        self.assertAlmostEqual(by_name["Bravo"]["avg"], (2 + 1 + 3) / 3, places=2)
        self.assertAlmostEqual(by_name["Charlie"]["avg"], (3 + 3 + 2) / 3, places=2)
        self.assertEqual([r["name"] for r in rb], ["Alpha", "Bravo", "Charlie"])
        self.assertEqual([r["rank"] for r in rb], [1, 2, 3])

    def test_name_variants_merge(self):
        src = {
            "S1": rows("WR", ["Marvin Harrison Jr."], "score"),
            "S2": rows("WR", ["Marvin Harrison"], "rank"),
        }
        wr = aggregate(src)["WR"]
        self.assertEqual(len(wr), 1)
        self.assertEqual(wr[0]["n"], 2)

    def test_single_source_player_excluded_when_multiple_sources(self):
        src = {
            "S1": rows("TE", ["Alpha", "Solo"], "score"),
            "S2": rows("TE", ["Alpha"], "score"),
        }
        names = [r["name"] for r in aggregate(src)["TE"]]
        self.assertEqual(names, ["Alpha"])

    def test_one_surviving_source_still_ranks(self):
        src = {"S1": rows("QB", ["Alpha", "Bravo"], "score"), "S2": []}
        self.assertEqual([r["name"] for r in aggregate(src)["QB"]], ["Alpha", "Bravo"])

    def test_no_sources(self):
        self.assertEqual(aggregate({"S1": []}), {})


class CalendarTests(unittest.TestCase):
    def test_kickoff_2026(self):
        self.assertEqual(kickoff(2026), date(2026, 9, 10))

    def test_upcoming_week(self):
        self.assertEqual(upcoming_week(date(2026, 9, 1), 2026), 1)
        self.assertEqual(upcoming_week(date(2026, 9, 15), 2026), 2)  # Tuesday after Week 1
        self.assertEqual(upcoming_week(date(2026, 10, 27), 2026), 8)  # Tuesday after Week 7
        self.assertEqual(upcoming_week(date(2026, 10, 28), 2026), 8)
        self.assertEqual(upcoming_week(date(2026, 10, 30), 2026), 8)  # Friday: Week 8's Sunday games are still ahead
        self.assertEqual(upcoming_week(date(2026, 11, 2), 2026), 8)  # Monday night
        self.assertEqual(upcoming_week(date(2026, 11, 3), 2026), 9)  # Tuesday morning switches
        self.assertEqual(upcoming_week(date(2027, 1, 20), 2026), 18)


if __name__ == "__main__":
    unittest.main()
