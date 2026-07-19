"""Native Hyperliquid 4h neutral-zone downside exhaustion reclaim."""

import argparse
import json
from pathlib import Path

try:
    from backtest import run_low_capital_hyperliquid_4h_state_lab as base
except ModuleNotFoundError:
    import run_low_capital_hyperliquid_4h_state_lab as base


def candidates():
    for coin in base.COINS:
        for pullback_lookback in (3, 6, 12):
            for entry_drawdown in (0.01, 0.02, 0.04):
                for trend_lookback in (42, 84):
                    for maximum_abs_trend in (0.05, 0.10):
                        for exit_recovery in (0.0, 0.01):
                            yield {
                                "coin": coin,
                                "pullback_lookback": pullback_lookback,
                                "entry_drawdown": entry_drawdown,
                                "trend_lookback": trend_lookback,
                                "maximum_abs_trend": maximum_abs_trend,
                                "exit_recovery": exit_recovery,
                                "maximum_entry_funding_payment": 0.0000125,
                                "long_weight": 0.5,
                                "short_weight": 0.0,
                                "max_hold": None,
                            }


def classifier(candidate, prices, funding_rate, index, holding):
    pullback = candidate["pullback_lookback"]
    trend_lookback = candidate["trend_lookback"]
    warmup = max(pullback, trend_lookback)
    if index < warmup:
        return bool(holding), "warmup"
    trend = prices[index] / prices[index - trend_lookback] - 1.0
    short_return = prices[index] / prices[index - pullback] - 1.0
    neutral = abs(trend) <= candidate["maximum_abs_trend"]
    if not holding:
        if not neutral:
            return False, "trend_filter"
        if short_return > -candidate["entry_drawdown"] or prices[index] <= prices[index - 1]:
            return False, "waiting_reclaim"
        if funding_rate > candidate["maximum_entry_funding_payment"]:
            return False, "crowded_funding_filter"
        return True, "exhaustion_reclaim_entry"
    if not neutral:
        return False, "neutral_regime_exit"
    if short_return >= candidate["exit_recovery"]:
        return False, "recovery_exit"
    return True, "neutral_reclaim_hold"


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
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_low_capital_exhaustion.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_hyperliquid_4h_exhaustion.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = base.fetch_fixture(fixture_path) if args.fetch else json.loads(fixture_path.read_text(encoding="utf-8"))
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
        holdout = {
            "normal": evaluate(best["candidate"], asset, [(start, len(asset["candles"]))], 6.5)[0],
            "stressed": evaluate(best["candidate"], asset, [(start, len(asset["candles"]))], 10.0)[0],
        }
    holdout_pass = bool(
        holdout
        and holdout["normal"]["net_return_pct"] > 0.0
        and holdout["stressed"]["net_return_pct"] > 0.0
        and holdout["stressed"]["max_drawdown_pct"] <= 20.0
    )
    capital_replay = None
    if holdout_pass:
        asset = payload["assets"][best["candidate"]["coin"]]
        start = len(asset["candles"]) - base.HOLDOUT_BARS
        capital_replay = {
            str(capital): {
                "normal": base.simulate(
                    best["candidate"], asset, start=start, end=len(asset["candles"]),
                    capital=float(capital), cost_bps=6.5, classifier=classifier,
                ),
                "stressed": base.simulate(
                    best["candidate"], asset, start=start, end=len(asset["candles"]),
                    capital=float(capital), cost_bps=10.0, classifier=classifier,
                ),
            }
            for capital in (20, 21, 25, 50, 100)
        }
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "route": "native_4h_neutral_zone_exhaustion_reclaim",
        "holding_rule": "no minimum or maximum duration; exit only on recovery or neutral-regime failure",
        "candidate_count": len(evaluated),
        "development_pass_count": sum(row["development_pass"] for row in evaluated),
        "decision": "holdout_pass" if holdout_pass else "rejected_in_holdout" if holdout else "development_pass_holdout_locked" if best["development_pass"] else "rejected_in_development",
        "best": best,
        "holdout": holdout,
        "holdout_pass": holdout_pass,
        "capital_replay": capital_replay,
        "fixture_sha256": base.hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "ranked_candidates": ranked,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps({key: artifact[key] for key in ("route", "candidate_count", "development_pass_count", "decision")}, indent=2))
    print(json.dumps({key: best[key] for key in ("candidate", "normal", "stressed", "development_pass", "failed_gates")}, indent=2))
    if holdout:
        print(json.dumps({"holdout": holdout, "holdout_pass": holdout_pass}, indent=2))


if __name__ == "__main__":
    main()
