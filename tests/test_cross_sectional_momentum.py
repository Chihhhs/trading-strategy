import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.strategies import get_strategy_definition, overlapping_momentum_weights


class CrossSectionalMomentumTest(unittest.TestCase):
    def test_registry_exposes_locked_portfolio_parameters(self):
        definition = get_strategy_definition("cross_sectional_momentum")
        parameters = definition.parse_parameters({})
        self.assertEqual(parameters.timeframe, "4h")
        self.assertEqual(parameters.lookback_bars, 84)
        self.assertEqual(parameters.overlap_cohorts, 7)
        self.assertEqual(parameters.rebalance_hour_utc, 0)
        self.assertIn("market_neutral", definition.capabilities)

    def test_target_is_market_neutral_and_uses_only_prior_bars(self):
        closes = {
            f"C{coin}": [100.0 + coin * index for index in range(20)]
            for coin in range(1, 7)
        }
        before = overlapping_momentum_weights(
            closes,
            index=15,
            lookback_bars=5,
            top_n=2,
            overlap_cohorts=3,
            cohort_spacing_bars=2,
        )
        closes["C1"][19] = 1_000_000.0
        after = overlapping_momentum_weights(
            closes,
            index=15,
            lookback_bars=5,
            top_n=2,
            overlap_cohorts=3,
            cohort_spacing_bars=2,
        )
        self.assertEqual(before, after)
        self.assertAlmostEqual(sum(before.values()), 0.0)
        self.assertAlmostEqual(sum(abs(weight) for weight in before.values()), 1.0)

    def test_manifest_adapter_reproduces_locked_holdout(self):
        from trading_strategy.experiments import BacktestExperimentAdapter, load_experiment

        spec = load_experiment(Path(ROOT) / "experiments" / "cross_sectional_momentum_4h.json")
        result = BacktestExperimentAdapter().run(spec)[0]
        self.assertAlmostEqual(result.net_pnl_pct, 15.419487512379959)
        self.assertAlmostEqual(result.max_drawdown_pct, 7.5670947728549045)
        self.assertEqual(result.trades, 593)

    def test_shadow_snapshot_uses_fixed_midnight_utc_anchor(self):
        from apps.runners.momentum_shadow_runner import build_snapshot

        snapshot = build_snapshot(Path(ROOT) / "data" / "clean_room" / "hyperliquid_4h_current.json")
        source = datetime.fromtimestamp(snapshot["source_bar_time"] / 1000, timezone.utc)
        self.assertEqual(source.hour, 0)
        self.assertLessEqual(snapshot["source_bar_time"], snapshot["market_data_time"])
        self.assertFalse(snapshot["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
