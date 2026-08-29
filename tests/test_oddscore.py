"""Unit tests for oddscore.py. Standard library only:

    python3 -m unittest discover -s tests -v

The parlay-math vectors are copied verbatim from the inline self-test
of https://parlay-api.com/tools/parlay-calculator so the bot can never
drift from the site calculator.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oddscore as oc


class TestAmericanToDecimal(unittest.TestCase):
    def test_canonical(self):
        self.assertAlmostEqual(oc.american_to_decimal(100), 2.0)
        self.assertAlmostEqual(oc.american_to_decimal(-110), 21 / 11)
        self.assertAlmostEqual(oc.american_to_decimal(-200), 1.5)
        self.assertAlmostEqual(oc.american_to_decimal(150), 2.5)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            oc.american_to_decimal(0)
        with self.assertRaises(ValueError):
            oc.american_to_decimal("nope")
        with self.assertRaises(ValueError):
            oc.american_to_decimal(float("inf"))

    def test_sub_100_magnitudes_do_not_exist(self):
        # Mirrors the site calculator's self-test: a2d(+50), a2d(-99),
        # and a2d(0) are all NaN there, because American prices between
        # -100 and +100 (exclusive) do not exist. +100 and -100 are the
        # boundary and stay valid.
        for bad in (50, -99, 99, -1):
            with self.assertRaises(ValueError, msg=bad):
                oc.american_to_decimal(bad)
        self.assertAlmostEqual(oc.american_to_decimal(-100), 2.0)
        self.assertAlmostEqual(oc.american_to_decimal(100), 2.0)


class TestCalculatorVectors(unittest.TestCase):
    """The seven vectors from the site calculator's self-test."""

    def test_v1_two_dash_110(self):
        d = oc.combined_decimal([oc.american_to_decimal(-110)] * 2)
        self.assertAlmostEqual(d, 3.6446280991735537, places=9)
        self.assertAlmostEqual(oc.parlay_payout(100, d), 364.46280991735534, places=6)
        self.assertAlmostEqual(oc.parlay_profit(100, d), 264.46280991735534, places=6)
        self.assertAlmostEqual(oc.combined_implied_prob(d), 0.27437641723356004, places=9)

    def test_v2_three_evens(self):
        d = oc.combined_decimal([2, 2, 2])
        self.assertEqual(d, 8.0)
        self.assertEqual(oc.parlay_payout(100, d), 800.0)
        self.assertEqual(oc.parlay_profit(100, d), 700.0)
        self.assertEqual(oc.combined_implied_prob(d), 0.125)

    def test_v3_plus150_minus200(self):
        d = oc.combined_decimal([oc.american_to_decimal(150),
                                 oc.american_to_decimal(-200)])
        self.assertAlmostEqual(d, 3.75)
        self.assertAlmostEqual(oc.parlay_payout(50, d), 187.5)
        self.assertAlmostEqual(oc.parlay_profit(50, d), 137.5)
        self.assertAlmostEqual(oc.combined_implied_prob(d), 0.26666666666666666, places=9)

    def test_v4_decimal_legs(self):
        d = oc.combined_decimal([1.5, 2.0, 3.0])
        self.assertAlmostEqual(d, 9.0, places=9)
        self.assertAlmostEqual(oc.parlay_payout(20, d), 180.0, places=9)
        self.assertAlmostEqual(oc.parlay_profit(20, d), 160.0, places=9)
        self.assertAlmostEqual(oc.combined_implied_prob(d), 0.1111111111111111, places=9)

    def test_v5_three_dash_110(self):
        d = oc.combined_decimal([oc.american_to_decimal(-110)] * 3)
        self.assertAlmostEqual(d, 6.957926371240581, places=9)
        self.assertAlmostEqual(oc.parlay_payout(100, d), 695.7926371240581, places=6)
        self.assertAlmostEqual(oc.parlay_profit(100, d), 595.7926371240581, places=6)
        self.assertAlmostEqual(oc.combined_implied_prob(d), 0.1437209804556743, places=9)

    def test_v6_plus200_plus300(self):
        d = oc.combined_decimal([oc.american_to_decimal(200),
                                 oc.american_to_decimal(300)])
        self.assertEqual(d, 12.0)
        self.assertEqual(oc.parlay_payout(25, d), 300.0)
        self.assertEqual(oc.parlay_profit(25, d), 275.0)
        self.assertAlmostEqual(oc.combined_implied_prob(d), 0.08333333333333333, places=9)

    def test_v7_mixed_four_legs(self):
        d = oc.combined_decimal([oc.american_to_decimal(-110),
                                 oc.american_to_decimal(120),
                                 oc.american_to_decimal(-150),
                                 oc.american_to_decimal(200)])
        self.assertAlmostEqual(d, 21.0, places=9)
        self.assertAlmostEqual(oc.parlay_payout(10, d), 210.0, places=9)
        self.assertAlmostEqual(oc.parlay_profit(10, d), 200.0, places=9)
        self.assertAlmostEqual(oc.combined_implied_prob(d), 0.047619047619047616, places=9)


