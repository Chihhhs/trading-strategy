import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.cross_sectional import CrossSectionalStrengthBacktester
from trading_strategy.strategies import get_strategy_definition


def bars(closes):
    return [{"ts": index, "close": close} for index, close in enumerate(closes)]


class CrossSectionalStrengthTest(unittest.TestCase):
    def test_registry_exposes_typed_cross_sectional_strategy(self):
        definition = get_strategy_definition("cross_sectional_strength")
        parameters = definition.parse_parameters({"lookback_days": 2, "rebalance_days": 1, "top_n": 1})
        self.assertIn("cross_sectional", definition.capabilities)
        self.assertEqual(parameters.top_n, 1)

    def test_backtester_selects_strength_and_charges_turnover_cost(self):
        data = {
            "UP": bars([100, 101, 102, 104, 106, 108]),
            "DOWN": bars([100, 99, 98, 97, 96, 95]),
        }
        parameters = get_strategy_definition("cross_sectional_strength").parse_parameters(
            {"lookback_days": 2, "rebalance_days": 1, "top_n": 1}
        )
        free = CrossSectionalStrengthBacktester(
            initial_capital=1000, fee_bps=0, slippage_bps=0, parameters=parameters
        ).run(data, coins=("UP", "DOWN"))
        costed = CrossSectionalStrengthBacktester(
            initial_capital=1000, fee_bps=4.5, slippage_bps=2, parameters=parameters
        ).run(data, coins=("UP", "DOWN"))
        self.assertGreater(free.net_pnl_pct, 0)
        self.assertLess(costed.net_pnl_pct, free.net_pnl_pct)
        self.assertEqual(set(free.coin_contributions), {"UP"})

    def test_backtester_holds_cash_when_all_momentum_is_negative(self):
        data = {"A": bars([100, 99, 98, 97]), "B": bars([100, 98, 96, 94])}
        parameters = get_strategy_definition("cross_sectional_strength").parse_parameters(
            {"lookback_days": 2, "rebalance_days": 1, "top_n": 1}
        )
        result = CrossSectionalStrengthBacktester(
            initial_capital=1000, fee_bps=4.5, slippage_bps=2, parameters=parameters
        ).run(data, coins=("A", "B"))
        self.assertEqual(result.net_pnl_pct, 0.0)
        self.assertEqual(result.trades, 0)

    def test_breadth_filter_holds_cash_when_only_a_minority_is_positive(self):
        data = {
            "UP": bars([100, 101, 102, 103]),
            "DOWN_A": bars([100, 99, 98, 97]),
            "DOWN_B": bars([100, 98, 96, 94]),
        }
        parameters = get_strategy_definition("cross_sectional_strength").parse_parameters(
            {"lookback_days": 2, "rebalance_days": 1, "top_n": 1, "min_positive_fraction": 0.5}
        )
        result = CrossSectionalStrengthBacktester(
            initial_capital=1000, fee_bps=4.5, slippage_bps=2, parameters=parameters
        ).run(data, coins=("UP", "DOWN_A", "DOWN_B"))
        self.assertEqual(result.net_pnl_pct, 0.0)
        self.assertEqual(result.trades, 0)


if __name__ == "__main__":
    unittest.main()
