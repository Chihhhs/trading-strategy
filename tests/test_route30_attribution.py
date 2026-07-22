import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtest.analyze_live38_route30_trades import summarize  # noqa: E402


class Route30AttributionTests(unittest.TestCase):
    def test_giveback_share_uses_only_losing_pnl(self):
        trades = [
            {"failure_class": "giveback_loss", "exit_reason": "trend_failure", "net_pnl_usd": -2.0, "gross_return_pct": -5.0, "mfe_pct": 3.0, "giveback_pct_points": 8.0},
            {"failure_class": "initial_failure", "exit_reason": "trend_failure", "net_pnl_usd": -1.0, "gross_return_pct": -2.0, "mfe_pct": 0.5, "giveback_pct_points": 2.5},
            {"failure_class": "clean_winner", "exit_reason": "stronger_selector", "net_pnl_usd": 4.0, "gross_return_pct": 8.0, "mfe_pct": 9.0, "giveback_pct_points": 1.0},
        ]
        result = summarize(trades)
        self.assertAlmostEqual(result["loss_pnl_from_giveback_pct"], 200.0 / 3.0)
        self.assertEqual(result["winners"], 1)


if __name__ == "__main__":
    unittest.main()
