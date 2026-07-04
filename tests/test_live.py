import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy import live
from trading_strategy.hyperliquid import choose_limit_price
from trading_strategy.live import account, cli, config, engine, market, orders


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

    def test_extract_hl_account_values_prefers_perp_but_keeps_spot(self):
        balance_info = {
            "perp": {"marginSummary": {"accountValue": "0.0"}},
            "spot": {
                "tokenToAvailableAfterMaintenance": [[0, "45.905278"]],
                "balances": [{"coin": "USDC", "total": "45.905278"}],
            },
        }
        values = account.extract_hl_account_values(balance_info)
        self.assertEqual(values["perp_account_value"], 0.0)
        self.assertEqual(values["spot_account_value"], 45.905278)
        self.assertEqual(values["effective_balance"], 0.0)
        self.assertEqual(values["balance_source"], "hyperliquid_perp")

    def test_ensure_live_perp_balance_rejects_zero_perp_even_with_spot(self):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {
                "balance": 45.905278,
                "_perp_account_value": 0.0,
                "_spot_account_value": 45.905278,
            }
            with self.assertRaisesRegex(RuntimeError, "perp tradable balance is 0"):
                cli.ensure_live_perp_balance(state)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.hyperliquid.get_best_bid_ask")
    def test_choose_limit_price_normalizes_to_tick(self, mock_get_best_bid_ask):
        mock_get_best_bid_ask.return_value = {
            "best_bid": {
                "price": 44.48,
                "price_decimal": orders.Decimal("44.48"),
                "raw_price": "44.48",
            },
            "best_ask": {
                "price": 44.49,
                "price_decimal": orders.Decimal("44.49"),
                "raw_price": "44.49",
            },
            "bids": [
                {"price_decimal": orders.Decimal("44.48"), "raw_price": "44.48"},
                {"price_decimal": orders.Decimal("44.47"), "raw_price": "44.47"},
            ],
            "asks": [
                {"price_decimal": orders.Decimal("44.49"), "raw_price": "44.49"},
                {"price_decimal": orders.Decimal("44.50"), "raw_price": "44.50"},
            ],
            "book": {"levels": []},
        }
        chosen = choose_limit_price("LTC", "buy", passive=False, price_pad_bps=5)
        self.assertEqual(chosen["tick_size"], 0.01)
        self.assertEqual(round(chosen["normalized_price"], 2), chosen["normalized_price"])
        self.assertGreaterEqual(chosen["normalized_price"], chosen["best_ask"])

    def test_classify_order_rejection(self):
        self.assertEqual(orders.classify_order_rejection("Order has invalid price."), "invalid_price")
        self.assertEqual(orders.classify_order_rejection("Insufficient margin"), "margin_insufficient")

    @patch("trading_strategy.live.orders.get_best_bid_ask")
    @patch("trading_strategy.live.orders.verify_hl_order", return_value=None)
    @patch("trading_strategy.live.orders.get_hl_exchange_client")
    def test_place_hl_trigger_order_rejected_returns_error(
        self,
        mock_get_exchange,
        _mock_verify,
        mock_get_best_bid_ask,
    ):
        class DummyExchange:
            def __init__(self):
                self.calls = []

            def order(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return {
                    "status": "ok",
                    "response": {"data": {"statuses": [{"error": "Order has invalid price."}]}},
                }

        dummy_exchange = DummyExchange()
        mock_get_exchange.return_value = dummy_exchange
        mock_get_best_bid_ask.return_value = {
            "best_bid": {
                "price": 99.5,
                "price_decimal": orders.Decimal("99.5"),
                "raw_price": "99.5",
            },
            "best_ask": {
                "price": 100.0,
                "price_decimal": orders.Decimal("100.0"),
                "raw_price": "100.0",
            },
            "bids": [
                {"price_decimal": orders.Decimal("99.5"), "raw_price": "99.5"},
                {"price_decimal": orders.Decimal("99.0"), "raw_price": "99.0"},
            ],
            "asks": [
                {"price_decimal": orders.Decimal("100.0"), "raw_price": "100.0"},
                {"price_decimal": orders.Decimal("100.5"), "raw_price": "100.5"},
            ],
            "book": {"levels": []},
        }
        with patch("trading_strategy.live.orders.get_trigger_limit_price", return_value=100.37):
            result = orders.place_hl_trigger_order("BTC", "sell", 1.0, 100.21, "sl")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["rejection_reason"], "invalid_price")
        self.assertEqual(result["requested_trigger_px"], 100.21)
        self.assertEqual(result["trigger_px"], 100.2)
        self.assertEqual(result["requested_limit_px"], 100.37)
        self.assertEqual(result["limit_px"], 100.3)
        self.assertEqual(result["tick_size"], 0.1)
        self.assertEqual(dummy_exchange.calls[0][0][3], 100.3)
        self.assertEqual(dummy_exchange.calls[0][0][4]["trigger"]["triggerPx"], 100.2)

    @patch("trading_strategy.live.orders.get_hl_exchange_client")
    def test_cancel_hl_order_returns_ok(self, mock_get_exchange):
        class DummyExchange:
            def cancel(self, coin, oid):
                return {"status": "ok", "response": {"data": {"statuses": [{"success": {"oid": oid}}]}}}

        mock_get_exchange.return_value = DummyExchange()
        result = orders.cancel_hl_order("BTC", 123)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cancel_status"], "canceled")
        self.assertEqual(result["oid"], 123)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=None):
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
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

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal):
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
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

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
    def test_check_entries_tracks_missing_price_summary(
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
            mock_get_current_prices.return_value = {}
            mock_get_klines.return_value = None
            state = {"balance": 100.0, "positions": [], "history": []}
            summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["missing_price_count"], 1)
            self.assertEqual(summary["missing_price_coins_sample"], ["BTC"])
            self.assertEqual(summary["priced_ratio"], 0.0)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.calc_position_size", return_value=0.0
            ):
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["size_zero"], 1)
            self.assertTrue(
                any(
                    call.args[0] == "entry_skipped" and call.kwargs.get("reason") == "size_zero"
                    for call in mock_record_trade_event.call_args_list
                )
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal):
                summary = engine.check_entries(
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

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.calc_position_size", return_value=0.0
            ) as mock_calc_position_size:
                engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(mock_calc_position_size.call_args.args[0], 50.0)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.calc_position_size"
            ) as mock_calc_position_size:
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
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

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal), patch(
                "trading_strategy.live.engine.calc_position_size", return_value=0.0
            ) as mock_calc_position_size:
                engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(mock_calc_position_size.call_args.args[0], 100.0)
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.save_state")
    @patch("trading_strategy.live.engine.place_hl_order")
    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal):
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
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

    @patch("trading_strategy.live.engine.save_state")
    @patch("trading_strategy.live.engine.place_hl_sl_order")
    @patch("trading_strategy.live.engine.place_hl_order")
    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal):
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["orders_attempted"], 1)
            self.assertEqual(summary["positions_opened"], 0)
            self.assertEqual(state["positions"], [])
            self.assertTrue(
                any(call.args[0] == "sl_submit_failed" for call in mock_record_trade_event.call_args_list)
            )
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.save_state")
    @patch("trading_strategy.live.engine.place_hl_sl_order")
    @patch("trading_strategy.live.engine.place_hl_order")
    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.get_current_prices")
    @patch("trading_strategy.live.engine.get_btc_direction")
    @patch("trading_strategy.live.engine.get_klines")
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
            with patch("trading_strategy.live.engine.generate_signal", return_value=signal):
                summary = engine.check_entries(state, [{"name": "BTC", "symbol": "BTCUSDT"}])
            self.assertEqual(summary["positions_opened"], 1)
            self.assertEqual(len(state["positions"]), 1)
            self.assertIsNone(state["positions"][0]["tp"])
            self.assertIsNone(state["positions"][0]["tp_order"])
            self.assertEqual(state["positions"][0]["sl_order"]["oid"], 22)
            self.assertEqual(state["positions"][0]["exit_policy"]["name"], "trend_sl_only")
        finally:
            live.config.set_mode(old_mode)

    def test_load_coin_list_rebuilds_cache_when_metadata_mismatch(self):
        old_mode = config.MODE
        old_state_dir = config.STATE_DIR
        tmpdir = tempfile.mkdtemp()
        config.STATE_DIR = tmpdir
        config.set_mode("live")
        try:
            cache_path = os.path.join(tmpdir, "coin_list.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                handle.write('{"metadata":{"mode":"paper","market_data_source":"binance"},"coins":[{"name":"OLD","symbol":"OLDUSDT"}]}')
            with patch("trading_strategy.live.market._load_hyperliquid_coin_list", return_value=[{"name": "BTC", "symbol": "BTCUSDT"}]):
                coins = market.load_coin_list()
            self.assertEqual(coins, [{"name": "BTC", "symbol": "BTCUSDT"}])
        finally:
            config.STATE_DIR = old_state_dir
            config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.record_trade_event")
    def test_sync_state_with_exchange_positions_adopts_exchange_position(self, mock_record_trade_event):
        old_mode = live.config.MODE
        live.config.set_mode("live")
        try:
            state = {"positions": []}
            synced = engine.sync_state_with_exchange_positions(
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

    @patch("trading_strategy.live.engine.record_trade_event")
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
            synced = engine.sync_state_with_exchange_positions(
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

    @patch("trading_strategy.live.engine.record_trade_event")
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
            synced = engine.sync_state_with_exchange_positions(
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

    @patch("trading_strategy.live.engine.record_trade_event")
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
            synced = engine.sync_state_with_exchange_positions(
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

    @patch("trading_strategy.live.engine.record_trade_event")
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
            synced = engine.sync_state_with_exchange_positions(
                state,
                {"assetPositions": []},
                [{"oid": 99, "coin": "ETH", "reduceOnly": False, "side": "B", "sz": "0.0454"}],
            )
            self.assertEqual(len(synced["positions"]), 1)
            self.assertEqual(synced["managed_orders"][0]["order_role"], "entry_pending")
            self.assertEqual(synced["_orphan_orders"], [])
        finally:
            live.config.set_mode(old_mode)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.cancel_hl_order")
    def test_cancel_orphan_orders_cancels_unknown_open_order(self, mock_cancel_hl_order, mock_record_trade_event):
        mock_cancel_hl_order.return_value = {"status": "ok", "message": "canceled", "oid": 55, "coin": "BTC"}
        state = {
            "managed_orders": [{"oid": 55, "coin": "BTC", "order_role": "orphan_unknown"}],
            "_orphan_orders": [{"oid": 55, "coin": "BTC", "order_role": "orphan_unknown"}],
            "_frontend_open_orders": [{"oid": 55, "coin": "BTC"}],
            "_exchange_open_orders_count": 1,
        }
        summary = engine.cancel_orphan_orders(state)
        self.assertEqual(summary["orphan_orders_detected_count"], 1)
        self.assertEqual(summary["orphan_orders_canceled_count"], 1)
        self.assertEqual(state["managed_orders"], [])
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("orphan_order_cancel_attempted", event_names)
        self.assertIn("orphan_order_canceled", event_names)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.place_hl_sl_order")
    @patch("trading_strategy.live.engine.cancel_hl_order")
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
        summary = engine.ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 1)
        self.assertEqual(state["positions"][0]["sl_order"]["oid"], 3)
        event_names = [call.args[0] for call in mock_record_trade_event.call_args_list]
        self.assertIn("sl_replace_attempted", event_names)
        self.assertIn("sl_replaced", event_names)
        self.assertEqual(state["positions"][0]["sl_stage"], 2)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.place_hl_sl_order")
    @patch("trading_strategy.live.engine.cancel_hl_order")
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
        summary = engine.ensure_position_protection(state)
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
        target = engine.compute_dynamic_sl_target(pos)
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
        target = engine.compute_dynamic_sl_target(pos)
        self.assertEqual(target["stage"], 2)
        self.assertEqual(target["sl"], 105.0)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.place_hl_sl_order")
    @patch("trading_strategy.live.engine.cancel_hl_order")
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
        summary = engine.ensure_position_protection(state)
        self.assertEqual(summary["sl_replaced_count"], 0)
        self.assertEqual(summary["unprotected_positions_count"], 0)
        self.assertEqual(mock_cancel_hl_order.call_count, 0)
        self.assertEqual(mock_place_hl_sl_order.call_count, 0)

    @patch("trading_strategy.live.engine.record_trade_event")
    @patch("trading_strategy.live.engine.place_hl_tpsl_orders")
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
        summary = engine.ensure_position_protection(state)
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

    @patch("trading_strategy.live.engine.record_trade_event")
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
        summary = engine.ensure_position_protection(state)
        self.assertEqual(summary["tpsl_missing_count"], 0)
        self.assertEqual(summary["protection_missing_count"], 0)
        self.assertEqual(state["positions"][0]["protection_status"], "protected")
        self.assertEqual(mock_record_trade_event.call_count, 0)

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
        finally:
            live.config.set_mode(old_mode)


if __name__ == "__main__":
    unittest.main()
