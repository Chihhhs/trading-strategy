"""Lower-frequency decisions on 1h bars, with an untouched early validation window."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

try:
    from backtest.run_low_capital_short_cycle_lab import (
        DAY_BARS,
        FOLD_BARS,
        FOLD_COUNT,
        failed_gates,
        load_aligned,
        simulate,
        summary,
    )
except ModuleNotFoundError:
    from run_low_capital_short_cycle_lab import (
        DAY_BARS,
        FOLD_BARS,
        FOLD_COUNT,
        failed_gates,
        load_aligned,
        simulate,
        summary,
    )


EARLY_VALIDATION_START = 60 * DAY_BARS
EARLY_VALIDATION_BARS = 180 * DAY_BARS
KNOWN_LATEST_BARS = 90 * DAY_BARS


def route_candidates(coins):
    routes = {"multi_hour_momentum": [], "aligned_multi_hour_momentum": []}
    for coin in coins:
        for interval in (2, 4):
            for lookback in (12, 24):
                for threshold in (1.0, 1.5):
                    for hold in (12, 18):
                        base = {
                            "coin": coin,
                            "lookback": lookback,
                            "threshold": threshold,
                            "max_hold": hold,
                            "decision_interval": interval,
                        }
                        routes["multi_hour_momentum"].append(base | {"route": "multi_hour_momentum"})
                        for trend in (72, 168):
                            routes["aligned_multi_hour_momentum"].append(
                                base | {"route": "aligned_multi_hour_momentum", "trend_lookback": trend}
                            )
    return routes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/binance_hl_low_capital_1h.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_multi_hour_routes.json")
    parser.add_argument("--unlock-early-validation", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload, timestamps, closes, funding = load_aligned(fixture_path)
    development_end = len(timestamps) - KNOWN_LATEST_BARS
    development_start = development_end - FOLD_BARS * FOLD_COUNT
    folds = [
        (development_start + fold * FOLD_BARS, development_start + (fold + 1) * FOLD_BARS)
        for fold in range(FOLD_COUNT)
    ]
    validation = (EARLY_VALIDATION_START, EARLY_VALIDATION_START + EARLY_VALIDATION_BARS)
    if validation[1] >= development_start:
        raise ValueError("early validation overlaps development")
    routes = []
    for route, candidates in route_candidates(tuple(payload["coins"])).items():
        evaluated = []
        for candidate in candidates:
            normal_rows = [
                simulate(candidate, timestamps, closes, funding, payload["sz_decimals"], start=start, end=end)
                for start, end in folds
            ]
            stressed_rows = [
                simulate(
                    candidate,
                    timestamps,
                    closes,
                    funding,
                    payload["sz_decimals"],
                    start=start,
                    end=end,
                    cost_bps=10.0,
                )
                for start, end in folds
            ]
            normal = summary(normal_rows)
            stressed = summary(stressed_rows)
            failures = failed_gates(normal, stressed)
            evaluated.append(
                {
                    "candidate": candidate,
                    "passed": not failures,
                    "failed_gates": failures,
                    "normal": normal,
                    "stressed": stressed,
                    "normal_folds": normal_rows,
                    "stressed_folds": stressed_rows,
                }
            )
        passing = [row for row in evaluated if row["passed"]]
        pool = passing or evaluated
        best = max(pool, key=lambda row: (row["stressed"]["positive_folds"], row["stressed"]["median_net_return_pct"]))
        report = {
            "route": route,
            "hypothesis": (
                "two/four-hour decisions reduce noise and cost while preserving sub-day momentum"
                if route == "multi_hour_momentum"
                else "sub-day momentum persists only when aligned with a three/seven-day trend"
            ),
            "candidate_count": len(evaluated),
            "passing_candidates": len(passing),
            "decision": "development_pass" if passing else "rejected_in_development",
            "review": [] if passing else best["failed_gates"],
            "best": best,
            "candidates": evaluated,
        }
        if args.unlock_early_validation and passing:
            report["early_validation"] = simulate(
                best["candidate"],
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=validation[0],
                end=validation[1],
            )
            report["early_validation_stressed"] = simulate(
                best["candidate"],
                timestamps,
                closes,
                funding,
                payload["sz_decimals"],
                start=validation[0],
                end=validation[1],
                cost_bps=10.0,
            )
            failures = []
            if report["early_validation"]["net_return_pct"] <= 0:
                failures.append("normal_early_validation_net_return_not_positive")
            if report["early_validation_stressed"]["net_return_pct"] <= 0:
                failures.append("stressed_early_validation_net_return_not_positive")
            if report["early_validation_stressed"]["max_drawdown_pct"] > 20.0:
                failures.append("stressed_early_validation_drawdown_above_20_pct")
            report["decision"] = "rejected_in_early_validation" if failures else "early_validation_pass"
            report["review"] = failures
            report["capital_replay"] = {
                str(capital): simulate(
                    best["candidate"],
                    timestamps,
                    closes,
                    funding,
                    payload["sz_decimals"],
                    start=validation[0],
                    end=validation[1],
                    capital=float(capital),
                )
                for capital in (15, 20, 25, 30, 40, 50, 75, 100)
            }
        routes.append(report)
    artifact = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_authorized": False,
        "capital": 50.0,
        "minimum_order_notional": 10.0,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "data": {
            "development_start": timestamps[development_start],
            "development_end": timestamps[development_end - 1],
            "known_latest_excluded_start": timestamps[development_end],
            "early_validation_start": timestamps[validation[0]],
            "early_validation_end": timestamps[validation[1] - 1],
        },
        "routes": routes,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "route": row["route"],
                    "decision": row["decision"],
                    "passing_candidates": row["passing_candidates"],
                    "best": row["best"]["candidate"],
                    "normal": row["best"]["normal"],
                    "stressed": row["best"]["stressed"],
                    "review": row["review"],
                    "early_validation": row.get("early_validation"),
                }
                for row in routes
            ],
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
