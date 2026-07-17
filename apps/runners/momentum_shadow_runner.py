"""Emit isolated target-weight observations; never places orders."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from trading_strategy.backtest.independent_lab import (
    _aligned_closes,
    fetch_current_daily_fixture,
    fetch_current_perp_meta,
    fetch_hyperliquid_funding_fixture,
    load_fixture,
    load_funding_fixture,
)
from trading_strategy.backtest.overlapping_momentum import OverlappingMomentumBacktester
from trading_strategy.experiments import load_experiment
from trading_strategy.strategies import build_execution_plan, get_strategy_definition, overlapping_momentum_weights


def build_snapshot(fixture_path, *, meta_path=None, capital=1000.0):
    fixture = load_fixture(fixture_path)
    timestamps, closes = _aligned_closes(fixture["data"])
    parameters = get_strategy_definition("cross_sectional_momentum").parse_parameters({})
    signal_index = next(
        index
        for index in range(len(timestamps) - 1, -1, -1)
        if datetime.fromtimestamp(timestamps[index] / 1000, timezone.utc).hour == parameters.rebalance_hour_utc
    )
    weights = overlapping_momentum_weights(
        closes,
        index=signal_index,
        lookback_bars=parameters.lookback_bars,
        top_n=parameters.top_n,
        overlap_cohorts=parameters.overlap_cohorts,
        cohort_spacing_bars=parameters.cohort_spacing_bars,
    )
    snapshot = {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_bar_time": timestamps[signal_index],
        "market_data_time": timestamps[-1],
        "strategy": "cross_sectional_momentum",
        "parameters": asdict(parameters),
        "weights": dict(sorted(weights.items())),
        "gross_exposure": sum(abs(weight) for weight in weights.values()),
        "net_exposure": sum(weights.values()),
        "execution_authorized": False,
    }
    if meta_path and Path(meta_path).is_file():
        meta = load_fixture(meta_path)["assets"]
        active = {coin: row for coin, row in meta.items() if not row["is_delisted"]}
        snapshot["execution_plan"] = build_execution_plan(
            weights,
            equity=capital,
            prices={coin: values[-1] for coin, values in closes.items()},
            sz_decimals={coin: row["sz_decimals"] for coin, row in active.items()},
        )
        snapshot["execution_plan"]["paper_equity"] = capital
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_current.json")
    parser.add_argument("--output", default="data/paper_strategies_momentum_shadow/latest.json")
    parser.add_argument("--records", default="data/paper_strategies_momentum_shadow/observations.jsonl")
    parser.add_argument("--meta", default="data/clean_room/hyperliquid_meta_current.json")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--funding", default="data/clean_room/hyperliquid_4h_funding.json")
    parser.add_argument("--paper-state")
    parser.add_argument("--experiment", default="experiments/cross_sectional_momentum_4h.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--fetch-meta", action="store_true")
    parser.add_argument("--fetch-funding", action="store_true")
    args = parser.parse_args()
    spec = load_experiment(args.experiment)
    if args.fetch:
        fetch_current_daily_fixture(
            args.fixture,
            min_bars=4000,
            max_assets=len(spec.coins),
            interval="4h",
            coins=spec.coins,
        )
    if args.fetch_meta:
        fetch_current_perp_meta(args.meta)
    if args.fetch_funding:
        fetch_hyperliquid_funding_fixture(args.fixture, args.funding)
    snapshot = build_snapshot(args.fixture, meta_path=args.meta, capital=args.capital)
    if args.paper_state:
        fixture = load_fixture(args.fixture)
        data = {coin.upper(): bars for coin, bars in fixture["data"].items()}
        funding = {coin.upper(): rows for coin, rows in load_funding_fixture(args.funding).items()}
        assets = load_fixture(args.meta)["assets"]
        decimals = {
            coin.upper(): row["sz_decimals"]
            for coin, row in assets.items()
            if not row["is_delisted"]
        }
        state_path = Path(args.paper_state)
        previous_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
        if previous_state and previous_state["experiment_fingerprint"] != spec.fingerprint:
            raise ValueError("paper state experiment fingerprint does not match")
        if previous_state and float(previous_state["initial_capital"]) != args.capital:
            raise ValueError("paper state initial capital does not match")
        if previous_state and previous_state.get("execution_authorized") is not False:
            raise ValueError("paper state authorization boundary is invalid")
        paper = OverlappingMomentumBacktester(
            fee_bps=spec.costs.fee_bps,
            slippage_bps=spec.costs.slippage_bps,
            parameters=spec.strategy.parameters,
            funding_data=funding,
        ).advance_paper(
            data,
            sz_decimals=decimals,
            portfolio_state=previous_state["paper"]["portfolio"] if previous_state else None,
            initial_capital=args.capital,
        )
        state_payload = {
            "schema_version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "experiment_fingerprint": spec.fingerprint,
            "initial_capital": args.capital,
            "execution_authorized": False,
            "paper": paper,
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(state_payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        snapshot["paper"] = {
            "initialized": paper["initialized"],
            "bars_processed": paper["bars_processed"],
            "equity": paper["portfolio"]["equity"],
            "fees_paid": paper["portfolio"]["fees_paid"],
            "funding_pnl": paper["portfolio"]["funding_pnl"],
            "submitted_orders": paper["submitted_orders"],
            "skipped_small_orders": paper["skipped_small_orders"],
        }
    output = Path(args.output)
    records = Path(args.records)
    output.parent.mkdir(parents=True, exist_ok=True)
    records.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else None
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    if not previous or previous.get("source_bar_time") != snapshot["source_bar_time"]:
        with records.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, sort_keys=True) + "\n")
    print(json.dumps(snapshot, sort_keys=True))


if __name__ == "__main__":
    main()
