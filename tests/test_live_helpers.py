from tests.live_test_support import (
    account,
    choose_limit_price,
    cli,
    config,
    helpers,
    live,
    market,
    orders,
    os,
    patch,
    tempfile,
    unittest,
)
from trading_strategy.core.exit_policy import build_exit_policy


class LiveHelpersTest(unittest.TestCase):
    def test_check_atr_trailing_exit_triggers_after_activation(self):
        old_mode = config.MODE
        config.set_mode("live")
        try:
            old_enabled = config.STRATEGY["atr_trailing_enabled"]
            config.STRATEGY["atr_trailing_enabled"] = True
            pos = {
                "direction": "long",
                "entry": 100.0,
                "sl": 90.0,
                "current_price": 112.0,
                "initial_risk": 10.0,
                "best_price": 120.0,
                "exit_policy": build_exit_policy(signal={"reason": "TREND_BUY"}),
            }
            klines = [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(20)] + [
                {"close": 112.0, "high": 113.0, "low": 111.0}
            ]
            result = helpers.check_atr_trailing_exit(pos, klines)
            self.assertTrue(result["triggered"])
            self.assertAlmostEqual(result["target_sl"], 114.42857142857143)
        finally:
            config.STRATEGY["atr_trailing_enabled"] = old_enabled
            config.set_mode(old_mode)

    def test_check_atr_trailing_exit_requires_activation(self):
        old_mode = config.MODE
        config.set_mode("live")
        try:
            old_enabled = config.STRATEGY["atr_trailing_enabled"]
            config.STRATEGY["atr_trailing_enabled"] = True
            pos = {
                "direction": "long",
                "entry": 100.0,
                "sl": 90.0,
                "current_price": 108.0,
                "initial_risk": 10.0,
                "best_price": 108.0,
                "exit_policy": build_exit_policy(signal={"reason": "TREND_BUY"}),
            }
            klines = [{"close": 100.0, "high": 101.0, "low": 99.0} for _ in range(20)] + [
                {"close": 108.0, "high": 109.0, "low": 107.0}
            ]
            result = helpers.check_atr_trailing_exit(pos, klines)
            self.assertFalse(result["triggered"])
            self.assertFalse(result["active"])
        finally:
            config.STRATEGY["atr_trailing_enabled"] = old_enabled
            config.set_mode(old_mode)

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

    def test_load_coin_list_rebuilds_cache_when_metadata_mismatch(self):
        old_mode = config.MODE
        old_live_state_dir = config.LIVE_STATE_DIR
        old_universe = config.STRATEGY.get("coin_universe")
        tmpdir = tempfile.mkdtemp()
        config.LIVE_STATE_DIR = tmpdir
        config.STRATEGY["coin_universe"] = None
        config.set_mode("live")
        try:
            cache_path = os.path.join(tmpdir, "coin_list.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                handle.write('{"metadata":{"mode":"paper","market_data_source":"binance"},"coins":[{"name":"OLD","symbol":"OLDUSDT"}]}')
            with patch("trading_strategy.live.market._load_hyperliquid_coin_list", return_value=[{"name": "BTC", "symbol": "BTCUSDT"}]):
                coins = market.load_coin_list()
            self.assertEqual(coins, [{"name": "BTC", "symbol": "BTCUSDT"}])
        finally:
            config.STRATEGY["coin_universe"] = old_universe
            config.LIVE_STATE_DIR = old_live_state_dir
            config.set_mode(old_mode)

    def test_get_state_dir_separates_paper_and_live(self):
        old_mode = config.MODE
        try:
            config.set_mode("paper")
            self.assertEqual(config.get_state_dir(), config.PAPER_STATE_DIR)
            config.set_mode("live")
            self.assertEqual(config.get_state_dir(), config.LIVE_STATE_DIR)
        finally:
            config.set_mode(old_mode)

    def test_load_coin_list_uses_configured_universe(self):
        old_universe = config.STRATEGY.get("coin_universe")
        config.STRATEGY["coin_universe"] = ["btc", "ETH"]
        try:
            self.assertEqual(
                market.load_coin_list(),
                [{"name": "BTC", "symbol": "BTCUSDT"}, {"name": "ETH", "symbol": "ETHUSDT"}],
            )
        finally:
            config.STRATEGY["coin_universe"] = old_universe

    def test_paper_klines_fall_back_to_persisted_cache_after_network_failure(self):
        old_mode = config.MODE
        old_paper_state_dir = config.PAPER_STATE_DIR
        tmpdir = tempfile.mkdtemp()
        config.PAPER_STATE_DIR = tmpdir
        config.set_mode("paper")
        online_bars = [
            {"time": 1, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100.0},
            {"time": 2, "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5, "volume": 120.0},
        ]
        try:
            with patch("trading_strategy.live.market.api_get", return_value=[
                [bar["time"], str(bar["open"]), str(bar["high"]), str(bar["low"]), str(bar["close"]), str(bar["volume"])]
                for bar in online_bars
            ]):
                self.assertEqual(market.get_klines("BTCUSDT", 2), online_bars)
            with patch("trading_strategy.live.market.api_get", return_value=None):
                self.assertEqual(market.get_klines("BTCUSDT", 2), online_bars)
        finally:
            config.PAPER_STATE_DIR = old_paper_state_dir
            config.set_mode(old_mode)

    def test_live_klines_never_fall_back_to_paper_cache(self):
        old_mode = config.MODE
        old_live_state_dir = config.LIVE_STATE_DIR
        tmpdir = tempfile.mkdtemp()
        config.LIVE_STATE_DIR = tmpdir
        config.set_mode("live")
        try:
            with patch("trading_strategy.live.market.hl_info_post", return_value=None):
                self.assertIsNone(market.get_klines("BTCUSDT", 2))
        finally:
            config.LIVE_STATE_DIR = old_live_state_dir
            config.set_mode(old_mode)
