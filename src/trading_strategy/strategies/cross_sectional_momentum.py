"""Pure portfolio target for the clean-room overlapping momentum strategy."""

from decimal import Decimal, ROUND_DOWN

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


def build_execution_plan(weights, *, equity, prices, sz_decimals, min_notional=10.0, current_sizes=None):
    if equity <= 0 or min_notional <= 0:
        raise ValueError("execution plan requires positive equity and minimum notional")
    current = current_sizes or {}
    orders = []
    blockers = []
    for coin in sorted(set(weights) | set(current)):
        weight = weights.get(coin, 0.0)
        if coin not in prices or coin not in sz_decimals or prices[coin] <= 0:
            blockers.append({"coin": coin, "reason": "missing_market_metadata"})
            continue
        lot = Decimal(1).scaleb(-int(sz_decimals[coin]))
        raw_target = Decimal(str(weight * equity / prices[coin]))
        target_size = raw_target.copy_abs().quantize(lot, rounding=ROUND_DOWN)
        if raw_target < 0:
            target_size = -target_size
        delta = target_size - Decimal(str(current.get(coin, 0.0)))
        notional = float(abs(delta)) * float(prices[coin])
        if not delta:
            continue
        if notional < min_notional:
            blockers.append({"coin": coin, "reason": "below_minimum_notional", "notional": notional})
            continue
        orders.append(
            {
                "coin": coin,
                "side": "buy" if delta > 0 else "sell",
                "size": float(abs(delta)),
                "notional": notional,
                "target_size": float(target_size),
                "target_weight": float(weight),
            }
        )
    return {
        "feasible": not blockers,
        "orders": orders,
        "blockers": blockers,
        "planned_gross_notional": sum(order["notional"] for order in orders),
    }


class CrossSectionalMomentumStrategy(BaseStrategy):
    name = "cross_sectional_momentum"

    def generate_signal(self, context):
        raise RuntimeError("cross_sectional_momentum requires a portfolio-level evaluator")


__all__ = ["CrossSectionalMomentumStrategy", "build_execution_plan", "overlapping_momentum_weights"]
