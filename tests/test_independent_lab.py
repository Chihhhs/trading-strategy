import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.independent_lab import Candidate, _aligned_funding, evaluate, search


def fixture():
    data = {}
    for coin, slope in (("UP", 1.0), ("FLAT", 0.0), ("DOWN", -0.3)):
        data[coin] = [
            {"time": day, "close": max(100.0 + slope * day, 1.0)}
            for day in range(180)
        ]
    return data


class IndependentLabTest(unittest.TestCase):
    def test_rotation_uses_prior_data_and_profits_from_persistent_strength(self):
        candidate = Candidate("rotation", "rotation", lookback=20, rebalance_days=7, top_n=1)
        result = evaluate(candidate, fixture(), start_index=40, end_index=160)
        self.assertGreater(result.net_pnl_pct, 0.0)
        self.assertEqual(set(result.coin_contributions), {"UP"})

    def test_costs_reduce_net_return(self):
        candidate = Candidate("rotation", "rotation", lookback=20, rebalance_days=7, top_n=1)
        free = evaluate(candidate, fixture(), start_index=40, end_index=160, one_way_cost_bps=0.0)
        costed = evaluate(candidate, fixture(), start_index=40, end_index=160, one_way_cost_bps=20.0)
        self.assertLess(costed.net_pnl_pct, free.net_pnl_pct)

    def test_positive_funding_costs_long_positions_and_benefits_shorts(self):
        long_candidate = Candidate("rotation", "rotation", lookback=20, rebalance_days=7, top_n=1)
        short_candidate = Candidate("reversal", "reversal_long_short", lookback=20, rebalance_days=7, top_n=1)
        data = fixture()
        aligned_funding = {coin: [0.001] * 180 for coin in data}
        long_free = evaluate(long_candidate, data, start_index=40, end_index=80, one_way_cost_bps=0.0)
        long_funded = evaluate(
            long_candidate,
            data,
            start_index=40,
            end_index=80,
            one_way_cost_bps=0.0,
            aligned_funding=aligned_funding,
        )
        short_free = evaluate(short_candidate, data, start_index=40, end_index=80, one_way_cost_bps=0.0)
        short_funded = evaluate(
            short_candidate,
            data,
            start_index=40,
            end_index=80,
            one_way_cost_bps=0.0,
            aligned_funding=aligned_funding,
        )
        self.assertLess(long_funded.net_pnl_pct, long_free.net_pnl_pct)
        self.assertAlmostEqual(short_funded.net_pnl_pct, short_free.net_pnl_pct, places=10)

    def test_hourly_funding_is_aggregated_into_causal_bar_interval(self):
        hour = 3_600_000
        aligned = _aligned_funding(
            [0, 4 * hour, 8 * hour],
            ("BTC",),
            {"BTC": [{"time": hour, "funding_rate": 0.001}, {"time": 4 * hour, "funding_rate": 0.002}]},
        )
        self.assertEqual(aligned["BTC"], [0.0, 0.003, 0.0])

    def test_search_keeps_holdout_locked_by_default(self):
        result = search(
            fixture(),
            holdout_days=30,
            fold_days=30,
            candidates=(Candidate("rotation", "rotation", lookback=20, rebalance_days=7, top_n=1),),
        )
        self.assertFalse(result["holdout_unlocked"])
        self.assertIsNone(result["holdout"])

    def test_market_neutral_reversal_can_profit_when_leaders_reverse(self):
        data = {
            "WINNER": [{"time": day, "close": 100 + day if day < 60 else 220 - day} for day in range(120)],
            "LOSER": [{"time": day, "close": 200 - day if day < 60 else 80 + day} for day in range(120)],
            "FLAT_A": [{"time": day, "close": 100.0} for day in range(120)],
            "FLAT_B": [{"time": day, "close": 100.0} for day in range(120)],
        }
        candidate = Candidate("reversal", "reversal_long_short", lookback=30, rebalance_days=7, top_n=1)
        result = evaluate(candidate, data, start_index=61, end_index=68)
        self.assertGreater(result.net_pnl_pct, 0.0)

    def test_overlapping_reversal_averages_staggered_cohorts(self):
        candidate = Candidate(
            "overlap",
            "overlapping_reversal_long_short",
            lookback=20,
            rebalance_days=1,
            top_n=1,
            overlap_cohorts=3,
            cohort_spacing=1,
        )
        result = evaluate(candidate, fixture(), start_index=30, end_index=80)
        self.assertGreater(result.turnover, 0.0)
        self.assertGreater(result.changed_legs, 0)

    def test_overlapping_momentum_profits_from_persistent_strength(self):
        candidate = Candidate(
            "overlap-momentum",
            "overlapping_momentum_long_short",
            lookback=20,
            rebalance_days=1,
            top_n=1,
            overlap_cohorts=3,
            cohort_spacing=1,
        )
        result = evaluate(candidate, fixture(), start_index=30, end_index=80)
        self.assertGreater(result.net_pnl_pct, 0.0)
        self.assertGreater(result.coin_contributions["UP"], 0.0)


if __name__ == "__main__":
    unittest.main()
