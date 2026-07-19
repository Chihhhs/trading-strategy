"""Native Hyperliquid 4h state momentum with no holding-time limit."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median, pstdev
import time

try:
    from backtest.run_low_capital_lab import _json_request, _rounded_size
except ModuleNotFoundError:
    from run_low_capital_lab import _json_request, _rounded_size


COINS = ("BTC", "ETH", "SOL", "BNB")
BAR_MS = 4 * 3_600_000
DAY_BARS = 6
HOLDOUT_BARS = 120 * DAY_BARS
FOLD_BARS = 120 * DAY_BARS
FOLD_COUNT = 5


def fetch_funding(coin, start_ms, end_ms):
    rows = []
    cursor = start_ms
    while cursor <= end_ms:
        page = _json_request(
            "https://api.hyperliquid.xyz/info",
            {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms},
        )
        if not page:
            break
        rows.extend(
            [int(row["time"]), float(row["fundingRate"])]
            for row in page
            if int(row["time"]) <= end_ms
        )
        cursor = int(page[-1]["time"]) + 1
        if len(page) < 500:
            break
        time.sleep(0.2)
    return sorted({timestamp: rate for timestamp, rate in rows}.items())


def fetch_fixture(path):
    now = int(time.time() * 1000)
    end_ms = now // BAR_MS * BAR_MS - 1
    start_ms = end_ms - (5000 - 1) * BAR_MS
    meta = _json_request("https://api.hyperliquid.xyz/info", {"type": "meta"})
    active = {row["name"]: row for row in meta["universe"] if not row.get("isDelisted", False)}
    assets = {}
    for coin in COINS:
        candles = _json_request(
            "https://api.hyperliquid.xyz/info",
            {"type": "candleSnapshot", "req": {"coin": coin, "interval": "4h", "startTime": start_ms, "endTime": end_ms}},
        )
        assets[coin] = {
            "sz_decimals": int(active[coin]["szDecimals"]),
            "candles": [
                [int(row["t"]), float(row["c"]), float(row["v"])]
                for row in candles
                if int(row["T"]) <= end_ms
            ],
            "funding": fetch_funding(coin, start_ms, end_ms),
        }
    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Hyperliquid public candleSnapshot and fundingHistory",
        "interval": "4h",
        "assets": assets,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def aligned(asset):
    timestamps = [int(row[0]) for row in asset["candles"]]
    prices = [float(row[1]) for row in asset["candles"]]
    events = [(int(row[0]), float(row[1])) for row in asset["funding"]]
    cursor = 0
    rates = [0.0]
    for index in range(1, len(timestamps)):
        total = 0.0
        while cursor < len(events) and events[cursor][0] <= timestamps[index]:
            if events[cursor][0] > timestamps[index - 1]:
                total += events[cursor][1]
            cursor += 1
        rates.append(total)
    return timestamps, prices, rates


def candidates():
    rows = []
    for coin in COINS:
        for entry_lookback, entry_threshold in ((3, 1.0), (6, 1.0), (6, 1.5), (12, 1.5)):
            for trend_lookback in (42, 84):
                for efficiency_lookback in (6, 12):
                    rows.append(
                        {
                            "coin": coin,
                            "entry_lookback": entry_lookback,
                            "entry_threshold": entry_threshold,
                            "trend_lookback": trend_lookback,
                            "efficiency_lookback": efficiency_lookback,
                            "efficiency_threshold": 0.4,
                            "continuation_threshold": 0.5,
                            "maximum_entry_funding_payment": 0.0000125,
                            "long_weight": 0.5,
                            "short_weight": 0.0,
                            "max_hold": None,
                        }
                    )
    return rows


def momentum_score(prices, index, lookback):
    total = prices[index] / prices[index - lookback] - 1.0
    returns = [prices[row] / prices[row - 1] - 1.0 for row in range(index - lookback + 1, index + 1)]
    scale = math.sqrt(sum(value * value for value in returns))
    return total / scale if scale else 0.0


def classify(candidate, prices, funding_rate, index, holding):
    warmup = max(candidate["entry_lookback"], candidate["trend_lookback"], candidate["efficiency_lookback"])
    if index < warmup:
        return holding, "warmup"
    score = momentum_score(prices, index, candidate["entry_lookback"])
    trend = prices[index] / prices[index - candidate["trend_lookback"]] - 1.0
    start = index - candidate["efficiency_lookback"]
    path = sum(abs(prices[row] - prices[row - 1]) for row in range(start + 1, index + 1))
    efficiency = abs(prices[index] - prices[start]) / path if path else 0.0
    if not holding:
        if score < candidate["entry_threshold"]:
            return False, "flat"
        if trend <= 0 or efficiency < candidate.get("entry_efficiency_threshold", candidate["efficiency_threshold"]):
            return False, "range_filter"
        if funding_rate > candidate["maximum_entry_funding_payment"]:
            return False, "crowded_funding_filter"
        return True, "impulse_entry"
    strong = (
        score >= candidate["continuation_threshold"]
        and trend > 0
        and efficiency >= candidate.get("continuation_efficiency_threshold", candidate["efficiency_threshold"])
    )
    return (True, "strong_trend") if strong else (False, "decay_exit")


def simulate(
    candidate,
    asset,
    *,
    start,
    end,
    capital=50.0,
    cost_bps=6.5,
    min_notional=10.0,
    classifier=classify,
):
    timestamps, prices, funding = aligned(asset)
    cash = float(capital)
    size = 0.0
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
            payment = -size * price * funding[index]
            cash += payment
            funding_pnl += payment
        equity = cash + size * price
        target, state = classifier(candidate, prices, funding[index], index, bool(size))
        if isinstance(target, bool):
            target_direction = 1 if target else 0
        else:
            target_direction = int(target)
        current_direction = 1 if size > 0 else -1 if size < 0 else 0
        states[state] = states.get(state, 0) + 1
        if target_direction != current_direction:
            target_size = _rounded_size(
                (target_direction * 0.5 * equity / price) if target_direction else 0.0,
                asset["sz_decimals"],
            )
            delta = target_size - size
            notional = abs(delta) * price
            if delta and notional >= min_notional:
                fee = notional * cost_bps / 10_000.0
                cash -= delta * price + fee
                size = target_size
                age = 0
                fees += fee
                turnover += notional
                orders += 1
            elif delta:
                skipped += 1
        if size:
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


def summary(rows):
    return {
        "positive_folds": sum(row["net_return_pct"] > 0 for row in rows),
        "median_net_return_pct": median(row["net_return_pct"] for row in rows),
        "median_sharpe": median(row["sharpe"] for row in rows),
        "worst_drawdown_pct": max(row["max_drawdown_pct"] for row in rows),
        "orders": sum(row["orders"] for row in rows),
    }


def failed_gates(normal, stressed):
    checks = {
        "normal_positive_folds_below_4_of_5": normal["positive_folds"] < 4,
        "stressed_positive_folds_below_4_of_5": stressed["positive_folds"] < 4,
        "median_normal_sharpe_not_above_0_5": normal["median_sharpe"] <= 0.5,
        "stressed_worst_drawdown_above_20_pct": stressed["worst_drawdown_pct"] > 20.0,
        "too_few_orders_below_40": normal["orders"] < 40,
    }
    return [name for name, failed in checks.items() if failed]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_low_capital_state.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_hyperliquid_4h_state.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = fetch_fixture(fixture_path) if args.fetch else json.loads(fixture_path.read_text(encoding="utf-8"))
    evaluated = []
    for candidate in candidates():
        asset = payload["assets"][candidate["coin"]]
        bars = len(asset["candles"])
        holdout_start = bars - HOLDOUT_BARS
        development_start = holdout_start - FOLD_BARS * FOLD_COUNT
        if development_start < candidate["trend_lookback"]:
            raise ValueError(f"insufficient {candidate['coin']} 4h history")
        folds = [(development_start + fold * FOLD_BARS, development_start + (fold + 1) * FOLD_BARS) for fold in range(FOLD_COUNT)]
        normal_rows = [simulate(candidate, asset, start=start, end=end) for start, end in folds]
        stressed_rows = [simulate(candidate, asset, start=start, end=end, cost_bps=10.0) for start, end in folds]
        normal = summary(normal_rows)
        stressed = summary(stressed_rows)
        failures = failed_gates(normal, stressed)
        evaluated.append({"candidate": candidate, "passed": not failures, "failed_gates": failures, "normal": normal, "stressed": stressed, "normal_folds": normal_rows, "stressed_folds": stressed_rows})
    passing = [row for row in evaluated if row["passed"]]
    pool = passing or evaluated
    best = max(pool, key=lambda row: (row["stressed"]["positive_folds"], row["stressed"]["median_net_return_pct"]))
    coin = best["candidate"]["coin"]
    asset = payload["assets"][coin]
    timestamps, _, _ = aligned(asset)
    holdout_start = len(timestamps) - HOLDOUT_BARS
    route = {
        "route": "hyperliquid_4h_state_only_momentum",
        "holding_time_constraint": None,
        "candidate_count": len(evaluated),
        "passing_candidates": len(passing),
        "decision": "development_pass" if passing else "rejected_in_development",
        "review": [] if passing else best["failed_gates"],
        "best": best,
        "candidates": evaluated,
    }
    if args.unlock_holdout and passing:
        route["holdout"] = simulate(best["candidate"], asset, start=holdout_start, end=len(timestamps))
        route["holdout_stressed"] = simulate(best["candidate"], asset, start=holdout_start, end=len(timestamps), cost_bps=10.0)
        failures = []
        if route["holdout"]["net_return_pct"] <= 0:
            failures.append("normal_holdout_net_return_not_positive")
        if route["holdout_stressed"]["net_return_pct"] <= 0:
            failures.append("stressed_holdout_net_return_not_positive")
        if route["holdout_stressed"]["max_drawdown_pct"] > 20.0:
            failures.append("stressed_holdout_drawdown_above_20_pct")
        route["decision"] = "rejected_in_holdout" if failures else "holdout_pass"
        route["review"] = failures
        route["capital_replay"] = {
            str(capital): simulate(best["candidate"], asset, start=holdout_start, end=len(timestamps), capital=float(capital))
            for capital in (20, 25, 30, 50, 100)
        }
    artifact = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "capital": 50.0,
        "minimum_order_notional": 10.0,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "holdout": {"bars": HOLDOUT_BARS, "start": timestamps[holdout_start], "end": timestamps[-1]},
        "route": route,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": route["decision"], "passing_candidates": route["passing_candidates"], "best": best["candidate"], "normal": best["normal"], "stressed": best["stressed"], "review": route["review"], "holdout": route.get("holdout")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
