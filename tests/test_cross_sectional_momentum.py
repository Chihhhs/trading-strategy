import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.strategies import build_execution_plan, get_strategy_definition, overlapping_momentum_weights


class CrossSectionalMomentumTest(unittest.TestCase):
    def test_execution_plan_rounds_to_lot_size_and_enforces_minimum_notional(self):
        plan = build_execution_plan(
            {"BTC": 0.5, "SMALL": 0.005},
            equity=1000.0,
            prices={"BTC": 60_000.0, "SMALL": 1.0},
            sz_decimals={"BTC": 5, "SMALL": 2},
        )
        self.assertEqual(plan["orders"][0]["coin"], "BTC")
        self.assertEqual(plan["orders"][0]["size"], 0.00833)
        self.assertFalse(plan["feasible"])
        self.assertEqual(plan["blockers"], [{"coin": "SMALL", "reason": "below_minimum_notional", "notional": 5.0}])

    def test_execution_plan_closes_positions_removed_from_target(self):
        plan = build_execution_plan(
            {},
            equity=1000.0,
            prices={"BTC": 60_000.0},
            sz_decimals={"BTC": 5},
            current_sizes={"BTC": 0.001},
        )
        self.assertEqual(plan["orders"][0]["side"], "sell")
        self.assertEqual(plan["orders"][0]["target_size"], 0.0)

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

    def test_isolated_paper_state_initializes_and_resumes_idempotently(self):
        from trading_strategy.backtest.overlapping_momentum import OverlappingMomentumBacktester

        parameters = get_strategy_definition("cross_sectional_momentum").parse_parameters({})
        interval = 4 * 3_600_000
        data = {
            f"C{coin}": [
                {"time": index * interval, "close": 100.0 + coin * index}
                for index in range(130)
            ]
            for coin in range(1, 7)
        }
        latest = 129 * interval
        funding = {coin: [{"time": latest - 3_600_000, "funding_rate": 0.0}] for coin in data}
        runner = OverlappingMomentumBacktester(
            fee_bps=4.5,
            slippage_bps=2.0,
            parameters=parameters,
            funding_data=funding,
        )
        first = runner.advance_paper(data, sz_decimals={coin: 3 for coin in data})
        second = runner.advance_paper(
            data,
            sz_decimals={coin: 3 for coin in data},
            portfolio_state=first["portfolio"],
        )
        self.assertTrue(first["initialized"])
        self.assertGreater(first["bars_processed"], 0)
        self.assertFalse(second["initialized"])
        self.assertEqual(second["bars_processed"], 0)
        self.assertEqual(second["portfolio"], first["portfolio"])


if __name__ == "__main__":
    unittest.main()
