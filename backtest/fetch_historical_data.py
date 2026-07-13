#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from trading_strategy.backtest.historical_fetch import build_hourly_fixture


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch paginated Binance 1h OHLCV data")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--max-days", type=int, default=240)
    parser.add_argument("--end-date", default="", help="Exclusive UTC end date, for example 2026-07-01")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    coins = tuple(item.strip().upper() for item in args.coins.split(",") if item.strip())
    now_ms = None
    if args.end_date:
        parsed = datetime.fromisoformat(args.end_date).replace(tzinfo=timezone.utc)
        now_ms = int(parsed.timestamp() * 1000)
    data, diagnostics = build_hourly_fixture(coins, args.max_days, now_ms=now_ms)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=True)
    for coin, row in diagnostics.items():
        print(
            f"{coin}: bars={row['available_bars']}/{row['expected_bars']}, "
            f"coverage={row['coverage_pct']:.2f}%"
        )
    return diagnostics


if __name__ == "__main__":
    main()
