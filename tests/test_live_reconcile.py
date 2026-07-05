from tests.live_test_support import live, patch, sync_state_with_exchange_positions, unittest


class LiveReconcileTest(unittest.TestCase):
    @patch("trading_strategy.live.engine.reconcile.record_trade_event")
    def test_sync_state_with_exchange_positions_adopts_exchange_position(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {"positions": []}
            synced = sync_state_with_exchange_positions(
                state,
                {"assetPositions": [{"position": {"coin": "ETH", "entryPx": "1755.5", "szi": "0.0454"}}]},
                [],
            )
            self.assertEqual(len(synced["positions"]), 1)
            self.assertEqual(synced["positions"][0]["coin"], "ETH")
            self.assertEqual(synced["positions"][0]["position_source"], "exchange_adopted")
            self.assertIn("ETH", synced["_adopted_positions"])
            event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
            self.assertIn("position_adopted", event_names)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.reconcile.record_trade_event")
    def test_sync_state_with_exchange_positions_attaches_existing_open_sl(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
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
                ]
            }
            synced = sync_state_with_exchange_positions(
                state,
                {"assetPositions": [{"position": {"coin": "ETH", "entryPx": "1755.5", "szi": "0.0454"}}]},
                [{"oid": 2, "coin": "ETH", "reduceOnly": True, "tpsl": "sl", "triggerPx": "1674.0"}],
            )
            self.assertEqual(synced["positions"][0]["sl_order"]["oid"], 2)
            self.assertEqual(synced["managed_orders"][0]["order_role"], "protection_sl")
            event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
            self.assertIn("open_orders_synced", event_names)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.reconcile.record_trade_event")
    def test_sync_state_with_exchange_positions_matches_reduce_only_sl_without_tpsl_by_oid(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {
                "positions": [
                    {
                        "coin": "ETH",
                        "direction": "long",
                        "entry": 1755.5,
                        "size": 0.0454,
                        "sl": 1674.4214285714284,
                        "sig": "TREND_BUY",
                        "sl_order": {"oid": 2, "trigger_px": 1674.4, "requested_trigger_px": 1674.4214285714284},
                        "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                    }
                ]
            }
            synced = sync_state_with_exchange_positions(
                state,
                {"assetPositions": [{"position": {"coin": "ETH", "entryPx": "1755.5", "szi": "0.0454"}}]},
                [{"oid": 2, "coin": "ETH", "reduceOnly": True, "triggerPx": "1674.4"}],
            )
            self.assertEqual(synced["positions"][0]["sl_order"]["oid"], 2)
            self.assertEqual(synced["managed_orders"][0]["order_role"], "protection_sl")
            self.assertEqual(synced["_orphan_orders"], [])
            event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
            self.assertNotIn("orphan_order_detected", event_names)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.reconcile.record_trade_event")
    def test_sync_state_with_exchange_positions_matches_reduce_only_sl_without_tpsl_by_trigger(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {
                "positions": [
                    {
                        "coin": "ETH",
                        "direction": "long",
                        "entry": 1755.5,
                        "size": 0.0454,
                        "sl": 1674.4214285714284,
                        "sig": "TREND_BUY",
                        "exit_policy": {"name": "trend_sl_only", "requires_tp": False, "requires_sl": True, "protection_event_prefix": "sl"},
                    }
                ]
            }
            synced = sync_state_with_exchange_positions(
                state,
                {"assetPositions": [{"position": {"coin": "ETH", "entryPx": "1755.5", "szi": "0.0454"}}]},
                [{"oid": 7, "coin": "ETH", "reduceOnly": True, "triggerPx": "1674.4"}],
            )
            self.assertEqual(synced["positions"][0]["sl_order"]["oid"], 7)
            self.assertEqual(synced["managed_orders"][0]["order_role"], "protection_sl")
            self.assertEqual(synced["_orphan_orders"], [])
            event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
            self.assertNotIn("orphan_order_detected", event_names)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.reconcile.record_trade_event")
    def test_sync_state_with_exchange_positions_keeps_pending_entry_as_managed_order(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {
                "positions": [
                    {
                        "coin": "ETH",
                        "direction": "long",
                        "entry_oid": 99,
                        "entry_time": "2026-07-02T23:47:02.163776",
                    }
                ]
            }
            synced = sync_state_with_exchange_positions(
                state,
                {"assetPositions": []},
                [{"oid": 99, "coin": "ETH", "reduceOnly": False, "side": "B", "sz": "0.0454"}],
            )
            self.assertEqual(len(synced["positions"]), 1)
            self.assertEqual(synced["managed_orders"][0]["order_role"], "entry_pending")
            self.assertEqual(synced["_orphan_orders"], [])
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.reconcile.record_trade_event")
    def test_sync_state_with_exchange_positions_records_closed_trade_for_stale_position(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {
                "positions": [
                    {
                        "coin": "ETH",
                        "direction": "long",
                        "entry": 100.0,
                        "current_price": 108.0,
                        "size": 1.5,
                        "entry_time": "2026-07-02T23:47:02.163776",
                        "entry_reason": "TREND_BUY",
                        "signal_reason": "TREND_BUY",
                        "pending_exit_reason": "REVERSAL",
                    }
                ],
                "history": [],
                "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "max_win": 0.0, "max_loss": 0.0},
            }
            synced = sync_state_with_exchange_positions(
                state,
                {"assetPositions": []},
                [],
            )
            self.assertEqual(synced["positions"], [])
            self.assertEqual(len(synced["history"]), 1)
            self.assertEqual(synced["history"][0]["exit_reason"], "REVERSAL")
            self.assertEqual(synced["history"][0]["close_status"], "exchange_closed")
            self.assertEqual(synced["stats"]["wins"], 1)
            event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
            self.assertIn("position_closed_reconciled", event_names)
        finally:
            live.config.set_mode(old_mode)
