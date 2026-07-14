from types import SimpleNamespace
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.turnover import run_intraday_turnover_report
from trading_strategy.backtest.types import BacktestConfig


class TurnoverReportTest(unittest.TestCase):
    @patch("trading_strategy.backtest.turnover.PortfolioBacktester")
    def test_report_builds_candidate_matrix_and_excludes_baseline_from_promotion(self, mock_backtester):
        result = SimpleNamespace(
            trades=[
                {
                    "entry": 100.0,
                    "exit": 101.0,
                    "size": 1.0,
                    "hold_bars": 2,
                    "mfe_r": 1.0,
                    "mae_r": -0.5,
                    "exit_reason": "TP",
                    "direction": "long",
                    "pnl": 1.0,
                }
            ],
            portfolio={
                "starting_balance": 1000.0,
                "avg_hold_bars": 2.0,
                "gross_pnl_pct": 0.1,
                "total_pnl_pct": 0.05,
                "total_cost_pct": 0.05,
                "max_drawdown": 1.0,
                "exit_reason_counts": {"TP": 1},
                "direction_summary": {"long": {"trades": 1}, "short": {"trades": 0}},
            },
        )
        mock_backtester.return_value.run.return_value = result
        report = run_intraday_turnover_report(
            {},
            config=BacktestConfig(coins=("BTC",), strategy="intraday_momentum"),
            min_trades=1,
        )
        self.assertEqual(
            {row["candidate"] for row in report["candidates"]},
            {
                "baseline",
                "cooldown_8",
                "btc_filter",
                "cooldown_8_btc_filter",
                "atr_2pct",
                "cooldown_8_atr_2pct",
            },
        )
        self.assertNotIn("baseline", report["promotion_gate"]["passing_candidates"])
