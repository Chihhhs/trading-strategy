"""Test multi-horizon entry agreement on the validated Route30 selector."""

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
    VOLATILITY_FLOOR,
    build_position_sizes,
    build_volatility,
    load_frames,
)
from backtest.backtesting_py_live38_4h_volume_state import development_pass, rank_key


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h_multi_horizon.json")
MOMENTUM_BARS = 12
TREND_BARS = 42
MIN_TREND = 0.01
VOLATILITY_TARGET = 0.015
ALLOCATION_PER_POSITION = 0.5
CAPITALS = (25.0, 30.0, 40.0, 50.0, 100.0)
HORIZON_SETS = {"m3_m6": (3, 6), "m6_m24": (6, 24), "m3_m6_m24": (3, 6, 24)}


def build_signals(closes, *, confirmation_mode, switch_margin):
    score = closes / closes.shift(MOMENTUM_BARS) - 1.0
    trend = closes / closes.shift(TREND_BARS) - 1.0
    confirmations = [closes / closes.shift(horizon) - 1.0 for horizon in HORIZON_SETS[confirmation_mode]]
    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    incumbent = None
    warmup = max(TREND_BARS, *HORIZON_SETS[confirmation_mode])
    for index in range(warmup, len(closes)):
        scores = score.iloc[index]
        trends = trend.iloc[index]
        confirmed = pd.Series(True, index=closes.columns)
        for frame in confirmations:
            confirmed &= frame.iloc[index].notna() & (frame.iloc[index] > 0.0)
        eligible = scores.notna() & trends.notna() & confirmed & (scores >= 0.0) & (trends >= MIN_TREND)
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
        {"name": f"multi_horizon_{mode}_switch{margin}", "confirmation_mode": mode, "switch_margin": margin}
        for mode in HORIZON_SETS
        for margin in (0.005, 0.01)
    ]


def _signals(candidate, closes):
    return build_signals(closes, confirmation_mode=candidate["confirmation_mode"], switch_margin=candidate["switch_margin"])


def evaluate(candidate, frames, closes, volatility, folds, fee_bps):
    signals = _signals(candidate, closes)
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
            for capital in CAPITALS
        }
        for name, start, end in folds
    }


def evaluate_coins(candidate, frames, closes, volatility, fold, fee_bps):
    signals = _signals(candidate, closes)
    sizes = {coin: build_position_sizes(volatility[coin], VOLATILITY_TARGET) for coin in LIVE_UNIVERSE}
    name, start, end = fold
    rows = [
        {"coin": coin, **run_coin(frames[coin], signals[coin], start=start, end=end, fee_bps=fee_bps, position_size=sizes[coin])}
        for coin in LIVE_UNIVERSE
    ]
    return [{"name": name, "start": start, "end": end, "summary": summarize(rows), "coins": rows}]


def benchmark_issues(normal, stressed, extra, extra_development, *, capital=50.0):
    rows = [normal[str(capital)], stressed[str(capital)], extra[str(capital)]]
    issues = []
    if any(row["strategy_return_pct"] <= 0.0 for row in rows):
        issues.append("known_oos_return_not_positive_through_15bps")
    if any(row["max_drawdown_pct"] <= -25.0 for row in rows):
        issues.append("known_oos_drawdown_exceeds_25pct")
    if any(row["skipped_entries_below_min_order"] for row in rows):
        issues.append("known_oos_has_50usd_minimum_order_skips")
    if stressed[str(capital)]["positive_pnl_top2_share_pct"] > 80.0:
        issues.append("known_oos_positive_pnl_top2_concentration_exceeds_80pct")
    if any(row[str(capital)]["strategy_return_pct"] <= 0.0 for row in extra_development.values()):
        issues.append("development_not_positive_at_15bps")
    if any(row[str(capital)]["strategy_minus_equal_weight_buy_hold_pct"] <= 0.0 for row in extra_development.values()):
        issues.append("development_not_above_buy_hold_at_15bps")
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    parser.add_argument("--unlock-known-oos", action="store_true")
    parser.add_argument("--reuse-development-artifact", type=Path)
    args = parser.parse_args(argv)
    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    size = args.bars_per_fold
    folds = [("development_1", 0, size), ("development_2", size, size * 2), ("development_3", size * 2, size * 3)]
    known_oos = ("known_oos_benchmark", size * 3, size * 4)
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

    benchmark = extra = extra_development = None
    issues = []
    if args.unlock_known_oos and selected["development_pass"]:
        candidate = selected["candidate"]
        normal = evaluate(candidate, frames, closes, volatility, [known_oos], DEFAULT_FEE_BPS)[known_oos[0]]
        stressed = evaluate(candidate, frames, closes, volatility, [known_oos], DEFAULT_STRESS_FEE_BPS)[known_oos[0]]
        extra = evaluate(candidate, frames, closes, volatility, [known_oos], EXTRA_STRESS_FEE_BPS)[known_oos[0]]
        extra_development = evaluate(candidate, frames, closes, volatility, folds, EXTRA_STRESS_FEE_BPS)
        benchmark = {
            "normal": normal,
            "stressed": stressed,
            "extra_stress": extra,
            "development_extra_stress": extra_development,
            "backtesting_py_normal": evaluate_coins(candidate, frames, closes, volatility, known_oos, DEFAULT_FEE_BPS),
            "backtesting_py_stressed": evaluate_coins(candidate, frames, closes, volatility, known_oos, DEFAULT_STRESS_FEE_BPS),
        }
        issues = benchmark_issues(normal, stressed, extra, extra_development)

    decision = "rejected_in_known_oos" if benchmark and issues else "forward_validation_candidate" if benchmark else "development_pass_known_oos_locked" if selected["development_pass"] else "rejected_in_development"
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "backtesting_py_version": getattr(backtesting, "__version__", "unknown"),
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "universe": list(LIVE_UNIVERSE),
        "decision_timeframe": "4h",
        "portfolio_capitals_tested": list(CAPITALS),
        "normal_fee_bps": DEFAULT_FEE_BPS,
        "stress_fee_bps": DEFAULT_STRESS_FEE_BPS,
        "extra_stress_fee_bps": EXTRA_STRESS_FEE_BPS,
        "minimum_order_usd": MIN_ORDER_USD,
        "max_positions": 1,
        "allocation_per_position": ALLOCATION_PER_POSITION,
        "state_definition": "Route30 entry requires every predeclared short/intermediate momentum horizon to be positive",
        "holding_rule": "confirmation affects new candidates only; no elapsed-time exit",
        "validation_note": "the 900:1200 segment is a known diagnostic benchmark, not a sealed holdout; promotion requires future paper data",
        "development_folds": folds,
        "known_oos_benchmark": known_oos,
        "candidate_count": len(rows),
        "candidates": evaluated,
        "selected": selected,
        "benchmark_result": benchmark,
        "benchmark_issues": issues,
        "decision": decision,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": decision, "selected": selected["candidate"], "development_pass": selected["development_pass"], "benchmark_issues": issues}, indent=2))
    return artifact


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
