"""Clean-room cross-sectional strength strategy definition.

The portfolio evaluator owns ranking and execution. This class is deliberately
not usable as a per-coin signal generator because a rank without the universe
would be a different strategy.
"""

from .base import BaseStrategy


class CrossSectionalStrengthStrategy(BaseStrategy):
    name = "cross_sectional_strength"

    def generate_signal(self, context):
        raise RuntimeError("cross_sectional_strength requires the portfolio evaluator")


__all__ = ["CrossSectionalStrengthStrategy"]
