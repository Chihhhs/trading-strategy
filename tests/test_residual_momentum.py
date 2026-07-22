import os
import sys
import unittest

import pandas as pd


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backtest.analyze_live38_4h_residual_momentum import build_scores, summarize_segment  # noqa: E402


class ResidualMomentumTests(unittest.TestCase):
    def _closes(self):
        index = pd.RangeIndex(100)
        return pd.DataFrame(
            {
                "BTC": [100.0 + value for value in index],
                "ALT": [100.0 + value * 1.2 for value in index],
            },
            index=index,
        )

    def test_future_change_does_not_change_past_scores(self):
        closes = self._closes()
        before = build_scores(closes)
        closes.iloc[-1, 1] *= 10.0
        after = build_scores(closes)
        for name in before:
            pd.testing.assert_frame_equal(before[name].iloc[:-1], after[name].iloc[:-1])

    def test_summary_contains_all_score_modes(self):
        closes = self._closes()
        result = summarize_segment(closes, build_scores(closes), 0, len(closes))
        self.assertEqual(set(result), {"raw", "btc_beta_residual", "cross_sectional_excess"})


if __name__ == "__main__":
    unittest.main()
