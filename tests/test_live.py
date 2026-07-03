import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy import live


class LiveHelpersTest(unittest.TestCase):
    def test_summarize_hl_order_result_filled(self):
        result = {
            "status": "ok",
            "response": {"data": {"statuses": [{"filled": {"oid": 123}}]}},
        }
        summary = live.summarize_hl_order_result(result)
        self.assertEqual(summary["order_status"], "filled")
        self.assertEqual(summary["oid"], 123)

    def test_normalize_order_status_unknown_without_oid(self):
        summary = {"order_status": "unknown", "oid": None}
        self.assertEqual(live.normalize_order_status(summary, None), "unknown")

    def test_place_tpsl_result_shape(self):
        order = {
            "status": "ok",
            "oid": 11,
            "trigger_px": 100.0,
            "limit_px": 99.0,
            "size": 1.5,
            "is_trigger": True,
            "reduce_only": True,
            "tpsl": "sl",
            "verify_status": "open",
        }
        ref = live.build_order_ref(order)
        self.assertEqual(ref["oid"], 11)
        self.assertEqual(ref["tpsl"], "sl")
        self.assertTrue(ref["reduce_only"])

    def test_sync_state_with_exchange_positions_removes_stale(self):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {
                "positions": [
                    {
                        "coin": "IOTA",
                        "entry_oid": None,
                        "entry_time": "2026-07-02T23:47:02.163776",
                    }
                ]
            }
            synced = live.sync_state_with_exchange_positions(
                state,
                {"assetPositions": []},
                [],
            )
            self.assertEqual(synced["positions"], [])
        finally:
            live.config.set_mode(old_mode)


if __name__ == "__main__":
    unittest.main()
