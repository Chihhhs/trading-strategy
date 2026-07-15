import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from backtest import fetch_derivatives_data


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest import cli, load_historical_data
from trading_strategy.backtest.alpha import (
    _build_short_cycle_promotion_gate,
    _bucket_events,
    _forward_signed_return,
    format_alpha_report_lines,
    run_alpha_report,
)
from trading_strategy.backtest.carry import (
    CarryConfig,
    format_carry_report_lines,
    format_funding_trend_report_lines,
    run_carry_report,
    run_funding_trend_report,
)
from trading_strategy.backtest.derivatives import load_derivatives_data, normalize_derivatives_data_map
from trading_strategy.backtest.microstructure import build_microstructure_diagnostic_report, normalize_l2_snapshots
from trading_strategy.backtest.evaluation import _exit_diagnostics, run_trend_evaluation
from trading_strategy.backtest.exit_replay import effective_stop, resolve_hourly_stop_fill, timestamp_iso
from trading_strategy.backtest.exit_replay_report import classify_stop_sweep_event
from trading_strategy.backtest.exit_replay_report import analyze_stop_sweep_events
from trading_strategy.backtest.live_like import build_mark_to_market_point, classify_stop_kind, drawdown_diagnostics
from trading_strategy.backtest.historical_fetch import fetch_binance_hourly_klines
from trading_strategy.backtest.optimizer import run_parameter_sweep
from trading_strategy.backtest.portfolio import PortfolioBacktester
from trading_strategy.backtest.research import format_research_report_lines, run_research_report
from trading_strategy.backtest.trend_attribution import (
    TrendSignalObservation,
    _net_return,
    run_trend_entry_attribution_report,
)
from trading_strategy.shared.trade_history import build_trade_record
from trading_strategy.strategies.trend import TrendStrategy
from trading_strategy.strategies.trend import evaluate_trend_entry_eligibility, generate_raw_trend_candidate
from trading_strategy.backtest.types import BacktestConfig, StrategySignal
from trading_strategy.core.trend_trade import compute_atr_trailing_result


def build_bar(close_price, index):
    return {
        "time": f"2026-01-{index + 1:02d}T00:00:00",
        "open": close_price,
        "high": close_price + 1,
        "low": close_price - 1,
        "close": close_price,
        "volume": 1000 + index,
    }


class FakeStrategy:
    name = "fake"

    def __init__(self, signal_factory):
        self.signal_factory = signal_factory

    def generate_signal(self, context):
        return self.signal_factory(context)


