"""Research a single-position, stateful selector across Hyperliquid live 38.

The selector ranks all 38 coins by recent momentum, requires a positive longer
trend, and keeps the incumbent until its state fails or a materially stronger
coin appears.  It is intentionally cash-capable, has no elapsed-time exit, and
is never connected to paper/live execution by this module.
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
    _frame,
    backtesting,
    run_coin,
    simulate_portfolio,
    summarize,
)
from backtest.backtesting_py_live38_4h import (
    BARS_PER_FOLD,
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
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h_single_selector.json")
MAX_POSITIONS = 1
ALLOCATION_PER_POSITION = 0.5
INITIAL_CAPITAL = 100.0
VOLATILITY_LOOKBACK = 42


def build_selector_signals(
    closes,
    *,
    momentum_bars,
    trend_bars,
    score_mode,
    min_trend,
    min_score,
    switch_margin,
    entry_confirmation_bars=1,
):
    """Return causal one-hot target states with a stateful incumbent.

    The selector only uses prices through the current close.  A target is
    executed by the portfolio replay at the following open.  The incumbent is
    not replaced by a marginally better coin, which makes turnover a result of
    state change rather than an elapsed holding-time rule.
    """

    momentum = closes / closes.shift(momentum_bars) - 1.0
    trend = closes / closes.shift(trend_bars) - 1.0
    volatility = closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()
    if score_mode == "vol_normalized":
        score = momentum / volatility
    elif score_mode == "raw":
        score = momentum
    else:
        raise ValueError(f"unsupported score_mode: {score_mode}")

    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    warmup = max(momentum_bars, trend_bars, VOLATILITY_LOOKBACK)
    confirmation_bars = max(1, int(entry_confirmation_bars))
    incumbent = None
    pending_candidate = None
    pending_streak = 0
    for index in range(warmup, len(closes)):
        scores = score.iloc[index]
        trends = trend.iloc[index]
        eligible = scores.notna() & trends.notna() & (trends >= float(min_trend)) & (scores >= float(min_score))
        ranked = scores[eligible].sort_values(ascending=False)
        best = str(ranked.index[0]) if len(ranked) else None
        if best is not None and best == pending_candidate:
            pending_streak += 1
        else:
            pending_candidate = best
            pending_streak = 1 if best is not None else 0
        confirmed_best = best if pending_streak >= confirmation_bars else None

        if incumbent is None:
            incumbent = confirmed_best
        elif not bool(eligible.get(incumbent, False)):
            incumbent = confirmed_best
        elif confirmed_best is not None and confirmed_best != incumbent:
            lead = float(scores[confirmed_best]) - float(scores[incumbent])
            if lead >= float(switch_margin):
                incumbent = confirmed_best

        if incumbent is not None:
            signals.iloc[index, signals.columns.get_loc(incumbent)] = 1.0
    return signals


def evaluate_portfolio(candidate, frames, closes, volatility, folds, *, fee_bps):
    signal_parameters = {
        key: candidate[key]
        for key in (
            "momentum_bars",
            "trend_bars",
            "score_mode",
            "min_trend",
            "min_score",
            "switch_margin",
        )
    }
    signal_parameters["entry_confirmation_bars"] = candidate.get("entry_confirmation_bars", 1)
    signals = build_selector_signals(closes, **signal_parameters)
    target = float(candidate["volatility_target"])
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
                volatility_target=target,
                volatility_floor=VOLATILITY_FLOOR,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        for name, start, end in folds
    }


def evaluate_backtesting_py(candidate, frames, closes, volatility, folds, *, fee_bps):
    signal_parameters = {
        key: candidate[key]
        for key in (
            "momentum_bars",
            "trend_bars",
            "score_mode",
            "min_trend",
            "min_score",
            "switch_margin",
        )
    }
    signal_parameters["entry_confirmation_bars"] = candidate.get("entry_confirmation_bars", 1)
    signals = build_selector_signals(closes, **signal_parameters)
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
        evaluations.append(
            {
                "name": name,
                "start": start,
                "end": end,
                "summary": summarize(rows),
                "coins": rows,
            }
        )
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
    development_results = [
        fold[str(capital)] for fold in extra_cost["development"].values()
    ]
    if any(item["strategy_return_pct"] <= 0.0 for item in development_results):
        issues.append("development_not_positive_at_15bps")
    if any(item["strategy_minus_equal_weight_buy_hold_pct"] <= 0.0 for item in development_results):
        issues.append("development_not_above_buy_hold_at_15bps")
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args(argv)
    if args.bars_per_fold <= 0:
        raise SystemExit("--bars-per-fold must be positive")

    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    folds = [
        ("development_1", 0, args.bars_per_fold),
        ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
        ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
    ]
    holdout = ("holdout", args.bars_per_fold * 3, args.bars_per_fold * 4)

    candidates = []
    for momentum_bars in (6, 12, 24):
        for trend_bars in (42, 84):
            for score_mode, min_scores, margins in (
                ("raw", (0.0, 0.01), (0.0, 0.01)),
                ("vol_normalized", (0.0, 0.5), (0.0, 0.25)),
            ):
                for min_score in min_scores:
                    for switch_margin in margins:
                        for min_trend in (0.0, 0.01):
                            for target in (0.010, 0.015):
                                candidates.append(
                                    {
                                        "name": (
                                            f"selector_m{momentum_bars}_t{trend_bars}_{score_mode}"
                                            f"_s{min_score}_w{switch_margin}_trend{min_trend}_vol{target}"
                                        ),
                                        "momentum_bars": momentum_bars,
                                        "trend_bars": trend_bars,
                                        "score_mode": score_mode,
                                        "min_score": min_score,
                                        "switch_margin": switch_margin,
                                        "min_trend": min_trend,
                                        "volatility_target": target,
                                    }
                                )

    evaluated = []
    for candidate in candidates:
        normal = evaluate_portfolio(candidate, frames, closes, volatility, folds, fee_bps=DEFAULT_FEE_BPS)
        stressed = evaluate_portfolio(candidate, frames, closes, volatility, folds, fee_bps=DEFAULT_STRESS_FEE_BPS)
        evaluated.append(
            {
                "candidate": candidate,
                "normal": normal,
                "stressed": stressed,
                "development_pass": development_pass(normal, stressed),
            }
        )
    evaluated.sort(key=rank_key, reverse=True)
    selected = evaluated[0]
    holdout_result = None
    extra_cost = None
    review = []
    if args.unlock_holdout and selected["development_pass"]:
        candidate = selected["candidate"]
        normal = evaluate_portfolio(candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_FEE_BPS)
        stressed = evaluate_portfolio(candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS)
        holdout_result = {
            "normal": [{"name": "holdout", "portfolio": normal["holdout"]}],
            "stressed": [{"name": "holdout", "portfolio": stressed["holdout"]}],
            "backtesting_py_normal": evaluate_backtesting_py(candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_FEE_BPS),
            "backtesting_py_stressed": evaluate_backtesting_py(candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS),
        }
        extra_cost = {
            "fee_bps": EXTRA_STRESS_FEE_BPS,
            "development": evaluate_portfolio(candidate, frames, closes, volatility, folds, fee_bps=EXTRA_STRESS_FEE_BPS),
            "holdout": evaluate_portfolio(candidate, frames, closes, volatility, [holdout], fee_bps=EXTRA_STRESS_FEE_BPS),
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
        "volatility": {"lookback_bars": VOLATILITY_LOOKBACK, "scale_floor": VOLATILITY_FLOOR},
        "holding_rule": "no minimum or maximum holding duration; incumbent exits only on state failure or a stronger eligible selector",
        "comparison": "backtesting.py Buy & Hold Return [%] per coin and executable single-position replay",
        "development_folds": folds,
        "holdout": holdout,
        "bars_per_fold": args.bars_per_fold,
        "candidate_count": len(candidates),
        "candidates": evaluated,
        "selected": selected,
        "holdout_result": holdout_result,
        "extra_cost_sensitivity": extra_cost,
        "holdout_review": review,
        "decision": (
            "holdout_pass_but_review_required"
            if holdout_result and review
            else "holdout_pass_candidate"
            if holdout_result
            else "development_pass_holdout_locked"
            if selected["development_pass"]
            else "rejected_in_development"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": artifact["decision"], "candidate_count": len(candidates), "selected": selected["candidate"], "development_pass": selected["development_pass"], "holdout": holdout_result is not None, "review": review}, indent=2))
    return artifact


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
