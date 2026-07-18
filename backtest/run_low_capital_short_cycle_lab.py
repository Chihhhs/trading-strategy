"""One-hour, one-leg strategy search for sub-100-USDC accounts."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median, pstdev
import time
from urllib.parse import urlencode

try:
    from backtest.run_low_capital_lab import COINS, _json_request, _rounded_size
except ModuleNotFoundError:
    from run_low_capital_lab import COINS, _json_request, _rounded_size


BAR_MS = 3_600_000
DAY_BARS = 24
HOLDOUT_BARS = 90 * DAY_BARS
FOLD_BARS = 90 * DAY_BARS
FOLD_COUNT = 6


def fetch_klines(coin, start_ms, end_ms):
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        query = urlencode(
            {"symbol": f"{coin}USDT", "interval": "1h", "startTime": cursor, "endTime": end_ms, "limit": 1500}
        )
        page = _json_request(f"https://fapi.binance.com/fapi/v1/klines?{query}")
        if not page:
            break
        rows.extend([int(row[0]), float(row[4])] for row in page if int(row[6]) <= end_ms)
        cursor = int(page[-1][0]) + BAR_MS
        if len(page) < 1500:
            break
        time.sleep(0.1)
    return rows


def fetch_fixture(path, funding_fixture):
    source = json.loads(funding_fixture.read_text(encoding="utf-8"))
    start_ms = max(int(source["prices"][coin][0][0]) for coin in COINS)
    end_ms = int(time.time() * 1000) - BAR_MS
    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "price_source": "Binance USD-M perpetual public 1h klines",
        "funding_source": source["funding_source"],
        "coins": list(COINS),
        "sz_decimals": source["sz_decimals"],
        "prices": {coin: fetch_klines(coin, start_ms, end_ms) for coin in COINS},
        "funding": source["funding"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def load_aligned(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    maps = {coin: {int(row[0]): float(row[1]) for row in payload["prices"][coin]} for coin in COINS}
    timestamps = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    if len(timestamps) < HOLDOUT_BARS + FOLD_BARS * FOLD_COUNT + 200:
        raise ValueError("insufficient common 1h history")
    closes = {coin: [maps[coin][timestamp] for timestamp in timestamps] for coin in COINS}
    funding = {}
    for coin in COINS:
        events = [(int(row[0]), float(row[1])) for row in payload["funding"][coin]]
        cursor = 0
        aligned = [0.0]
        for index in range(1, len(timestamps)):
            total = 0.0
            while cursor < len(events) and events[cursor][0] <= timestamps[index]:
                if events[cursor][0] > timestamps[index - 1]:
                    total += events[cursor][1]
                cursor += 1
            aligned.append(total)
        funding[coin] = aligned
    return payload, timestamps, closes, funding


def route_candidates():
    routes = {"breakout": [], "return_momentum": [], "mean_reversion": []}
    for coin in COINS:
        for lookback in (48, 96):
            for hold in (12, 24):
                routes["breakout"].append(
                    {"route": "breakout", "coin": coin, "lookback": lookback, "max_hold": hold}
                )
        for lookback in (12, 24):
            for threshold in (1.0, 1.5):
                for hold in (6, 12):
                    routes["return_momentum"].append(
                        {
                            "route": "return_momentum",
                            "coin": coin,
                            "lookback": lookback,
                            "threshold": threshold,
                            "max_hold": hold,
                        }
                    )
        for lookback in (24, 48):
            for threshold in (1.5, 2.0):
                for hold in (6, 12):
                    routes["mean_reversion"].append(
                        {
                            "route": "mean_reversion",
                            "coin": coin,
                            "lookback": lookback,
                            "threshold": threshold,
                            "max_hold": hold,
                        }
                    )
    return routes


def desired_sign(candidate, prices, index, current_sign, age):
    lookback = candidate["lookback"]
    if index < lookback:
        return 0
    if current_sign and age >= candidate["max_hold"]:
        return 0
    if index % candidate.get("decision_interval", 1):
        return current_sign
    current = prices[index]
    prior = prices[index - lookback : index]
    if candidate["route"] == "breakout":
        signal = 1 if current > max(prior) else -1 if current < min(prior) else 0
        if signal and signal != current_sign:
            return signal
        return current_sign
    if candidate["route"] in {"return_momentum", "multi_hour_momentum", "aligned_multi_hour_momentum"}:
        total_return = current / prices[index - lookback] - 1.0
        hourly = [prices[i] / prices[i - 1] - 1.0 for i in range(index - lookback + 1, index + 1)]
        scale = math.sqrt(sum(value * value for value in hourly))
        score = total_return / scale if scale else 0.0
        signal = 1 if score >= candidate["threshold"] else -1 if score <= -candidate["threshold"] else 0
        trend_lookback = candidate.get("trend_lookback")
        if trend_lookback:
            if index < trend_lookback:
                return current_sign
            trend = current / prices[index - trend_lookback] - 1.0
            if not signal or signal * trend <= 0:
                signal = 0
        if signal and signal != current_sign:
            return signal
        return current_sign
    average = sum(prior) / len(prior)
    deviation = pstdev(prior)
    zscore = (current - average) / deviation if deviation else 0.0
    signal = -1 if zscore >= candidate["threshold"] else 1 if zscore <= -candidate["threshold"] else 0
    if not current_sign:
        return signal
    crossed_mean = (current_sign > 0 and current >= average) or (current_sign < 0 and current <= average)
    if crossed_mean:
        return 0
    return signal if signal and signal != current_sign else current_sign


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
    fees = 0.0
    funding_pnl = 0.0
    turnover = 0.0
    orders = 0
    skipped = 0
    for index in range(start, end):
        price = prices[index]
        if index > start:
            payment = -size * price * funding[coin][index]
            cash += payment
            funding_pnl += payment
        equity = cash + size * price
        target_sign = desired_sign(candidate, prices, index, sign, age)
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
    exit_notional = abs(size) * prices[end - 1]
    exit_fee = exit_notional * cost_bps / 10_000.0
    fees += exit_fee
    turnover += exit_notional
    curve[-1] -= exit_fee
    returns = [curve[0] / capital - 1.0]
    returns.extend(curve[index] / curve[index - 1] - 1.0 for index in range(1, len(curve)))
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


def summary(rows):
    return {
        "positive_folds": sum(row["net_return_pct"] > 0 for row in rows),
        "median_net_return_pct": median(row["net_return_pct"] for row in rows),
        "median_sharpe": median(row["sharpe"] for row in rows),
        "worst_drawdown_pct": max(row["max_drawdown_pct"] for row in rows),
        "orders": sum(row["orders"] for row in rows),
        "skipped_small_orders": sum(row["skipped_small_orders"] for row in rows),
    }


def failed_gates(normal, stressed):
    checks = {
        "normal_positive_folds_below_5_of_6": normal["positive_folds"] < 5,
        "stressed_positive_folds_below_5_of_6": stressed["positive_folds"] < 5,
        "median_normal_sharpe_not_above_0_5": normal["median_sharpe"] <= 0.5,
        "stressed_worst_drawdown_above_20_pct": stressed["worst_drawdown_pct"] > 20.0,
        "too_few_orders_below_60": normal["orders"] < 60,
    }
    return [name for name, failed in checks.items() if failed]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/binance_hl_low_capital_1h.json")
    parser.add_argument("--funding-fixture", default="data/clean_room/binance_hl_low_capital_4h.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_short_cycle_routes.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    if args.fetch:
        fetch_fixture(fixture_path, Path(args.funding_fixture))
    payload, timestamps, closes, funding = load_aligned(fixture_path)
    holdout_start = len(timestamps) - HOLDOUT_BARS
    development_start = holdout_start - FOLD_BARS * FOLD_COUNT
    folds = [
        (development_start + fold * FOLD_BARS, development_start + (fold + 1) * FOLD_BARS)
        for fold in range(FOLD_COUNT)
    ]
    route_reports = []
    for route, route_rows in route_candidates().items():
        evaluated = []
        for candidate in route_rows:
            normal_rows = [
                simulate(candidate, timestamps, closes, funding, payload["sz_decimals"], start=start, end=end)
                for start, end in folds
            ]
            stress_rows = [
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
            stressed = summary(stress_rows)
            failures = failed_gates(normal, stressed)
            evaluated.append(
                {
                    "candidate": candidate,
                    "passed": not failures,
                    "failed_gates": failures,
                    "normal": normal,
                    "stressed": stressed,
                    "normal_folds": normal_rows,
                    "stressed_folds": stress_rows,
                }
            )
        passing = [row for row in evaluated if row["passed"]]
        pool = passing or evaluated
        best = max(pool, key=lambda row: (row["stressed"]["positive_folds"], row["stressed"]["median_net_return_pct"]))
        route_report = {
            "route": route,
            "hypothesis": {
                "breakout": "prior-range breaks persist for 12-24 hours",
                "return_momentum": "volatility-scaled 12-24 hour returns persist for 6-12 hours",
                "mean_reversion": "1.5-2 sigma hourly dislocations revert within 6-12 hours",
            }[route],
            "candidate_count": len(evaluated),
            "passing_candidates": len(passing),
            "decision": "development_pass" if passing else "rejected_in_development",
            "best": best,
            "review": best["failed_gates"] if not passing else [],
            "candidates": evaluated,
        }
        if args.unlock_holdout and passing:
            route_report["holdout"] = simulate(
                best["candidate"],
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=holdout_start,
                end=len(timestamps),
            )
            route_report["holdout_stressed"] = simulate(
                best["candidate"],
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=holdout_start,
                end=len(timestamps),
                cost_bps=10.0,
            )
            holdout_failures = []
            if route_report["holdout"]["net_return_pct"] <= 0:
                holdout_failures.append("normal_holdout_net_return_not_positive")
            if route_report["holdout_stressed"]["net_return_pct"] <= 0:
                holdout_failures.append("stressed_holdout_net_return_not_positive")
            if route_report["holdout_stressed"]["max_drawdown_pct"] > 20.0:
                holdout_failures.append("stressed_holdout_drawdown_above_20_pct")
            route_report["decision"] = "rejected_in_holdout" if holdout_failures else "holdout_pass"
            route_report["review"] = holdout_failures
        route_reports.append(route_report)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "capital": 50.0,
        "minimum_order_notional": 10.0,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "sources": {"prices": payload["price_source"], "funding": payload["funding_source"]},
        "data": {
            "bars": len(timestamps),
            "start": timestamps[0],
            "development_start": timestamps[development_start],
            "holdout_start": timestamps[holdout_start],
            "end": timestamps[-1],
        },
        "gate": {
            "positive_folds": "at least 5/6 normal and stressed",
            "median_normal_sharpe": "above 0.5",
            "worst_stressed_drawdown_pct": "at most 20",
            "minimum_orders_across_folds": 60,
        },
        "routes": route_reports,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
                    "holdout": row.get("holdout"),
                }
                for row in route_reports
            ],
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