class TestDecimalToAmerican(unittest.TestCase):
    def test_three_dash_110_is_plus_596(self):
        # The canonical sanity check from the task and the site FAQ.
        d = oc.combined_decimal([oc.american_to_decimal(-110)] * 3)
        self.assertEqual(oc.decimal_to_american(d), 596)

    def test_round_trip_simple(self):
        self.assertEqual(oc.decimal_to_american(2.0), 100)
        self.assertEqual(oc.decimal_to_american(2.5), 150)
        self.assertEqual(oc.decimal_to_american(1.5), -200)
        self.assertEqual(oc.decimal_to_american(12.0), 1100)

    def test_js_round_half_toward_plus_infinity(self):
        # JS Math.round(2.5) == 3 and Math.round(-2.5) == -2. Python's
        # built-in round() would give 2 and -2. The site uses JS.
        self.assertEqual(oc.js_round(2.5), 3)
        self.assertEqual(oc.js_round(-2.5), -2)
        self.assertEqual(oc.js_round(595.7926371240581), 596)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            oc.decimal_to_american(1.0)
        with self.assertRaises(ValueError):
            oc.decimal_to_american(0.5)


class TestCombinedDecimal(unittest.TestCase):
    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            oc.combined_decimal([])

    def test_bad_leg_raises(self):
        with self.assertRaises(ValueError):
            oc.combined_decimal([2.0, 1.0])
        with self.assertRaises(ValueError):
            oc.combined_decimal([2.0, 0.9])


class TestParsePrices(unittest.TestCase):
    def test_commas_and_spaces(self):
        self.assertEqual(oc.parse_american_prices("-110, -110, +150"),
                         [-110, -110, 150])
        self.assertEqual(oc.parse_american_prices("-110 -110 150"),
                         [-110, -110, 150])

    def test_rejects_junk(self):
        for bad in ("", "abc", "-110, x", "0", "-110, 0",
                    "50", "-99", "-110, +50"):
            with self.assertRaises(ValueError, msg=bad):
                oc.parse_american_prices(bad)

    def test_boundary_100_accepted(self):
        self.assertEqual(oc.parse_american_prices("+100, -100"), [100, -100])

    def test_max_legs(self):
        ok = ",".join(["-110"] * oc.MAX_PARLAY_LEGS)
        self.assertEqual(len(oc.parse_american_prices(ok)), oc.MAX_PARLAY_LEGS)
        too_many = ",".join(["-110"] * (oc.MAX_PARLAY_LEGS + 1))
        with self.assertRaises(ValueError):
            oc.parse_american_prices(too_many)


class TestFormatting(unittest.TestCase):
    def test_fmt_american(self):
        self.assertEqual(oc.fmt_american(-110), "-110")
        self.assertEqual(oc.fmt_american(150), "+150")
        self.assertEqual(oc.fmt_american(None), "?")

    def test_fmt_points(self):
        self.assertEqual(oc.fmt_point(-2.5), "-2.5")
        self.assertEqual(oc.fmt_point(7), "+7")
        self.assertEqual(oc.fmt_total_point(224.5), "224.5")
        self.assertEqual(oc.fmt_total_point(47.0), "47")

    def test_fmt_prob_and_money(self):
        self.assertEqual(oc.fmt_prob(0.27437641723356004), "27.4%")
        self.assertEqual(oc.fmt_money(364.46280991735534), "$364.46")


