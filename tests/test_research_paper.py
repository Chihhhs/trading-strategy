import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.live.research_paper import (  # noqa: E402
    INTERVAL_MS,
    _empty_state,
    _validate_replay_continuity,
    compute_selector_decision,
    compute_selector_decisions,
    forward_gate_status,
    run_once,
)


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
            bars.append({"time": index * INTERVAL_MS, "open": close, "close": close, "volume": volume})
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

    def test_unseen_decisions_are_chronological(self):
        rows = _bars(("FAST", "SLOW", "FLAT"))
        after = rows["FAST"][-4]["time"]
        decisions = compute_selector_decisions(rows, "30", initial_incumbent="FAST", after_bar_time=after)
        self.assertEqual([row["bar_time"] for row in decisions], [bar["time"] for bar in rows["FAST"][-3:]])

    def test_replay_gap_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "paper replay history gap"):
            _validate_replay_continuity(1000, [{"bar_time": 1000 + INTERVAL_MS * 2}])

    def test_run_once_rejects_regressed_cache(self):
        rows = _bars(("FAST", "SLOW", "FLAT"))
        state = _empty_state("30", 50.0)
        state["last_processed_bar"] = rows["FAST"][-1]["time"] + INTERVAL_MS
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with (
                patch("trading_strategy.live.research_paper._state_path", return_value=state_path),
                patch("trading_strategy.live.research_paper._universe", return_value=("FAST", "SLOW", "FLAT")),
                patch("trading_strategy.live.research_paper._fetch_completed_bars", return_value=rows),
            ):
                with self.assertRaisesRegex(RuntimeError, "paper replay data regressed"):
                    run_once("30", capital=50.0)

    def test_run_once_replays_each_missed_bar_at_next_open(self):
        rows = _bars(("FAST", "SLOW", "FLAT"))
        state = _empty_state("30", 50.0)
        state.update(
            {
                "last_processed_bar": rows["FAST"][-4]["time"],
                "paper_start_bar": rows["FAST"][-10]["time"],
                "completed_bars_observed": 10,
                "last_decision": {"target": "FAST"},
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            events_path = Path(directory) / "events.jsonl"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with (
                patch("trading_strategy.live.research_paper._state_path", return_value=state_path),
                patch("trading_strategy.live.research_paper._events_path", return_value=events_path),
                patch("trading_strategy.live.research_paper._universe", return_value=("FAST", "SLOW", "FLAT")),
                patch("trading_strategy.live.research_paper._fetch_completed_bars", return_value=rows),
                patch(
                    "trading_strategy.live.research_paper.get_current_prices",
                    return_value={coin: bars[-1]["close"] for coin, bars in rows.items()},
                ),
            ):
                result = run_once("30", capital=50.0)
                repeated = run_once("30", capital=50.0)
            saved = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(result["processed_new_bars"], 3)
        self.assertEqual(result["historical_replay_bars"], 2)
        self.assertEqual(saved["completed_bars_observed"], 13)
        self.assertEqual(saved["last_processed_bar"], rows["FAST"][-1]["time"])
        self.assertEqual(saved["entries"], 1)
        self.assertEqual(saved["position"]["price_source"], "next_bar_open_replay")
        self.assertEqual(saved["position"]["execution_bar_time"], rows["FAST"][-2]["time"])
        self.assertEqual(repeated["processed_new_bars"], 0)
        self.assertEqual(saved["completed_bars_observed"], 13)


if __name__ == "__main__":
    unittest.main()
