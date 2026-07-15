#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import tempfile
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from trading_strategy.backtest.historical_fetch import fetch_binance_hourly_klines
from trading_strategy.backtest.fixture_metadata import build_fixture_metadata


def _write_fixture(path, data):
    """Persist each resume checkpoint without exposing a partial JSON file."""
    directory = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
    ) as handle:
        json.dump(data, handle, ensure_ascii=True)
        temporary_path = handle.name
    for attempt in range(5):
        try:
            os.replace(temporary_path, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.25 * (attempt + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch paginated Binance 1h OHLCV data")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--max-days", type=int, default=240)
    parser.add_argument("--end-date", default="", help="Exclusive UTC end date, for example 2026-07-01")
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", default="")
    parser.add_argument("--resume", action="store_true", help="Reuse complete coins already present in output")
    args = parser.parse_args(argv)
    coins = tuple(item.strip().upper() for item in args.coins.split(",") if item.strip())
    now_ms = None
    if args.end_date:
        parsed = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
        now_ms = int(parsed.timestamp() * 1000)
    end_ms = int(now_ms or datetime.now(tz=timezone.utc).timestamp() * 1000)
    hour_ms = 60 * 60 * 1000
    end_ms -= end_ms % hour_ms
    expected_bars = int(args.max_days) * 24
    start_ms = end_ms - expected_bars * hour_ms
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    data = {}
    if args.resume and os.path.isfile(args.output):
        with open(args.output, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    diagnostics = {}
    for coin in coins:
        existing = data.get(coin) or []
        if len(existing) >= expected_bars:
            bars = existing
        else:
            bars = fetch_binance_hourly_klines(coin, start_ms, end_ms)
            data[coin] = bars
            _write_fixture(args.output, data)
        diagnostics[coin] = {
            "expected_bars": expected_bars,
            "available_bars": len(bars),
            "coverage_pct": round(len(bars) / expected_bars * 100, 2) if expected_bars else 0.0,
        }
    for coin, row in diagnostics.items():
        print(
            f"{coin}: bars={row['available_bars']}/{row['expected_bars']}, "
            f"coverage={row['coverage_pct']:.2f}%"
        )
    metadata_path = args.metadata_output or f"{args.output}.metadata.json"
    metadata = build_fixture_metadata(
        data,
        venue="binance",
        market_type="spot",
        interval="1h",
        start_ms=start_ms,
        end_ms=end_ms,
        request_parameters={"coins": coins, "max_days": int(args.max_days)},
    )
    _write_fixture(metadata_path, metadata)
    return diagnostics


if __name__ == "__main__":
    main()
