"""Funding and BTC-relative one-leg routes for low-capital hourly trading."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median, pstdev

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


def route_candidates():
    routes = {"funding_fade": [], "relative_momentum": [], "relative_reversion": []}
    for coin in ("BTC", "ETH", "SOL", "BNB"):
        for threshold in (0.0000125, 0.000025, 0.00005):
            for hold in (6, 12):
                routes["funding_fade"].append(
                    {"route": "funding_fade", "coin": coin, "threshold": threshold, "max_hold": hold}
                )
    for route in ("relative_momentum", "relative_reversion"):
        for coin in ("ETH", "SOL", "BNB"):
            for lookback in (6, 12, 24):
                for threshold in (1.0, 1.5):
                    for hold in (6, 12):
                        routes[route].append(
                            {
                                "route": route,
                                "coin": coin,
                                "lookback": lookback,
                                "threshold": threshold,
                                "max_hold": hold,
                            }
                        )
    return routes


def desired_sign(candidate, closes, funding, index, current_sign, age):
    if current_sign and age >= candidate["max_hold"]:
        return 0
    coin = candidate["coin"]
    if candidate["route"] == "funding_fade":
        rate = funding[coin][index]
        signal = -1 if rate >= candidate["threshold"] else 1 if rate <= -candidate["threshold"] else 0
    else:
        lookback = candidate["lookback"]
        if index < lookback:
            return current_sign
        relative = [closes[coin][row] / closes["BTC"][row] for row in range(index - lookback, index + 1)]
        total_return = relative[-1] / relative[0] - 1.0
        hourly = [relative[row] / relative[row - 1] - 1.0 for row in range(1, len(relative))]
        scale = math.sqrt(sum(value * value for value in hourly))
        score = total_return / scale if scale else 0.0
        signal = 1 if score >= candidate["threshold"] else -1 if score <= -candidate["threshold"] else 0
        if candidate["route"] == "relative_reversion":
            signal = -signal
    if signal and signal != current_sign:
        return signal
    return current_sign


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
    cash = float(capital)
    size = 0.0
    sign = 0
    age = 0
    curve = []
    fees = 0.0
    funding_pnl = 0.0
    turnover = 0.0
    orders = 0
    skipped = 0
    for index in range(start, end):
        price = closes[coin][index]
        if index > start:
            payment = -size * price * funding[coin][index]
            cash += payment
            funding_pnl += payment
        equity = cash + size * price
        target_sign = desired_sign(candidate, closes, funding, index, sign, age)
        if target_sign != sign:
            target_size = _rounded_size(target_sign * 0.5 * equity / price, decimals[coin])
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
        if sign:
            age += 1
        curve.append(cash + size * price)
    exit_notional = abs(size) * closes[coin][end - 1]
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
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/binance_hl_low_capital_1h.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_context_routes.json")
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
    if validation[1] >= development_start:
        raise ValueError("early validation overlaps development")
    route_reports = []
    for route, candidates in route_candidates().items():
        evaluated = []
        for candidate in candidates:
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
        report = {
            "route": route,
            "hypothesis": {
                "funding_fade": "extreme paid funding identifies crowded positions that unwind within 6-12 hours",
                "relative_momentum": "short-term altcoin strength versus BTC persists in the altcoin leg",
                "relative_reversion": "short-term altcoin dislocation versus BTC mean-reverts in the altcoin leg",
            }[route],
            "candidate_count": len(evaluated),
            "passing_candidates": len(passing),
            "decision": "development_pass" if passing else "rejected_in_development",
            "review": [] if passing else best["failed_gates"],
            "best": best,
            "candidates": evaluated,
        }
        if args.unlock_early_validation and passing:
            report["early_validation"] = simulate(
                best["candidate"], timestamps, closes, funding, payload["sz_decimals"], start=validation[0], end=validation[1]
            )
            report["early_validation_stressed"] = simulate(
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
            if report["early_validation"]["net_return_pct"] <= 0:
                failures.append("normal_early_validation_net_return_not_positive")
            if report["early_validation_stressed"]["net_return_pct"] <= 0:
                failures.append("stressed_early_validation_net_return_not_positive")
            if report["early_validation_stressed"]["max_drawdown_pct"] > 20.0:
                failures.append("stressed_early_validation_drawdown_above_20_pct")
            report["decision"] = "rejected_in_early_validation" if failures else "early_validation_pass"
            report["review"] = failures
        route_reports.append(report)
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
        "routes": route_reports,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "route": row["route"],
                    "decision": row["decision"],
                    "passing_candidates": row["passing_candidates"],
                    "best": row["best"]["candidate"],
                    "normal": row["best"]["normal"],
                    "stressed": row["best"]["stressed"],
                    "review": row["review"],
                    "early_validation": row.get("early_validation"),
                }
                for row in route_reports
            ],
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
