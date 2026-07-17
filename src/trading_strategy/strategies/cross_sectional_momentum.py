"""Pure portfolio target for the clean-room overlapping momentum strategy."""

from .base import BaseStrategy


def overlapping_momentum_weights(
    closes,
    *,
    index,
    lookback_bars,
    top_n,
    overlap_cohorts,
    cohort_spacing_bars,
):
    if top_n < 1 or overlap_cohorts < 1 or cohort_spacing_bars < 1:
        raise ValueError("momentum portfolio parameters must be positive")
    if len(closes) < top_n * 2:
        raise ValueError("momentum portfolio requires at least twice top_n assets")
    warmup = lookback_bars + (overlap_cohorts - 1) * cohort_spacing_bars
    if index < warmup:
        raise ValueError("insufficient history for overlapping momentum target")

    target = {}
    cohort_weight = 0.5 / top_n / overlap_cohorts
    for cohort in range(overlap_cohorts):
        signal_index = index - cohort * cohort_spacing_bars
        ranked = sorted(
            closes,
            key=lambda coin: closes[coin][signal_index] / closes[coin][signal_index - lookback_bars],
        )
        for coin in ranked[:top_n]:
            target[coin] = target.get(coin, 0.0) - cohort_weight
        for coin in ranked[-top_n:]:
            target[coin] = target.get(coin, 0.0) + cohort_weight
    return {coin: weight for coin, weight in target.items() if abs(weight) > 1e-12}


class CrossSectionalMomentumStrategy(BaseStrategy):
    name = "cross_sectional_momentum"

    def generate_signal(self, context):
        raise RuntimeError("cross_sectional_momentum requires a portfolio-level evaluator")


__all__ = ["CrossSectionalMomentumStrategy", "overlapping_momentum_weights"]
