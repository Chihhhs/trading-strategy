from tests.live_test_support import (
    cancel_orphan_orders,
    ensure_position_protection,
    helpers,
    patch,
    unittest,
)


class LiveProtectionTest(unittest.TestCase):
    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_cancel_orphan_orders_cancels_unknown_open_order(self, mock_cancel_hl_order, mock_record_trade_event):
        mock_cancel_hl_order.return_value = {"status": "ok", "message": "canceled", "oid": 55, "coin": "BTC"}
        state = {
            "managed_orders": [{"oid": 55, "coin": "BTC", "order_role": "orphan_unknown"}],
            "_orphan_orders": [{"oid": 55, "coin": "BTC", "order_role": "orphan_unknown"}],
            "_frontend_open_orders": [{"oid": 55, "coin": "BTC"}],
            "_exchange_open_orders_count": 1,
        }
        summary = cancel_orphan_orders(state)
        self.assertEqual(summary["orphan_orders_detected_count"], 1)
        self.assertEqual(summary["orphan_orders_canceled_count"], 1)
        self.assertEqual(state["managed_orders"], [])
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("orphan_order_cancel_attempted", event_names)
        self.assertIn("orphan_order_canceled", event_names)

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_replaces_trend_sl_when_more_protective(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        mock_cancel_hl_order.return_value = {"status": "ok", "message": "canceled", "oid": 2, "coin": "ETH"}
        mock_place_hl_sl_order.return_value = {
            "ok": True,
            "message": None,
            "tp_order": None,
            "sl_order": {"oid": 3, "status": "ok", "trigger_px": 1700.0},
        }
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 1755.5,
                    "size": 0.0454,
                    "sl": 1674.0,
                    "current_price": 1878.0,
                    "sig": "TREND_BUY",
                    "initial_risk": 81.5,
                    "sl_stage": 0,
                    "best_price": 1755.5,
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "1674.0"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 1)
        self.assertEqual(state["positions"][0]["sl_order"]["oid"], 3)
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("sl_replace_attempted", event_names)
        self.assertIn("sl_replaced", event_names)
        self.assertEqual(state["positions"][0]["sl_stage"], 2)

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_does_not_replace_sl_when_cancel_fails(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        mock_cancel_hl_order.return_value = {"status": "error", "message": "cancel failed", "oid": 2, "coin": "ETH"}
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 1755.5,
                    "size": 0.0454,
                    "sl": 1700.0,
                    "sig": "TREND_BUY",
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "1674.0"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 0)
        self.assertEqual(summary["unprotected_positions_count"], 1)
        self.assertEqual(mock_place_hl_sl_order.call_count, 0)
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("sl_replace_failed", event_names)

    def test_compute_dynamic_sl_target_moves_to_break_even_at_one_r(self):
        pos = {
            "coin": "ETH",
            "direction": "long",
            "entry": 100.0,
            "sl": 90.0,
            "current_price": 110.0,
            "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
            "initial_risk": 10.0,
            "sl_stage": 0,
            "best_price": 100.0,
        }
        target = helpers.compute_dynamic_sl_target(pos)
        self.assertEqual(target["stage"], 1)
        self.assertEqual(target["sl"], 100.0)

    def test_compute_dynamic_sl_target_moves_to_half_r_at_one_point_five_r(self):
        pos = {
            "coin": "ETH",
            "direction": "long",
            "entry": 100.0,
            "sl": 90.0,
            "current_price": 115.0,
            "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
            "initial_risk": 10.0,
            "sl_stage": 0,
            "best_price": 100.0,
        }
        target = helpers.compute_dynamic_sl_target(pos)
        self.assertEqual(target["stage"], 2)
        self.assertEqual(target["sl"], 105.0)

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_does_not_replace_trend_sl_before_one_r(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        _mock_record_trade_event,
    ):
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 100.0,
                    "sl": 90.0,
                    "current_price": 108.0,
                    "size": 1.0,
                    "sig": "TREND_BUY",
                    "initial_risk": 10.0,
                    "sl_stage": 0,
                    "best_price": 108.0,
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "90.0"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 0)
        self.assertEqual(summary["unprotected_positions_count"], 0)
        self.assertEqual(mock_cancel_hl_order.call_count, 0)
        self.assertEqual(mock_place_hl_sl_order.call_count, 0)

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_tpsl_orders")
    def test_ensure_position_protection_repairs_missing_orders(self, mock_place_hl_tpsl_orders, mock_record_trade_event):
        mock_place_hl_tpsl_orders.return_value = {
            "ok": True,
            "tp_order": {
                "oid": 1,
                "status": "ok",
                "requested_trigger_px": 1874.03,
                "trigger_px": 1874.0,
                "requested_limit_px": 1781.07,
                "limit_px": 1781.0,
                "tick_size": 0.1,
                "price_source": "l2_book",
                "rejection_reason": None,
            },
            "sl_order": {
                "oid": 2,
                "status": "ok",
                "requested_trigger_px": 1674.03,
                "trigger_px": 1674.0,
                "requested_limit_px": 1590.94,
                "limit_px": 1590.9,
                "tick_size": 0.1,
                "price_source": "l2_book",
                "rejection_reason": None,
            },
            "message": None,
            "order_side": "sell",
            "price_source": "l2_book",
        }
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 1755.5,
                    "size": 0.0454,
                    "tp": 1874.0,
                    "sl": 1674.0,
                    "position_source": "exchange_adopted",
                }
            ],
            "_frontend_open_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["tpsl_missing_count"], 1)
        self.assertEqual(summary["tpsl_repaired_count"], 1)
        self.assertEqual(state["positions"][0]["protection_status"], "protected")
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("tpsl_missing_detected", event_names)
        self.assertIn("tpsl_repaired", event_names)
        attempted_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "tpsl_repair_attempted")
        self.assertEqual(attempted_call.kwargs["tp_requested_trigger_px"], 1874.03)
        self.assertEqual(attempted_call.kwargs["sl_trigger_px"], 1674.0)
        repaired_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "tpsl_repaired")
        self.assertEqual(repaired_call.kwargs["order_side"], "sell")
        self.assertEqual(repaired_call.kwargs["price_source"], "l2_book")

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    def test_ensure_position_protection_accepts_sl_only_for_trend_policy(self, mock_record_trade_event):
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 1755.5,
                    "size": 0.0454,
                    "sl": 1674.0,
                    "sig": "TREND_BUY",
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl"}
            ],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["tpsl_missing_count"], 0)
        self.assertEqual(summary["protection_missing_count"], 0)
        self.assertEqual(state["positions"][0]["protection_status"], "protected")
        self.assertEqual(mock_record_trade_event.call_count, 0)

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_tpsl_orders")
    def test_ensure_position_protection_requires_tp_and_sl_for_fixed_policy(
        self,
        mock_place_hl_tpsl_orders,
        mock_record_trade_event,
    ):
        mock_place_hl_tpsl_orders.return_value = {
            "ok": True,
            "message": None,
            "tp_order": {"oid": 41, "status": "ok", "trigger_px": 110.0},
            "sl_order": {"oid": 42, "status": "ok", "trigger_px": 95.0},
        }
        state = {
            "positions": [
                {
                    "coin": "BTC",
                    "direction": "long",
                    "entry": 100.0,
                    "tp": 110.0,
                    "sl": 95.0,
                    "size": 1.0,
                    "sig": "FVG_LONG",
                    "exit_policy": {
                        "name": "fixed_tpsl",
                        "requires_tp": True,
                        "requires_sl": True,
                        "protection_event_prefix": "tpsl",
                    },
                }
            ],
            "_frontend_open_orders": [
                {"oid": 7, "coin": "BTC", "reduceOnly": True, "tpsl": "sl", "triggerPx": "95.0"}
            ],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["protection_missing_count"], 1)
        self.assertEqual(summary["tpsl_missing_count"], 1)
        self.assertEqual(summary["tpsl_repaired_count"], 1)
        self.assertEqual(state["positions"][0]["protection_status"], "protected")
        self.assertEqual(state["positions"][0]["tp_order"]["oid"], 41)
        self.assertEqual(state["positions"][0]["sl_order"]["oid"], 42)
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("tpsl_missing_detected", event_names)
        self.assertIn("tpsl_repair_attempted", event_names)
        self.assertIn("tpsl_repaired", event_names)
