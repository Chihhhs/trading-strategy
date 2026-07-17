import argparse
import json
import os
from pathlib import Path
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.independent_lab import (
    fetch_coinbase_daily_fixture,
    fetch_current_daily_fixture,
    fetch_hyperliquid_funding_fixture,
    load_fixture,
    load_funding_fixture,
    write_search_report,
)
from trading_strategy.backtest.overlapping_momentum import OverlappingMomentumBacktester
from trading_strategy.experiments import load_experiment


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
    parser.add_argument("--execution-replay-output")
    parser.add_argument("--experiment", default="experiments/cross_sectional_momentum_4h.json")
    parser.add_argument("--meta-input")
    parser.add_argument("--paper-capital", type=float, default=1000.0)
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
    report = write_search_report(
        args.fixture,
        args.output,
        unlock_holdout=args.unlock_holdout,
        funding_path=args.funding_input,
    )
    if args.execution_replay_output:
        if not args.funding_input:
            parser.error("--execution-replay-output requires --funding-input")
        spec = load_experiment(args.experiment)
        fixture = load_fixture(args.fixture)
        data = {coin.upper(): bars for coin, bars in fixture["data"].items()}
        funding = {coin.upper(): rows for coin, rows in load_funding_fixture(args.funding_input).items()}
        replay = OverlappingMomentumBacktester(
            fee_bps=spec.costs.fee_bps,
            slippage_bps=spec.costs.slippage_bps,
            parameters=spec.strategy.parameters,
            funding_data=funding,
        )
        audit = replay.audit_fixed_unit(data, development_starts=report["development_fold_starts"])
        if args.meta_input:
            assets = load_fixture(args.meta_input)["assets"]
            decimals = {
                coin.upper(): row["sz_decimals"]
                for coin, row in assets.items()
                if not row["is_delisted"]
            }
            exchange = replay.run_exchange_replay(
                data,
                max_bars=720,
                sz_decimals=decimals,
                initial_capital=args.paper_capital,
            )
            audit["exchange_replay"] = {
                key: value
                for key, value in exchange.items()
                if key not in {"state", "coin_contributions"}
            }
            audit["exchange_replay"]["initial_capital"] = args.paper_capital
        audit["experiment_fingerprint"] = spec.fingerprint
        target = Path(args.execution_replay_output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(audit, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
