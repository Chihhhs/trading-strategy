import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.core.exit_policy import build_exit_policy
from trading_strategy.positions import build_position_snapshot, build_position_status_counts
from trading_strategy.strategies import available_strategy_names, resolve_strategy
from trading_strategy.strategies.base import StrategyContext


def build_bar(close_price, index, *, volume=1000):
    return {
        "time": f"2026-01-{index + 1:02d}T00:00:00",
        "open": close_price,
        "high": close_price + 0.5,
        "low": close_price - 0.5,
        "close": close_price,
        "volume": volume,
    }


class StrategyModulesTest(unittest.TestCase):
    def test_resolve_strategy_returns_trend(self):
        strategy = resolve_strategy("trend")
        self.assertEqual(strategy.name, "trend")

    def test_resolve_strategy_returns_intraday_momentum(self):
        self.assertIn("intraday_momentum", available_strategy_names())
        strategy = resolve_strategy("intraday_momentum")
        self.assertEqual(strategy.name, "intraday_momentum")

    def test_resolve_strategy_rejects_unknown_name(self):
        with self.assertRaisesRegex(ValueError, "Unknown strategy 'unknown'"):
            resolve_strategy("unknown")

    def test_intraday_momentum_generates_breakout_signal(self):
        bars = [build_bar(100.0, index) for index in range(30)]
        bars.append(build_bar(103.0, 30, volume=1600))
        strategy = resolve_strategy("intraday_momentum")
        signal = strategy.generate_signal(
            StrategyContext(
                coin="BTC",
                window=bars,
                current_bar=bars[-1],
                config={"min_score": 4},
            )
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.reason, "INTRADAY_MOMENTUM_BUY")
        self.assertGreater(signal.tp, bars[-1]["close"])
        self.assertLess(signal.sl, bars[-1]["close"])

    def test_core_exit_policy_wrapper_still_resolves_trend_policy(self):
        exit_policy = build_exit_policy(signal={"reason": "TREND_BUY"})
        self.assertEqual(exit_policy["name"], "trend_sl_only")
        self.assertFalse(exit_policy["requires_tp"])

    def test_position_snapshot_marks_live_protected_position(self):
        snapshot = build_position_snapshot(
            {
                "coin": "BTC",
                "direction": "long",
                "entry": 100.0,
                "current_price": 110.0,
                "size": 1.5,
                "protection_status": "protected",
                "strategy_name": "trend",
            },
            mode="live",
        )
        self.assertEqual(snapshot["lifecycle_status"], "open_protected")
        self.assertEqual(snapshot["strategy_name"], "trend")
        self.assertAlmostEqual(snapshot["pnl"], 15.0)

    def test_position_snapshot_marks_missing_protection_and_close_pending(self):
        missing = build_position_snapshot(
            {
                "coin": "ETH",
                "direction": "short",
                "entry": 200.0,
                "current_price": 190.0,
                "size": 2.0,
                "protection_status": "missing_sl",
            },
            mode="live",
        )
        pending = build_position_snapshot(
            {
                "coin": "SOL",
                "direction": "long",
                "entry": 50.0,
                "current_price": 55.0,
                "size": 1.0,
                "close_pending": True,
                "pending_exit_reason": "TIME",
            },
            mode="live",
        )
        self.assertEqual(missing["lifecycle_status"], "open_unprotected")
        self.assertEqual(pending["lifecycle_status"], "close_pending")
        self.assertEqual(pending["pending_exit_reason"], "TIME")

    def test_position_status_counts_group_by_lifecycle(self):
        counts = build_position_status_counts(
            [
                {"coin": "BTC", "close_pending": True},
                {"coin": "ETH", "protection_status": "protected"},
                {"coin": "SOL", "protection_status": "missing_tpsl"},
            ],
            mode="live",
        )
        self.assertEqual(counts["close_pending"], 1)
        self.assertEqual(counts["open_protected"], 1)
        self.assertEqual(counts["open_unprotected"], 1)


if __name__ == "__main__":
    unittest.main()
