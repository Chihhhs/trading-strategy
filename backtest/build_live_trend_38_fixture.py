#!/usr/bin/env python3
"""Build the frozen 38-coin daily and 1h research fixture from Binance history."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request


FUTURES_URL = "https://fapi.binance.com/fapi/v1/klines"
SPOT_URL = "https://api.binance.com/api/v3/klines"
HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS


def _request(url, params):
    try:
        with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=15) as response:
            payload = json.loads(response.read())
        return payload if isinstance(payload, list) else None
    except Exception:
        return None


def _fetch(coin, interval, start_ms, end_ms):
    step = HOUR_MS if interval == "1h" else DAY_MS
    expected = (end_ms - start_ms) // step
    best_bars, best_venue = [], "unavailable"
    for venue, url in (("binance_usdm", FUTURES_URL), ("binance_spot", SPOT_URL)):
        rows, cursor = [], start_ms
        while cursor < end_ms:
            page = _request(url, {"symbol": f"{coin}USDT", "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000})
            if not page:
                break
            rows.extend(page)
            cursor = int(page[-1][0]) + step
            if len(page) < 1000:
                break
            time.sleep(0.05)
        bars = [
            {"time": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])}
            for row in rows if len(row) >= 6 and start_ms <= int(row[0]) < end_ms
        ]
        if len(bars) > len(best_bars):
            best_bars, best_venue = bars, venue
        if len(bars) == expected:
            return bars, venue
    return best_bars, best_venue


def _write(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the fixed 38-coin live-like Trend fixture")
    parser.add_argument("--coins", required=True)
    parser.add_argument("--end-date", required=True, help="Exclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--max-days", type=int, default=240)
    parser.add_argument("--daily-warmup-days", type=int, default=60)
    parser.add_argument("--daily-output", required=True)
    parser.add_argument("--hourly-output", required=True)
    parser.add_argument("--metadata-output", required=True)
    args = parser.parse_args(argv)
    coins = tuple(item.strip().upper() for item in args.coins.split(",") if item.strip())
    end_ms = int(datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms -= end_ms % DAY_MS
    hourly_start = end_ms - args.max_days * DAY_MS
    daily_start = hourly_start - args.daily_warmup_days * DAY_MS
    daily, hourly, coverage = {}, {}, {}
    for coin in coins:
        daily[coin], daily_source = _fetch(coin, "1d", daily_start, end_ms)
        hourly[coin], hourly_source = _fetch(coin, "1h", hourly_start, end_ms)
        coverage[coin] = {
            "daily_bars": len(daily[coin]),
            "daily_expected_bars": args.max_days + args.daily_warmup_days,
            "hourly_bars": len(hourly[coin]),
            "hourly_expected_bars": args.max_days * 24,
            "daily_source": daily_source,
            "hourly_source": hourly_source,
        }
        print(f"{coin}: daily={len(daily[coin])} hourly={len(hourly[coin])} source={daily_source}/{hourly_source}")
    _write(args.daily_output, daily)
    _write(args.hourly_output, hourly)
    complete = all(
        row["daily_bars"] >= args.max_days and row["hourly_bars"] == row["hourly_expected_bars"]
        for row in coverage.values()
    )
    hourly_checksum = sha256(json.dumps(hourly, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    _write(args.metadata_output, {
        "complete": complete,
        "coverage_bars": {coin: row["hourly_bars"] for coin, row in coverage.items()},
        "checksum_sha256": hourly_checksum,
        "interval": "1h",
        "market_data_policy": "binance_usdm_then_binance_spot_historical_only",
        "end_date_exclusive": args.end_date,
        "coins": coins,
        "coverage": coverage,
    })
    return complete


if __name__ == "__main__":
    main()
