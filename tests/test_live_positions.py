from tests.live_test_support import live, patch, unittest, update_positions


class LivePositionsTest(unittest.TestCase):
    def test_update_positions_records_paper_trade_reason_and_outcome(self):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            state = {
                "balance": 1000.0,
                "positions": [
                    {
                        "coin": "BTC",
                        "direction": "long",
                        "entry": 100.0,
                        "tp": 110.0,
                        "sl": 95.0,
                        "size": 2.0,
                        "entry_time": "2026-07-05T09:00:00",
                        "signal_reason": "TREND_BUY",
                        "entry_reason": "TREND_BUY",
                        "signal_score": 5,
                        "btc_dir_at_entry": "bull",
                        "risk_pct": 0.1,
                        "entry_order_type": "paper",
                        "exit_policy": {"name": "trend_sl_only"},
                    }
                ],
                "history": [],
                "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "max_win": 0.0, "max_loss": 0.0},
            }
            update_positions(state, {"BTC": 111.0}, {})
            self.assertEqual(state["positions"], [])
            self.assertEqual(len(state["history"]), 1)
            trade = state["history"][0]
            self.assertEqual(trade["entry_reason"], "TREND_BUY")
            self.assertEqual(trade["exit_reason"], "TP")
            self.assertEqual(trade["outcome"], "win")
            self.assertEqual(trade["signal_score"], 5)
            self.assertEqual(state["stats"]["wins"], 1)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.positions.record_trade_event")
    @patch("trading_strategy.live.engine.positions.close_hl_position")
    def test_update_positions_marks_live_close_pending_until_reconciled(
        self,
        mock_close_hl_position,
        mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_close_hl_position.return_value = {
                "status": "ok",
                "order_summary": {"order_status": "filled"},
                "verified_summary": {"verify_status": "filled"},
            }
            state = {
                "_reconciled_at": "2026-07-05T10:00:00",
                "positions": [
                    {
                        "coin": "BTC",
                        "direction": "long",
                        "entry": 100.0,
                        "size": 1.0,
                        "entry_time": "2026-07-01T00:00:00",
                    }
                ],
                "history": [],
                "stats": {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "max_win": 0.0, "max_loss": 0.0},
            }
            old_max_hold_days = live.config.STRATEGY["max_hold_days"]
            live.config.STRATEGY["max_hold_days"] = 1
            update_positions(state, {"BTC": 98.0}, {})
            self.assertEqual(len(state["positions"]), 1)
            self.assertTrue(state["positions"][0]["close_pending"])
            self.assertEqual(state["positions"][0]["pending_exit_reason"], "TIME")
            self.assertEqual(state["history"], [])
            self.assertTrue(
                any(
                    call.args[0] == "position_close_submitted" and call.kwargs.get("exit_reason") == "TIME"
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.STRATEGY["max_hold_days"] = old_max_hold_days
            live.config.set_mode(old_mode)
