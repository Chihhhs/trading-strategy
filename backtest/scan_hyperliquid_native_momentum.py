"""Scan a predeclared Hyperliquid-native 4h cross-sectional momentum grid.

The scan is development-only.  It uses BTC regime state, cross-sectional
momentum, volatility-scaled sizing, and no elapsed-time exit.  Holdout data is
never read by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.backtesting_py_live38 import LIVE_UNIVERSE, MIN_ORDER_USD, simulate_portfolio
from backtest.backtesting_py_live38_4h import build_volatility, load_frames


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/hyperliquid_native_momentum_scan.json")
DEFAULT_FEE_BPS = 6.5
DEFAULT_STRESS_FEE_BPS = 10.0
PORTFOLIO_CAPITALS = (25.0, 50.0, 100.0)
MAX_POSITIONS = 2
ALLOCATION_PER_POSITION = 0.5
VOLATILITY_LOOKBACK = 42
VOLATILITY_FLOOR = 0.5


def build_signals(closes, *, momentum_bars, regime_bars, top_n, score_mode):
    momentum = closes / closes.shift(momentum_bars) - 1.0
    if score_mode == "vol_normalized":
        score = momentum / closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()
    else:
        score = momentum
    btc_regime = closes["BTC"] / closes["BTC"].shift(regime_bars) - 1.0
    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    warmup = max(momentum_bars, regime_bars, VOLATILITY_LOOKBACK)
    for index in range(warmup, len(closes)):
        ranked = score.iloc[index].dropna().sort_values(ascending=False)
        target = {coin: 0.0 for coin in closes.columns}
        if float(btc_regime.iloc[index]) >= 0.0:
            for coin, value in ranked.head(top_n).items():
                if float(value) > 0.0:
                    target[coin] = 1.0
        else:
            for coin, value in ranked.tail(top_n).items():
                if float(value) < 0.0:
                    target[coin] = -1.0
        signals.iloc[index] = pd.Series(target)
    return signals


def evaluate(candidate, frames, closes, volatility, folds, *, fee_bps):
    signal_parameters = {
        key: value for key, value in candidate.items() if key in {"momentum_bars", "regime_bars", "top_n", "score_mode"}
    }
    signals = build_signals(closes, **signal_parameters)
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


def development_pass(normal, stressed, *, capital=50.0):
    checks = []
    for name in normal:
        for result in (normal[name][str(capital)], stressed[name][str(capital)]):
            checks.extend(
                [
                    result["strategy_return_pct"] > 0.0,
                    result["strategy_minus_equal_weight_buy_hold_pct"] > 0.0,
                    result["skipped_entries_below_min_order"] == 0,
                ]
            )
    return all(checks)


def rank_key(row):
    stress = [row["stressed"][name]["50.0"] for name in row["stressed"]]
    mean_return = float(np.mean([item["strategy_return_pct"] for item in stress]))
    worst_dd = min(item["max_drawdown_pct"] for item in stress)
    return (row["development_pass"], worst_dd > -25.0, mean_return, -abs(worst_dd))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    args = parser.parse_args(argv)
    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    folds = [
        ("development_1", 0, args.bars_per_fold),
        ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
        ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
    ]
    grid = itertools.product(
        (6, 12, 24, 42, 84),
        (42, 84, 126, 252),
        ("raw", "vol_normalized"),
        (1, 2),
        (0.010, 0.015),
    )
    evaluated = []
    for momentum_bars, regime_bars, score_mode, top_n, target in grid:
        if regime_bars <= momentum_bars:
            continue
        candidate = {
            "momentum_bars": momentum_bars,
            "regime_bars": regime_bars,
            "score_mode": score_mode,
            "top_n": top_n,
            "volatility_target": target,
        }
        normal = evaluate(candidate, frames, closes, volatility, folds, fee_bps=DEFAULT_FEE_BPS)
        stressed = evaluate(candidate, frames, closes, volatility, folds, fee_bps=DEFAULT_STRESS_FEE_BPS)
        evaluated.append({"candidate": candidate, "normal": normal, "stressed": stressed, "development_pass": development_pass(normal, stressed)})
    evaluated.sort(key=rank_key, reverse=True)
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "source": "hyperliquid_public_info_candleSnapshot",
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "universe": list(LIVE_UNIVERSE),
        "universe_size": len(LIVE_UNIVERSE),
        "decision_timeframe": "4h",
        "development_only": True,
        "development_folds": folds,
        "normal_fee_bps": DEFAULT_FEE_BPS,
        "stress_fee_bps": DEFAULT_STRESS_FEE_BPS,
        "minimum_order_usd": MIN_ORDER_USD,
        "max_positions": MAX_POSITIONS,
        "holding_rule": "no minimum or maximum holding duration; BTC regime and signal changes control exposure",
        "candidate_count": len(evaluated),
        "candidates": evaluated,
        "selected": evaluated[0],
        "development_pass_count": sum(item["development_pass"] for item in evaluated),
        "decision": "development_pass_holdout_locked" if evaluated[0]["development_pass"] else "rejected_in_development",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    compact = []
    for item in evaluated[:10]:
        compact.append(
            {
                "candidate": item["candidate"],
                "development_pass": item["development_pass"],
                "stress_returns": [round(item["stressed"][f"development_{i}"]["50.0"]["strategy_return_pct"], 3) for i in range(1, 4)],
                "stress_relative": [round(item["stressed"][f"development_{i}"]["50.0"]["strategy_minus_equal_weight_buy_hold_pct"], 3) for i in range(1, 4)],
                "worst_drawdown": round(min(item["stressed"][f"development_{i}"]["50.0"]["max_drawdown_pct"] for i in range(1, 4)), 3),
                "skips_50": sum(item["stressed"][f"development_{i}"]["50.0"]["skipped_entries_below_min_order"] for i in range(1, 4)),
            }
        )
    print(json.dumps({"decision": artifact["decision"], "candidate_count": len(evaluated), "development_pass_count": artifact["development_pass_count"], "top10": compact}, indent=2))
    return artifact


if __name__ == "__main__":
    main()
