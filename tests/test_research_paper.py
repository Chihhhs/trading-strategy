import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.live.research_paper import compute_selector_decision, forward_gate_status  # noqa: E402


def _bars(coins, count=230):
    rows = {}
    for coin in coins:
        bars = []
        for index in range(count):
            if coin == "FAST":
                close = 100.0 + index * 0.8
                volume = 100.0 + (50.0 if index == count - 1 else 0.0)
            elif coin == "SLOW":
                close = 100.0 + index * 0.2
                volume = 100.0
            else:
                close = 100.0
                volume = 100.0
            bars.append({"time": index * 4 * 60 * 60 * 1000, "close": close, "volume": volume})
        rows[coin] = bars
    return rows


class ResearchPaperSelectorTests(unittest.TestCase):
    def test_route30_is_single_target_and_uses_momentum_leader(self):
        decision = compute_selector_decision(_bars(("FAST", "SLOW", "FLAT")), "30")
        self.assertEqual(decision["target"], "FAST")
        self.assertLessEqual(len(decision["ranked"]), 5)
        self.assertEqual(decision["common_bars"], 230)

    def test_route31_requires_high_volume_state(self):
        rows = _bars(("FAST", "SLOW", "FLAT"))
        # Make FAST fail the current high-volume state while SLOW confirms it.
        for bar in rows["FAST"][-24:-1]:
            bar["volume"] = 100.0
        rows["FAST"][-1]["volume"] = 1.0
        for bar in rows["SLOW"][-24:-1]:
            bar["volume"] = 100.0
        rows["SLOW"][-1]["volume"] = 1000.0
        decision = compute_selector_decision(rows, "31")
        self.assertEqual(decision["target"], "SLOW")
        self.assertGreaterEqual(decision["volume_ratio"], 1.10)

    def test_forward_gate_never_authorizes_execution(self):
        state = {
            "initial_capital": 50.0,
            "completed_bars_observed": 300,
            "exits": 20,
            "skipped_entries_below_min_order": 0,
            "max_drawdown_pct": -10.0,
            "last_snapshot": {"equity": 55.0},
        }
        result = forward_gate_status(state)
        self.assertTrue(result["ready_for_manual_review"])
        self.assertFalse(result["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
