"""Test entry-volume confirmation for native Hyperliquid 4h state momentum."""

import argparse
import json
from pathlib import Path
from statistics import median

try:
    from backtest import run_low_capital_hyperliquid_4h_state_lab as base
except ModuleNotFoundError:
    import run_low_capital_hyperliquid_4h_state_lab as base


def candidates():
    for candidate in base.candidates():
        for volume_ratio in (1.0, 1.5):
            yield {
                **candidate,
                "volume_lookback": 42,
                "minimum_entry_volume_ratio": volume_ratio,
            }


def classifier_for(volumes):
    def classify(candidate, prices, funding_rate, index, holding):
        target, state = base.classify(candidate, prices, funding_rate, index, holding)
        if holding or not target:
            return target, state
        lookback = candidate["volume_lookback"]
        if index < lookback:
            return False, "warmup"
        typical = median(volumes[index - lookback:index])
        ratio = volumes[index] / typical if typical else 0.0
        if ratio < candidate["minimum_entry_volume_ratio"]:
            return False, "weak_volume_filter"
        return True, state

    return classify


def evaluate(candidate, asset, folds, cost_bps):
    volumes = [float(row[2]) for row in asset["candles"]]
    classifier = classifier_for(volumes)
    return [
        base.simulate(
            candidate,
            asset,
            start=start,
            end=end,
            cost_bps=cost_bps,
            classifier=classifier,
        )
        for start, end in folds
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_low_capital_state.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_hyperliquid_4h_volume.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = base.fetch_fixture(fixture_path) if args.fetch else json.loads(fixture_path.read_text(encoding="utf-8"))
    if any(len(row) < 3 for asset in payload["assets"].values() for row in asset["candles"]):
        raise ValueError("fixture has no volume; rerun with --fetch")

    evaluated = []
    for candidate in candidates():
        asset = payload["assets"][candidate["coin"]]
        bars = len(asset["candles"])
        holdout_start = bars - base.HOLDOUT_BARS
        development_start = holdout_start - base.FOLD_BARS * base.FOLD_COUNT
        folds = [
            (
                development_start + fold * base.FOLD_BARS,
                development_start + (fold + 1) * base.FOLD_BARS,
            )
            for fold in range(base.FOLD_COUNT)
        ]
        normal_rows = evaluate(candidate, asset, folds, 6.5)
        stressed_rows = evaluate(candidate, asset, folds, 10.0)
        normal = base.summary(normal_rows)
        stressed = base.summary(stressed_rows)
        failures = base.failed_gates(normal, stressed)
        evaluated.append(
            {
                "candidate": candidate,
                "normal": normal,
                "stressed": stressed,
                "normal_folds": normal_rows,
                "stressed_folds": stressed_rows,
                "development_pass": not failures,
                "failed_gates": failures,
            }
        )

    ranked = sorted(
        evaluated,
        key=lambda row: (
            row["development_pass"],
            min(row["normal"]["positive_folds"], row["stressed"]["positive_folds"]),
            row["stressed"]["median_net_return_pct"],
            row["normal"]["median_sharpe"],
        ),
        reverse=True,
    )
    best = ranked[0]
    holdout = None
    if args.unlock_holdout:
        if not best["development_pass"]:
            raise ValueError("holdout remains locked: no development-pass candidate")
        asset = payload["assets"][best["candidate"]["coin"]]
        start = len(asset["candles"]) - base.HOLDOUT_BARS
        folds = [(start, len(asset["candles"]))]
        holdout = {
            "normal": evaluate(best["candidate"], asset, folds, 6.5)[0],
            "stressed": evaluate(best["candidate"], asset, folds, 10.0)[0],
        }

    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "route": "native_hyperliquid_4h_state_momentum_with_entry_volume_confirmation",
        "holding_rule": "no minimum or maximum duration; exit only when momentum/trend/efficiency state decays",
        "volume_rule": "entry only; current volume must exceed a multiple of the previous 42-bar median",
        "candidate_count": len(evaluated),
        "development_pass_count": sum(row["development_pass"] for row in evaluated),
        "decision": "holdout_unlocked" if holdout else ("development_pass_holdout_locked" if best["development_pass"] else "rejected_in_development"),
        "best": best,
        "holdout": holdout,
        "fixture_sha256": base.hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "ranked_candidates": ranked,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps({key: artifact[key] for key in ("route", "candidate_count", "development_pass_count", "decision")}, indent=2))
    print(json.dumps({key: best[key] for key in ("candidate", "normal", "stressed", "development_pass", "failed_gates")}, indent=2))


if __name__ == "__main__":
    main()