class BacktestModuleTest(unittest.TestCase):
    def test_trend_entry_eligibility_is_pure_and_raw_candidate_survives_block(self):
        bars = [build_bar(100.0, index) for index in range(40)]
        bars.extend(build_bar(92.0 + index * 0.25, 40 + index) for index in range(20))
        bars.append(build_bar(106.0, 60))
        candidate = generate_raw_trend_candidate(bars, min_score=4)
        self.assertIsNotNone(candidate)
        eligibility = evaluate_trend_entry_eligibility(candidate["direction"], candidate, rsi_max_long=100, long_max_price_position=0.75)
        self.assertFalse(eligibility["allowed"])
        self.assertIn("trend_price_position_filtered_signals", eligibility["reasons"])

    def test_trend_attribution_forward_labels_apply_direction_and_cost(self):
        self.assertAlmostEqual(_net_return(100.0, 101.0, "long", 13.0), 0.87)
        self.assertAlmostEqual(_net_return(100.0, 99.0, "short", 13.0), 0.87)
        observations = [
            TrendSignalObservation("BTC", "t", 60, "long", 4, False, ("trend_rsi_filtered_signals",), "bull", "strong_trend", {}, {1: 0.87, 3: None, 5: None, 10: None})
        ]
        self.assertEqual(observations[0].blocked_reasons, ("trend_rsi_filtered_signals",))

    def test_trend_attribution_uses_completed_future_bars_only(self):
        prices = [100.0 + index * 0.1 for index in range(80)]
        prices.extend([110.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0, 117.0, 118.0, 119.0, 120.0])
        data = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        report = run_trend_entry_attribution_report(
            data,
            config=BacktestConfig(coins=("BTC",), strategy_parameters={"min_score": 3}, trend_entry_filter_enabled=True),
            max_bars=len(prices),
        )
        for observation in report.observations:
            if observation.bar_index + 10 >= len(prices):
                self.assertIsNone(observation.forward_net_returns[10])
    def test_market_context_disabled_preserves_fake_strategy_trade(self):
        def build_signal(context):
            if len(context.window) == 2:
                return {"direction": "long", "tp": 200.0, "sl": 90.0, "score": 5, "reason": "TREND_BUY"}
            return None

        data = {"BTC": [build_bar(100.0 + index, index) for index in range(5)]}
        baseline = PortfolioBacktester(
            config=BacktestConfig(coins=("BTC",), min_bars=1, btc_filter_enabled=False),
            strategy=FakeStrategy(build_signal),
        ).run(data)
        disabled = PortfolioBacktester(
            config=BacktestConfig(coins=("BTC",), min_bars=1, btc_filter_enabled=False, market_context_enabled=False),
            strategy=FakeStrategy(build_signal),
        ).run(data)
        self.assertEqual(baseline.trades, disabled.trades)

    def test_momentum_decay_deadline_exits_without_modifying_stop(self):
        class ExhaustionDetector:
            def observe(self, coin, window):
                from trading_strategy.market_context import MarketContext, MarketRegime
                return MarketContext(MarketRegime.EXHAUSTION, "long", 1.0, ("test",))

        def build_signal(context):
            if len(context.window) == 2:
                return {"direction": "long", "tp": 200.0, "sl": 90.0, "score": 5, "reason": "TREND_BUY"}
            return None

        # Patch the detector at its construction boundary so the position lifecycle is tested separately from classifier math.
        data = {"BTC": [build_bar(100.0 + index, index) for index in range(8)]}
        with patch("trading_strategy.backtest.portfolio.MarketContextDetector", return_value=ExhaustionDetector()):
            result = PortfolioBacktester(
                config=BacktestConfig(
                    coins=("BTC",), min_bars=1, btc_filter_enabled=False,
                    momentum_decay_time_limit_enabled=True, momentum_decay_grace_bars=2,
                ),
                strategy=FakeStrategy(build_signal),
            ).run(data)
        self.assertEqual(result.trades[0]["exit_reason"], "MOMENTUM_DECAY_TIME_LIMIT")
        self.assertEqual(result.trades[0]["initial_risk"], 11.0)
        self.assertEqual(result.portfolio["diagnostics"]["momentum_decay_deadlines_set"], 1)
    def test_exit_replay_cli_defaults_to_strict_canonical_mode(self):
        args = cli.build_parser().parse_args([])
        self.assertEqual(args.exit_replay_mode, "strict")

    def test_timestamp_iso_normalizes_numeric_and_iso_values(self):
        self.assertEqual(timestamp_iso({"ts": 0}), "1970-01-01T00:00:00+00:00")
        self.assertEqual(
            timestamp_iso({"time": "2026-01-01T00:00:00Z"}),
            "2026-01-01T00:00:00+00:00",
        )

    def test_mark_to_market_point_includes_unrealized_pnl_and_liquidation_cost(self):
        point = build_mark_to_market_point(
            balance=1000.0,
            positions=[
                {"coin": "BTC", "direction": "long", "entry": 100.0, "size": 2.0},
                {"coin": "ETH", "direction": "short", "entry": 50.0, "size": 1.0},
            ],
            prices={"BTC": 110.0, "ETH": 45.0},
            timestamp_ms=3600000,
            fee_bps=5.0,
            slippage_bps=0.0,
        )
        self.assertAlmostEqual(point["unrealized_pnl"], 25.0)
        self.assertAlmostEqual(point["estimated_exit_cost"], 0.2575)
        self.assertAlmostEqual(point["equity"], 1024.7425)
        self.assertEqual(point["open_positions"], 2)
        self.assertEqual(point["gross_exposure"], 265.0)

    def test_mark_to_market_point_rejects_missing_position_price(self):
        self.assertIsNone(
            build_mark_to_market_point(
                balance=1000.0,
                positions=[{"coin": "BTC", "direction": "long", "entry": 100.0, "size": 1.0}],
                prices={},
                timestamp_ms=0,
            )
        )

    def test_drawdown_diagnostics_reports_peak_trough_and_duration(self):
        report = drawdown_diagnostics(
            [
                {"timestamp_ms": 0, "equity": 100.0},
                {"timestamp_ms": 3600000, "equity": 120.0},
                {"timestamp_ms": 7200000, "equity": 90.0},
                {"timestamp_ms": 10800000, "equity": 110.0},
            ]
        )
        self.assertEqual(report["max_drawdown_pct"], 25.0)
        self.assertEqual(report["peak_timestamp_ms"], 3600000)
        self.assertEqual(report["trough_timestamp_ms"], 7200000)
        self.assertEqual(report["drawdown_duration_hours"], 2.0)

    def test_stop_kind_distinguishes_initial_dynamic_and_atr(self):
        self.assertEqual(classify_stop_kind({"sl_stage": 0}, "SL"), "initial")
        self.assertEqual(classify_stop_kind({"sl_stage": 1}, "SL"), "breakeven")
        self.assertEqual(classify_stop_kind({"sl_stage": 2}, "SL"), "half_r")
        self.assertEqual(classify_stop_kind({"sl_stage": 2}, "ATR_TRAIL"), "atr")

    def test_exit_replay_uses_most_protective_known_stop(self):
        self.assertEqual(
            effective_stop({"direction": "long", "sl": 95.0, "atr_trailing_stop": 98.0}),
            98.0,
        )
        self.assertEqual(
            effective_stop({"direction": "short", "sl": 105.0, "atr_trailing_stop": 102.0}),
            102.0,
        )
        self.assertEqual(
            resolve_hourly_stop_fill(
                {"direction": "long", "sl": 95.0, "atr_trailing_stop": 98.0},
                {"open": 100.0, "high": 101.0, "low": 97.0},
            )["reason"],
            "ATR_TRAIL",
        )

    def test_hourly_fetch_paginates_and_deduplicates(self):
        hour_ms = 60 * 60 * 1000
        pages = [
            [[0, "1", "2", "0.5", "1.5", "10"], [hour_ms, "2", "3", "1", "2.5", "20"]],
            [[2 * hour_ms, "3", "4", "2", "3.5", "30"]],
        ]

        bars = fetch_binance_hourly_klines(
            "BTC",
            0,
            3 * hour_ms,
            request_json=lambda _url: pages.pop(0),
            limit=2,
        )

        self.assertEqual([bar["open_time"] for bar in bars], [0, hour_ms, 2 * hour_ms])
        self.assertEqual(bars[-1]["close"], 3.5)

    def test_exit_replay_fills_stop_touch_and_gap_causally(self):
        long_position = {"direction": "long", "sl": 95.0}
        short_position = {"direction": "short", "sl": 105.0}
        self.assertEqual(
            resolve_hourly_stop_fill(long_position, {"open": 97.0, "high": 99.0, "low": 94.0}),
            {"price": 95.0, "reason": "SL", "fill_type": "stop"},
        )
        self.assertEqual(
            resolve_hourly_stop_fill(long_position, {"open": 93.0, "high": 96.0, "low": 92.0}),
            {"price": 93.0, "reason": "SL", "fill_type": "gap"},
        )
        self.assertEqual(
            resolve_hourly_stop_fill(short_position, {"open": 103.0, "high": 106.0, "low": 101.0}),
            {"price": 105.0, "reason": "SL", "fill_type": "stop"},
        )
        self.assertEqual(
            resolve_hourly_stop_fill(short_position, {"open": 107.0, "high": 108.0, "low": 104.0}),
            {"price": 107.0, "reason": "SL", "fill_type": "gap"},
        )

    def test_close_confirmed_stop_ignores_reclaimed_touch(self):
        position = {"direction": "long", "sl": 95.0}
        self.assertIsNone(
            resolve_hourly_stop_fill(
                position,
                {"open": 100.0, "high": 101.0, "low": 94.0, "close": 98.0},
                mode="close_confirmed",
            )
        )
        self.assertEqual(
            resolve_hourly_stop_fill(
                position,
                {"open": 100.0, "high": 101.0, "low": 94.0, "close": 93.0},
                mode="close_confirmed",
            ),
            {"price": 93.0, "reason": "SL", "fill_type": "confirmed"},
        )

    def test_close_confirmed_stop_still_exits_on_gap_open(self):
        self.assertEqual(
            resolve_hourly_stop_fill(
                {"direction": "short", "sl": 105.0},
                {"open": 107.0, "high": 108.0, "low": 101.0, "close": 103.0},
                mode="close_confirmed",
            ),
            {"price": 107.0, "reason": "SL", "fill_type": "gap"},
        )

    def test_stop_sweep_classification_boundaries(self):
        self.assertEqual(
            classify_stop_sweep_event({"eligible": False}),
            "ineligible",
        )
        self.assertEqual(
            classify_stop_sweep_event({"eligible": True, "reclaimed": True, "max_favorable_r": 0.5}),
            "false_sweep",
        )
        self.assertEqual(
            classify_stop_sweep_event({"eligible": True, "reclaimed": True, "max_favorable_r": 0.2}),
            "reclaimed_stop",
        )
        self.assertEqual(
            classify_stop_sweep_event({"eligible": True, "reclaimed": False, "signed_return_r": -0.5}),
            "valid_stop",
        )
        self.assertEqual(
            classify_stop_sweep_event({"eligible": True, "reclaimed": False, "signed_return_r": -0.2}),
            "unclear",
        )
        self.assertEqual(
            classify_stop_sweep_event({"eligible": True, "fill_type": "gap", "reclaimed": True, "max_favorable_r": 2.0}),
            "ineligible",
        )

    def test_stop_sweep_horizons_are_independently_eligible(self):
        hour_ms = 60 * 60 * 1000
        hourly = {
            "BTC": [
                {"open_time": index * hour_ms, "open": 100, "high": 101, "low": 99, "close": 100 + index}
                for index in range(25)
            ]
        }
        report = analyze_stop_sweep_events(
            [{"coin": "BTC", "direction": "long", "fill_type": "stop", "open_time": 0, "fill_price": 95, "stop_price": 95, "initial_risk": 5}],
            hourly,
            forward_hours=(6, 12, 72),
            reclaim_hours=24,
        )

        self.assertEqual(report["events_eligible"], 1)
        self.assertEqual(report["forward_summary"][6]["events"], 1)
        self.assertEqual(report["forward_summary"][72]["events"], 0)

    def test_strict_exit_replay_fixture_regression(self):
        data = load_historical_data(os.path.join(ROOT, "data", "historical_prices", "1000d_50coins.json"))
        hourly = load_historical_data(
            os.path.join(ROOT, "data", "historical_prices", "binance_1h_240d_BTC_ETH_BNB.json")
        )
        derivatives = load_derivatives_data(
            os.path.join(ROOT, "data", "derivatives", "bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json")
        )
        result = PortfolioBacktester(
            config=BacktestConfig(
                coins=("BTC", "ETH", "BNB"),
                max_days=240,
                atr_trailing_enabled=True,
                derivatives_crowding_exit_enabled=True,
                derivatives_crowding_action="reduce",
                derivatives_crowding_reduce_fraction=0.75,
                fee_bps=4.5,
                slippage_bps=2.0,
            ),
            derivatives_data_map=derivatives,
            exit_replay_data_map=hourly,
            exit_replay_mode="strict",
        ).run(data)

        self.assertEqual(result.portfolio["total_pnl_pct"], -26.7)
        self.assertEqual(result.portfolio["max_drawdown"], 26.7)
        self.assertEqual(result.portfolio["closed_balance_max_drawdown"], 26.7)
        self.assertAlmostEqual(result.portfolio["mark_to_market_max_drawdown"], 26.7169)
        self.assertEqual(result.portfolio["mark_to_market"]["points"], 4560)
        self.assertEqual(result.portfolio["mark_to_market"]["daily_points"], 190)
        self.assertEqual(result.portfolio["mark_to_market"]["max_open_positions"], 2)
        self.assertTrue(all(trade["entry_time"] for trade in result.trades))
        self.assertTrue(all(trade["exit_time"] for trade in result.trades))
        events = result.portfolio["diagnostics"]["exit_replay_events"]
        self.assertEqual({event["stop_kind"] for event in events}, {"initial", "breakeven"})
        self.assertTrue(all(event["stop_effective_time"] and event["trigger_time"] for event in events))

    def test_exit_replay_does_not_fill_without_complete_bar_or_touch(self):
        position = {"direction": "long", "sl": 95.0}
        self.assertIsNone(resolve_hourly_stop_fill(position, {"open": 100.0, "high": 101.0}))
        self.assertIsNone(
            resolve_hourly_stop_fill(position, {"open": 100.0, "high": 102.0, "low": 96.0})
        )

    def test_portfolio_exit_replay_uses_only_hours_after_entry_boundary(self):
        day_ms = 24 * 60 * 60 * 1000
        daily = {
            "BTC": [
                {**build_bar(100.0, index), "ts": index * day_ms}
                for index in range(4)
            ]
        }
        hourly = {
            "BTC": [
                {
                    "open_time": 2 * day_ms - 60 * 60 * 1000,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 80.0,
                    "close": 90.0,
                },
                {
                    "open_time": 2 * day_ms,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 89.0,
                    "close": 90.0,
                },
            ]
        }

        def signal_factory(context):
            if context.current_bar["ts"] == day_ms:
                return StrategySignal(direction="long", sl=95.0, tp=None, score=5, reason="TEST")
            return None

        result = PortfolioBacktester(
            config=BacktestConfig(coins=("BTC",), min_bars=1, btc_filter_enabled=False),
            strategy=FakeStrategy(signal_factory),
            exit_replay_data_map=hourly,
        ).run(daily)

        self.assertEqual(result.trades[0]["exit"], 95.0)
        self.assertEqual(result.trades[0]["exit_reason"], "SL")
        self.assertEqual(result.portfolio["diagnostics"]["exit_replay_stop_fills"], 1)
        self.assertEqual(result.portfolio["diagnostics"]["exit_replay_gap_fills"], 0)
        self.assertGreater(result.portfolio["diagnostics"]["exit_replay_missing_hours"], 0)

    def test_closed_trade_records_initial_risk_and_r_excursions(self):
        trade = build_trade_record(
            {
                "coin": "BTC",
                "direction": "long",
                "entry": 100.0,
                "size": 1.0,
                "initial_risk": 10.0,
                "best_price": 115.0,
                "max_favorable_price": 120.0,
                "max_adverse_price": 90.0,
            },
            110.0,
            "EOD",
        )
        self.assertEqual(trade["initial_risk"], 10.0)
        self.assertEqual(trade["initial_risk_pct"], 10.0)
        self.assertEqual(trade["mfe_r"], 2.0)
        self.assertEqual(trade["mae_r"], -1.0)
        self.assertEqual(trade["best_close_r"], 1.5)

    def test_exit_diagnostics_aggregates_r_excursions(self):
        diagnostics = _exit_diagnostics(
            [
                {"exit_reason": "SL", "pnl_pct": -3.0, "hold_bars": 2, "mfe_pct": 5.0, "mae_pct": -6.0, "mfe_r": 1.0, "mae_r": -1.2},
                {"exit_reason": "SL", "pnl_pct": -4.0, "hold_bars": 4, "mfe_pct": 10.0, "mae_pct": -8.0, "mfe_r": 2.0, "mae_r": -1.6},
            ]
        )
        self.assertEqual(diagnostics["SL"]["avg_mfe_r"], 1.5)
        self.assertEqual(diagnostics["SL"]["avg_mae_r"], -1.4)

    def test_adaptive_atr_trail_uses_entry_adx_to_select_multiplier(self):
        position = {
            "direction": "long",
            "entry": 100.0,
            "sl": 90.0,
            "current_price": 112.0,
            "initial_risk": 10.0,
            "best_price": 120.0,
            "entry_adx": 40.0,
            "exit_policy": {"name": "trend_sl_only"},
        }
        config = BacktestConfig(
            coins=("BTC",),
            atr_trailing_enabled=True,
            adaptive_atr_trailing_enabled=True,
            adaptive_atr_strong_adx=35.0,
            adaptive_atr_strong_mult=3.0,
            adaptive_atr_weak_mult=1.5,
        )
        window = [{"high": 114.0, "low": 110.0, "close": 112.0}] * 15
        result = TrendStrategy().check_atr_trailing_exit(position, window, config)
        self.assertEqual(result["effective_atr_trailing_mult"], 3.0)
        self.assertEqual(result["target_sl"], 108.0)

    def test_trend_evaluation_compares_baseline_and_candidate_by_window_and_universe(self):
        data_map = {
            "BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 110, 111, 112))],
            "ETH": [build_bar(price, index) for index, price in enumerate((50, 51, 60, 61, 62))],
        }

        def build_signal(context):
            if context.current_bar["close"] not in (101, 51):
                return None
            return StrategySignal("long", tp=context.current_bar["close"] + 5, sl=context.current_bar["close"] - 4, score=5, reason="TEST_BUY")

        base = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1, btc_filter_enabled=False)
        candidate = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1, btc_filter_enabled=False)
        report = run_trend_evaluation(
            data_map,
            baseline_config=base,
            candidate_config=candidate,
            baseline_strategy=FakeStrategy(build_signal),
            candidate_strategy=FakeStrategy(build_signal),
            windows=(3,),
            universes=(("BTC",), ("BTC", "ETH")),
        )
        self.assertEqual(len(report["comparisons"]), 2)
        self.assertEqual(report["comparisons"][1]["coins"], ("BTC", "ETH"))
        self.assertIn("exit_diagnostics", report["comparisons"][0])
        self.assertFalse(report["summary"]["passes_majority_gate"])

    def test_microstructure_outcome_report_measures_would_block_forward_move(self):
        from trading_strategy.backtest.microstructure import build_microstructure_guard_outcome_report

        snapshots = normalize_l2_snapshots(
            {
                "BTC": [
                    {"timestamp": 1, "bids": [["99", "1"]], "asks": [["101", "5"]], "signal_direction": "long"},
                    {"timestamp": 2, "bids": [["89", "1"]], "asks": [["91", "5"]], "signal_direction": "long"},
                ]
            }
        )
        report = build_microstructure_guard_outcome_report(
            snapshots,
            max_spread_bps=50.0,
            min_top_depth_usd=0.0,
            max_opposing_imbalance=0.5,
            forward_steps=(1,),
        )
        self.assertEqual(report[0]["would_block_events"], 1)
        self.assertLess(report[0]["would_block_forward_return_pct"], 0.0)
    def test_compute_atr_trailing_result_triggers_for_long_after_activation(self):
        position = {
            "direction": "long",
            "entry": 100.0,
            "sl": 90.0,
            "current_price": 112.0,
            "initial_risk": 10.0,
            "best_price": 120.0,
            "exit_policy": {"name": "trend_sl_only"},
        }
        result = compute_atr_trailing_result(
            position,
            current_atr=4.0,
            enabled=True,
            atr_activation_r=1.5,
            atr_trailing_mult=2.0,
        )
        self.assertTrue(result["triggered"])
        self.assertEqual(result["target_sl"], 112.0)

    def test_compute_atr_trailing_result_does_not_activate_before_threshold(self):
        position = {
            "direction": "long",
            "entry": 100.0,
            "sl": 90.0,
            "current_price": 108.0,
            "initial_risk": 10.0,
            "best_price": 108.0,
            "exit_policy": {"name": "trend_sl_only"},
        }
        result = compute_atr_trailing_result(
            position,
            current_atr=4.0,
            enabled=True,
            atr_activation_r=1.5,
            atr_trailing_mult=2.0,
        )
        self.assertFalse(result["triggered"])
        self.assertFalse(result["active"])

    def test_compute_atr_trailing_result_only_updates_more_protective_stop(self):
        position = {
            "direction": "long",
            "entry": 100.0,
            "sl": 113.0,
            "current_price": 114.0,
            "initial_risk": 10.0,
            "best_price": 120.0,
            "exit_policy": {"name": "trend_sl_only"},
        }
        result = compute_atr_trailing_result(
            position,
            current_atr=4.0,
            enabled=True,
            atr_activation_r=1.5,
            atr_trailing_mult=2.0,
        )
        self.assertFalse(result["should_update"])

    def test_load_historical_data_respects_max_days(self):
        payload = {
            "BTC": [build_bar(100 + index, index) for index in range(5)],
            "ETH": [build_bar(200 + index, index) for index in range(3)],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            data_map = load_historical_data(path, max_days=2)
        finally:
            os.remove(path)
        self.assertEqual(len(data_map["BTC"]), 2)
        self.assertEqual(data_map["BTC"][0]["close"], 103)
        self.assertEqual(len(data_map["ETH"]), 2)

    def test_load_derivatives_data_normalizes_coin_fields_and_max_days(self):
        payload = {
            "btc": [
                {"time": "t1", "funding_rate": "0.0001", "open_interest": "100", "basis_pct": "0.2"},
                {"time": "t2", "funding_rate": "bad", "open_interest": "110", "basis_pct": None},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            data_map = load_derivatives_data(path, max_days=1)
        finally:
            os.remove(path)
        self.assertEqual(list(data_map), ["BTC"])
        self.assertIsNone(data_map["BTC"][0]["funding_rate"])
        self.assertEqual(data_map["BTC"][0]["open_interest"], 110.0)

    def test_normalize_derivatives_data_map_keeps_ohlcv_contract_optional(self):
        data_map = normalize_derivatives_data_map({"ETH": [{"timestamp": 1, "mark_price": "2000"}]})
        self.assertEqual(data_map["ETH"][0]["time"], 1)
        self.assertEqual(data_map["ETH"][0]["mark_price"], 2000.0)

    def test_fetch_open_interest_paginates_daily_windows(self):
        calls = []

        def fake_request(_base_url, path, params):
            calls.append((path, params))
            return [
                {
                    "timestamp": params["startTime"],
                    "sumOpenInterest": str(100 + len(calls)),
                }
            ]

        with patch("backtest.fetch_derivatives_data._request_json", side_effect=fake_request), patch(
            "backtest.fetch_derivatives_data.time.sleep"
        ):
            result = fetch_derivatives_data._fetch_open_interest(
                "BTCUSDT",
                0,
                fetch_derivatives_data.OI_WINDOW_MS * 2 + fetch_derivatives_data.DAY_MS,
            )
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "/openInterestHist")
        self.assertEqual(len(result), len(calls))

    def test_fetch_bybit_open_interest_paginates_cursor(self):
        calls = []

        def fake_request(_base_url, path, params):
            calls.append((path, params))
            cursor = params.get("cursor")
            if cursor:
                return {
                    "retCode": 0,
                    "result": {
                        "list": [{"timestamp": str(fetch_derivatives_data.DAY_MS), "openInterest": "200"}],
                        "nextPageCursor": "",
                    },
                }
            return {
                "retCode": 0,
                "result": {
                    "list": [{"timestamp": "0", "openInterest": "100"}],
                    "nextPageCursor": "next",
                },
            }

        with patch("backtest.fetch_derivatives_data._request_json", side_effect=fake_request), patch(
            "backtest.fetch_derivatives_data.time.sleep"
        ):
            result = fetch_derivatives_data._fetch_open_interest(
                "BTCUSDT",
                0,
                fetch_derivatives_data.DAY_MS,
                source="bybit",
            )
        self.assertEqual(calls[0][0], "/v5/market/open-interest")
        self.assertEqual(calls[1][1]["cursor"], "next")
        self.assertEqual(result, {"1970-01-01": 100.0, "1970-01-02": 200.0})

    def test_engine_opens_position_from_signal(self):
        data_map = {"BTC": [build_bar(100 + index, index) for index in range(4)]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=95, score=5, reason="TEST_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0]["exit_reason"], "EOD")
        self.assertEqual(result.trades[0]["entry"], 101.0)

    def test_engine_closes_long_on_tp(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TEST_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.trades[0]["exit_reason"], "TP")
        self.assertGreater(result.trades[0]["pnl"], 0)

    def test_backtest_transaction_cost_reduces_reported_pnl(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TEST_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1, fee_bps=10.0)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        trade = result.trades[0]
        self.assertGreater(trade["cost"], 0)
        self.assertGreater(trade["gross_pnl"], trade["pnl"])
        self.assertGreater(result.portfolio["gross_pnl"], result.portfolio["total_pnl"])
        rendered = "\n".join(cli.format_result_lines(result))
        self.assertIn("net_pnl=", rendered)
        self.assertIn("cost=", rendered)

    def test_engine_closes_short_on_sl(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 99, 105, 106))]}

        def build_signal(context):
            if context.current_bar["close"] != 99:
                return None
            return StrategySignal("short", tp=90, sl=103, score=-5, reason="TREND_SELL")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.trades[0]["exit_reason"], "SL")
        self.assertLess(result.trades[0]["pnl"], 0)

    def test_closed_trade_records_mae_on_stop_bar(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 95))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TREND_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertLess(result.trades[0]["mae_pct"], 0.0)

    def test_engine_closes_long_on_atr_trail_exit(self):
        prices = [100] * 20 + [101, 120, 108, 107]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal(
                "long",
                tp=140,
                sl=90,
                score=5,
                reason="TREND_BUY",
                raw={"atr": 4.0, "breakout_level": 100.0, "ema20": 100.5, "ema50": 99.5},
            )

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1, atr_trailing_enabled=True)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.trades[0]["exit_reason"], "ATR_TRAIL")

    def test_engine_tp_has_priority_over_atr_trail(self):
        prices = [100] * 20 + [101, 120, 121]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal(
                "long",
                tp=110,
                sl=90,
                score=5,
                reason="TREND_BUY",
                raw={"atr": 4.0, "breakout_level": 100.0, "ema20": 100.5, "ema50": 99.5},
            )

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1, atr_trailing_enabled=True)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.trades[0]["exit_reason"], "TP")

    def test_engine_skips_zero_size_position(self):
        data_map = {"BTC": [build_bar(100 + index, index) for index in range(4)]}

        def build_signal(context):
            return StrategySignal("long", tp=110, sl=context.current_bar["close"], score=5, reason="TEST_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 0)
        self.assertEqual(result.trades, [])

    def test_btc_filter_blocks_conflicting_signal(self):
        btc = [build_bar(price, index) for index, price in enumerate((100, 101, 102, 103, 104, 120, 130, 140))]
        eth = [build_bar(price, index) for index, price in enumerate((50, 49, 48, 47, 46, 45, 44, 43))]
        data_map = {"BTC": btc, "ETH": eth}

        def build_signal(_context):
            return StrategySignal("short", tp=40, sl=60, score=-5, reason="TREND_SELL")

        config = BacktestConfig(coins=("ETH",), max_days=None, min_bars=6, btc_filter_enabled=True)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 0)

    def test_derivatives_filter_blocks_existing_signal_only(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113))]}
        derivatives = {
            "BTC": [
                {"time": bar["time"], "funding_rate": 0.001, "open_interest": 100 + index, "basis_pct": 0.2}
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TEST_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            derivatives_filter_enabled=True,
        )
        result = PortfolioBacktester(
            config=config,
            strategy=FakeStrategy(build_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertEqual(result.portfolio["trades"], 0)
        self.assertEqual(result.portfolio["diagnostics"]["derivatives_funding_filtered_signals"], 1)

    def test_derivatives_filter_missing_data_does_not_create_or_block_trades(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TEST_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            derivatives_filter_enabled=True,
        )
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.portfolio["diagnostics"]["derivatives_missing_context_signals"], 1)

    def test_oi_entry_filter_allows_same_direction_oi_expansion(self):
        prices = (100, 101, 102, 103, 104, 106, 110, 112)
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {"time": bar["time"], "open_interest": 100 + index * 5, "funding_rate": 0.0}
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def build_signal(context):
            if context.current_bar["close"] != 106:
                return None
            return StrategySignal("long", tp=111, sl=99, score=5, reason="TEST_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            oi_entry_filter_enabled=True,
        )
        result = PortfolioBacktester(
            config=config,
            strategy=FakeStrategy(build_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertGreaterEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.portfolio["diagnostics"]["oi_entry_filter_confirmed_signals"], 1)

    def test_oi_entry_filter_blocks_unconfirmed_signal(self):
        prices = (100, 99, 98, 97, 96, 95, 94, 93)
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {"time": bar["time"], "open_interest": 100 + index * 5, "funding_rate": 0.0}
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def build_signal(context):
            if context.current_bar["close"] != 95:
                return None
            return StrategySignal("long", tp=105, sl=90, score=5, reason="TEST_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            oi_entry_filter_enabled=True,
        )
        result = PortfolioBacktester(
            config=config,
            strategy=FakeStrategy(build_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertEqual(result.portfolio["trades"], 0)
        self.assertEqual(result.portfolio["diagnostics"]["oi_entry_filter_unconfirmed_signals"], 1)

    def test_trend_alpha_entry_disabled_leaves_signal_unchanged(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TREND_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            trend_alpha_entry_enabled=False,
        )
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.trades[0]["signal_score"], 5)
        self.assertNotIn("trend_alpha_missing_derivatives_bars", result.portfolio["diagnostics"])

    def test_trend_alpha_entry_btc_regime_boosts_supported_alt_direction(self):
        btc = [build_bar(price, index) for index, price in enumerate((100, 101, 102, 103, 104, 105, 106, 112, 116))]
        eth = [build_bar(price, index) for index, price in enumerate((50, 51, 52, 53, 54, 55, 56, 57, 65))]
        data_map = {"BTC": btc, "ETH": eth}

        def build_signal(context):
            if len(context.window) != 8:
                return None
            return StrategySignal("long", tp=65, sl=50, score=5, reason="TREND_BUY")

        config = BacktestConfig(
            coins=("ETH",),
            max_days=None,
            min_bars=7,
            btc_filter_enabled=False,
            trend_alpha_entry_enabled=True,
            trend_alpha_mode="combined",
            trend_alpha_score_boost=1,
        )
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.trades[0]["signal_score"], 6)
        self.assertEqual(result.portfolio["diagnostics"]["trend_alpha_btc_regime_boosts"], 1)

    def test_trend_alpha_entry_blocks_crowded_funding_basis_long_not_short(self):
        prices = [100.0 + index * 0.1 for index in range(42)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.00001 if index < 35 else 0.0002,
                    "basis_pct": -0.05 if index >= 35 else 0.0,
                }
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def long_signal(context):
            if len(context.window) != 37:
                return None
            return StrategySignal("long", tp=120, sl=90, score=5, reason="TREND_BUY")

        long_config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=36,
            btc_filter_enabled=False,
            trend_alpha_entry_enabled=True,
            derivatives_crowding_funding_z_threshold=0.5,
            derivatives_crowding_basis_abs_threshold_pct=0.03,
        )
        long_result = PortfolioBacktester(
            config=long_config,
            strategy=FakeStrategy(long_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertEqual(long_result.portfolio["trades"], 0)
        self.assertEqual(long_result.portfolio["diagnostics"]["trend_alpha_crowded_blocks"], 1)

        def short_signal(context):
            if len(context.window) != 37:
                return None
            return StrategySignal("short", tp=90, sl=120, score=-5, reason="TREND_SELL")

        short_result = PortfolioBacktester(
            config=long_config,
            strategy=FakeStrategy(short_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertGreaterEqual(short_result.portfolio["trades"], 1)

    def test_trend_alpha_entry_oi_confirmation_boosts_same_direction_signal(self):
        prices = (100, 101, 102, 103, 104, 105, 107, 110)
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "open_interest": 100 + index * 5,
                    "funding_rate": 0.00001,
                    "basis_pct": 0.0,
                }
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def build_signal(context):
            if len(context.window) != 7:
                return None
            return StrategySignal("long", tp=110, sl=95, score=5, reason="TREND_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=6,
            btc_filter_enabled=False,
            trend_alpha_entry_enabled=True,
            trend_alpha_mode="combined",
        )
        result = PortfolioBacktester(
            config=config,
            strategy=FakeStrategy(build_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertEqual(result.trades[0]["signal_score"], 6)
        self.assertEqual(result.portfolio["diagnostics"]["trend_alpha_oi_boosts"], 1)

    def test_trend_alpha_entry_missing_derivatives_does_not_crash_or_block(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=5, reason="TREND_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            trend_alpha_entry_enabled=True,
        )
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.portfolio["diagnostics"]["trend_alpha_missing_derivatives_bars"], 1)

    def test_derivatives_crowding_exit_closes_open_trend_long(self):
        prices = [100.0 + index * 0.1 for index in range(45)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.00001 if index < 35 else 0.0002,
                    "basis_pct": -0.05 if index >= 35 else 0.0,
                }
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def build_signal(context):
            if context.current_bar["close"] != data_map["BTC"][2]["close"]:
                return None
            return StrategySignal("long", tp=None, sl=90, score=5, reason="TREND_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            derivatives_crowding_exit_enabled=True,
            derivatives_crowding_funding_z_threshold=0.5,
            derivatives_crowding_basis_abs_threshold_pct=0.03,
        )
        result = PortfolioBacktester(
            config=config,
            strategy=FakeStrategy(build_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        self.assertEqual(result.trades[0]["exit_reason"], "DERIVATIVES_CROWDING")
        self.assertEqual(result.portfolio["diagnostics"]["derivatives_crowding_exit_long_signals"], 1)

    def test_derivatives_crowding_reduce_partially_closes_trend_long(self):
        prices = [100.0 + index * 0.1 for index in range(45)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.00001 if index < 35 else 0.0002,
                    "basis_pct": -0.05 if index >= 35 else 0.0,
                }
                for index, bar in enumerate(data_map["BTC"])
            ]
        }

        def build_signal(context):
            if context.current_bar["close"] != data_map["BTC"][2]["close"]:
                return None
            return StrategySignal("long", tp=None, sl=90, score=5, reason="TREND_BUY")

        config = BacktestConfig(
            coins=("BTC",),
            max_days=None,
            min_bars=1,
            btc_filter_enabled=False,
            derivatives_crowding_exit_enabled=True,
            derivatives_crowding_action="reduce",
            derivatives_crowding_reduce_fraction=0.5,
            derivatives_crowding_funding_z_threshold=0.5,
            derivatives_crowding_basis_abs_threshold_pct=0.03,
        )
        result = PortfolioBacktester(
            config=config,
            strategy=FakeStrategy(build_signal),
            derivatives_data_map=derivatives,
        ).run(data_map)
        reasons = [trade["exit_reason"] for trade in result.trades]
        self.assertIn("DERIVATIVES_CROWDING_REDUCE", reasons)
        self.assertEqual(result.portfolio["diagnostics"]["derivatives_crowding_reduce_long_signals"], 1)
        reduce_trade = next(trade for trade in result.trades if trade["exit_reason"] == "DERIVATIVES_CROWDING_REDUCE")
        final_trade = result.trades[-1]
        self.assertTrue(reduce_trade["is_partial"])
        self.assertFalse(final_trade["is_partial"])
        self.assertEqual(reduce_trade["position_id"], final_trade["position_id"])
        self.assertLess(reduce_trade["size"], reduce_trade["size"] + final_trade["size"])
        self.assertEqual(round(reduce_trade["size"], 6), round(final_trade["size"], 6))

    def test_trade_history_fields_align_with_core_helpers(self):
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112))]}

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=96, score=7, reason="TREND_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        trade = result.trades[0]
        self.assertEqual(trade["entry_reason"], "TREND_BUY")
        self.assertEqual(trade["signal_reason"], "TREND_BUY")
        self.assertEqual(trade["signal_score"], 7)
        self.assertEqual(trade["exit_policy"], "trend_sl_only")
        self.assertEqual(trade["close_status"], "simulated")

    def test_portfolio_aggregates_multi_coin_results(self):
        data_map = {
            "BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 110, 111))],
            "ETH": [build_bar(price, index) for index, price in enumerate((50, 51, 60, 61))],
        }

        def build_signal(context):
            if context.current_bar["close"] not in (101, 51):
                return None
            return StrategySignal("long", tp=context.current_bar["close"] + 5, sl=context.current_bar["close"] - 4, score=5, reason="TEST_BUY")

        config = BacktestConfig(coins=("BTC", "ETH"), max_days=None, min_bars=1, btc_filter_enabled=False)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 2)
        self.assertEqual(len(result.coin_results), 2)
        self.assertGreater(result.portfolio["ending_balance"], result.portfolio["starting_balance"])

    def test_backtest_respects_max_positions_for_new_entries(self):
        data_map = {
            "BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 102, 103))],
            "ETH": [build_bar(price, index) for index, price in enumerate((50, 51, 52, 53))],
        }

        def build_signal(context):
            if context.current_bar["time"].endswith("02T00:00:00"):
                return StrategySignal("long", tp=999, sl=context.current_bar["close"] - 10, score=5, reason="TEST_BUY")
            return None

        config = BacktestConfig(
            coins=("BTC", "ETH"),
            max_days=None,
            min_bars=1,
            max_positions=1,
            btc_filter_enabled=False,
        )
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.portfolio["trades"], 1)
        self.assertEqual(result.trades[0]["coin"], "BTC")

    def test_cli_returns_portfolio_and_coin_summaries(self):
        payload = {
            "BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113))],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--strategy",
                        "trend",
                        "--max-days",
                        "4",
                        "--data-path",
                        path,
                    ]
                )
        finally:
            os.remove(path)
        rendered = output.getvalue()
        self.assertIn("Portfolio:", rendered)
        self.assertIn("Exit reasons:", rendered)
        self.assertIn("avg_hold_bars=", rendered)
        self.assertIn("score=", rendered)
        self.assertIn("BTC:", rendered)
        self.assertEqual(result.coin_results[0].coin, "BTC")

    def test_cli_accepts_intraday_momentum_strategy(self):
        prices = [100.0] * 55 + [104.0, 105.0]
        payload = {
            "BTC": [
                {
                    **build_bar(price, index),
                    "volume": 1600 if index >= 55 else 1000,
                }
                for index, price in enumerate(prices)
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--strategy",
                        "intraday_momentum",
                        "--max-days",
                        str(len(prices)),
                        "--data-path",
                        path,
                    ]
                )
        finally:
            os.remove(path)
        self.assertIn("Portfolio:", output.getvalue())
        self.assertEqual(result.config.strategy, "intraday_momentum")

    def test_optimizer_returns_ranked_rows(self):
        payload = {
            "BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113, 114))],
        }
        rows = run_parameter_sweep(
            payload,
            coins=("BTC",),
            max_days=5,
            initial_capital=1000.0,
            strategies=("trend",),
            leverages=(2.0, 3.0),
            risk_pcts=(0.03, 0.05),
            btc_filter_modes=(True, False),
            atr_trailing_modes=(False, True),
        )
        self.assertEqual(len(rows), 16)
        self.assertGreaterEqual(rows[0]["score"], rows[-1]["score"])

    def test_cli_optimize_prints_ranked_results(self):
        payload = {
            "BTC": [build_bar(price, index) for index, price in enumerate((100, 101, 112, 113, 114))],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                rows = cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        "5",
                        "--data-path",
                        path,
                        "--optimize",
                        "--top",
                        "2",
                        "--strategy-grid",
                        "trend",
                        "--leverage-grid",
                        "2,3",
                        "--risk-grid",
                        "0.03",
                        "--btc-filter-grid",
                        "on,off",
                    ]
                )
        finally:
            os.remove(path)
        rendered = output.getvalue()
        self.assertIn("1. strategy=", rendered)
        self.assertIn("atr_trailing=", rendered)
        self.assertIn("atr_trail_exits=", rendered)
        self.assertEqual(len(rows), 8)

    def test_research_report_groups_existing_and_new_strategy_tracks(self):
        prices = [100.0] * 55 + [104.0, 105.0, 106.0]
        payload = {
            "BTC": [
                {
                    **build_bar(price, index),
                    "volume": 1600 if index >= 55 else 1000,
                }
                for index, price in enumerate(prices)
            ],
            "BNB": [build_bar(50 + index * 0.2, index) for index in range(len(prices))],
        }
        report = run_research_report(
            payload,
            derivatives_data_map={},
            coins=("BTC", "BNB"),
            max_days=len(prices),
            fee_bps=4.5,
        )
        rendered = "\n".join(format_research_report_lines(report))
        self.assertEqual(len(report["runnable"]), 6)
        self.assertIn("[optimize_existing]", rendered)
        self.assertIn("trend_unfiltered_reference:", rendered)
        self.assertIn("trend_filtered_control:", rendered)
        self.assertIn("trend_derivatives_filtered:", rendered)
        self.assertIn("[new_strategy]", rendered)
        self.assertIn("intraday_momentum_probe:", rendered)
        self.assertIn("funding_basis_monitor:", rendered)
        self.assertIn("[portfolio_correlation]", rendered)

    def test_cli_research_report_prints_dual_track_report(self):
        prices = [100.0] * 55 + [104.0, 105.0, 106.0]
        payload = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                report = cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        str(len(prices)),
                        "--data-path",
                        path,
                        "--research-report",
                    ]
                )
        finally:
            os.remove(path)
        rendered = output.getvalue()
        self.assertIn("Dual-track research report", rendered)
        self.assertIn("score_delta=", rendered)
        self.assertIn("new_strategy_pending", rendered)
        self.assertEqual(len(report["runnable"]), 6)

    def test_cli_research_report_accepts_derivatives_data_path(self):
        prices = [100.0] * 55 + [104.0, 105.0, 106.0]
        payload = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.0001,
                    "open_interest": 1000 + index,
                    "basis_pct": 0.1,
                }
                for index, bar in enumerate(payload["BTC"])
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as price_handle:
            json.dump(payload, price_handle)
            price_path = price_handle.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as derivatives_handle:
            json.dump(derivatives, derivatives_handle)
            derivatives_path = derivatives_handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        str(len(prices)),
                        "--data-path",
                        price_path,
                        "--derivatives-data-path",
                        derivatives_path,
                        "--research-report",
                    ]
                )
        finally:
            os.remove(price_path)
            os.remove(derivatives_path)
        rendered = output.getvalue()
        self.assertIn("funding_basis_monitor BTC:", rendered)
        self.assertIn("derivative_bars=58", rendered)

    def test_microstructure_replay_diagnostic_normalizes_l2_snapshots(self):
        snapshots = normalize_l2_snapshots(
            {
                "btc": [
                    {
                        "timestamp": 1,
                        "bids": [["99", "3"]],
                        "asks": [["101", "1"]],
                    }
                ]
            }
        )
        report = build_microstructure_diagnostic_report(snapshots)
        self.assertEqual(snapshots["BTC"][0]["spread"], 2.0)
        self.assertGreater(snapshots["BTC"][0]["book_imbalance"], 0)
        self.assertEqual(report[0]["snapshots"], 1)

    def test_legacy_strategy_uses_fixed_tp_policy(self):
        prices = [100.0] * 60 + [101.0, 100.8, 101.1, 101.0, 101.2]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        config = BacktestConfig(
            coins=("BTC",),
            strategy="legacy_unified",
            max_days=None,
            min_bars=50,
            btc_filter_enabled=False,
            intrabar_exit_enabled=True,
            price_position_filter_enabled=False,
            dead_cat_filter_enabled=False,
            max_hold_bars=2,
        )
        result = PortfolioBacktester(config=config).run(data_map)
        self.assertGreaterEqual(result.portfolio["trades"], 0)
        if result.trades:
            self.assertEqual(result.trades[0]["exit_policy"], "legacy_fixed_tpsl")

    def test_intrabar_exit_prefers_stop_first(self):
        data_map = {
            "BTC": [
                build_bar(100, 0),
                build_bar(101, 1),
                {
                    **build_bar(102, 2),
                    "high": 111,
                    "low": 94,
                    "close": 102,
                },
            ]
        }

        def build_signal(context):
            if context.current_bar["close"] != 101:
                return None
            return StrategySignal("long", tp=110, sl=95, score=5, reason="TEST_BUY")

        config = BacktestConfig(coins=("BTC",), max_days=None, min_bars=1, intrabar_exit_enabled=True)
        result = PortfolioBacktester(config=config, strategy=FakeStrategy(build_signal)).run(data_map)
        self.assertEqual(result.trades[0]["exit_reason"], "SL")
        self.assertEqual(result.trades[0]["exit"], 95.0)

    def test_compare_strategies_cli_outputs_comparison(self):
        prices = [100.0] * 60 + [101.0, 102.0, 103.0, 104.0]
        payload = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                results = cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        str(len(prices)),
                        "--data-path",
                        path,
                        "--compare-strategies",
                        "trend,legacy_unified",
                    ]
                )
        finally:
            os.remove(path)
        rendered = output.getvalue()
        self.assertIn("Comparison:", rendered)
        self.assertIn("legacy_unified:", rendered)
        self.assertIn("trend:", rendered)
        self.assertIn("legacy_unified", results)
        self.assertIn("trend", results)

    def test_alpha_forward_signed_return_handles_long_and_short(self):
        series = [build_bar(price, index) for index, price in enumerate((100.0, 110.0, 121.0))]
        self.assertAlmostEqual(_forward_signed_return(series, 0, 1, "long"), 10.0)
        self.assertAlmostEqual(_forward_signed_return(series, 0, 1, "short"), -10.0)

    def test_alpha_bucket_events_skips_missing_features(self):
        events = [
            {"feature_value": 2.0},
            {"feature_value": None},
            {"feature_value": 1.0},
            {"feature_value": 3.0},
        ]
        buckets = _bucket_events(events, 2)
        self.assertEqual(sorted(buckets), [1, 2])
        self.assertEqual(len(buckets[1]), 2)
        self.assertEqual(len(buckets[2]), 1)

    def test_alpha_report_runs_on_synthetic_ohlcv(self):
        btc_prices = [100.0 + index * 0.4 for index in range(100)]
        eth_prices = [50.0 + index * 0.3 for index in range(100)]
        data_map = {
            "BTC": [build_bar(price, index) for index, price in enumerate(btc_prices)],
            "ETH": [build_bar(price, index) for index, price in enumerate(eth_prices)],
        }
        report = run_alpha_report(
            data_map,
            coins=("BTC", "ETH"),
            max_days=100,
            alpha_set=("btc_regime_trend",),
            forward_bars=(1, 3),
            bucket_count=3,
            random_baseline_runs=5,
            fee_bps=4.5,
            slippage_bps=2.0,
        )
        self.assertEqual(report["alpha_set"], ("btc_regime_trend",))
        self.assertGreater(report["alphas"][0]["events"], 0)
        rendered = "\n".join(format_alpha_report_lines(report))
        self.assertIn("Alpha signal report", rendered)
        self.assertIn("[btc_regime_trend]", rendered)
        self.assertIn("random_delta=", rendered)

    def test_short_cycle_alpha_report_runs_on_synthetic_15m_ohlcv(self):
        prices = []
        price = 100.0
        for index in range(160):
            if index in (45, 90, 125):
                price += 4.0
            elif index in (70, 110, 145):
                price -= 4.5
            else:
                price += 0.15 if index % 6 < 3 else -0.08
            prices.append(price)
        data_map = {
            "BTC": [
                {
                    **build_bar(price, index),
                    "time": f"2026-01-01T{index // 4:02d}:{(index % 4) * 15:02d}:00",
                    "volume": 1000 + (600 if index in (45, 70, 90, 110, 125, 145) else index),
                }
                for index, price in enumerate(prices)
            ]
        }
        report = run_alpha_report(
            data_map,
            coins=("BTC",),
            max_days=160,
            alpha_set=(
                "intraday_breakout_continuation",
                "intraday_vwap_reversion",
                "intraday_volatility_expansion",
            ),
            forward_bars=(1, 3, 6, 12, 24),
            bucket_count=4,
            random_baseline_runs=5,
            report_type="short_cycle_15m",
            fee_bps=4.5,
            slippage_bps=2.0,
        )
        self.assertEqual(report["report_type"], "short_cycle_15m")
        events_by_name = {alpha["name"]: alpha["events"] for alpha in report["alphas"]}
        self.assertGreater(events_by_name["intraday_breakout_continuation"], 0)
        self.assertGreater(events_by_name["intraday_vwap_reversion"], 0)
        self.assertGreater(events_by_name["intraday_volatility_expansion"], 0)
        rendered = "\n".join(format_alpha_report_lines(report))
        self.assertIn("Alpha signal report (short_cycle_15m)", rendered)
        self.assertIn("[intraday_breakout_continuation]", rendered)

    def test_short_cycle_alpha_report_outputs_split_summary_and_gate(self):
        prices = []
        price = 100.0
        for index in range(9000):
            cycle = index % 24
            if cycle == 4:
                price += 2.5
            elif cycle == 12:
                price -= 3.0
            else:
                price += 0.08 if cycle < 12 else -0.06
            prices.append(price)
        data_map = {
            "BTC": [
                {
                    **build_bar(price, index),
                    "time": f"2026-01-01T{index // 4:02d}:{(index % 4) * 15:02d}:00",
                    "volume": 1000 + (400 if index % 24 in (4, 12) else index),
                }
                for index, price in enumerate(prices)
            ]
        }
        report = run_alpha_report(
            data_map,
            coins=("BTC",),
            max_days=9000,
            alpha_set=(
                "intraday_breakout_continuation",
                "intraday_vwap_reversion",
                "intraday_volatility_expansion",
            ),
            forward_bars=(12, 24),
            bucket_count=4,
            random_baseline_runs=5,
            report_type="short_cycle_15m",
            short_cycle_splits=("rolling_30", "train60_test30"),
            short_cycle_min_events=1,
            short_cycle_focus_alpha="intraday_vwap_reversion",
            fee_bps=4.5,
            slippage_bps=2.0,
        )
        short_cycle = report["short_cycle"]
        self.assertEqual(short_cycle["focus_alpha"], "intraday_vwap_reversion")
        self.assertTrue(short_cycle["splits"])
        self.assertIn("intraday_breakout_continuation", {row["alpha"] for row in short_cycle["splits"]})
        self.assertIn("intraday_vwap_reversion", {row["alpha"] for row in short_cycle["splits"]})
        self.assertIn("intraday_volatility_expansion", {row["alpha"] for row in short_cycle["splits"]})
        self.assertIn("promotion_gate", short_cycle)
        self.assertIn("passes_signal_gate", short_cycle["promotion_gate"])
        rendered = "\n".join(format_alpha_report_lines(report))
        self.assertIn("promotion_gate", rendered)
        self.assertIn("split=", rendered)

    def test_short_cycle_alpha_report_insufficient_split_data_does_not_crash(self):
        data_map = {"BTC": [build_bar(100.0 + index * 0.1, index) for index in range(50)]}
        report = run_alpha_report(
            data_map,
            coins=("BTC",),
            max_days=50,
            alpha_set=("intraday_vwap_reversion",),
            forward_bars=(12, 24),
            report_type="short_cycle_15m",
            short_cycle_splits=("rolling_30", "train60_test30"),
            short_cycle_min_events=100,
        )
        diagnostics = report["diagnostics"]
        self.assertIn("short_cycle_rolling_30_insufficient_bars", diagnostics)
        self.assertIn("short_cycle_train60_test30_insufficient_bars", diagnostics)
        self.assertFalse(report["short_cycle"]["promotion_gate"]["passes_signal_gate"])

    def test_short_cycle_promotion_gate_classifies_positive_and_negative_split_sets(self):
        positive_splits = [
            {"eligible": True, "events": 120, "net": {"mean": 0.03}, "random_delta": 0.02, "dominant_coin": "BTC", "dominant_bucket": 4},
            {"eligible": True, "events": 150, "net": {"mean": 0.02}, "random_delta": 0.01, "dominant_coin": "ETH", "dominant_bucket": 5},
            {"eligible": True, "events": 130, "net": {"mean": -0.01}, "random_delta": -0.005, "dominant_coin": "SOL", "dominant_bucket": 4},
        ]
        positive = _build_short_cycle_promotion_gate(positive_splits, min_events=100)
        self.assertTrue(positive["passes_signal_gate"])
        self.assertEqual(positive["eligible_splits"], 3)
        self.assertEqual(positive["recommended_next_step"], "deep_dive_vwap_reversion")

        negative_splits = [
            {"eligible": True, "events": 120, "net": {"mean": -0.02}, "random_delta": 0.01, "dominant_coin": "BTC", "dominant_bucket": 5},
            {"eligible": True, "events": 120, "net": {"mean": -0.03}, "random_delta": 0.02, "dominant_coin": "BTC", "dominant_bucket": 5},
            {"eligible": True, "events": 120, "net": {"mean": -0.01}, "random_delta": -0.01, "dominant_coin": "BTC", "dominant_bucket": 5},
        ]
        negative = _build_short_cycle_promotion_gate(negative_splits, min_events=100)
        self.assertFalse(negative["passes_signal_gate"])
        self.assertEqual(negative["recommended_next_step"], "collect_more_data_or_reject")

    def test_alpha_report_missing_derivatives_emits_diagnostics(self):
        prices = [100.0 + index * 0.2 for index in range(80)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        report = run_alpha_report(
            data_map,
            coins=("BTC",),
            max_days=80,
            alpha_set=("funding_extreme_reversion", "oi_expansion_confirmation"),
            forward_bars=(1,),
            random_baseline_runs=3,
        )
        diagnostics = report["diagnostics"]
        self.assertIn("funding_extreme_reversion_BTC_missing_funding_bars", diagnostics)
        self.assertIn("oi_expansion_confirmation_BTC_missing_open_interest_bars", diagnostics)

    def test_alpha_report_uses_derivatives_features_when_available(self):
        prices = [100.0 + index * 0.2 for index in range(90)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives_data_map = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.0001 if index < 35 else (0.001 if index % 2 == 0 else -0.001),
                    "open_interest": 1000.0 + index * 15.0,
                }
                for index, bar in enumerate(data_map["BTC"])
            ]
        }
        report = run_alpha_report(
            data_map,
            derivatives_data_map=derivatives_data_map,
            coins=("BTC",),
            max_days=90,
            alpha_set=("funding_extreme_reversion", "oi_expansion_confirmation"),
            forward_bars=(1,),
            random_baseline_runs=3,
        )
        events_by_name = {alpha["name"]: alpha["events"] for alpha in report["alphas"]}
        self.assertGreater(events_by_name["funding_extreme_reversion"], 0)
        self.assertGreater(events_by_name["oi_expansion_confirmation"], 0)

    def test_alpha_random_baseline_is_deterministic(self):
        prices = [100.0 + index * 0.4 for index in range(100)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        kwargs = {
            "coins": ("BTC",),
            "max_days": 100,
            "alpha_set": ("btc_regime_trend",),
            "forward_bars": (1,),
            "bucket_count": 4,
            "random_baseline_runs": 10,
            "random_seed": 42,
        }
        first = run_alpha_report(data_map, **kwargs)
        second = run_alpha_report(data_map, **kwargs)
        first_baseline = first["alphas"][0]["forward"][0]["random_baseline"]
        second_baseline = second["alphas"][0]["forward"][0]["random_baseline"]
        self.assertEqual(first_baseline, second_baseline)

    def test_cli_alpha_report_prints_expected_sections(self):
        prices = [100.0 + index * 0.5 for index in range(100)]
        payload = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        "100",
                        "--data-path",
                        path,
                        "--alpha-report",
                        "--alpha-set",
                        "btc_regime_trend",
                        "--forward-bars",
                        "1,3",
                        "--bucket-count",
                        "3",
                        "--random-baseline-runs",
                        "5",
                    ]
                )
        finally:
            os.remove(path)
        rendered = output.getvalue()
        self.assertIn("Alpha signal report", rendered)
        self.assertIn("[btc_regime_trend]", rendered)
        self.assertIn("buckets", rendered)

    def test_cli_short_cycle_alpha_report_prints_15m_sections(self):
        price = 100.0
        bars = []
        for index in range(160):
            price += 3.5 if index in (50, 95, 130) else (-3.0 if index in (75, 115, 145) else 0.1)
            bar = build_bar(price, index)
            bar["time"] = f"2026-01-01T{index // 4:02d}:{(index % 4) * 15:02d}:00"
            bar["volume"] = 1000 + (500 if index in (50, 75, 95, 115, 130, 145) else index)
            bars.append(bar)
        payload = {"BTC": bars}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        "160",
                        "--data-path",
                        path,
                        "--short-cycle-alpha-report",
                        "--short-cycle-splits",
                        "rolling_30,train60_test30",
                        "--short-cycle-min-events",
                        "1",
                        "--short-cycle-focus-alpha",
                        "intraday_vwap_reversion",
                        "--bucket-count",
                        "4",
                        "--random-baseline-runs",
                        "5",
                    ]
                )
        finally:
            os.remove(path)
        rendered = output.getvalue()
        self.assertIn("Alpha signal report (short_cycle_15m)", rendered)
        self.assertIn("[intraday_breakout_continuation]", rendered)
        self.assertIn("[intraday_vwap_reversion]", rendered)
        self.assertIn("[intraday_volatility_expansion]", rendered)
        self.assertIn("promotion_gate", rendered)

    def test_cli_trend_alpha_entry_flags_build_config(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "--coins",
                "BTC,ETH",
                "--enable-trend-alpha-entry",
                "--trend-alpha-mode",
                "combined",
                "--trend-alpha-score-boost",
                "2",
                "--trend-alpha-require-confirmation",
            ]
        )
        config = cli.build_config(args)
        self.assertTrue(config.trend_alpha_entry_enabled)
        self.assertEqual(config.trend_alpha_mode, "combined")
        self.assertEqual(config.trend_alpha_score_boost, 2)
        self.assertTrue(config.trend_alpha_require_confirmation)
        self.assertTrue(config.trend_alpha_block_crowded_entry)

    def test_cli_adaptive_atr_flags_build_config(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "--coins",
                "BTC",
                "--enable-atr-trailing",
                "--enable-adaptive-atr-trail",
                "--adaptive-atr-strong-adx",
                "40",
                "--adaptive-atr-strong-mult",
                "3.5",
                "--adaptive-atr-weak-mult",
                "1.25",
            ]
        )
        config = cli.build_config(args)
        self.assertTrue(config.adaptive_atr_trailing_enabled)
        self.assertEqual(config.adaptive_atr_strong_adx, 40.0)
        self.assertEqual(config.adaptive_atr_strong_mult, 3.5)
        self.assertEqual(config.adaptive_atr_weak_mult, 1.25)

    def test_cli_trend_evaluation_report_prints_gate(self):
        payload = {
            "BTC": [build_bar(100.0 + index, index) for index in range(70)],
            "ETH": [build_bar(50.0 + index, index) for index in range(70)],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--data-path",
                        path,
                        "--max-days",
                        "60",
                        "--trend-evaluation-report",
                        "--evaluation-windows",
                        "60",
                        "--enable-adaptive-atr-trail",
                    ]
                )
        finally:
            os.remove(path)
        self.assertIn("Trend robustness evaluation", output.getvalue())
        self.assertIn("Gate:", output.getvalue())
        self.assertNotIn("coins=BTC,ETH", output.getvalue())

    def test_cli_microstructure_report_prints_would_block_outcomes(self):
        payload = {
            "BTC": [
                {"timestamp": 1, "bids": [["99", "1"]], "asks": [["101", "5"]], "signal_direction": "long"},
                {"timestamp": 2, "bids": [["89", "1"]], "asks": [["91", "5"]], "signal_direction": "long"},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            path = handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--microstructure-report",
                        "--microstructure-data-path",
                        path,
                        "--microstructure-forward-steps",
                        "1",
                        "--microstructure-max-spread-bps",
                        "50",
                        "--microstructure-min-top-depth-usd",
                        "0",
                    ]
                )
        finally:
            os.remove(path)
        self.assertIn("Microstructure guard outcome report", output.getvalue())
        self.assertIn("would_block=1", output.getvalue())

    def test_cli_oi_entry_filter_flags_build_config(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "--coins",
                "BTC,ETH",
                "--enable-oi-entry-filter",
                "--oi-entry-lookback",
                "7",
                "--oi-entry-min-change-pct",
                "1.5",
                "--oi-entry-min-price-move-pct",
                "0.3",
                "--disable-oi-entry-block-late-crowded",
            ]
        )
        config = cli.build_config(args)
        self.assertTrue(config.oi_entry_filter_enabled)
        self.assertEqual(config.oi_entry_filter_lookback, 7)
        self.assertEqual(config.oi_entry_filter_min_change_pct, 1.5)
        self.assertEqual(config.oi_entry_filter_min_price_move_pct, 0.3)
        self.assertFalse(config.oi_entry_filter_block_late_crowded)

    def test_carry_report_runs_funding_and_basis_backtests(self):
        derivatives_data_map = {
            "BTC": [
                {
                    "time": index,
                    "funding_rate": 0.00012 if index < 5 else 0.00001,
                    "basis_pct": 0.08 if index < 5 else 0.005,
                }
                for index in range(10)
            ]
        }
        report = run_carry_report(
            derivatives_data_map,
            config=CarryConfig(
                coins=("BTC",),
                max_days=10,
                fee_bps=0.0,
                slippage_bps=0.0,
                funding_entry_abs=0.00008,
                basis_entry_abs_pct=0.04,
            ),
        )
        rows = {(row["name"], row["coin"]): row for row in report["rows"]}
        self.assertGreater(rows[("funding_carry", "BTC")]["trades"], 0)
        self.assertGreater(rows[("basis_compression", "BTC")]["trades"], 0)
        rendered = "\n".join(format_carry_report_lines(report))
        self.assertIn("Carry / Funding / Basis report", rendered)
        self.assertIn("[funding_carry:BTC]", rendered)

    def test_carry_report_missing_data_produces_paper_plan(self):
        report = run_carry_report(
            {},
            config=CarryConfig(coins=("BTC",), max_days=10),
        )
        self.assertTrue(report["paper_trade_plan"])
        self.assertIn("missing_derivatives_data", report["rows"][0]["diagnostics"])

    def test_cli_carry_report_prints_expected_sections(self):
        derivatives = {
            "BTC": [
                {
                    "time": index,
                    "funding_rate": 0.00012 if index < 5 else 0.00001,
                    "basis_pct": 0.08 if index < 5 else 0.005,
                }
                for index in range(10)
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as derivatives_handle:
            json.dump(derivatives, derivatives_handle)
            derivatives_path = derivatives_handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        "10",
                        "--derivatives-data-path",
                        derivatives_path,
                        "--carry-report",
                        "--fee-bps",
                        "0",
                        "--slippage-bps",
                        "0",
                    ]
                )
        finally:
            os.remove(derivatives_path)
        rendered = output.getvalue()
        self.assertIn("Carry / Funding / Basis report", rendered)
        self.assertIn("[basis_compression:BTC]", rendered)

    def test_cli_trend_position_control_uses_reduce_mode(self):
        prices = [100.0 + index * 0.1 for index in range(45)]
        payload = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.00001 if index < 35 else 0.0002,
                    "basis_pct": -0.05 if index >= 35 else 0.0,
                }
                for index, bar in enumerate(payload["BTC"])
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as price_handle:
            json.dump(payload, price_handle)
            price_path = price_handle.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as derivatives_handle:
            json.dump(derivatives, derivatives_handle)
            derivatives_path = derivatives_handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                result = cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        "45",
                        "--data-path",
                        price_path,
                        "--derivatives-data-path",
                        derivatives_path,
                        "--strategy",
                        "trend",
                        "--enable-trend-position-control",
                        "--derivatives-crowding-funding-z-threshold",
                        "0.5",
                    ]
                )
        finally:
            os.remove(price_path)
            os.remove(derivatives_path)
        self.assertTrue(result.config.derivatives_crowding_exit_enabled)
        self.assertEqual(result.config.derivatives_crowding_action, "reduce")
        self.assertEqual(result.config.derivatives_crowding_reduce_fraction, 0.75)

    def test_funding_trend_report_classifies_short_term_context(self):
        prices = [100.0 + index * 0.2 for index in range(70)]
        data_map = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives_data_map = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.00001 if index < 35 else 0.0002,
                    "basis_pct": 0.04,
                }
                for index, bar in enumerate(data_map["BTC"])
            ]
        }
        report = run_funding_trend_report(
            data_map,
            derivatives_data_map,
            config=CarryConfig(
                coins=("BTC",),
                max_days=70,
                trend_forward_days=(1, 3),
                trend_funding_z_threshold=0.5,
            ),
        )
        self.assertGreater(report["rows"][0]["signals"], 0)
        self.assertIsNotNone(report["rows"][0]["latest_context"])
        labels = {row["label"] for row in report["rows"][0]["labels"]}
        self.assertTrue(labels)
        rendered = "\n".join(format_funding_trend_report_lines(report))
        self.assertIn("Funding / Basis short-term trend report", rendered)
        self.assertIn("latest:", rendered)
        self.assertIn("forward=1d", rendered)

    def test_cli_funding_trend_report_prints_expected_sections(self):
        prices = [100.0 + index * 0.2 for index in range(70)]
        payload = {"BTC": [build_bar(price, index) for index, price in enumerate(prices)]}
        derivatives = {
            "BTC": [
                {
                    "time": bar["time"],
                    "funding_rate": 0.00001 if index < 35 else 0.0002,
                    "basis_pct": 0.04,
                }
                for index, bar in enumerate(payload["BTC"])
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as price_handle:
            json.dump(payload, price_handle)
            price_path = price_handle.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as derivatives_handle:
            json.dump(derivatives, derivatives_handle)
            derivatives_path = derivatives_handle.name
        try:
            output = io.StringIO()
            with redirect_stdout(output):
                cli.main(
                    [
                        "--coins",
                        "BTC",
                        "--max-days",
                        "70",
                        "--data-path",
                        price_path,
                        "--derivatives-data-path",
                        derivatives_path,
                        "--funding-trend-report",
                        "--trend-forward-days",
                        "1,3",
                        "--trend-funding-z-threshold",
                        "0.5",
                    ]
                )
        finally:
            os.remove(price_path)
            os.remove(derivatives_path)
        rendered = output.getvalue()
        self.assertIn("Funding / Basis short-term trend report", rendered)
        self.assertIn("[BTC]", rendered)


if __name__ == "__main__":
    unittest.main()
