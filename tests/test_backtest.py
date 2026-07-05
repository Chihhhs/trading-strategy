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
from trading_strategy.backtest.optimizer import run_parameter_sweep
from trading_strategy.backtest.portfolio import PortfolioBacktester
from trading_strategy.backtest.types import BacktestConfig, StrategySignal


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
        self.assertIn("BTC:", rendered)
        self.assertEqual(result.coin_results[0].coin, "BTC")

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
        )
        self.assertEqual(len(rows), 8)
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
        self.assertEqual(len(rows), 4)


if __name__ == "__main__":
    unittest.main()
