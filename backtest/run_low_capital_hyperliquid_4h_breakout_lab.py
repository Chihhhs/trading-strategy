"""Test native Hyperliquid 4h close-channel state momentum without a time exit."""

import argparse
import json
from pathlib import Path

try:
    from backtest import run_low_capital_hyperliquid_4h_state_lab as base
except ModuleNotFoundError:
    import run_low_capital_hyperliquid_4h_state_lab as base


def candidates():
    for coin in base.COINS:
        for entry_lookback in (12, 24, 42):
            for exit_lookback in (3, 6, 12):
                yield {
                    "coin": coin,
                    "entry_lookback": entry_lookback,
                    "exit_lookback": exit_lookback,
                    "maximum_entry_funding_payment": 0.0000125,
                    "long_weight": 0.5,
                    "short_weight": 0.0,
                    "max_hold": None,
                }


def classifier(candidate, prices, funding_rate, index, holding):
    warmup = max(candidate["entry_lookback"], candidate["exit_lookback"])
    if index < warmup:
        return holding, "warmup"
    if not holding:
        if prices[index] <= max(prices[index - candidate["entry_lookback"]:index]):
            return False, "range_filter"
        if funding_rate > candidate["maximum_entry_funding_payment"]:
            return False, "crowded_funding_filter"
        return True, "breakout_entry"
    if prices[index] < min(prices[index - candidate["exit_lookback"]:index]):
        return False, "channel_decay_exit"
    return True, "strong_trend"


def evaluate(candidate, asset, folds, cost_bps):
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
    parser.add_argument("--output", default="data/research_artifacts/low_capital_hyperliquid_4h_breakout.json")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
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
    holdout_pass = bool(
        holdout
        and holdout["normal"]["net_return_pct"] > 0.0
        and holdout["stressed"]["net_return_pct"] > 0.0
        and holdout["stressed"]["max_drawdown_pct"] <= 20.0
    )
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "route": "native_hyperliquid_4h_close_channel_state_momentum",
        "holding_rule": "no minimum or maximum duration; exit only on a trailing close-channel break",
        "candidate_count": len(evaluated),
        "development_pass_count": sum(row["development_pass"] for row in evaluated),
        "decision": (
            "holdout_pass"
            if holdout_pass
            else "rejected_in_holdout"
            if holdout
            else "development_pass_holdout_locked"
            if best["development_pass"]
            else "rejected_in_development"
        ),
        "best": best,
        "holdout": holdout,
        "holdout_pass": holdout_pass,
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
