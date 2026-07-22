import os
import sys
import unittest

import pandas as pd


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtest.backtesting_py_live38_4h_state_transition import build_signals  # noqa: E402


class StateTransitionTests(unittest.TestCase):
    def test_signal_holds_at_most_one_coin(self):
        index = pd.RangeIndex(100)
        closes = pd.DataFrame(
            {
                "A": [100.0 + value for value in index],
                "B": [100.0 + value * 0.5 for value in index],
            },
            index=index,
        )
        volumes = pd.DataFrame({"A": [100.0] * 100, "B": [100.0] * 100}, index=index)
        signals = build_signals(closes, volumes)
        self.assertTrue((signals.sum(axis=1) <= 1.0).all())


if __name__ == "__main__":
    unittest.main()
