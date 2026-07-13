from tests.live_test_support import unittest

from trading_strategy.live.observations import (
    advance_signal_observations,
    record_signal_observation,
    summarize_signal_observations,
)


def build_bar(time, close):
    return {"time": time, "open": close, "high": close + 1, "low": close - 1, "close": close}


class LiveObservationTest(unittest.TestCase):
    def test_record_signal_observation_keeps_full_context_and_pending_horizons(self):
        state = {}
        observation = record_signal_observation(
            state,
            coin="BTC",
            signal={"direction": "long", "score": 5, "reason": "TREND_BUY"},
            window=[build_bar(1, 100.0)],
            derivatives_context={"funding_rate": 0.0001, "basis_pct": 0.02, "open_interest": 123.0},
            microstructure_context={"allowed": True, "reason": "microstructure_ok", "spread_bps": 2.0, "top_depth_usd": 2000.0, "book_imbalance": 0.1},
            horizons=(1, 3, 6),
        )
        self.assertEqual(observation["entry_bar_time"], 1)
        self.assertEqual(observation["open_interest"], 123.0)
        self.assertEqual(observation["would_block"], False)
        self.assertEqual(len(state["_signal_observations_pending"]), 1)
        summary = summarize_signal_observations(state, min_samples=30)
        self.assertEqual(summary["signals_observed"], 1)
        self.assertEqual(summary["remaining_signals"], 29)

    def test_advance_signal_observations_records_signed_forward_outcomes_and_completes(self):
        state = {}
        record_signal_observation(
            state,
            coin="BTC",
            signal={"direction": "short", "score": -5, "reason": "TREND_SELL"},
            window=[build_bar(1, 100.0)],
            derivatives_context={},
            microstructure_context={"allowed": False, "reason": "microstructure_spread_too_wide"},
            horizons=(1, 3),
        )
        outcomes = advance_signal_observations(
            state,
            {"BTC": [build_bar(1, 100.0), build_bar(2, 95.0), build_bar(3, 94.0), build_bar(4, 90.0)]},
        )
        self.assertEqual([item["forward_bars"] for item in outcomes], [1, 3])
        self.assertEqual(outcomes[0]["forward_return_pct"], 5.0)
        self.assertEqual(outcomes[1]["forward_return_pct"], 10.0)
        self.assertEqual(state["_signal_observations_pending"], [])
        self.assertEqual(summarize_signal_observations(state)["outcomes_observed"], 2)
