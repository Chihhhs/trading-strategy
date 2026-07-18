import unittest
from datetime import datetime, timezone

from backtest.run_low_capital_lab import BAR_MS as FOUR_HOUR_MS, COINS, simulate as simulate_long
from backtest.run_low_capital_regime_momentum_lab import simulate as simulate_regime
from backtest.run_low_capital_short_cycle_lab import BAR_MS, desired_sign, simulate as simulate_short


class LowCapitalResearchTest(unittest.TestCase):
    def test_long_pair_stays_in_cash_when_both_legs_are_too_small(self):
        timestamps = [index * FOUR_HOUR_MS for index in range(500)]
        closes = {
            coin: [100.0 + (coin_index + 1) * index / 10 for index in range(500)]
            for coin_index, coin in enumerate(COINS)
        }
        result = simulate_long(
            {"kind": "top_bottom_pair", "days": 7},
            timestamps,
            closes,
            {coin: [0.0] * 500 for coin in COINS},
            {coin: 3 for coin in COINS},
            start=100,
            end=200,
            capital=10.0,
        )
        self.assertEqual(result["orders"], 0)
        self.assertGreater(result["blocked_starts"], 0)
        self.assertEqual(result["net_return_pct"], 0.0)

    def test_short_cycle_signal_does_not_read_future_prices(self):
        prices = [100.0 + index / 10 for index in range(300)]
        candidate = {
            "route": "return_momentum",
            "coin": "ETH",
            "lookback": 24,
            "threshold": 1.5,
            "max_hold": 12,
        }
        before = desired_sign(candidate, prices, 100, 0, 0)
        prices[250] = 1.0
        self.assertEqual(desired_sign(candidate, prices, 100, 0, 0), before)

    def test_short_cycle_fees_reduce_the_same_trade_path(self):
        start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        timestamps = [start + index * BAR_MS for index in range(500)]
        closes = {coin: [100.0] * 500 for coin in COINS}
        closes["ETH"] = [100.0 + index / 20 for index in range(500)]
        funding = {coin: [0.0] * 500 for coin in COINS}
        decimals = {coin: 3 for coin in COINS}
        candidate = {
            "route": "return_momentum",
            "coin": "ETH",
            "lookback": 24,
            "threshold": 1.0,
            "max_hold": 12,
        }
        free = simulate_short(
            candidate, timestamps, closes, funding, decimals, start=100, end=400, cost_bps=0.0
        )
        costed = simulate_short(candidate, timestamps, closes, funding, decimals, start=100, end=400)
        self.assertEqual(free["orders"], costed["orders"])
        self.assertGreater(free["net_return_pct"], costed["net_return_pct"])

    def test_state_only_momentum_has_no_hidden_holding_limit(self):
        start = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        timestamps = [start + index * BAR_MS for index in range(600)]
        closes = {coin: [100.0] * 600 for coin in COINS}
        closes["ETH"] = [100.0 * 1.001 ** index for index in range(600)]
        candidate = {
            "coin": "ETH",
            "decision_interval": 1,
            "entry_lookback": 12,
            "entry_threshold": 0.5,
            "entry_requires_trend": True,
            "maximum_entry_funding_payment": 0.0000125,
            "long_weight": 0.5,
            "short_weight": 0.0,
            "base_hold": 0,
            "max_hold": None,
            "trend_lookback": 72,
            "efficiency_lookback": 24,
            "efficiency_threshold": 0.4,
            "continuation_threshold": 0.25,
        }
        result = simulate_regime(
            candidate,
            timestamps,
            closes,
            {coin: [0.0] * 600 for coin in COINS},
            {coin: 3 for coin in COINS},
            start=100,
            end=500,
        )
        self.assertGreater(result["max_observed_holding_bars"], 48)
        self.assertNotIn("safety_exit", result["state_counts"])


if __name__ == "__main__":
    unittest.main()
