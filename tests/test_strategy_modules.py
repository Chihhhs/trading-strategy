import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.strategies import build_exit_policy
from trading_strategy.strategies.legacy_unified_helpers import analyze_market_regime, is_dead_cat_bounce, is_price_position_blocked
from trading_strategy.market_context import MarketContextDetector, MarketRegime, entry_decision
from trading_strategy.backtest.types import BacktestConfig
from trading_strategy.positions import build_position_snapshot, build_position_status_counts
from trading_strategy.strategies import available_strategy_names, generate_trend_signal, resolve_strategy
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
    def test_market_context_warmup_is_unknown(self):
        detector = MarketContextDetector(BacktestConfig(coins=("BTC",), market_context_enabled=True))
        bars = [build_bar(100.0 + index, index) for index in range(30)]
        context = detector.observe("BTC", bars)
        self.assertEqual(context.regime, MarketRegime.UNKNOWN)

    def test_market_context_compression_blocks_trend_entry(self):
        detector = MarketContextDetector(BacktestConfig(coins=("BTC",), market_context_enabled=True))
        prices = [100.0 + index for index in range(60)] + [160.0, 160.6, 161.0, 161.2, 161.3, 161.35, 161.4, 161.45]
        bars = [build_bar(price, index) for index, price in enumerate(prices)]
        for index in range(len(bars)):
            context = detector.observe("BTC", bars[: index + 1])
        self.assertEqual(context.regime, MarketRegime.COMPRESSION)
        self.assertFalse(entry_decision("long", context)["allowed"])

    def test_market_context_confirmed_breakout_allows_matching_direction(self):
        detector = MarketContextDetector(BacktestConfig(coins=("BTC",), market_context_enabled=True))
        bars = [build_bar(100.0 + index * 0.1, index) for index in range(65)]
        bars.append(build_bar(110.0, 65, volume=3000))
        context = detector.observe("BTC", bars)
        self.assertEqual(context.regime, MarketRegime.BREAKOUT)
        self.assertTrue(context.breakout_confirmed)
        self.assertTrue(entry_decision("long", context)["allowed"])
        self.assertFalse(entry_decision("short", context)["allowed"])

    def test_resolve_strategy_returns_trend(self):
        strategy = resolve_strategy("trend")
        self.assertEqual(strategy.name, "trend")

    def test_resolve_strategy_returns_intraday_momentum(self):
        self.assertIn("intraday_momentum", available_strategy_names())
        strategy = resolve_strategy("intraday_momentum")
        self.assertEqual(strategy.name, "intraday_momentum")

    def test_trend_pullback_reclaim_has_state_exit_without_time_limit(self):
        prices = [100.0 + index * 0.5 for index in range(100)]
        prices.extend([148.0, 146.0, 144.0, 142.0, 140.0, 139.0, 140.0])
        bars = [build_bar(price, index) for index, price in enumerate(prices)]
        strategy = resolve_strategy("trend_pullback_reclaim")
        signal = strategy.generate_signal(
            StrategyContext(
                coin="BNB",
                window=bars,
                current_bar=bars[-1],
                config={"pullback_lookback": 6, "trend_lookback": 84, "entry_drawdown": 0.02},
            )
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.reason, "TREND_PULLBACK_RECLAIM")
        self.assertIsNone(signal.tp)
        self.assertLess(signal.sl, bars[-1]["close"])

        recovered = bars + [build_bar(150.0, len(bars))]
        result = strategy.evaluate_open_position(
            {"bars_since_entry": 10000},
            StrategyContext(
                coin="BNB",
                window=recovered,
                current_bar=recovered[-1],
                config={"pullback_lookback": 6, "trend_lookback": 84, "exit_recovery": 0.0},
            ),
        )
        self.assertEqual(result["exit_reason"], "PULLBACK_RECOVERED")

    def test_trend_pullback_reclaim_is_registered(self):
        self.assertIn("trend_pullback_reclaim", available_strategy_names())
        self.assertEqual(resolve_strategy("trend_pullback_reclaim").name, "trend_pullback_reclaim")

    def test_short_breakdown_generates_short_without_time_exit(self):
        prices = [200.0 - index * 0.5 for index in range(110)]
        bars = [build_bar(price, index) for index, price in enumerate(prices)]
        strategy = resolve_strategy("short_breakdown")
        signal = strategy.generate_signal(
            StrategyContext(
                coin="ETH",
                window=bars,
                current_bar=bars[-1],
                config={"lookback": 12, "trend_lookback": 84, "entry_drawdown": 0.01},
            )
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "short")
        self.assertIsNone(signal.tp)
        self.assertGreater(signal.sl, bars[-1]["close"])

    def test_neutral_exhaustion_reclaim_generates_state_exit(self):
        prices = [100.0 + index * 0.05 for index in range(50)]
        prices.extend([100.0, 98.0, 96.0, 95.0, 94.0, 95.0])
        bars = [build_bar(price, index) for index, price in enumerate(prices)]
        strategy = resolve_strategy("neutral_exhaustion_reclaim")
        signal = strategy.generate_signal(
            StrategyContext(
                coin="BTC",
                window=bars,
                current_bar=bars[-1],
                config={"pullback_lookback": 6, "trend_lookback": 42, "entry_drawdown": 0.02},
            )
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.reason, "NEUTRAL_EXHAUSTION_RECLAIM")
        recovered = bars + [build_bar(102.0, len(bars))]
        result = strategy.evaluate_open_position(
            {},
            StrategyContext(
                coin="BTC",
                window=recovered,
                current_bar=recovered[-1],
                config={"pullback_lookback": 6, "trend_lookback": 42, "exit_recovery": 0.01},
            ),
        )
        self.assertEqual(result["exit_reason"], "PULLBACK_RECOVERED")

    def test_resolve_strategy_returns_legacy_unified(self):
        self.assertIn("legacy_unified", available_strategy_names())
        strategy = resolve_strategy("legacy_unified")
        self.assertEqual(strategy.name, "legacy_unified")

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

    def test_trend_entry_filter_blocks_chasing_range_extreme(self):
        bars = [build_bar(100.0, index, volume=1000) for index in range(40)]
        bars.extend(build_bar(92.0 + index * 0.25, 40 + index, volume=1000) for index in range(20))
        bars.append(build_bar(106.0, 60, volume=1800))
        diagnostics = {}
        signal = generate_trend_signal(
            bars,
            min_score=4,
            rsi_max_long=100,
            long_max_price_position=0.75,
            diagnostics=diagnostics,
        )
        self.assertIsNone(signal)
        self.assertEqual(diagnostics.get("trend_price_position_filtered_signals"), 1)

    def test_trend_entry_filter_can_be_disabled_for_ab_tests(self):
        bars = [build_bar(100.0, index, volume=1000) for index in range(40)]
        bars.extend(build_bar(92.0 + index * 0.25, 40 + index, volume=1000) for index in range(20))
        bars.append(build_bar(106.0, 60, volume=1800))
        signal = generate_trend_signal(
            bars,
            min_score=4,
            rsi_max_long=100,
            long_max_price_position=0.75,
            entry_filter_enabled=False,
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "long")

    def test_core_exit_policy_wrapper_still_resolves_trend_policy(self):
        exit_policy = build_exit_policy(signal={"reason": "TREND_BUY"})
        self.assertEqual(exit_policy["name"], "trend_sl_only")
        self.assertFalse(exit_policy["requires_tp"])

    def test_legacy_core_market_regime_and_filters(self):
        bars = [build_bar(100 + index * 0.6, index, volume=1200 + index * 10) for index in range(70)]
        regime = analyze_market_regime(bars)
        self.assertIsNotNone(regime)
        self.assertIn(regime["regime"], ("long_term", "short_term"))
        self.assertTrue(is_price_position_blocked("long", regime, enabled=True))

        bear_bounce_bars = [build_bar(100 - index * 0.8, index, volume=1000) for index in range(60)]
        bear_bounce_bars.extend(build_bar(53 + (index * 1.5), 60 + index, volume=1100) for index in range(10))
        bounce_regime = analyze_market_regime(bear_bounce_bars)
        self.assertTrue(is_dead_cat_bounce("long", bounce_regime, enabled=True, bounce_threshold_pct=15))

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
