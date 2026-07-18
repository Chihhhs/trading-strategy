"""Native 4h momentum with strict entry and looser state-continuation thresholds."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

try:
    from backtest.run_low_capital_hyperliquid_4h_state_lab import (
        COINS,
        FOLD_BARS,
        FOLD_COUNT,
        HOLDOUT_BARS,
        aligned,
        failed_gates,
        simulate,
        summary,
    )
except ModuleNotFoundError:
    from run_low_capital_hyperliquid_4h_state_lab import COINS, FOLD_BARS, FOLD_COUNT, HOLDOUT_BARS, aligned, failed_gates, simulate, summary


def candidates():
    rows = []
    for coin in COINS:
        for entry_lookback, entry_threshold in ((3, 1.0), (6, 1.0), (6, 1.5), (12, 1.5)):
            for trend_lookback in (42, 84):
                for continuation_threshold in (0.0, 0.25):
                    for continuation_efficiency in (0.2, 0.3):
                        rows.append(
                            {
                                "coin": coin,
                                "entry_lookback": entry_lookback,
                                "entry_threshold": entry_threshold,
                                "trend_lookback": trend_lookback,
                                "efficiency_lookback": 6,
                                "efficiency_threshold": 0.4,
                                "entry_efficiency_threshold": 0.4,
                                "continuation_efficiency_threshold": continuation_efficiency,
                                "continuation_threshold": continuation_threshold,
                                "maximum_entry_funding_payment": 0.0000125,
                                "long_weight": 0.5,
                                "short_weight": 0.0,
                                "max_hold": None,
                            }
                        )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_low_capital_state.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_hyperliquid_4h_hysteresis.json")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    evaluated = []
    for candidate in candidates():
        asset = payload["assets"][candidate["coin"]]
        bars = len(asset["candles"])
        holdout_start = bars - HOLDOUT_BARS
        development_start = holdout_start - FOLD_BARS * FOLD_COUNT
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
        "route": "hyperliquid_4h_state_hysteresis_momentum",
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
