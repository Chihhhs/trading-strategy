"""Research a volume/volatility-state selector across Hyperliquid live 38.

This route starts from the stateful single-position selector and adds an
entry-state filter based on relative volume and realized-volatility regime.
Volume/volatility state confirms or rejects a new candidate; it is not a
time-based exit and the incumbent still exits only when its trend state fails
or a materially stronger eligible candidate appears.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.backtesting_py_live38 import (
    LIVE_UNIVERSE,
    MIN_ORDER_USD,
    backtesting,
    run_coin,
    simulate_portfolio,
    summarize,
)
from backtest.backtesting_py_live38_4h import (
    DEFAULT_FEE_BPS,
    DEFAULT_STRESS_FEE_BPS,
    EXTRA_STRESS_FEE_BPS,
    PORTFOLIO_CAPITALS,
    VOLATILITY_FLOOR,
    build_position_sizes,
    build_volatility,
    load_frames,
)


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h_volume_state.json")
MAX_POSITIONS = 1
ALLOCATION_PER_POSITION = 0.5
INITIAL_CAPITAL = 100.0
VOLATILITY_LOOKBACK = 42
VOLUME_LOOKBACK = 24
VOLATILITY_STATE_LOOKBACK = 168
MIN_TREND = 0.01
RAW_SWITCH_MARGIN = 0.01
NORMALIZED_SWITCH_MARGIN = 0.25


def state_mask(volume_ratio, volatility_ratio, state_mode):
    if state_mode == "any":
        return pd.DataFrame(True, index=volume_ratio.index, columns=volume_ratio.columns)
    if state_mode == "high_volume":
        return volume_ratio >= 1.10
    if state_mode == "normal_volatility":
        return volatility_ratio <= 1.50
    if state_mode == "low_volatility":
        return volatility_ratio <= 1.00
    if state_mode == "expansion_confirmation":
        return (volume_ratio >= 1.10) & (volatility_ratio >= 1.00) & (volatility_ratio <= 2.00)
    raise ValueError(f"unsupported state_mode: {state_mode}")


def build_volume_state_signals(
    closes,
    volumes,
    *,
    momentum_bars,
    trend_bars,
    score_mode,
    state_mode,
):
    momentum = closes / closes.shift(momentum_bars) - 1.0
    trend = closes / closes.shift(trend_bars) - 1.0
    volatility = closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()
    volume_ratio = volumes / volumes.rolling(VOLUME_LOOKBACK).median()
    volatility_ratio = volatility / volatility.rolling(VOLATILITY_STATE_LOOKBACK).median()
    score = momentum / volatility if score_mode == "vol_normalized" else momentum
    if score_mode not in {"raw", "vol_normalized"}:
        raise ValueError(f"unsupported score_mode: {score_mode}")
    state = state_mask(volume_ratio, volatility_ratio, state_mode)

    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    warmup = max(momentum_bars, trend_bars, VOLATILITY_LOOKBACK, VOLUME_LOOKBACK, VOLATILITY_STATE_LOOKBACK)
    switch_margin = RAW_SWITCH_MARGIN if score_mode == "raw" else NORMALIZED_SWITCH_MARGIN
    incumbent = None
    for index in range(warmup, len(closes)):
        scores = score.iloc[index]
        trends = trend.iloc[index]
        eligible = (
            scores.notna()
            & trends.notna()
            & state.iloc[index].fillna(False)
            & (trends >= MIN_TREND)
            & (scores >= 0.0)
        )
        ranked = scores[eligible].sort_values(ascending=False)
        best = str(ranked.index[0]) if len(ranked) else None
        if incumbent is None:
            incumbent = best
        elif not bool((trends >= MIN_TREND).get(incumbent, False)):
            incumbent = best
        elif best is not None and best != incumbent:
            lead = float(scores[best]) - float(scores[incumbent])
            if lead >= switch_margin:
                incumbent = best
        if incumbent is not None:
            signals.iloc[index, signals.columns.get_loc(incumbent)] = 1.0
    return signals


def evaluate_portfolio(candidate, frames, closes, volumes, volatility, folds, *, fee_bps):
    signals = build_volume_state_signals(
        closes,
        volumes,
        momentum_bars=candidate["momentum_bars"],
        trend_bars=candidate["trend_bars"],
        score_mode=candidate["score_mode"],
        state_mode=candidate["state_mode"],
    )
    return {
        name: {
            str(capital): simulate_portfolio(
                frames,
                signals,
                start=start,
                end=end,
                fee_bps=fee_bps,
                initial_capital=capital,
                max_positions=MAX_POSITIONS,
                allocation_per_position=ALLOCATION_PER_POSITION,
                min_order_usd=MIN_ORDER_USD,
                volatility=volatility,
                volatility_target=float(candidate["volatility_target"]),
                volatility_floor=VOLATILITY_FLOOR,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        for name, start, end in folds
    }


def evaluate_backtesting_py(candidate, frames, closes, volumes, volatility, folds, *, fee_bps):
    signals = build_volume_state_signals(
        closes,
        volumes,
        momentum_bars=candidate["momentum_bars"],
        trend_bars=candidate["trend_bars"],
        score_mode=candidate["score_mode"],
        state_mode=candidate["state_mode"],
    )
    sizes = {
        coin: build_position_sizes(volatility[coin], float(candidate["volatility_target"]))
        for coin in LIVE_UNIVERSE
    }
    evaluations = []
    for name, start, end in folds:
        rows = [
            {
                "coin": coin,
                **run_coin(
                    frames[coin],
                    signals[coin],
                    start=start,
                    end=end,
                    fee_bps=fee_bps,
                    position_size=sizes[coin],
                ),
            }
            for coin in LIVE_UNIVERSE
        ]
        evaluations.append({"name": name, "start": start, "end": end, "summary": summarize(rows), "coins": rows})
    return evaluations


def development_pass(normal, stressed, *, capital=50.0):
    checks = []
    for name in normal:
        for result in (normal[name][str(capital)], stressed[name][str(capital)]):
            checks.extend(
                [
                    result["strategy_return_pct"] > 0.0,
                    result["strategy_minus_equal_weight_buy_hold_pct"] > 0.0,
                    result["skipped_entries_below_min_order"] == 0,
                    result["max_drawdown_pct"] > -25.0,
                    result["entries"] > 0,
                ]
            )
    return all(checks)


def rank_key(row):
    stress = [row["stressed"][name]["50.0"] for name in row["stressed"]]
    mean_return = float(np.mean([item["strategy_return_pct"] for item in stress]))
    worst_dd = min(item["max_drawdown_pct"] for item in stress)
    return (row["development_pass"], worst_dd > -25.0, mean_return, -abs(worst_dd))


def holdout_review(holdout, extra_cost, *, capital=50.0):
    normal = holdout["normal"][0]["portfolio"][str(capital)]
    stressed = holdout["stressed"][0]["portfolio"][str(capital)]
    issues = []
    if min(normal["strategy_return_pct"], stressed["strategy_return_pct"]) <= 0.0:
        issues.append("portfolio_return_not_positive_under_10bps_stress")
    if min(normal["max_drawdown_pct"], stressed["max_drawdown_pct"]) <= -25.0:
        issues.append("portfolio_drawdown_exceeds_25pct")
    development = [fold[str(capital)] for fold in extra_cost["development"].values()]
    if any(item["strategy_return_pct"] <= 0.0 for item in development):
        issues.append("development_not_positive_at_15bps")
    if any(item["strategy_minus_equal_weight_buy_hold_pct"] <= 0.0 for item in development):
        issues.append("development_not_above_buy_hold_at_15bps")
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    parser.add_argument("--unlock-holdout", action="store_true")
    parser.add_argument(
        "--state-only",
        action="store_true",
        help="select the best non-baseline volume/volatility state candidate",
    )
    parser.add_argument(
        "--reuse-development-artifact",
        type=Path,
        help="reuse a completed development artifact and only run the holdout review",
    )
    args = parser.parse_args(argv)
    if args.bars_per_fold <= 0:
        raise SystemExit("--bars-per-fold must be positive")

    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volumes = pd.DataFrame({coin: frame["Volume"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    if args.reuse_development_artifact:
        previous = json.loads(args.reuse_development_artifact.read_text(encoding="utf-8"))
        folds = [tuple(row) for row in previous["development_folds"]]
        holdout = tuple(previous["holdout"])
        candidates = [item["candidate"] for item in previous["candidates"]]
        evaluated = previous["candidates"]
        selected = previous["selected"]
        selection_scope = previous.get("selection_scope", "state_only")
    else:
        folds = [
            ("development_1", 0, args.bars_per_fold),
            ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
            ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
        ]
        holdout = ("holdout", args.bars_per_fold * 3, args.bars_per_fold * 4)
        candidates = []
        for momentum_bars in (6, 12, 24):
            for trend_bars in (42, 84):
                for score_mode in ("raw", "vol_normalized"):
                    for state_mode in ("any", "high_volume", "normal_volatility", "low_volatility", "expansion_confirmation"):
                        for target in (0.010, 0.015):
                            candidates.append(
                                {
                                    "name": f"volume_state_m{momentum_bars}_t{trend_bars}_{score_mode}_{state_mode}_vol{target}",
                                    "momentum_bars": momentum_bars,
                                    "trend_bars": trend_bars,
                                    "score_mode": score_mode,
                                    "state_mode": state_mode,
                                    "volatility_target": target,
                                }
                            )
        evaluated = []
        for candidate in candidates:
            normal = evaluate_portfolio(candidate, frames, closes, volumes, volatility, folds, fee_bps=DEFAULT_FEE_BPS)
            stressed = evaluate_portfolio(candidate, frames, closes, volumes, volatility, folds, fee_bps=DEFAULT_STRESS_FEE_BPS)
            evaluated.append({"candidate": candidate, "normal": normal, "stressed": stressed, "development_pass": development_pass(normal, stressed)})
        evaluated.sort(key=rank_key, reverse=True)
        selection_pool = (
            [item for item in evaluated if item["candidate"]["state_mode"] != "any"]
            if args.state_only
            else evaluated
        )
        selected = selection_pool[0]
        selection_scope = "state_only" if args.state_only else "all_including_baseline"
    holdout_result = None
    extra_cost = None
    review = []
    if args.unlock_holdout and selected["development_pass"]:
        candidate = selected["candidate"]
        normal = evaluate_portfolio(candidate, frames, closes, volumes, volatility, [holdout], fee_bps=DEFAULT_FEE_BPS)
        stressed = evaluate_portfolio(candidate, frames, closes, volumes, volatility, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS)
        holdout_result = {
            "normal": [{"name": "holdout", "portfolio": normal["holdout"]}],
            "stressed": [{"name": "holdout", "portfolio": stressed["holdout"]}],
            "backtesting_py_normal": evaluate_backtesting_py(candidate, frames, closes, volumes, volatility, [holdout], fee_bps=DEFAULT_FEE_BPS),
            "backtesting_py_stressed": evaluate_backtesting_py(candidate, frames, closes, volumes, volatility, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS),
        }
        extra_cost = {
            "fee_bps": EXTRA_STRESS_FEE_BPS,
            "development": evaluate_portfolio(candidate, frames, closes, volumes, volatility, folds, fee_bps=EXTRA_STRESS_FEE_BPS),
            "holdout": evaluate_portfolio(candidate, frames, closes, volumes, volatility, [holdout], fee_bps=EXTRA_STRESS_FEE_BPS),
        }
        review = holdout_review(holdout_result, extra_cost)

    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "backtesting_py_version": getattr(backtesting, "__version__", "unknown"),
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "universe": list(LIVE_UNIVERSE),
        "universe_size": len(LIVE_UNIVERSE),
        "source_timeframe": "1h",
        "decision_timeframe": "4h",
        "initial_capital": INITIAL_CAPITAL,
        "portfolio_capitals_tested": list(PORTFOLIO_CAPITALS),
        "normal_fee_bps": DEFAULT_FEE_BPS,
        "stress_fee_bps": DEFAULT_STRESS_FEE_BPS,
        "extra_stress_fee_bps": EXTRA_STRESS_FEE_BPS,
        "minimum_order_usd": MIN_ORDER_USD,
        "max_positions": MAX_POSITIONS,
        "allocation_per_position": ALLOCATION_PER_POSITION,
        "state_definition": {
            "volume_ratio": "current 4h volume / rolling 24-bar median volume",
            "volatility_ratio": "42-bar realized volatility / rolling 168-bar median realized volatility",
            "modes": {
                "high_volume": "volume_ratio >= 1.10",
                "normal_volatility": "volatility_ratio <= 1.50",
                "low_volatility": "volatility_ratio <= 1.00",
                "expansion_confirmation": "volume_ratio >= 1.10 and 1.00 <= volatility_ratio <= 2.00",
            },
        },
        "holding_rule": "no minimum or maximum holding duration; state filter confirms entries and trend failure or stronger eligible selector changes exposure",
        "comparison": "backtesting.py Buy & Hold Return [%] per coin and executable single-position replay",
        "development_folds": folds,
        "holdout": holdout,
        "bars_per_fold": args.bars_per_fold,
        "candidate_count": len(candidates),
        "selection_scope": selection_scope,
        "candidates": evaluated,
        "selected": selected,
        "holdout_result": holdout_result,
        "extra_cost_sensitivity": extra_cost,
        "holdout_review": review,
        "decision": "holdout_pass_but_review_required" if holdout_result and review else "holdout_pass_candidate" if holdout_result else "development_pass_holdout_locked" if selected["development_pass"] else "rejected_in_development",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": artifact["decision"], "candidate_count": len(candidates), "selected": selected["candidate"], "development_pass": selected["development_pass"], "holdout": holdout_result is not None, "review": review}, indent=2))
    return artifact


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
