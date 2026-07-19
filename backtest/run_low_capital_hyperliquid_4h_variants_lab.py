"""Two independent native Hyperliquid 4h state routes for low-capital paper."""

import argparse
import json
import math
from pathlib import Path

try:
    from backtest import run_low_capital_hyperliquid_4h_state_lab as base
except ModuleNotFoundError:
    import run_low_capital_hyperliquid_4h_state_lab as base


def short_breakdown_candidates():
    for coin in base.COINS:
        for lookback in (3, 6, 12):
            for entry_drawdown in (0.01, 0.02, 0.04):
                for trend_lookback in (42, 84):
                    for minimum_downtrend in (0.0, 0.02):
                        for exit_recovery in (0.0, 0.01):
                            yield {
                                "coin": coin,
                                "lookback": lookback,
                                "entry_drawdown": entry_drawdown,
                                "trend_lookback": trend_lookback,
                                "minimum_downtrend": minimum_downtrend,
                                "exit_recovery": exit_recovery,
                                "maximum_entry_funding_payment": -0.0000125,
                                "long_weight": 0.0,
                                "short_weight": 0.5,
                                "max_hold": None,
                            }


def volatility_breakout_candidates():
    for coin in base.COINS:
        for breakout_lookback in (3, 6, 12):
            for trend_lookback in (42, 84):
                for volatility_lookback in (6, 12):
                    for volatility_ratio in (1.2, 1.5):
                        for exit_lookback in (3, 6, 12):
                            yield {
                                "coin": coin,
                                "breakout_lookback": breakout_lookback,
                                "trend_lookback": trend_lookback,
                                "volatility_lookback": volatility_lookback,
                                "volatility_ratio": volatility_ratio,
                                "exit_lookback": exit_lookback,
                                "maximum_entry_funding_payment": 0.0000125,
                                "long_weight": 0.5,
                                "short_weight": 0.0,
                                "max_hold": None,
                            }


def short_classifier(candidate, prices, funding_rate, index, holding):
    lookback = candidate["lookback"]
    trend_lookback = candidate["trend_lookback"]
    warmup = max(lookback, trend_lookback)
    if index < warmup:
        return (-1 if holding else 0), "warmup"
    trend = prices[index] / prices[index - trend_lookback] - 1.0
    short_return = prices[index] / prices[index - lookback] - 1.0
    if not holding:
        if trend >= -candidate["minimum_downtrend"]:
            return 0, "trend_filter"
        if short_return >= -candidate["entry_drawdown"] or prices[index] >= prices[index - 1]:
            return 0, "waiting_breakdown"
        if funding_rate < candidate["maximum_entry_funding_payment"]:
            return 0, "crowded_funding_filter"
        return -1, "breakdown_short_entry"
    if trend > 0:
        return 0, "trend_decay_exit"
    if short_return >= -candidate["exit_recovery"]:
        return 0, "short_recovery_exit"
    return -1, "bear_trend_hold"


def _realized_volatility(prices, index, lookback):
    returns = [
        prices[row] / prices[row - 1] - 1.0
        for row in range(index - lookback + 1, index + 1)
    ]
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    return math.sqrt(sum((value - mean) ** 2 for value in returns) / len(returns))


def volatility_classifier(candidate, prices, funding_rate, index, holding):
    breakout = candidate["breakout_lookback"]
    trend_lookback = candidate["trend_lookback"]
    volatility_lookback = candidate["volatility_lookback"]
    warmup = max(breakout, trend_lookback, volatility_lookback * 2)
    if index < warmup:
        return bool(holding), "warmup"
    trend = prices[index] / prices[index - trend_lookback] - 1.0
    current_vol = _realized_volatility(prices, index, volatility_lookback)
    previous_vol = _realized_volatility(prices, index - volatility_lookback, volatility_lookback)
    expanding = current_vol >= previous_vol * candidate["volatility_ratio"] if previous_vol else False
    if not holding:
        if trend <= 0:
            return False, "trend_filter"
        if prices[index] <= max(prices[index - breakout:index]):
            return False, "waiting_breakout"
        if not expanding:
            return False, "volatility_filter"
        if funding_rate > candidate["maximum_entry_funding_payment"]:
            return False, "crowded_funding_filter"
        return True, "volatility_breakout_entry"
    if trend <= 0:
        return False, "trend_decay_exit"
    if prices[index] < min(prices[index - candidate["exit_lookback"]:index]):
        return False, "trailing_channel_exit"
    return True, "expanding_trend_hold"


def evaluate(candidate, asset, folds, cost_bps, classifier):
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


def evaluate_route(payload, candidate_rows, classifier, name, *, unlock_holdout):
    evaluated = []
    for candidate in candidate_rows:
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
        normal_rows = evaluate(candidate, asset, folds, 6.5, classifier)
        stressed_rows = evaluate(candidate, asset, folds, 10.0, classifier)
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
    if unlock_holdout:
        if not best["development_pass"]:
            raise ValueError(f"{name} holdout remains locked: no development-pass candidate")
        asset = payload["assets"][best["candidate"]["coin"]]
        start = len(asset["candles"]) - base.HOLDOUT_BARS
        holdout = {
            "normal": evaluate(best["candidate"], asset, [(start, len(asset["candles"]))], 6.5, classifier)[0],
            "stressed": evaluate(best["candidate"], asset, [(start, len(asset["candles"]))], 10.0, classifier)[0],
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
    return {
        "route": name,
        "candidate_count": len(evaluated),
        "development_pass_count": sum(row["development_pass"] for row in evaluated),
        "decision": "holdout_pass" if holdout_pass else "rejected_in_holdout" if holdout else "development_pass_holdout_locked" if best["development_pass"] else "rejected_in_development",
        "best": best,
        "holdout": holdout,
        "holdout_pass": holdout_pass,
        "capital_replay": capital_replay,
        "ranked_candidates": ranked,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="data/clean_room/hyperliquid_4h_low_capital_variants.json")
    parser.add_argument("--output", default="data/research_artifacts/low_capital_hyperliquid_4h_variants.json")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args()
    fixture_path = Path(args.fixture)
    payload = base.fetch_fixture(fixture_path) if args.fetch else json.loads(fixture_path.read_text(encoding="utf-8"))
    routes = [
        evaluate_route(payload, short_breakdown_candidates(), short_classifier, "native_4h_short_breakdown", unlock_holdout=args.unlock_holdout),
        evaluate_route(payload, volatility_breakout_candidates(), volatility_classifier, "native_4h_volatility_breakout", unlock_holdout=args.unlock_holdout),
    ]
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "holding_rule": "no minimum or maximum duration; state transitions alone control exits",
        "route_switch_rule": "close a route after failed holdout; do not tune the failed route using its holdout",
        "routes": routes,
        "fixture_sha256": base.hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    for route in routes:
        print(json.dumps({key: route[key] for key in ("route", "candidate_count", "development_pass_count", "decision")}, indent=2))
        print(json.dumps({key: route["best"][key] for key in ("candidate", "normal", "stressed", "development_pass", "failed_gates")}, indent=2))
        if route["holdout"]:
            print(json.dumps({"holdout": route["holdout"], "holdout_pass": route["holdout_pass"]}, indent=2))


if __name__ == "__main__":
    main()
