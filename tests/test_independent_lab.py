import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.independent_lab import (
    Candidate,
    _aligned_funding,
    evaluate,
    fetch_current_daily_fixture,
    fetch_hyperliquid_funding_fixture,
    search,
)


def fixture():
    data = {}
    for coin, slope in (("UP", 1.0), ("FLAT", 0.0), ("DOWN", -0.3)):
        data[coin] = [
            {"time": day, "close": max(100.0 + slope * day, 1.0)}
            for day in range(180)
        ]
    return data


class IndependentLabTest(unittest.TestCase):
    def test_fixed_fixture_fetch_preserves_manifest_universe(self):
        coins = ("BTC", "ETH", "SOL", "SUI", "KBONK")
        universe = [
            {"name": "kBONK" if coin == "KBONK" else coin, "szDecimals": 2}
            for coin in coins
        ]
        contexts = [{"dayNtlVlm": str(index + 1)} for index in range(len(coins))]
        candle = [{"t": 1, "o": "1", "h": "1", "l": "1", "c": "1", "v": "1"}]
        with tempfile.TemporaryDirectory() as directory, patch(
            "trading_strategy.backtest.independent_lab._post",
            side_effect=[({"universe": universe}, contexts)] + [candle] * len(coins),
        ):
            payload = fetch_current_daily_fixture(
                Path(directory) / "fixture.json",
                coins=coins,
                min_bars=1,
            )
        self.assertEqual(payload["selection"]["rule"], "fixed manifest universe")
        self.assertEqual(tuple(payload["data"]), ("BTC", "ETH", "SOL", "SUI", "kBONK"))

    def test_funding_fetch_resumes_completed_coin_when_candles_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candles = root / "candles.json"
            candles.write_text(json.dumps({"data": {"BTC": [{"time": 0}, {"time": 100}]}}), encoding="utf-8")
            manifest = root / "funding.json"
            data_dir = root / "funding"
            data_dir.mkdir()
            (data_dir / "BTC.json").write_text(
                json.dumps([{"time": 50, "funding_rate": 0.0, "premium": 0.0}]),
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps({"completed_coins": ["BTC"], "data_directory": str(data_dir)}),
                encoding="utf-8",
            )
            with patch(
                "trading_strategy.backtest.independent_lab._post",
                return_value=[{"time": 75, "fundingRate": "0.001", "premium": "0"}],
            ) as post:
                fetch_hyperliquid_funding_fixture(candles, manifest, page_pause_seconds=0)
            rows = json.loads((data_dir / "BTC.json").read_text(encoding="utf-8"))
        post.assert_called_once()
        self.assertEqual(rows[-1]["time"], 75)

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
