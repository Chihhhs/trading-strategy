"""Fresh-data research for strategies executable with a 50 USDC account."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median, pstdev
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


COINS = ("BTC", "ETH", "SOL", "BNB")
BAR_MS = 4 * 3_600_000
DAY_BARS = 6
START_MS = int(datetime(2023, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
HOLDOUT_BARS = 180 * DAY_BARS
FOLD_BARS = 120 * DAY_BARS
FOLD_COUNT = 5


def _json_request(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            time.sleep(float(error.headers.get("Retry-After", 2 ** attempt)))


def fetch_binance_klines(coin, end_ms):
    rows = []
    cursor = START_MS
    while cursor < end_ms:
        query = urlencode(
            {"symbol": f"{coin}USDT", "interval": "4h", "startTime": cursor, "endTime": end_ms, "limit": 1500}
        )
        page = _json_request(f"https://fapi.binance.com/fapi/v1/klines?{query}")
        if not page:
            break
        rows.extend([int(row[0]), float(row[4])] for row in page if int(row[6]) <= end_ms)
        cursor = int(page[-1][0]) + BAR_MS
        if len(page) < 1500:
            break
        time.sleep(0.15)
    return rows


def fetch_hyperliquid_funding(coin, end_ms):
    rows = []
    cursor = START_MS
    while cursor < end_ms:
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
        time.sleep(0.15)
    return sorted({timestamp: rate for timestamp, rate in rows}.items())


def fetch_sz_decimals():
    meta = _json_request("https://api.hyperliquid.xyz/info", {"type": "meta"})
    active = {row["name"]: row for row in meta["universe"] if not row.get("isDelisted", False)}
    missing = sorted(set(COINS) - set(active))
    if missing:
        raise ValueError(f"inactive Hyperliquid contracts: {', '.join(missing)}")
    return {coin: int(active[coin]["szDecimals"]) for coin in COINS}


def fetch_fixture(path):
    end_ms = int(time.time() * 1000) - BAR_MS
    payload = {
        "schema_version": 1,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "price_source": "Binance USD-M perpetual public klines",
        "funding_source": "Hyperliquid public fundingHistory",
        "interval": "4h",
        "coins": list(COINS),
        "sz_decimals": fetch_sz_decimals(),
        "prices": {coin: fetch_binance_klines(coin, end_ms) for coin in COINS},
        "funding": {coin: fetch_hyperliquid_funding(coin, end_ms) for coin in COINS},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def load_aligned(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    maps = {coin: {int(row[0]): float(row[1]) for row in payload["prices"][coin]} for coin in COINS}
    timestamps = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    if len(timestamps) < HOLDOUT_BARS + FOLD_BARS * FOLD_COUNT + 700:
        raise ValueError("insufficient common history for frozen development and holdout")
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


def candidates():
    rows = []
    for days in (7, 14, 28, 56):
        for coin in COINS:
            rows.append({"kind": "single_tsmom", "days": days, "coin": coin})
        rows.extend(
            [
                {"kind": "absolute_rotation", "days": days},
                {"kind": "long_cash_rotation", "days": days},
                {"kind": "top_bottom_pair", "days": days},
            ]
        )
    return rows


def target_weights(candidate, closes, index):
    lookback = candidate["days"] * DAY_BARS
    scores = {coin: closes[coin][index] / closes[coin][index - lookback] - 1.0 for coin in COINS}
    if candidate["kind"] == "single_tsmom":
        score = scores[candidate["coin"]]
        return {candidate["coin"]: 0.5 if score > 0 else -0.5}
    if candidate["kind"] == "absolute_rotation":
        coin = max(COINS, key=lambda item: abs(scores[item]))
        return {coin: 0.5 if scores[coin] > 0 else -0.5}
    if candidate["kind"] == "long_cash_rotation":
        coin = max(COINS, key=scores.get)
        return {coin: 0.5} if scores[coin] > 0 else {}
    ranked = sorted(COINS, key=scores.get)
    return {ranked[0]: -0.4, ranked[-1]: 0.4}


def _rounded_size(raw_size, decimals):
    scale = 10 ** decimals
    return math.copysign(math.floor(abs(raw_size) * scale + 1e-12) / scale, raw_size)


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
    daily_drag_bps=0.0,
    min_notional=10.0,
):
    cash = float(capital)
    sizes = {coin: 0.0 for coin in COINS}
    equity_curve = []
    fees = 0.0
    funding_pnl = 0.0
    turnover = 0.0
    orders = 0
    skipped = 0
    blocked_starts = 0
    started = False
    for index in range(start, end):
        prices = {coin: closes[coin][index] for coin in COINS}
        if index > start:
            funding_delta = -sum(sizes[coin] * prices[coin] * funding[coin][index] for coin in COINS)
            cash += funding_delta
            funding_pnl += funding_delta
        equity = cash + sum(sizes[coin] * prices[coin] for coin in COINS)
        if daily_drag_bps and index % DAY_BARS == 0:
            drag = sum(abs(sizes[coin] * prices[coin]) for coin in COINS) * daily_drag_bps / 10_000.0
            cash -= drag
            equity -= drag
        hour = datetime.fromtimestamp(timestamps[index] / 1000, timezone.utc).hour
        if hour == 0:
            weights = target_weights(candidate, closes, index)
            targets = {
                coin: _rounded_size(weights.get(coin, 0.0) * equity / prices[coin], decimals[coin])
                for coin in COINS
            }
            deltas = {coin: targets[coin] - sizes[coin] for coin in COINS}
            executable = {
                coin: delta
                for coin, delta in deltas.items()
                if delta and abs(delta) * prices[coin] >= min_notional
            }
            desired = {coin for coin, weight in weights.items() if weight}
            unavailable = {
                coin
                for coin in desired
                if not sizes[coin] and (not targets[coin] or coin not in executable)
            }
            if not started and unavailable:
                blocked_starts += 1
                executable = {}
            elif not started and executable:
                started = True
            skipped += sum(bool(delta) and coin not in executable for coin, delta in deltas.items())
            for coin, delta in executable.items():
                notional = abs(delta) * prices[coin]
                fee = notional * cost_bps / 10_000.0
                cash -= delta * prices[coin] + fee
                sizes[coin] += delta
                fees += fee
                turnover += notional
                orders += 1
            equity = cash + sum(sizes[coin] * prices[coin] for coin in COINS)
        equity_curve.append(equity)
    final_prices = {coin: closes[coin][end - 1] for coin in COINS}
    exit_notional = sum(abs(sizes[coin]) * final_prices[coin] for coin in COINS)
    exit_fee = exit_notional * cost_bps / 10_000.0
    final_equity = equity_curve[-1] - exit_fee
    fees += exit_fee
    turnover += exit_notional
    equity_curve[-1] = final_equity
    returns = [equity_curve[0] / capital - 1.0]
    returns.extend(equity_curve[i] / equity_curve[i - 1] - 1.0 for i in range(1, len(equity_curve)))
    volatility = pstdev(returns) if returns else 0.0
    sharpe = (sum(returns) / len(returns)) / volatility * math.sqrt(365 * DAY_BARS) if volatility else 0.0
    peak = float(capital)
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, 1.0 - value / peak)
    return {
        "net_return_pct": (final_equity / capital - 1.0) * 100.0,
        "sharpe": sharpe,
        "max_drawdown_pct": max_drawdown * 100.0,
        "orders": orders,
        "skipped_small_orders": skipped,
        "blocked_starts": blocked_starts,
        "fees": fees,
        "funding_pnl": funding_pnl,
        "turnover_x": turnover / capital,
    }


def summarize(rows):
    return {
        "positive": sum(row["net_return_pct"] > 0 for row in rows),
        "median_net_return_pct": median(row["net_return_pct"] for row in rows),
        "median_sharpe": median(row["sharpe"] for row in rows),
        "worst_drawdown_pct": max(row["max_drawdown_pct"] for row in rows),
        "total_orders": sum(row["orders"] for row in rows),
        "total_blocked_starts": sum(row["blocked_starts"] for row in rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/binance_hl_low_capital_4h.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_strategy_search.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = fetch_fixture(fixture_path) if args.fetch else json.loads(fixture_path.read_text(encoding="utf-8"))
    payload, timestamps, closes, funding = load_aligned(fixture_path)
    holdout_start = len(timestamps) - HOLDOUT_BARS
    development_start = holdout_start - FOLD_BARS * FOLD_COUNT
    fold_ranges = [
        (development_start + fold * FOLD_BARS, development_start + (fold + 1) * FOLD_BARS)
        for fold in range(FOLD_COUNT)
    ]
    results = []
    for candidate in candidates():
        normal = [
            simulate(candidate, timestamps, closes, funding, payload["sz_decimals"], start=start, end=end)
            for start, end in fold_ranges
        ]
        stressed = [
            simulate(
                candidate,
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=start,
                end=end,
                cost_bps=10.0,
                daily_drag_bps=1.0,
            )
            for start, end in fold_ranges
        ]
        normal_summary = summarize(normal)
        stress_summary = summarize(stressed)
        passed = (
            normal_summary["positive"] >= 4
            and stress_summary["positive"] >= 4
            and normal_summary["median_sharpe"] > 0.5
            and stress_summary["worst_drawdown_pct"] <= 25.0
            and stress_summary["total_blocked_starts"] == 0
        )
        results.append(
            {
                "candidate": candidate,
                "passed": passed,
                "normal": normal_summary,
                "stressed": stress_summary,
                "normal_folds": normal,
                "stressed_folds": stressed,
            }
        )
    passing = [row for row in results if row["passed"]]
    winner = max(
        passing,
        key=lambda row: (row["stressed"]["median_net_return_pct"], -row["stressed"]["worst_drawdown_pct"]),
        default=None,
    )
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "capital": 50.0,
        "minimum_order_notional": 10.0,
        "sources": {"prices": payload["price_source"], "funding": payload["funding_source"]},
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "data": {
            "bars": len(timestamps),
            "start": timestamps[0],
            "end": timestamps[-1],
            "development_start": timestamps[development_start],
            "holdout_start": timestamps[holdout_start],
            "holdout_bars": HOLDOUT_BARS,
        },
        "gate": {
            "positive_folds": "at least 4/5 normal and stressed",
            "median_normal_sharpe": "above 0.5",
            "worst_stressed_drawdown_pct": "at most 25",
            "blocked_starts": 0,
        },
        "passing_candidates": len(passing),
        "winner": winner,
        "candidates": results,
    }
    if args.unlock_holdout and winner:
        candidate = winner["candidate"]
        report["holdout"] = simulate(
            candidate,
            timestamps,
            closes,
            funding,
            payload["sz_decimals"],
            start=holdout_start,
            end=len(timestamps),
        )
        report["holdout_stressed"] = simulate(
            candidate,
            timestamps,
            closes,
            funding,
            payload["sz_decimals"],
            start=holdout_start,
            end=len(timestamps),
            cost_bps=10.0,
            daily_drag_bps=1.0,
        )
        report["capital_replay"] = {
            str(capital): simulate(
                candidate,
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=holdout_start,
                end=len(timestamps),
                capital=float(capital),
            )
            for capital in (20, 25, 30, 40, 50, 75, 100)
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    compact = {
        "passing_candidates": len(passing),
        "winner": winner["candidate"] if winner else None,
        "winner_normal": winner["normal"] if winner else None,
        "winner_stressed": winner["stressed"] if winner else None,
        "holdout": report.get("holdout"),
        "holdout_stressed": report.get("holdout_stressed"),
    }
    print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
