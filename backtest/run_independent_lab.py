import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.independent_lab import (
    fetch_coinbase_daily_fixture,
    fetch_current_daily_fixture,
    fetch_hyperliquid_funding_fixture,
    write_search_report,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_daily_current.json")
    parser.add_argument("--output", default="data/research_artifacts/independent_strategy_search.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--fetch-coinbase", action="store_true")
    parser.add_argument("--volume-pool", type=int, default=30)
    parser.add_argument("--min-bars", type=int, default=720)
    parser.add_argument("--max-assets", type=int, default=12)
    parser.add_argument("--interval", choices=("1d", "4h"), default="1d")
    parser.add_argument("--unlock-holdout", action="store_true")
    parser.add_argument("--fetch-funding", action="store_true")
    parser.add_argument("--funding-output", default="data/clean_room/hyperliquid_4h_funding.json")
    parser.add_argument("--funding-input")
    args = parser.parse_args()
    if args.fetch:
        fetch_current_daily_fixture(
            args.fixture,
            volume_pool=args.volume_pool,
            min_bars=args.min_bars,
            max_assets=args.max_assets,
            interval=args.interval,
        )
    if args.fetch_coinbase:
        fetch_coinbase_daily_fixture(args.fixture)
    if args.fetch_funding:
        fetch_hyperliquid_funding_fixture(args.fixture, args.funding_output)
    print(
        json.dumps(
            write_search_report(
                args.fixture,
                args.output,
                unlock_holdout=args.unlock_holdout,
                funding_path=args.funding_input,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
