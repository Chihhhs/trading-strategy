"""Scan a development-only 1h Hyperliquid 38-coin momentum route."""

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

from apps.live_config import LIVE_UNIVERSE
from backtest.backtesting_py_live38 import MIN_ORDER_USD, _frame, simulate_portfolio


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/hyperliquid_native_momentum_1h_scan.json")
DEFAULT_FEE_BPS = 6.5
DEFAULT_STRESS_FEE_BPS = 10.0
PORTFOLIO_CAPITALS = (25.0, 50.0, 100.0)
MAX_POSITIONS = 2
ALLOCATION_PER_POSITION = 0.5
VOLATILITY_LOOKBACK = 42
VOLATILITY_FLOOR = 0.5


def load_frames(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "coins" in payload and isinstance(payload["coins"], dict):
        payload = payload["coins"]
    missing = sorted(set(LIVE_UNIVERSE) - set(payload))
    if missing:
        raise ValueError(f"fixture missing live-universe coins: {', '.join(missing)}")
    frames = {coin: _frame(payload[coin]) for coin in LIVE_UNIVERSE}
    common_index = sorted(set.intersection(*(set(frame.index) for frame in frames.values())))
    return {coin: frame.loc[common_index].copy() for coin, frame in frames.items()}


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
    parameters = {key: value for key, value in candidate.items() if key in {"momentum_bars", "regime_bars", "top_n", "score_mode"}}
    signals = build_signals(closes, **parameters)
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
            checks.extend([
                result["strategy_return_pct"] > 0.0,
                result["strategy_minus_equal_weight_buy_hold_pct"] > 0.0,
                result["skipped_entries_below_min_order"] == 0,
            ])
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
    parser.add_argument("--bars-per-fold", type=int, default=600)
    args = parser.parse_args(argv)
    frames = load_frames(args.data_path)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()
    needed = args.bars_per_fold * 4
    if len(closes) < needed:
        raise ValueError(f"fixture has {len(closes)} common 1h bars; need {needed}")
    folds = [
        ("development_1", 0, args.bars_per_fold),
        ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
        ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
    ]
    evaluated = []
    for momentum_bars, regime_bars, score_mode, top_n, target in itertools.product(
        (3, 6, 12, 24),
        (24, 48, 168),
        ("raw",),
        (1, 2),
        (0.003, 0.005),
    ):
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
    selected = evaluated[0]
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "source": "hyperliquid_public_info_candleSnapshot",
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "universe": list(LIVE_UNIVERSE),
        "universe_size": len(LIVE_UNIVERSE),
        "decision_timeframe": "1h",
        "development_only": True,
        "development_folds": folds,
        "normal_fee_bps": DEFAULT_FEE_BPS,
        "stress_fee_bps": DEFAULT_STRESS_FEE_BPS,
        "minimum_order_usd": MIN_ORDER_USD,
        "max_positions": MAX_POSITIONS,
        "holding_rule": "no minimum or maximum holding duration; BTC regime and signal changes control exposure",
        "candidate_count": len(evaluated),
        "development_pass_count": sum(item["development_pass"] for item in evaluated),
        "candidates": evaluated,
        "selected": selected,
        "decision": "development_pass_holdout_locked" if selected["development_pass"] else "rejected_in_development",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    compact = []
    for item in evaluated[:10]:
        compact.append({
            "candidate": item["candidate"],
            "development_pass": item["development_pass"],
            "stress_returns": [round(item["stressed"][f"development_{i}"]["50.0"]["strategy_return_pct"], 3) for i in range(1, 4)],
            "stress_relative": [round(item["stressed"][f"development_{i}"]["50.0"]["strategy_minus_equal_weight_buy_hold_pct"], 3) for i in range(1, 4)],
            "worst_drawdown": round(min(item["stressed"][f"development_{i}"]["50.0"]["max_drawdown_pct"] for i in range(1, 4)), 3),
            "skips_50": sum(item["stressed"][f"development_{i}"]["50.0"]["skipped_entries_below_min_order"] for i in range(1, 4)),
        })
    print(json.dumps({"decision": artifact["decision"], "candidate_count": len(evaluated), "development_pass_count": artifact["development_pass_count"], "top10": compact}, indent=2))
    return artifact


if __name__ == "__main__":
    main()
