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
    def test_ensure_position_protection_marks_ambiguous_as_unprotected_without_cancel_or_replace(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 100.0,
                    "size": 1.0,
                    "sl": 90.0,
                    "position_source": "exchange_adopted",
                    "sig": "TREND_BUY",
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "90.0"},
                {"oid": 3, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "89.9"},
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(state["positions"][0]["protection_status"], "ambiguous_protection")
        self.assertEqual(summary["ambiguous_protection_count"], 1)
        self.assertEqual(summary["unprotected_positions_count"], 1)
        mock_cancel_hl_order.assert_not_called()
        mock_place_hl_sl_order.assert_not_called()
        event_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "sl_ambiguous_detected")
        self.assertEqual(event_call.kwargs["coin"], "ETH")
        self.assertEqual(event_call.kwargs["failure_reason"], "multiple_matching_orders")
        self.assertEqual(event_call.kwargs["sl_candidates"], 2)
        self.assertEqual(event_call.kwargs["sl_match_source"], "tpsl")
        self.assertEqual(event_call.kwargs["sl_match_confidence"], "exact")
        self.assertEqual(event_call.kwargs["position_source"], "exchange_adopted")

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_marks_unknown_verify_as_unprotected_without_repair(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 100.0,
                    "size": 1.0,
                    "sl": 90.0,
                    "position_source": "exchange_adopted",
                    "sig": "TREND_BUY",
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "90.0", "verify_status": "unknown"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(state["positions"][0]["protection_status"], "verification_unknown")
        self.assertEqual(state["positions"][0]["protection_failure_reason"], "order_status_unknown")
        self.assertEqual(summary["verification_unknown_count"], 1)
        self.assertEqual(summary["unprotected_positions_count"], 1)
        mock_cancel_hl_order.assert_not_called()
        mock_place_hl_sl_order.assert_not_called()
        event_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "sl_verification_unknown")
        self.assertEqual(event_call.kwargs["failure_reason"], "order_status_unknown")
        self.assertTrue(event_call.kwargs["sl_present"])
        self.assertEqual(event_call.kwargs["sl_verify_status"], "unknown")
        self.assertEqual(event_call.kwargs["sl_match_source"], "tpsl")

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_tpsl_orders")
    def test_ensure_position_protection_records_repair_failure_context(
        self,
        mock_place_hl_tpsl_orders,
        mock_record_trade_event,
    ):
        mock_place_hl_tpsl_orders.return_value = {
            "ok": False,
            "message": "Order has invalid price.",
            "tp_order": {"rejection_reason": "invalid_price", "requested_trigger_px": 120.0},
            "sl_order": {"rejection_reason": "invalid_price", "requested_trigger_px": 90.0},
            "order_side": "sell",
            "price_source": "l2_book",
        }
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 100.0,
                    "size": 1.0,
                    "tp": 120.0,
                    "sl": 90.0,
                    "position_source": "exchange_adopted",
                }
            ],
            "_frontend_open_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(state["positions"][0]["protection_status"], "repair_failed")
        self.assertEqual(state["positions"][0]["protection_failure_reason"], "Order has invalid price.")
        self.assertEqual(summary["protection_repair_failed_count"], 1)
        self.assertEqual(summary["unprotected_positions_count"], 1)
        failed_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "tpsl_repair_failed")
        self.assertEqual(failed_call.kwargs["message"], "Order has invalid price.")
        self.assertEqual(failed_call.kwargs["order_side"], "sell")
        self.assertEqual(failed_call.kwargs["price_source"], "l2_book")
        self.assertEqual(failed_call.kwargs["tp_rejection_reason"], "invalid_price")
        self.assertEqual(failed_call.kwargs["sl_rejection_reason"], "invalid_price")

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_records_update_failure_context(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        mock_cancel_hl_order.return_value = {"status": "ok", "message": "canceled", "oid": 2, "coin": "ETH"}
        mock_place_hl_sl_order.return_value = {"ok": False, "message": "replacement rejected"}
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 100.0,
                    "size": 1.0,
                    "sl": 90.0,
                    "current_price": 110.0,
                    "sig": "TREND_BUY",
                    "initial_risk": 10.0,
                    "sl_stage": 0,
                    "best_price": 100.0,
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "90.0"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(state["positions"][0]["protection_status"], "update_failed")
        self.assertEqual(state["positions"][0]["protection_failure_reason"], "sl_replace_failed")
        self.assertEqual(summary["protection_update_failed_count"], 1)
        self.assertEqual(summary["unprotected_positions_count"], 1)
        failed_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "sl_replace_failed")
        self.assertEqual(failed_call.kwargs["oid"], 2)
        self.assertEqual(failed_call.kwargs["previous_trigger_px"], 90.0)
        self.assertEqual(failed_call.kwargs["desired_trigger_px"], 100.0)
        self.assertEqual(failed_call.kwargs["message"], "replacement rejected")
        self.assertNotEqual(state["positions"][0]["protection_status"], "protected")

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
    def test_ensure_position_protection_replaces_trend_sl_at_one_r(
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
            "sl_order": {"oid": 3, "status": "ok", "trigger_px": 100.0},
        }
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 100.0,
                    "size": 1.0,
                    "sl": 90.0,
                    "current_price": 110.0,
                    "sig": "TREND_BUY",
                    "initial_risk": 10.0,
                    "sl_stage": 0,
                    "best_price": 100.0,
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "90.0"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 1)
        self.assertEqual(state["positions"][0]["sl"], 100.0)
        self.assertEqual(state["positions"][0]["sl_stage"], 1)
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("sl_replace_attempted", event_names)
        self.assertIn("sl_replaced", event_names)

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

    def test_compute_trend_stop_target_prefers_atr_trail_when_more_protective(self):
        old_enabled = helpers.config.STRATEGY["atr_trailing_enabled"]
        helpers.config.STRATEGY["atr_trailing_enabled"] = True
        try:
            pos = {
                "coin": "ETH",
                "direction": "long",
                "entry": 100.0,
                "sl": 105.0,
                "current_price": 116.0,
                "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                "initial_risk": 10.0,
                "sl_stage": 2,
                "best_price": 120.0,
            }
            klines = [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(20)] + [
                {"close": 116.0, "high": 118.0, "low": 114.0}
            ]
            target = helpers.compute_trend_stop_target(pos, klines)
            self.assertEqual(target["source"], "atr_trail")
            self.assertGreater(target["sl"], 105.0)
        finally:
            helpers.config.STRATEGY["atr_trailing_enabled"] = old_enabled

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_does_not_replace_trend_sl_before_one_r(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
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
        skipped_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "sl_replace_skipped")
        self.assertEqual(skipped_call.kwargs["reason"], "stage_not_advanced")

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_does_not_replace_when_reconciled_trigger_matches_same_stage(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        state = {
            "positions": [
                {
                    "coin": "ETH",
                    "direction": "long",
                    "entry": 1755.5,
                    "size": 0.0454,
                    "sl": 1674.4214285714284,
                    "current_price": 1794.95,
                    "sig": "TREND_BUY",
                    "initial_risk": 81.07857142857165,
                    "sl_stage": 0,
                    "best_price": 1794.95,
                    "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                }
            ],
            "_frontend_open_orders": [
                {"oid": 2, "coin": "ETH", "reduceOnly": True, "triggerPx": "1674.4"}
            ],
            "managed_orders": [],
        }
        summary = ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 0)
        self.assertEqual(mock_cancel_hl_order.call_count, 0)
        self.assertEqual(mock_place_hl_sl_order.call_count, 0)
        skipped_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "sl_replace_skipped")
        self.assertEqual(skipped_call.kwargs["reason"], "stage_not_advanced")


    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_replaces_sl_from_atr_trail(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        _mock_record_trade_event,
    ):
        old_enabled = helpers.config.STRATEGY["atr_trailing_enabled"]
        helpers.config.STRATEGY["atr_trailing_enabled"] = True
        try:
            mock_cancel_hl_order.return_value = {"status": "ok", "message": "canceled", "oid": 2, "coin": "ETH"}
            mock_place_hl_sl_order.return_value = {
                "ok": True,
                "message": None,
                "tp_order": None,
                "sl_order": {"oid": 3, "status": "ok", "trigger_px": 112.0},
            }
            state = {
                "positions": [
                    {
                        "coin": "ETH",
                        "direction": "long",
                        "entry": 100.0,
                        "size": 1.0,
                        "sl": 105.0,
                        "current_price": 116.0,
                        "sig": "TREND_BUY",
                        "initial_risk": 10.0,
                        "sl_stage": 2,
                        "best_price": 120.0,
                        "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                    }
                ],
                "_data_cache": {
                    "ETH": [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(20)] + [
                        {"close": 116.0, "high": 118.0, "low": 114.0}
                    ]
                },
                "_frontend_open_orders": [
                    {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "105.0"}
                ],
                "managed_orders": [],
            }
            summary = ensure_position_protection(state)
            self.assertEqual(summary["sl_replaced_count"], 1)
            self.assertEqual(state["positions"][0]["sl_order"]["oid"], 3)
        finally:
            helpers.config.STRATEGY["atr_trailing_enabled"] = old_enabled

    @patch("trading_strategy.live.engine.protection.record_trade_event")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.protection.cancel_hl_order")
    def test_ensure_position_protection_does_not_replace_atr_trail_when_normalized_trigger_unchanged(
        self,
        mock_cancel_hl_order,
        mock_place_hl_sl_order,
        mock_record_trade_event,
    ):
        old_enabled = helpers.config.STRATEGY["atr_trailing_enabled"]
        helpers.config.STRATEGY["atr_trailing_enabled"] = True
        try:
            state = {
                "positions": [
                    {
                        "coin": "ETH",
                        "direction": "long",
                        "entry": 100.0,
                        "size": 1.0,
                        "sl": 105.0,
                        "current_price": 116.0,
                        "sig": "TREND_BUY",
                        "initial_risk": 10.0,
                        "sl_stage": 2,
                        "best_price": 120.0,
                        "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                    }
                ],
                "_data_cache": {
                    "ETH": [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(20)] + [
                        {"close": 116.0, "high": 118.0, "low": 114.0}
                    ]
                },
                "_frontend_open_orders": [
                    {"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "113.7", "tick_size": 0.1}
                ],
                "managed_orders": [],
            }
            summary = ensure_position_protection(state)
            self.assertEqual(summary["sl_replaced_count"], 0)
            self.assertEqual(mock_cancel_hl_order.call_count, 0)
            self.assertEqual(mock_place_hl_sl_order.call_count, 0)
            skipped_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "sl_replace_skipped")
            self.assertEqual(skipped_call.kwargs["reason"], "normalized_trigger_unchanged")
        finally:
            helpers.config.STRATEGY["atr_trailing_enabled"] = old_enabled

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
