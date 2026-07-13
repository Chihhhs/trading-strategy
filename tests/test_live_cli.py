from tests.live_test_support import cli, live, patch, unittest


class LiveCliTest(unittest.TestCase):
    @patch("trading_strategy.live.cli.print_report")
    @patch("trading_strategy.live.cli.save_state")
    @patch("trading_strategy.live.cli.load_state")
    @patch("trading_strategy.live.cli.load_coin_list")
    @patch("trading_strategy.live.cli.get_current_prices")
    @patch("trading_strategy.live.cli.update_positions")
    @patch("trading_strategy.live.cli.check_entries")
    @patch("trading_strategy.live.cli.advance_paper_signal_observations")
    @patch("trading_strategy.live.cli.summarize_signal_observations")
    @patch("trading_strategy.live.cli.record_trade_event")
    def test_run_once_paper_includes_signal_observation_progress(
        self,
        mock_record_trade_event,
        mock_summarize,
        _mock_advance,
        mock_check_entries,
        _mock_update_positions,
        mock_get_current_prices,
        mock_load_coin_list,
        mock_load_state,
        _mock_save_state,
        _mock_print_report,
    ):
        old_mode = live.config.MODE
        old_enabled = live.config.STRATEGY["signal_observation_enabled"]
        live.config.set_mode("paper")
        live.config.STRATEGY["signal_observation_enabled"] = True
        try:
            mock_load_state.return_value = {"balance": 100.0, "positions": [], "history": []}
            mock_load_coin_list.return_value = [{"name": "BTC", "symbol": "BTCUSDT"}]
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_check_entries.return_value = {"top_blockers": []}
            mock_summarize.return_value = {
                "signals_observed": 4,
                "outcomes_observed": 2,
                "pending_observations": 4,
                "minimum_signals": 30,
                "remaining_signals": 26,
            }
            cli.run_once()
            run_summary_call = next(
                call for call in mock_record_trade_event.call_args_list if call.args[0] == "run_summary"
            )
            self.assertEqual(run_summary_call.kwargs["signals_observed"], 4)
            self.assertEqual(run_summary_call.kwargs["remaining_signals"], 26)
        finally:
            live.config.STRATEGY["signal_observation_enabled"] = old_enabled
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.cli.time.sleep")
    @patch("trading_strategy.live.cli.record_trade_event")
    @patch("trading_strategy.live.cli.run_once")
    def test_run_loop_stops_after_max_runs(self, mock_run_once, mock_record_trade_event, mock_sleep):
        cli.run_loop(interval_minutes=1, max_runs=2)
        self.assertEqual(mock_run_once.call_count, 2)
        mock_sleep.assert_called_once_with(60)
        self.assertTrue(
            any(
                call.args[0] == "loop_completed" and call.kwargs.get("runs") == 2
                for call in mock_record_trade_event.call_args_list
            )
        )

    @patch("trading_strategy.live.cli.print_report")
    @patch("trading_strategy.live.cli.save_state")
    @patch("trading_strategy.live.cli.load_state")
    @patch("trading_strategy.live.cli.load_coin_list")
    @patch("trading_strategy.live.cli.get_current_prices")
    @patch("trading_strategy.live.cli.update_positions")
    @patch("trading_strategy.live.cli.check_entries")
    @patch("trading_strategy.live.cli.ensure_position_protection")
    @patch("trading_strategy.live.cli.record_trade_event")
    def test_run_once_skips_new_entries_when_unprotected_positions_exist(
        self,
        mock_record_trade_event,
        mock_ensure_position_protection,
        mock_check_entries,
        _mock_update_positions,
        mock_get_current_prices,
        mock_load_coin_list,
        mock_load_state,
        _mock_save_state,
        _mock_print_report,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            mock_load_state.return_value = {
                "balance": 100.0,
                "positions": [],
                "history": [],
                "_balance_source": "hyperliquid_perp",
                "_perp_account_value": 100.0,
                "_spot_account_value": 0.0,
                "params": {"entry_order_type": "ioc", "leverage": 5, "risk_per_trade": 0.08, "max_positions": 3},
            }
            mock_load_coin_list.return_value = [{"name": "BTC", "symbol": "BTCUSDT"}]
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_ensure_position_protection.return_value = {
                "adopted_positions_count": 1,
                "tpsl_missing_count": 1,
                "tpsl_repaired_count": 0,
                "unprotected_positions_count": 1,
            }
            with patch("trading_strategy.live.cli.sync_state_with_hl_balance", side_effect=lambda state: state):
                cli.run_once()
            mock_check_entries.assert_not_called()
            run_summary_calls = [call for call in mock_record_trade_event.call_args_list if call.args[0] == "run_summary"]
            self.assertEqual(len(run_summary_calls), 1)
            self.assertEqual(run_summary_calls[0].kwargs["unprotected_positions_count"], 1)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.cli.print_report")
    @patch("trading_strategy.live.cli.save_state")
    @patch("trading_strategy.live.cli.load_state")
    @patch("trading_strategy.live.cli.load_coin_list")
    @patch("trading_strategy.live.cli.get_current_prices")
    @patch("trading_strategy.live.cli.update_positions")
    @patch("trading_strategy.live.cli.check_entries")
    @patch("trading_strategy.live.cli.record_trade_event")
    def test_run_once_paper_does_not_sync_exchange_even_with_account_address(
        self,
        _mock_record_trade_event,
        mock_check_entries,
        _mock_update_positions,
        mock_get_current_prices,
        mock_load_coin_list,
        mock_load_state,
        _mock_save_state,
        _mock_print_report,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            mock_load_state.return_value = {
                "balance": 100.0,
                "positions": [],
                "history": [],
                "_balance_source": "local_state",
                "params": dict(live.config.STRATEGY),
            }
            mock_load_coin_list.return_value = [{"name": "BTC", "symbol": "BTCUSDT"}]
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_check_entries.return_value = {"top_blockers": []}
            with patch("trading_strategy.live.cli.config.get_account_address", return_value="0xabc"), patch(
                "trading_strategy.live.cli.sync_state_with_hl_balance"
            ) as mock_sync:
                cli.run_once()
            mock_sync.assert_not_called()
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.cli.print_report")
    @patch("trading_strategy.live.cli.save_state")
    @patch("trading_strategy.live.cli.load_state")
    @patch("trading_strategy.live.cli.load_coin_list")
    @patch("trading_strategy.live.cli.get_current_prices")
    @patch("trading_strategy.live.cli.update_positions")
    @patch("trading_strategy.live.cli.check_entries")
    @patch("trading_strategy.live.cli.record_trade_event")
    def test_run_once_logs_run_summary_and_config_mismatch(
        self,
        mock_record_trade_event,
        mock_check_entries,
        _mock_update_positions,
        mock_get_current_prices,
        mock_load_coin_list,
        mock_load_state,
        _mock_save_state,
        _mock_print_report,
    ):
        old_mode = live.config.MODE
        live.config.set_mode("paper")
        try:
            mock_load_state.return_value = {
                "balance": 100.0,
                "positions": [],
                "history": [],
                "_balance_source": "local_state",
                "params": {"entry_order_type": "post_only", "leverage": 5, "risk_per_trade": 0.08, "max_positions": 3},
            }
            mock_load_coin_list.return_value = [{"name": "BTC", "symbol": "BTCUSDT"}]
            mock_get_current_prices.return_value = {"BTC": 100.0}
            mock_check_entries.return_value = {
                "coins_scanned": 1,
                "priced_coins": 1,
                "valid_klines": 1,
                "signals_found": 1,
                "btc_filtered": 0,
                "size_zero": 0,
                "orders_attempted": 0,
                "positions_opened": 1,
                "entry_rejected_count": 0,
                "entry_rejected_reasons": {},
                "missing_price_count": 0,
                "missing_price_coins_sample": [],
                "no_signal_count": 0,
                "priced_ratio": 1.0,
                "top_blockers": [],
            }
            cli.run_once()
            event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
            self.assertIn("config_mismatch", event_names)
            self.assertIn("run_summary", event_names)
            run_summary_call = next(call for call in mock_record_trade_event.call_args_list if call.args[0] == "run_summary")
            self.assertEqual(run_summary_call.kwargs["position_status_counts"], {})
            self.assertEqual(run_summary_call.kwargs["position_snapshots"], [])
        finally:
            live.config.set_mode(old_mode)
