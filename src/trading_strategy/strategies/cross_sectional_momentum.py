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
    target_sizes = {}
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
        target_sizes[coin] = float(target_size)
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
    remaining = list(orders)
    sequenced = []
    net_notional = sum(float(size) * float(prices.get(coin, 0.0)) for coin, size in current.items())
    starting_net = net_notional
    max_transient = abs(net_notional)
    while remaining:
        order = min(
            remaining,
            key=lambda row: abs(net_notional + (row["notional"] if row["side"] == "buy" else -row["notional"])),
        )
        remaining.remove(order)
        net_notional += order["notional"] if order["side"] == "buy" else -order["notional"]
        max_transient = max(max_transient, abs(net_notional))
        sequenced.append(order | {"sequence": len(sequenced) + 1})
    return {
        "feasible": not blockers,
        "orders": sequenced,
        "blockers": blockers,
        "target_sizes": target_sizes,
        "min_notional": float(min_notional),
        "planned_gross_notional": sum(order["notional"] for order in sequenced),
        "starting_net_notional": starting_net,
        "ending_net_notional": net_notional,
        "max_transient_net_notional": max_transient,
        "max_transient_net_exposure": max_transient / equity,
    }


def reconcile_execution_plan(plan, fills, *, equity, prices, current_sizes=None):
    actual = {coin: float(size) for coin, size in (current_sizes or {}).items()}
    for fill in fills:
        coin = fill["coin"]
        if coin not in prices or fill["side"] not in {"buy", "sell"} or float(fill["size"]) < 0:
            raise ValueError("invalid execution fill")
        signed_size = float(fill["size"]) if fill["side"] == "buy" else -float(fill["size"])
        actual[coin] = actual.get(coin, 0.0) + signed_size
    residuals = []
    for coin in sorted(set(plan["target_sizes"]) | set(actual)):
        residual_size = float(plan["target_sizes"].get(coin, 0.0)) - actual.get(coin, 0.0)
        residual_notional = abs(residual_size) * float(prices[coin])
        if residual_notional >= float(plan["min_notional"]):
            residuals.append(
                {"coin": coin, "residual_size": residual_size, "residual_notional": residual_notional}
            )
    net_notional = sum(size * float(prices[coin]) for coin, size in actual.items())
    gross_notional = sum(abs(size * float(prices[coin])) for coin, size in actual.items())
    missing_metadata = any(row["reason"] == "missing_market_metadata" for row in plan["blockers"])
    return {
        "complete": not residuals and not missing_metadata,
        "requires_repair": bool(residuals or missing_metadata),
        "residuals": residuals,
        "actual_sizes": actual,
        "net_exposure": net_notional / equity,
        "gross_exposure": gross_notional / equity,
    }


class CrossSectionalMomentumStrategy(BaseStrategy):
    name = "cross_sectional_momentum"

    def generate_signal(self, context):
        raise RuntimeError("cross_sectional_momentum requires a portfolio-level evaluator")


__all__ = [
    "CrossSectionalMomentumStrategy",
    "build_execution_plan",
    "overlapping_momentum_weights",
    "reconcile_execution_plan",
]