SAMPLE_EVENT = {
    "home_team": "Detroit Pistons",
    "away_team": "Boston Celtics",
    "commence_time": "2026-10-20T19:00:00Z",
    "bookmakers": [
        {"key": "fanduel", "title": "FanDuel", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Detroit Pistons", "price": -120},
                {"name": "Boston Celtics", "price": 102}]}]},
        {"key": "draftkings", "title": "DraftKings", "markets": [
            {"key": "h2h", "outcomes": [
                {"name": "Detroit Pistons", "price": -125},
                {"name": "Boston Celtics", "price": 105}]},
            {"key": "spreads", "outcomes": [
                {"name": "Detroit Pistons", "price": -110, "point": 2.5},
                {"name": "Boston Celtics", "price": -110, "point": -2.5}]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "price": -108, "point": 224.5},
                {"name": "Under", "price": -112, "point": 224.5}]}]},
    ],
}


class TestMatchEvents(unittest.TestCase):
    def test_single_team(self):
        self.assertEqual(len(oc.match_events([SAMPLE_EVENT], "celtics")), 1)
        self.assertEqual(len(oc.match_events([SAMPLE_EVENT], "PISTONS")), 1)
        self.assertEqual(len(oc.match_events([SAMPLE_EVENT], "knicks")), 0)

    def test_matchup(self):
        for q in ("celtics vs pistons", "pistons vs. celtics",
                  "celtics @ pistons", "celtics at pistons"):
            self.assertEqual(len(oc.match_events([SAMPLE_EVENT], q)), 1, q)
        self.assertEqual(len(oc.match_events([SAMPLE_EVENT], "celtics vs knicks")), 0)

    def test_empty_query_returns_all(self):
        self.assertEqual(len(oc.match_events([SAMPLE_EVENT], "")), 1)


class TestEmbedBuilders(unittest.TestCase):
    def test_odds_embed(self):
        p = oc.build_odds_embed(SAMPLE_EVENT)
        self.assertEqual(p["title"], "Boston Celtics @ Detroit Pistons")
        self.assertEqual(p["footer"], "via ParlayAPI")
        self.assertEqual(p["url"], "https://parlay-api.com")
        self.assertIn("FanDuel", p["description"])
        self.assertIn("+102", p["description"])
        self.assertIn("-120", p["description"])
        # Best row: away best +105 (DK), home best -120 (FD)
        best_line = [l for l in p["description"].splitlines() if l.startswith("Best")][0]
        self.assertIn("+105", best_line)
        self.assertIn("-120", best_line)

    def test_odds_embed_demo_notice(self):
        p = oc.build_odds_embed(SAMPLE_EVENT, demo_notice="Keyless demo data.")
        self.assertIn("Keyless demo data.", p["description"])
        self.assertIn(oc.SIGNUP_URL, p["description"])

    def test_line_embed(self):
        p = oc.build_line_embed(SAMPLE_EVENT)
        self.assertIn("DraftKings", p["description"])
        self.assertIn("+2.5 -110", p["description"])        # home spread
        self.assertIn("224.5 -108/-112", p["description"])  # total O/U
        # FanDuel has no spreads/totals market, so it is not listed.
        self.assertNotIn("FanDuel", p["description"])

    def test_moves_embed(self):
        movers = [{
            "sport_key": "americanfootball_nfl",
            "home_team": "Buffalo Bills", "away_team": "Kansas City Chiefs",
            "home_ml_first": -140, "home_ml_last": -205,
            "away_ml_first": 120, "away_ml_last": 170,
            "abs_max_prob_delta_pp": 8.88,
        }]
        p = oc.build_moves_embed(movers, "americanfootball_nfl", 60)
        self.assertIn("Kansas City Chiefs @ Buffalo Bills", p["description"])
        self.assertIn("-140 to -205", p["description"])
        self.assertIn("8.9pp", p["description"])

    def test_moves_embed_empty(self):
        p = oc.build_moves_embed([], None, 60)
        self.assertIn("No market has moved", p["description"])

    def test_parlaycheck_embed(self):
        p = oc.build_parlaycheck_embed([-110, -110, -110], stake=100.0)
        self.assertIn("+596", p["description"])
        self.assertIn("6.96", p["description"])
        self.assertIn("14.4%", p["description"])
        self.assertIn("$695.79", p["description"])
        self.assertIn("$595.79", p["description"])
        self.assertIn("not betting advice", p["description"])

    def test_try_envelope_events_key(self):
        # /v1/try nests events under an "events" key; make sure the
        # extraction convention stays stable.
        envelope = {"demo": True, "events_returned": 1, "events": [SAMPLE_EVENT]}
        events = envelope.get("events", [])
        self.assertEqual(len(oc.match_events(events, "celtics")), 1)


if __name__ == "__main__":
    unittest.main()
