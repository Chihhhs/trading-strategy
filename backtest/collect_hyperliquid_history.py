"""Create a Hyperliquid 1h research fixture without changing runtime state."""

import argparse
import json
from pathlib import Path

from trading_strategy.backtest.hyperliquid_history import collect_fixture
from trading_strategy.experiments import load_experiment


def main(argv=None):
    parser = argparse.ArgumentParser(prog="collect_hyperliquid_history")
    parser.add_argument("--experiment", default="experiments/live_trend_baseline.json")
    parser.add_argument("--days", type=int, default=240)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    spec = load_experiment(args.experiment)
    fixture = collect_fixture(spec.coins, days=args.days)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fixture, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(target), "requested": len(spec.coins), "missing": fixture["missing_coins"]}, sort_keys=True))
    return fixture


if __name__ == "__main__":
    main()
