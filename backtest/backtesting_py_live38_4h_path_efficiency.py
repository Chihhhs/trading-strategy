"""Test path-efficiency confirmation on the validated Route30 selector."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.backtesting_py_live38 import LIVE_UNIVERSE, MIN_ORDER_USD, backtesting, run_coin, simulate_portfolio, summarize
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
from backtest.backtesting_py_live38_4h_volume_state import development_pass, holdout_review, rank_key


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h_path_efficiency.json")
MOMENTUM_BARS = 12
TREND_BARS = 42
MIN_TREND = 0.01
VOLATILITY_TARGET = 0.015
ALLOCATION_PER_POSITION = 0.5


def build_signals(closes, *, efficiency_window, min_efficiency, switch_margin):
    momentum = closes / closes.shift(MOMENTUM_BARS) - 1.0
    trend = closes / closes.shift(TREND_BARS) - 1.0
    net_move = (closes / closes.shift(efficiency_window) - 1.0).abs()
    path = closes.pct_change().abs().rolling(efficiency_window).sum()
    efficiency = net_move / path.replace(0.0, float("nan"))
    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    incumbent = None
    for index in range(max(TREND_BARS, efficiency_window), len(closes)):
        scores = momentum.iloc[index]
        trends = trend.iloc[index]
        quality = efficiency.iloc[index]
        eligible = (
            scores.notna()
            & trends.notna()
            & quality.notna()
            & (scores >= 0.0)
            & (trends >= MIN_TREND)
            & (quality >= min_efficiency)
        )
        ranked = scores[eligible].sort_values(ascending=False)
        best = str(ranked.index[0]) if len(ranked) else None
        if incumbent is None:
            incumbent = best
        elif not bool((trends >= MIN_TREND).get(incumbent, False)):
            incumbent = best
        elif best is not None and best != incumbent and float(scores[best] - scores[incumbent]) >= switch_margin:
            incumbent = best
        if incumbent is not None:
            signals.iloc[index, signals.columns.get_loc(incumbent)] = 1.0
    return signals


def candidate_grid():
    return [
        {
            "name": f"path_efficiency_w{window}_q{quality}_switch{margin}",
            "efficiency_window": window,
            "min_efficiency": quality,
            "switch_margin": margin,
        }
        for window in (12, 24)
        for quality in (0.25, 0.40, 0.55)
        for margin in (0.005, 0.01)
    ]


def evaluate(candidate, frames, closes, volatility, folds, fee_bps):
    signals = build_signals(closes, **{key: candidate[key] for key in ("efficiency_window", "min_efficiency", "switch_margin")})
    return {
        name: {
            str(capital): simulate_portfolio(
                frames,
                signals,
                start=start,
                end=end,
                fee_bps=fee_bps,
                initial_capital=capital,
                max_positions=1,
                allocation_per_position=ALLOCATION_PER_POSITION,
                min_order_usd=MIN_ORDER_USD,
                volatility=volatility,
                volatility_target=VOLATILITY_TARGET,
                volatility_floor=VOLATILITY_FLOOR,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        for name, start, end in folds
    }


def evaluate_coins(candidate, frames, closes, volatility, fold, fee_bps):
    signals = build_signals(closes, **{key: candidate[key] for key in ("efficiency_window", "min_efficiency", "switch_margin")})
    sizes = {coin: build_position_sizes(volatility[coin], VOLATILITY_TARGET) for coin in LIVE_UNIVERSE}
    name, start, end = fold
    rows = [
        {"coin": coin, **run_coin(frames[coin], signals[coin], start=start, end=end, fee_bps=fee_bps, position_size=sizes[coin])}
        for coin in LIVE_UNIVERSE
    ]
    return [{"name": name, "start": start, "end": end, "summary": summarize(rows), "coins": rows}]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    parser.add_argument("--unlock-holdout", action="store_true")
    parser.add_argument("--reuse-development-artifact", type=Path)
    args = parser.parse_args(argv)
    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    size = args.bars_per_fold
    folds = [("development_1", 0, size), ("development_2", size, size * 2), ("development_3", size * 2, size * 3)]
    holdout = ("holdout", size * 3, size * 4)
    rows = candidate_grid()
    if args.reuse_development_artifact:
        previous = json.loads(args.reuse_development_artifact.read_text(encoding="utf-8"))
        evaluated = previous["candidates"]
        selected = previous["selected"]
    else:
        evaluated = []
        for candidate in rows:
            normal = evaluate(candidate, frames, closes, volatility, folds, DEFAULT_FEE_BPS)
            stressed = evaluate(candidate, frames, closes, volatility, folds, DEFAULT_STRESS_FEE_BPS)
            evaluated.append({"candidate": candidate, "normal": normal, "stressed": stressed, "development_pass": development_pass(normal, stressed)})
        evaluated.sort(key=rank_key, reverse=True)
        selected = evaluated[0]

    holdout_result = extra = None
    review = []
    if args.unlock_holdout and selected["development_pass"]:
        candidate = selected["candidate"]
        normal = evaluate(candidate, frames, closes, volatility, [holdout], DEFAULT_FEE_BPS)
        stressed = evaluate(candidate, frames, closes, volatility, [holdout], DEFAULT_STRESS_FEE_BPS)
        holdout_result = {
            "normal": [{"name": "holdout", "portfolio": normal["holdout"]}],
            "stressed": [{"name": "holdout", "portfolio": stressed["holdout"]}],
            "backtesting_py_normal": evaluate_coins(candidate, frames, closes, volatility, holdout, DEFAULT_FEE_BPS),
            "backtesting_py_stressed": evaluate_coins(candidate, frames, closes, volatility, holdout, DEFAULT_STRESS_FEE_BPS),
        }
        extra = {
            "fee_bps": EXTRA_STRESS_FEE_BPS,
            "development": evaluate(candidate, frames, closes, volatility, folds, EXTRA_STRESS_FEE_BPS),
            "holdout": evaluate(candidate, frames, closes, volatility, [holdout], EXTRA_STRESS_FEE_BPS),
        }
        review = holdout_review(holdout_result, extra)

    decision = "rejected_in_holdout" if holdout_result and review else "holdout_pass_candidate" if holdout_result else "development_pass_holdout_locked" if selected["development_pass"] else "rejected_in_development"
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "backtesting_py_version": getattr(backtesting, "__version__", "unknown"),
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "universe": list(LIVE_UNIVERSE),
        "decision_timeframe": "4h",
        "portfolio_capitals_tested": list(PORTFOLIO_CAPITALS),
        "normal_fee_bps": DEFAULT_FEE_BPS,
        "stress_fee_bps": DEFAULT_STRESS_FEE_BPS,
        "extra_stress_fee_bps": EXTRA_STRESS_FEE_BPS,
        "minimum_order_usd": MIN_ORDER_USD,
        "max_positions": 1,
        "allocation_per_position": ALLOCATION_PER_POSITION,
        "state_definition": "absolute net price move / summed absolute bar returns; confirms new candidates only",
        "holding_rule": "no elapsed-time exit; trend failure or a materially stronger eligible coin changes exposure",
        "development_folds": folds,
        "holdout": holdout,
        "candidate_count": len(rows),
        "candidates": evaluated,
        "selected": selected,
        "holdout_result": holdout_result,
        "extra_cost_sensitivity": extra,
        "holdout_review": review,
        "decision": decision,
    }
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": decision, "selected": selected["candidate"], "development_pass": selected["development_pass"], "review": review}, indent=2))
    return artifact


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
