"""Regime momentum where funding can block, but never create, an entry."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

try:
    from backtest.run_low_capital_regime_momentum_lab import simulate
    from backtest.run_low_capital_short_cycle_lab import DAY_BARS, FOLD_BARS, FOLD_COUNT, failed_gates, load_aligned, summary
except ModuleNotFoundError:
    from run_low_capital_regime_momentum_lab import simulate
    from run_low_capital_short_cycle_lab import DAY_BARS, FOLD_BARS, FOLD_COUNT, failed_gates, load_aligned, summary


EARLY_VALIDATION_START = 60 * DAY_BARS
EARLY_VALIDATION_BARS = 180 * DAY_BARS
KNOWN_LATEST_BARS = 90 * DAY_BARS


def candidates():
    rows = []
    for coin in ("BTC", "ETH", "SOL", "BNB"):
        for entry_lookback, entry_threshold in ((24, 1.5), (12, 1.0)):
            for trend_lookback in (72, 168):
                for efficiency_threshold in (0.25, 0.4):
                    for continuation_threshold in (0.5, 1.0):
                        for maximum_payment in (0.0, 0.0000125):
                            rows.append(
                                {
                                    "coin": coin,
                                    "entry_lookback": entry_lookback,
                                    "entry_threshold": entry_threshold,
                                    "entry_requires_trend": True,
                                    "maximum_entry_funding_payment": maximum_payment,
                                    "base_hold": 12,
                                    "trend_lookback": trend_lookback,
                                    "efficiency_lookback": 24,
                                    "efficiency_threshold": efficiency_threshold,
                                    "continuation_threshold": continuation_threshold,
                                    "max_hold": 48,
                                }
                            )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/binance_hl_low_capital_1h.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_funding_gated_momentum.json")
    parser.add_argument("--unlock-early-validation", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload, timestamps, closes, funding = load_aligned(fixture_path)
    development_end = len(timestamps) - KNOWN_LATEST_BARS
    development_start = development_end - FOLD_BARS * FOLD_COUNT
    folds = [(development_start + fold * FOLD_BARS, development_start + (fold + 1) * FOLD_BARS) for fold in range(FOLD_COUNT)]
    validation = (EARLY_VALIDATION_START, EARLY_VALIDATION_START + EARLY_VALIDATION_BARS)
    evaluated = []
    for candidate in candidates():
        normal_rows = [simulate(candidate, timestamps, closes, funding, payload["sz_decimals"], start=start, end=end) for start, end in folds]
        stressed_rows = [simulate(candidate, timestamps, closes, funding, payload["sz_decimals"], start=start, end=end, cost_bps=10.0) for start, end in folds]
        normal = summary(normal_rows)
        stressed = summary(stressed_rows)
        failures = failed_gates(normal, stressed)
        evaluated.append({"candidate": candidate, "passed": not failures, "failed_gates": failures, "normal": normal, "stressed": stressed, "normal_folds": normal_rows, "stressed_folds": stressed_rows})
    passing = [row for row in evaluated if row["passed"]]
    pool = passing or evaluated
    best = max(pool, key=lambda row: (row["stressed"]["positive_folds"], row["stressed"]["median_net_return_pct"]))
    route = {
        "route": "funding_gated_regime_momentum",
        "hypothesis": "confirmed hourly momentum is more robust when entries paying crowded funding are blocked",
        "candidate_count": len(evaluated),
        "passing_candidates": len(passing),
        "decision": "development_pass" if passing else "rejected_in_development",
        "review": [] if passing else best["failed_gates"],
        "best": best,
        "candidates": evaluated,
    }
    if args.unlock_early_validation and passing:
        route["early_validation"] = simulate(best["candidate"], timestamps, closes, funding, payload["sz_decimals"], start=validation[0], end=validation[1])
        route["early_validation_stressed"] = simulate(best["candidate"], timestamps, closes, funding, payload["sz_decimals"], start=validation[0], end=validation[1], cost_bps=10.0)
        failures = []
        if route["early_validation"]["net_return_pct"] <= 0:
            failures.append("normal_early_validation_net_return_not_positive")
        if route["early_validation_stressed"]["net_return_pct"] <= 0:
            failures.append("stressed_early_validation_net_return_not_positive")
        if route["early_validation_stressed"]["max_drawdown_pct"] > 20.0:
            failures.append("stressed_early_validation_drawdown_above_20_pct")
        route["decision"] = "rejected_in_early_validation" if failures else "early_validation_pass"
        route["review"] = failures
        route["capital_replay"] = {
            str(capital): simulate(best["candidate"], timestamps, closes, funding, payload["sz_decimals"], start=validation[0], end=validation[1], capital=float(capital))
            for capital in (15, 20, 25, 30, 40, 50, 75, 100)
        }
    artifact = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "capital": 50.0,
        "minimum_order_notional": 10.0,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "data": {"development_start": timestamps[development_start], "development_end": timestamps[development_end - 1], "known_latest_excluded_start": timestamps[development_end], "early_validation_start": timestamps[validation[0]], "early_validation_end": timestamps[validation[1] - 1]},
        "route": route,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": route["decision"], "passing_candidates": route["passing_candidates"], "best": best["candidate"], "normal": best["normal"], "stressed": best["stressed"], "review": route["review"], "early_validation": route.get("early_validation")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
