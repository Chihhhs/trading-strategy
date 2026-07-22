import os
import sys
import unittest

import pandas as pd


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtest.analyze_live38_4h_state_classification import (  # noqa: E402
    STATES,
    classify_states,
    summarize_segment,
)


class StateClassificationTests(unittest.TestCase):
    def test_current_volume_does_not_change_earlier_states(self):
        index = pd.RangeIndex(80)
        closes = pd.DataFrame({"A": [100.0 + value for value in index]}, index=index)
        volumes = pd.DataFrame({"A": [100.0] * len(index)}, index=index)
        before = classify_states(closes, volumes)
        volumes.iloc[-1, 0] = 100000.0
        after = classify_states(closes, volumes)
        pd.testing.assert_series_equal(before.iloc[:-1, 0], after.iloc[:-1, 0])

    def test_summary_uses_only_known_states(self):
        index = pd.RangeIndex(100)
        closes = pd.DataFrame({"A": [100.0 + value for value in index]}, index=index)
        volumes = pd.DataFrame({"A": [100.0 + value % 3 for value in index]}, index=index)
        states = classify_states(closes, volumes)
        result = summarize_segment(closes, states, 0, len(index))
        self.assertEqual(set(result["coin_opportunities"]), set(STATES))
        self.assertEqual(set(result["strongest_selector"]), set(STATES))
        self.assertEqual(set(result["transitions"]), set(STATES))
        self.assertTrue(result["strongest_selector_transitions"])


if __name__ == "__main__":
    unittest.main()
