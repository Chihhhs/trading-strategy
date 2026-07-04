from tests.live_test_support import check_entries, live, patch, unittest


class LiveEntriesTest(unittest.TestCase):
    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_logs_no_signal(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {"balance": 100.0, "positions": [], "history": []}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=None):
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["signals_found"], 0)
            self.assertEqual(summary["no_signal_count"], 1)
            self.assertTrue(
                any(
                    call.args[0] == "entry_skipped" and call.kwargs.get("reason") == "no_signal"
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_logs_btc_filter(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            mock_get_btc_direction.return_value = "bull"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {"balance": 100.0, "positions": [], "history": []}
            signal = {"direction": "short", "score": -4, "sl": 110.0, "tp": 90.0}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal):
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["signals_found"], 1)
            self.assertEqual(summary["btc_filtered"], 1)
            self.assertTrue(
                any(
                    call.args[0] == "entry_skipped" and call.kwargs.get("reason") == "btc_filter"
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_tracks_missing_price_summary(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        _mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {}
            mock_get_klines.return_value = None
            state = {"balance": 100.0, "positions": [], "history": []}
            summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["missing_price_count"], 1)
            self.assertEqual(summary["missing_price_coins_sample"], ["BTC"])
            self.assertEqual(summary["priced_ratio"], 0.0)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_logs_size_zero(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {"balance": 100.0, "positions": [], "history": []}
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.entries.calc_position_size", return_value=0.0
            ):
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["size_zero"], 1)
            self.assertTrue(
                any(
                    call.args[0] == "entry_skipped" and call.kwargs.get("reason") == "size_zero"
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_opens_fourth_position_and_blocks_fifth(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        old_max_positions = live.config.STRATEGY["max_positions"]
        live.config.set_mode("paper")
        live.config.STRATEGY["max_positions"] = 4
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0, "ETH": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {
                "balance": 100.0,
                "history": [],
                "positions": [
                    {"coin": "SOL", "direction": "long", "entry": 10.0, "size": 1.0},
                    {"coin": "BNB", "direction": "long", "entry": 10.0, "size": 1.0},
                    {"coin": "ADA", "direction": "long", "entry": 10.0, "size": 1.0},
                ],
            }
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal):
                summary = check_entries(
                    state,
                    [{"name": "BTC", "symbol": "BTCUSDT"}, {"name": "ETH", "symbol": "ETHUSDT"}],
                )
            self.assertEqual(summary["positions_opened"], 1)
            self.assertEqual(len(state["positions"]), 4)
            self.assertEqual(summary["top_blockers"], [{"reason": "max_positions_reached", "count": 1}])
            self.assertTrue(
                any(
                    call.args[0] == "entry_skipped" and call.kwargs.get("reason") == "max_positions_reached"
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.STRATEGY["max_positions"] = old_max_positions
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_uses_reduced_available_balance_for_live_sizing(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        _mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {
                "balance": 100.0,
                "positions": [
                    {"coin": "ETH", "entry": 100.0, "size": 2.0},
                    {"coin": "SOL", "entry": 50.0, "size": 1.0},
                ],
                "history": [],
            }
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.entries.calc_position_size", return_value=0.0
            ) as mock_calc_position_size:
                check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(mock_calc_position_size.call_args.args[0], 50.0)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.summary.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_skips_when_reserved_margin_exhausts_balance(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {
                "balance": 100.0,
                "positions": [{"coin": "ETH", "entry": 100.0, "size": 5.0}],
                "history": [],
            }
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.entries.calc_position_size"
            ) as mock_calc_position_size:
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertFalse(mock_calc_position_size.called)
            self.assertEqual(summary["positions_opened"], 0)
            self.assertEqual(summary["top_blockers"], [{"reason": "reserved_margin_exhausted", "count": 1}])
            self.assertTrue(
                any(
                    call.args[0] == "entry_skipped"
                    and call.kwargs.get("reason") == "reserved_margin_exhausted"
                    and call.kwargs.get("available_balance") == 0.0
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.entries.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_live_without_open_positions_uses_full_balance(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        _mock_record_trade_event,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            state = {"balance": 100.0, "positions": [], "history": []}
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.entries.calc_position_size", return_value=0.0
            ) as mock_calc_position_size:
                check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(mock_calc_position_size.call_args.args[0], 100.0)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.entries.save_state")
    @patch("trading_strategy.live.engine.entries.place_hl_order")
    @patch("trading_strategy.live.engine.entries.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_logs_entry_order_rejected_with_price_context(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
        mock_place_hl_order,
        _mock_save_state,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            mock_place_hl_order.return_value = {
                "status": "error",
                "normalized_status": "rejected",
                "message": "Order has invalid price.",
                "verified_summary": {"verify_status": None},
                "order_summary": {"order_status": "rejected", "oid": None},
                "size": 1.0,
                "resolved_price": 100.01,
                "raw_price": 100.013,
                "normalized_price": 100.01,
                "best_bid": 100.0,
                "best_ask": 100.01,
                "price_source": "l2_book",
                "rejection_reason": "invalid_price",
            }
            state = {"balance": 100.0, "positions": [], "history": []}
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal):
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["entry_rejected_count"], 1)
            self.assertEqual(summary["entry_rejected_reasons"], {"invalid_price": 1})
            rejected_calls = [
                call for call in mock_record_trade_event.call_args_list if call.args[0] == "entry_order_rejected"
            ]
            self.assertEqual(len(rejected_calls), 1)
            self.assertEqual(rejected_calls[0].kwargs["best_ask"], 100.01)
            self.assertEqual(rejected_calls[0].kwargs["rejection_reason"], "invalid_price")
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.entries.save_state")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.entries.place_hl_order")
    @patch("trading_strategy.live.engine.entries.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_logs_sl_failure_for_trend_policy(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        mock_record_trade_event,
        mock_place_hl_order,
        mock_place_hl_sl_order,
        _mock_save_state,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            mock_place_hl_order.return_value = {
                "status": "ok",
                "normalized_status": "filled",
                "message": "filled",
                "verified_summary": {"verify_status": "filled"},
                "order_summary": {"order_status": "filled", "oid": 12},
                "resolved_price": 100.0,
                "size": 1.0,
            }
            mock_place_hl_sl_order.return_value = {"ok": False, "message": "sl rejected"}
            state = {"balance": 100.0, "positions": [], "history": []}
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal):
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["orders_attempted"], 1)
            self.assertEqual(summary["positions_opened"], 0)
            self.assertEqual(state["positions"], [])
            self.assertTrue(
                any(call.args[0] == "sl_submit_failed" for call in mock_record_trade_event.call_args_list)
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.entries.save_state")
    @patch("trading_strategy.live.engine.protection.place_hl_sl_order")
    @patch("trading_strategy.live.engine.entries.place_hl_order")
    @patch("trading_strategy.live.engine.entries.record_trade_event")
    @patch("trading_strategy.live.engine.entries.get_current_prices")
    @patch("trading_strategy.live.engine.entries.get_btc_direction")
    @patch("trading_strategy.live.engine.entries.get_klines")
    def test_check_entries_opens_trend_position_without_tp_order(
        self,
        mock_get_klines,
        mock_get_btc_direction,
        mock_get_current_prices,
        _mock_record_trade_event,
        mock_place_hl_order,
        mock_place_hl_sl_order,
        _mock_save_state,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_get_btc_direction.return_value = "neutral"
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_get_klines.return_value = [{"open": 1, "high": 2, "low": 1, "close": 1.5}] * 60
            mock_place_hl_order.return_value = {
                "status": "ok",
                "normalized_status": "filled",
                "message": "filled",
                "verified_summary": {"verify_status": "filled"},
                "order_summary": {"order_status": "filled", "oid": 12},
                "resolved_price": 100.0,
                "size": 1.0,
            }
            mock_place_hl_sl_order.return_value = {
                "ok": True,
                "message": None,
                "tp_order": None,
                "sl_order": {"oid": 22, "status": "ok", "trigger_px": 95.0},
            }
            state = {"balance": 100.0, "positions": [], "history": []}
            signal = {"direction": "long", "score": 4, "sl": 95.0, "tp": 110.0, "reason": "TREND_BUY"}
            with patch("trading_strategy.live.engine.entries.generate_signal", return_value=signal):
                summary = check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["positions_opened"], 1)
            self.assertEqual(len(state["positions"]), 1)
            self.assertIsNone(state["positions"][0]["tp"])
            self.assertIsNone(state["positions"][0]["tp_order"])
            self.assertEqual(state["positions"][0]["sl_order"]["oid"], 22)
            self.assertEqual(state["positions"][0]["exit_policy"]["name"], "trend_sl_only")
        finally:
            live.config.set_mode(old_mode)
