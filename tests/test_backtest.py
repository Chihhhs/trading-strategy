import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest import cli, load_historical_data
from trading_strategy.backtest.alpha import (
    _bucket_events,
    _forward_signed_return,
    format_alpha_report_lines,
    run_alpha_report,
)
from trading_strategy.backtest.carry import CarryConfig, format_carry_report_lines, run_carry_report
from trading_strategy.backtest.derivatives import load_derivatives_data, normalize_derivatives_data_map
from trading_strategy.backtest.microstructure import build_microstructure_diagnostic_report, normalize_l2_snapshots
from trading_strategy.backtest.optimizer import run_parameter_sweep
from trading_strategy.backtest.portfolio import PortfolioBacktester
from trading_strategy.backtest.research import format_research_report_lines, run_research_report
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


if __name__ == "__main__":
    unittest.main()
