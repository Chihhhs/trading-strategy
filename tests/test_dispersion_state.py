import os
import sys
import unittest

import pandas as pd


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtest.backtesting_py_live38_4h_dispersion_state import (  # noqa: E402
    build_dispersion_signals,
    candidates,
)


class DispersionStateTests(unittest.TestCase):
    def test_candidate_grid_is_predeclared_and_has_no_baseline(self):
        rows = candidates()
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row["min_dispersion_ratio"] >= 1.0 for row in rows))

    def test_selector_holds_at_most_one_coin(self):
        index = pd.date_range("2026-01-01", periods=140, freq="4h", tz="UTC")
        closes = pd.DataFrame(
            {
                "FAST": [100.0 + value * 0.8 for value in range(140)],
                "SLOW": [100.0 + value * 0.2 for value in range(140)],
                "FLAT": [100.0 for _ in range(140)],
            },
            index=index,
        )
        signals = build_dispersion_signals(
            closes,
            upper_quantile=0.75,
            state_lookback=42,
            min_dispersion_ratio=1.0,
        )
        self.assertTrue((signals.abs().sum(axis=1) <= 1.0).all())


if __name__ == "__main__":
    unittest.main()
