import os
import sys
import unittest

import pandas as pd


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtest.backtesting_py_live38_4h_path_efficiency import build_signals, candidate_grid  # noqa: E402


class PathEfficiencyTests(unittest.TestCase):
    def test_grid_is_bounded(self):
        self.assertEqual(len(candidate_grid()), 12)

    def test_signal_never_holds_more_than_one_coin(self):
        index = pd.date_range("2026-01-01", periods=120, freq="4h", tz="UTC")
        closes = pd.DataFrame({"A": range(100, 220), "B": range(100, 340, 2), "C": [100] * 120}, index=index)
        signals = build_signals(closes, efficiency_window=12, min_efficiency=0.4, switch_margin=0.01)
        self.assertTrue((signals.sum(axis=1) <= 1.0).all())


if __name__ == "__main__":
    unittest.main()
