"""Evaluate one fixed persistent-expansion momentum hypothesis.

Route35 permits a new candidate only after two consecutive causal
high-volume/high-volatility states.  It keeps Route30's stateful holding rule
and has no elapsed-time exit.  The known benchmark is diagnostic only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.analyze_live38_4h_state_classification import STATES, classify_states
from backtest.backtesting_py_live38 import LIVE_UNIVERSE, MIN_ORDER_USD, simulate_portfolio
from backtest.backtesting_py_live38_4h import (
    DEFAULT_FEE_BPS,
    DEFAULT_STRESS_FEE_BPS,
    EXTRA_STRESS_FEE_BPS,
    VOLATILITY_FLOOR,
    build_volatility,
    load_frames,
)
from backtest.backtesting_py_live38_4h_single_selector import build_selector_signals


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h_state_transition.json")
MOMENTUM_BARS = 12
TREND_BARS = 42
MIN_TREND = 0.01
SWITCH_MARGIN = 0.01
VOLATILITY_TARGET = 0.015
INITIAL_CAPITAL = 50.0
ALLOCATION_PER_POSITION = 0.5


def build_signals(closes, volumes):
    momentum = closes / closes.shift(MOMENTUM_BARS) - 1.0
    trend = closes / closes.shift(TREND_BARS) - 1.0
    states = classify_states(closes, volumes)
    persistent_expansion = (states == STATES[0]) & (states.shift(1) == STATES[0])
    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    incumbent = None
    for index in range(TREND_BARS, len(closes)):
        scores = momentum.iloc[index]
        trends = trend.iloc[index]
        eligible = scores.notna() & trends.notna() & persistent_expansion.iloc[index] & (trends >= MIN_TREND) & (scores >= 0.0)
        ranked = scores[eligible].sort_values(ascending=False)
        best = str(ranked.index[0]) if len(ranked) else None
        if incumbent is None:
            incumbent = best
        elif not bool((trends >= MIN_TREND).get(incumbent, False)):
            incumbent = best
        elif best is not None and best != incumbent and float(scores[best]) - float(scores[incumbent]) >= SWITCH_MARGIN:
            incumbent = best
        if incumbent is not None:
            signals.iloc[index, signals.columns.get_loc(incumbent)] = 1.0
    return signals


def evaluate(frames, signals, volatility, folds, fee_bps):
    return {
        name: simulate_portfolio(
            frames,
            signals,
            start=start,
            end=end,
            fee_bps=fee_bps,
            initial_capital=INITIAL_CAPITAL,
            max_positions=1,
            allocation_per_position=ALLOCATION_PER_POSITION,
            min_order_usd=MIN_ORDER_USD,
            volatility=volatility,
            volatility_target=VOLATILITY_TARGET,
            volatility_floor=VOLATILITY_FLOOR,
        )
        for name, start, end in folds
    }


def passes_development(normal, stressed, extra_stress):
    return all(
        result["strategy_return_pct"] > 0.0
        and result["strategy_minus_equal_weight_buy_hold_pct"] > 0.0
        and result["max_drawdown_pct"] > -25.0
        and result["skipped_entries_below_min_order"] == 0
        and result["entries"] > 0
        for results in (normal, stressed, extra_stress)
        for result in results.values()
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    args = parser.parse_args(argv)
    if args.bars_per_fold <= 0:
        raise SystemExit("--bars-per-fold must be positive")
    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volumes = pd.DataFrame({coin: frame["Volume"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    signals = build_signals(closes, volumes)
    baseline_signals = build_selector_signals(
        closes,
        momentum_bars=MOMENTUM_BARS,
        trend_bars=TREND_BARS,
        score_mode="raw",
        min_trend=MIN_TREND,
        min_score=0.0,
        switch_margin=SWITCH_MARGIN,
    )
    development_folds = [
        ("development_1", 0, args.bars_per_fold),
        ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
        ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
    ]
    known_benchmark = [("known_benchmark_diagnostic_only", args.bars_per_fold * 3, args.bars_per_fold * 4)]
    post_boundary = [("post_boundary_observation", args.bars_per_fold * 4, len(closes))]
    normal = evaluate(frames, signals, volatility, development_folds, DEFAULT_FEE_BPS)
    stressed = evaluate(frames, signals, volatility, development_folds, DEFAULT_STRESS_FEE_BPS)
    extra_stress = evaluate(frames, signals, volatility, development_folds, EXTRA_STRESS_FEE_BPS)
    development_pass = passes_development(normal, stressed, extra_stress)
    baseline = {
        "normal": evaluate(frames, baseline_signals, volatility, development_folds, DEFAULT_FEE_BPS),
        "stressed": evaluate(frames, baseline_signals, volatility, development_folds, DEFAULT_STRESS_FEE_BPS),
        "extra_stress": evaluate(frames, baseline_signals, volatility, development_folds, EXTRA_STRESS_FEE_BPS),
    }
    benchmark_result = evaluate(frames, signals, volatility, known_benchmark, DEFAULT_STRESS_FEE_BPS)
    benchmark_baseline = evaluate(frames, baseline_signals, volatility, known_benchmark, DEFAULT_STRESS_FEE_BPS)
    benchmark_key = "known_benchmark_diagnostic_only"
    no_incremental_value = (
        benchmark_result[benchmark_key]["strategy_return_pct"] <= benchmark_baseline[benchmark_key]["strategy_return_pct"]
        and benchmark_result[benchmark_key]["max_drawdown_pct"] <= benchmark_baseline[benchmark_key]["max_drawdown_pct"]
    )
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "route_id": "35",
        "hypothesis": "two consecutive high-volume/high-volatility states confirm momentum continuation",
        "candidate_count": 1,
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "source_timeframe": "1h",
        "decision_timeframe": "4h",
        "universe": list(LIVE_UNIVERSE),
        "capital": INITIAL_CAPITAL,
        "minimum_order_usd": MIN_ORDER_USD,
        "parameters": {
            "momentum_bars": MOMENTUM_BARS,
            "trend_bars": TREND_BARS,
            "minimum_trend": MIN_TREND,
            "switch_margin": SWITCH_MARGIN,
            "volatility_target": VOLATILITY_TARGET,
            "allocation_per_position": ALLOCATION_PER_POSITION,
        },
        "holding_rule": "no minimum or maximum duration; hold until trend failure or a stronger confirmed selector",
        "development": {"normal": normal, "stressed": stressed, "extra_stress": extra_stress},
        "route30_baseline_development": baseline,
        "development_pass": development_pass,
        "known_benchmark_diagnostic_only": benchmark_result,
        "route30_baseline_known_benchmark": benchmark_baseline,
        "known_benchmark_no_incremental_value": no_incremental_value,
        "post_boundary_observation": (
            evaluate(frames, signals, volatility, post_boundary, DEFAULT_STRESS_FEE_BPS)
            if post_boundary[0][1] < post_boundary[0][2]
            else None
        ),
        "decision": (
            "rejected_no_incremental_value_in_known_benchmark"
            if development_pass and no_incremental_value
            else "development_pass_wait_for_fresh_validation"
            if development_pass
            else "rejected_in_development"
        ),
        "paper_eligible": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": artifact["decision"], "development_pass": development_pass, "development": artifact["development"]}, indent=2))
    return artifact


if __name__ == "__main__":
    main()
