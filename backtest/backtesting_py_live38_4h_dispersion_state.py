"""Research a market-dispersion state overlay for the Route30 selector.

New positions are eligible only when the cross-sectional spread of 12-bar
momentum is elevated relative to its own causal rolling median.  The incumbent
still exits only when its 42-bar trend fails or a materially stronger eligible
coin appears.  There is no elapsed-time exit and this module is research-only.
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
from backtest.backtesting_py_live38_4h_volume_state import (
    development_pass,
    holdout_review,
    rank_key,
)


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h_dispersion_state.json")
MAX_POSITIONS = 1
ALLOCATION_PER_POSITION = 0.5
INITIAL_CAPITAL = 100.0
MOMENTUM_BARS = 12
TREND_BARS = 42
MIN_TREND = 0.01
MIN_SCORE = 0.0
SWITCH_MARGIN = 0.01
VOLATILITY_TARGET = 0.015


def build_dispersion_signals(closes, *, upper_quantile, state_lookback, min_dispersion_ratio):
    momentum = closes / closes.shift(MOMENTUM_BARS) - 1.0
    trend = closes / closes.shift(TREND_BARS) - 1.0
    upper = momentum.quantile(float(upper_quantile), axis=1)
    median = momentum.median(axis=1)
    dispersion = upper - median
    baseline = dispersion.rolling(int(state_lookback)).median()
    dispersion_ratio = dispersion / baseline.replace(0.0, np.nan)
    state = dispersion_ratio >= float(min_dispersion_ratio)

    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    warmup = max(MOMENTUM_BARS, TREND_BARS, int(state_lookback))
    incumbent = None
    for index in range(warmup, len(closes)):
        scores = momentum.iloc[index]
        trends = trend.iloc[index]
        state_allows_entry = bool(state.iloc[index]) if pd.notna(state.iloc[index]) else False
        eligible = (
            scores.notna()
            & trends.notna()
            & (trends >= MIN_TREND)
            & (scores >= MIN_SCORE)
            & state_allows_entry
        )
        ranked = scores[eligible].sort_values(ascending=False)
        best = str(ranked.index[0]) if len(ranked) else None
        if incumbent is None:
            incumbent = best
        elif not bool((trends >= MIN_TREND).get(incumbent, False)):
            incumbent = best
        elif best is not None and best != incumbent:
            lead = float(scores[best]) - float(scores[incumbent])
            if lead >= SWITCH_MARGIN:
                incumbent = best
        if incumbent is not None:
            signals.iloc[index, signals.columns.get_loc(incumbent)] = 1.0
    return signals


def evaluate_portfolio(candidate, frames, closes, volatility, folds, *, fee_bps):
    signals = build_dispersion_signals(
        closes,
        upper_quantile=candidate["upper_quantile"],
        state_lookback=candidate["state_lookback"],
        min_dispersion_ratio=candidate["min_dispersion_ratio"],
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
                volatility_target=VOLATILITY_TARGET,
                volatility_floor=VOLATILITY_FLOOR,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        for name, start, end in folds
    }


def evaluate_backtesting_py(candidate, frames, closes, volatility, folds, *, fee_bps):
    signals = build_dispersion_signals(
        closes,
        upper_quantile=candidate["upper_quantile"],
        state_lookback=candidate["state_lookback"],
        min_dispersion_ratio=candidate["min_dispersion_ratio"],
    )
    sizes = {
        coin: build_position_sizes(volatility[coin], VOLATILITY_TARGET)
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


def candidates():
    rows = []
    for upper_quantile in (0.75, 0.90):
        for state_lookback in (42, 84):
            for min_dispersion_ratio in (1.0, 1.25, 1.5):
                rows.append(
                    {
                        "name": (
                            f"dispersion_q{int(upper_quantile * 100)}_w{state_lookback}"
                            f"_r{min_dispersion_ratio}_m12_t42_vol0.015"
                        ),
                        "upper_quantile": upper_quantile,
                        "state_lookback": state_lookback,
                        "min_dispersion_ratio": min_dispersion_ratio,
                    }
                )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    parser.add_argument("--unlock-holdout", action="store_true")
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
    volatility = build_volatility(closes)
    if args.reuse_development_artifact:
        previous = json.loads(args.reuse_development_artifact.read_text(encoding="utf-8"))
        folds = [tuple(row) for row in previous["development_folds"]]
        holdout = tuple(previous["holdout"])
        candidate_rows = [item["candidate"] for item in previous["candidates"]]
        evaluated = previous["candidates"]
        selected = previous["selected"]
    else:
        folds = [
            ("development_1", 0, args.bars_per_fold),
            ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
            ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
        ]
        holdout = ("holdout", args.bars_per_fold * 3, args.bars_per_fold * 4)
        candidate_rows = candidates()
        evaluated = []
        for candidate in candidate_rows:
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
            "backtesting_py_normal": evaluate_backtesting_py(
                candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_FEE_BPS
            ),
            "backtesting_py_stressed": evaluate_backtesting_py(
                candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS
            ),
        }
        extra_cost = {
            "fee_bps": EXTRA_STRESS_FEE_BPS,
            "development": evaluate_portfolio(
                candidate, frames, closes, volatility, folds, fee_bps=EXTRA_STRESS_FEE_BPS
            ),
            "holdout": evaluate_portfolio(
                candidate, frames, closes, volatility, [holdout], fee_bps=EXTRA_STRESS_FEE_BPS
            ),
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
        "selector_base": {
            "momentum_bars": MOMENTUM_BARS,
            "trend_bars": TREND_BARS,
            "min_trend": MIN_TREND,
            "min_score": MIN_SCORE,
            "switch_margin": SWITCH_MARGIN,
            "volatility_target": VOLATILITY_TARGET,
        },
        "state_definition": (
            "(cross-sectional upper-quantile 12-bar momentum minus median momentum) / "
            "its causal rolling median; the state confirms new candidates only"
        ),
        "holding_rule": (
            "no minimum or maximum holding duration; dispersion confirms entries and "
            "trend failure or a stronger eligible selector changes exposure"
        ),
        "comparison": "backtesting.py Buy & Hold Return [%] per coin and executable single-position replay",
        "development_folds": folds,
        "holdout": holdout,
        "bars_per_fold": args.bars_per_fold,
        "candidate_count": len(candidate_rows),
        "candidates": evaluated,
        "selected": selected,
        "holdout_result": holdout_result,
        "extra_cost_sensitivity": extra_cost,
        "holdout_review": review,
        "decision": (
            "rejected_in_holdout"
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
    print(
        json.dumps(
            {
                "decision": artifact["decision"],
                "candidate_count": len(candidate_rows),
                "selected": selected["candidate"],
                "development_pass": selected["development_pass"],
                "holdout": holdout_result is not None,
                "review": review,
            },
            indent=2,
        )
    )
    return artifact


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
