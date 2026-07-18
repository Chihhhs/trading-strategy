"""Hourly momentum with explicit trend-continuation and decay states."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import pstdev

try:
    from backtest.run_low_capital_lab import _rounded_size
    from backtest.run_low_capital_short_cycle_lab import (
        DAY_BARS,
        FOLD_BARS,
        FOLD_COUNT,
        failed_gates,
        load_aligned,
        summary,
    )
except ModuleNotFoundError:
    from run_low_capital_lab import _rounded_size
    from run_low_capital_short_cycle_lab import DAY_BARS, FOLD_BARS, FOLD_COUNT, failed_gates, load_aligned, summary


EARLY_VALIDATION_START = 60 * DAY_BARS
EARLY_VALIDATION_BARS = 180 * DAY_BARS
KNOWN_LATEST_BARS = 90 * DAY_BARS


def candidates():
    rows = []
    for coin in ("BTC", "ETH", "SOL", "BNB"):
        for entry_lookback, entry_threshold, base_hold in ((24, 1.5, 12), (12, 1.0, 12)):
            for trend_lookback in (72, 168):
                for efficiency_threshold in (0.25, 0.4):
                    for continuation_threshold in (0.5, 1.0):
                        for max_hold in (48, 72):
                            rows.append(
                                {
                                    "coin": coin,
                                    "entry_lookback": entry_lookback,
                                    "entry_threshold": entry_threshold,
                                    "base_hold": base_hold,
                                    "trend_lookback": trend_lookback,
                                    "efficiency_lookback": 24,
                                    "efficiency_threshold": efficiency_threshold,
                                    "continuation_threshold": continuation_threshold,
                                    "max_hold": max_hold,
                                }
                            )
    return rows


def _momentum_score(prices, index, lookback):
    total_return = prices[index] / prices[index - lookback] - 1.0
    hourly = [prices[row] / prices[row - 1] - 1.0 for row in range(index - lookback + 1, index + 1)]
    scale = math.sqrt(sum(value * value for value in hourly))
    return total_return / scale if scale else 0.0


def classify(candidate, prices, index, current_sign, age, funding_rate=0.0):
    warmup = max(candidate["entry_lookback"], candidate["trend_lookback"], candidate["efficiency_lookback"])
    if index < warmup:
        return current_sign, "warmup"
    if current_sign and candidate.get("max_hold") is not None and age >= candidate["max_hold"]:
        return 0, "safety_exit"
    if index % candidate.get("decision_interval", 1):
        return current_sign, "between_decisions" if current_sign else "flat"
    score = _momentum_score(prices, index, candidate["entry_lookback"])
    impulse = 1 if score >= candidate["entry_threshold"] else -1 if score <= -candidate["entry_threshold"] else 0
    if not current_sign:
        if impulse < 0 and candidate.get("short_weight", 0.5) == 0:
            return 0, "bearish_cash"
        if impulse and impulse * funding_rate > candidate.get("maximum_entry_funding_payment", float("inf")):
            return 0, "crowded_funding_filter"
        if impulse and candidate.get("entry_requires_trend"):
            trend = prices[index] / prices[index - candidate["trend_lookback"]] - 1.0
            start = index - candidate["efficiency_lookback"]
            path = sum(abs(prices[row] - prices[row - 1]) for row in range(start + 1, index + 1))
            efficiency = abs(prices[index] - prices[start]) / path if path else 0.0
            if impulse * trend <= 0 or efficiency < candidate["efficiency_threshold"]:
                return 0, "range_filter"
        return (impulse, "impulse_entry") if impulse else (0, "flat")
    if impulse and impulse != current_sign:
        if impulse < 0 and candidate.get("short_weight", 0.5) == 0:
            return 0, "bearish_exit"
        return impulse, "opposite_impulse"
    if age < candidate.get("base_hold", 0):
        return current_sign, "base_hold"
    trend = prices[index] / prices[index - candidate["trend_lookback"]] - 1.0
    start = index - candidate["efficiency_lookback"]
    path = sum(abs(prices[row] - prices[row - 1]) for row in range(start + 1, index + 1))
    efficiency = abs(prices[index] - prices[start]) / path if path else 0.0
    strong = (
        current_sign * score >= candidate["continuation_threshold"]
        and current_sign * trend > 0
        and efficiency >= candidate["efficiency_threshold"]
    )
    return (current_sign, "strong_trend") if strong else (0, "decay_exit")


def simulate(
    candidate,
    timestamps,
    closes,
    funding,
    decimals,
    *,
    start,
    end,
    capital=50.0,
    cost_bps=6.5,
    min_notional=10.0,
):
    coin = candidate["coin"]
    prices = closes[coin]
    cash = float(capital)
    size = 0.0
    sign = 0
    age = 0
    curve = []
    states = {}
    fees = 0.0
    funding_pnl = 0.0
    turnover = 0.0
    orders = 0
    skipped = 0
    max_observed_holding_bars = 0
    for index in range(start, end):
        price = prices[index]
        if index > start:
            payment = -size * price * funding[coin][index]
            cash += payment
            funding_pnl += payment
        equity = cash + size * price
        target_sign, state = classify(candidate, prices, index, sign, age, funding[coin][index])
        states[state] = states.get(state, 0) + 1
        if target_sign != sign:
            target_weight = candidate.get("long_weight", 0.5) if target_sign > 0 else candidate.get("short_weight", 0.5)
            target_size = _rounded_size(target_sign * target_weight * equity / price, decimals[coin])
            delta = target_size - size
            notional = abs(delta) * price
            if delta and notional >= min_notional:
                fee = notional * cost_bps / 10_000.0
                cash -= delta * price + fee
                size = target_size
                sign = 1 if size > 0 else -1 if size < 0 else 0
                age = 0
                fees += fee
                turnover += notional
                orders += 1
            elif delta:
                skipped += 1
                states["minimum_notional_block"] = states.get("minimum_notional_block", 0) + 1
        if sign:
            age += 1
            max_observed_holding_bars = max(max_observed_holding_bars, age)
        curve.append(cash + size * price)
    exit_notional = abs(size) * prices[end - 1]
    exit_fee = exit_notional * cost_bps / 10_000.0
    curve[-1] -= exit_fee
    fees += exit_fee
    turnover += exit_notional
    returns = [curve[0] / capital - 1.0]
    returns.extend(curve[row] / curve[row - 1] - 1.0 for row in range(1, len(curve)))
    volatility = pstdev(returns) if returns else 0.0
    sharpe = (sum(returns) / len(returns)) / volatility * math.sqrt(365 * DAY_BARS) if volatility else 0.0
    peak = float(capital)
    drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = max(drawdown, 1.0 - value / peak)
    return {
        "net_return_pct": (curve[-1] / capital - 1.0) * 100.0,
        "sharpe": sharpe,
        "max_drawdown_pct": drawdown * 100.0,
        "orders": orders,
        "skipped_small_orders": skipped,
        "fees": fees,
        "funding_pnl": funding_pnl,
        "turnover_x": turnover / capital,
        "max_observed_holding_bars": max_observed_holding_bars,
        "state_counts": states,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/binance_hl_low_capital_1h.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_regime_momentum.json")
    parser.add_argument("--unlock-early-validation", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload, timestamps, closes, funding = load_aligned(fixture_path)
    development_end = len(timestamps) - KNOWN_LATEST_BARS
    development_start = development_end - FOLD_BARS * FOLD_COUNT
    folds = [
        (development_start + fold * FOLD_BARS, development_start + (fold + 1) * FOLD_BARS)
        for fold in range(FOLD_COUNT)
    ]
    validation = (EARLY_VALIDATION_START, EARLY_VALIDATION_START + EARLY_VALIDATION_BARS)
    evaluated = []
    for candidate in candidates():
        normal_rows = [
            simulate(candidate, timestamps, closes, funding, payload["sz_decimals"], start=start, end=end)
            for start, end in folds
        ]
        stressed_rows = [
            simulate(
                candidate,
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=start,
                end=end,
                cost_bps=10.0,
            )
            for start, end in folds
        ]
        normal = summary(normal_rows)
        stressed = summary(stressed_rows)
        failures = failed_gates(normal, stressed)
        evaluated.append(
            {
                "candidate": candidate,
                "passed": not failures,
                "failed_gates": failures,
                "normal": normal,
                "stressed": stressed,
                "normal_folds": normal_rows,
                "stressed_folds": stressed_rows,
            }
        )
    passing = [row for row in evaluated if row["passed"]]
    pool = passing or evaluated
    best = max(pool, key=lambda row: (row["stressed"]["positive_folds"], row["stressed"]["median_net_return_pct"]))
    route = {
        "route": "regime_momentum",
        "hypothesis": "hourly momentum should extend only while direction, multi-hour trend, and path efficiency agree",
        "states": ["flat", "impulse_entry", "base_hold", "strong_trend", "decay_exit", "safety_exit"],
        "candidate_count": len(evaluated),
        "passing_candidates": len(passing),
        "decision": "development_pass" if passing else "rejected_in_development",
        "review": [] if passing else best["failed_gates"],
        "best": best,
        "candidates": evaluated,
    }
    if args.unlock_early_validation and passing:
        route["early_validation"] = simulate(
            best["candidate"], timestamps, closes, funding, payload["sz_decimals"], start=validation[0], end=validation[1]
        )
        route["early_validation_stressed"] = simulate(
            best["candidate"],
            timestamps,
            closes,
            funding,
            payload["sz_decimals"],
            start=validation[0],
            end=validation[1],
            cost_bps=10.0,
        )
        failures = []
        if route["early_validation"]["net_return_pct"] <= 0:
            failures.append("normal_early_validation_net_return_not_positive")
        if route["early_validation_stressed"]["net_return_pct"] <= 0:
            failures.append("stressed_early_validation_net_return_not_positive")
        if route["early_validation_stressed"]["max_drawdown_pct"] > 20.0:
            failures.append("stressed_early_validation_drawdown_above_20_pct")
        route["decision"] = "rejected_in_early_validation" if failures else "early_validation_pass"
        route["review"] = failures
        route["capital_replay"] = {
            str(capital): simulate(
                best["candidate"],
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=validation[0],
                end=validation[1],
                capital=float(capital),
            )
            for capital in (15, 20, 25, 30, 40, 50, 75, 100)
        }
    artifact = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "capital": 50.0,
        "minimum_order_notional": 10.0,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "data": {
            "development_start": timestamps[development_start],
            "development_end": timestamps[development_end - 1],
            "known_latest_excluded_start": timestamps[development_end],
            "early_validation_start": timestamps[validation[0]],
            "early_validation_end": timestamps[validation[1] - 1],
        },
        "route": route,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": route["decision"],
                "passing_candidates": route["passing_candidates"],
                "best": best["candidate"],
                "normal": best["normal"],
                "stressed": best["stressed"],
                "review": route["review"],
                "early_validation": route.get("early_validation"),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
