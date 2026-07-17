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

from trading_strategy.backtest.independent_lab import _aligned_closes, fetch_current_daily_fixture, load_fixture
from trading_strategy.strategies import get_strategy_definition, overlapping_momentum_weights


def build_snapshot(fixture_path):
    fixture = load_fixture(fixture_path)
    timestamps, closes = _aligned_closes(fixture["data"])
    parameters = get_strategy_definition("cross_sectional_momentum").parse_parameters({})
    weights = overlapping_momentum_weights(
        closes,
        index=len(timestamps) - 1,
        lookback_bars=parameters.lookback_bars,
        top_n=parameters.top_n,
        overlap_cohorts=parameters.overlap_cohorts,
        cohort_spacing_bars=parameters.cohort_spacing_bars,
    )
    return {
        "schema_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_bar_time": timestamps[-1],
        "strategy": "cross_sectional_momentum",
        "parameters": asdict(parameters),
        "weights": dict(sorted(weights.items())),
        "gross_exposure": sum(abs(weight) for weight in weights.values()),
        "net_exposure": sum(weights.values()),
        "execution_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_current.json")
    parser.add_argument("--output", default="data/paper_strategies_momentum_shadow/latest.json")
    parser.add_argument("--records", default="data/paper_strategies_momentum_shadow/observations.jsonl")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        fetch_current_daily_fixture(args.fixture, min_bars=4000, max_assets=10, interval="4h")
    snapshot = build_snapshot(args.fixture)
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
