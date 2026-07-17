import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.paper_portfolio import mark_portfolio, open_portfolio, rebalance_portfolio


class PaperPortfolioTest(unittest.TestCase):
    def test_fixed_units_apply_price_funding_and_rebalance_costs(self):
        state = open_portfolio(
            timestamp=0,
            prices={"LONG": 100.0, "SHORT": 100.0},
            target_weights={"LONG": 0.5, "SHORT": -0.5},
            equity=1000.0,
            one_way_cost_bps=10.0,
        )
        self.assertAlmostEqual(state.equity, 999.0)
        mark_portfolio(
            state,
            timestamp=1,
            prices={"LONG": 110.0, "SHORT": 90.0},
            funding_rates={"LONG": 0.001, "SHORT": 0.001},
        )
        self.assertAlmostEqual(state.equity, 1098.9)
        rebalance_portfolio(state, target_weights={"LONG": 0.0, "SHORT": 0.0}, one_way_cost_bps=10.0)
        self.assertAlmostEqual(state.equity, 1097.9)
        self.assertEqual(state.positions, {"LONG": 0.0, "SHORT": 0.0})

    def test_rejects_missing_prices_and_non_increasing_time(self):
        state = open_portfolio(timestamp=1, prices={"BTC": 100.0}, target_weights={"BTC": 1.0})
        with self.assertRaisesRegex(ValueError, "timestamps"):
            mark_portfolio(state, timestamp=1, prices={"BTC": 101.0})
        with self.assertRaisesRegex(ValueError, "cover"):
            mark_portfolio(state, timestamp=2, prices={})


if __name__ == "__main__":
    unittest.main()
