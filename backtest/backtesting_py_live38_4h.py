"""Backtest a short-cycle, live-38 cross-sectional strategy with backtesting.py.

This is a research-only 4h route.  A 3/42-bar moving-average strength score
chooses the strongest two coins in a positive 252-bar BTC regime and the
weakest two in a negative regime.  The state is recalculated every bar and
there is no elapsed-time exit.  Position size is reduced for high realized
4h volatility, with an explicit 10 USDC minimum-order replay.
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


DEFAULT_DATA_PATH = Path("data/historical_prices/binance_1h_240d_live_38coins.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38_4h.json")
DEFAULT_FEE_BPS = 6.5
DEFAULT_STRESS_FEE_BPS = 10.0
EXTRA_STRESS_FEE_BPS = 15.0
INITIAL_CAPITAL = 100.0
PORTFOLIO_CAPITALS = (25.0, 50.0, 100.0)
MAX_POSITIONS = 2
ALLOCATION_PER_POSITION = 0.5
VOLATILITY_LOOKBACK = 42
VOLATILITY_TARGET = 0.02
VOLATILITY_FLOOR = 0.5
BARS_PER_FOLD = 360


def _resample_4h(frame):
    return (
        frame.resample("4h", label="right", closed="right")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna()
    )


def load_frames(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(set(LIVE_UNIVERSE) - set(payload))
    if missing:
        raise ValueError(f"fixture is missing live-universe coins: {', '.join(missing)}")
    hourly = {coin: _frame(payload[coin]) for coin in LIVE_UNIVERSE}
    frames = {coin: _resample_4h(frame) for coin, frame in hourly.items()}
    common_index = sorted(set.intersection(*(set(frame.index) for frame in frames.values())))
    needed = BARS_PER_FOLD * 4
    if len(common_index) < needed:
        raise ValueError(f"4h fixture has only {len(common_index)} common bars; need {needed}")
    return {coin: frame.loc[common_index].copy() for coin, frame in frames.items()}


def build_signals(closes, *, fast_bars, slow_bars, regime_bars, top_n):
    score = closes.rolling(fast_bars).mean() / closes.rolling(slow_bars).mean() - 1.0
    btc_regime = closes["BTC"] / closes["BTC"].shift(regime_bars) - 1.0
    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    warmup = max(slow_bars, regime_bars)
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


def build_volatility(closes):
    return closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()


def build_position_sizes(volatility, target=VOLATILITY_TARGET):
    scale = (target / volatility).clip(lower=VOLATILITY_FLOOR, upper=1.0)
    return (ALLOCATION_PER_POSITION * scale).fillna(ALLOCATION_PER_POSITION)


def evaluate_candidate(candidate, frames, closes, volatility, folds, *, fee_bps):
    signal_keys = {"fast_bars", "slow_bars", "regime_bars", "top_n"}
    parameters = {key: value for key, value in candidate.items() if key in signal_keys}
    volatility_target = float(candidate.get("volatility_target", VOLATILITY_TARGET))
    signals = build_signals(closes, **parameters)
    position_sizes = build_position_sizes(volatility, volatility_target)
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
                    position_size=position_sizes[coin],
                ),
            }
            for coin in LIVE_UNIVERSE
        ]
        portfolio = {
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
                volatility_target=volatility_target,
                volatility_floor=VOLATILITY_FLOOR,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        evaluations.append(
            {
                "name": name,
                "start": start,
                "end": end,
                "summary": summarize(rows),
                "portfolio": portfolio,
                "coins": rows,
            }
        )
    return evaluations


def evaluate_portfolio_only(candidate, frames, closes, volatility, folds, *, fee_bps):
    signal_keys = {"fast_bars", "slow_bars", "regime_bars", "top_n"}
    parameters = {key: value for key, value in candidate.items() if key in signal_keys}
    volatility_target = float(candidate.get("volatility_target", VOLATILITY_TARGET))
    signals = build_signals(closes, **parameters)
    return {
        fold[0]: {
            str(capital): simulate_portfolio(
                frames,
                signals,
                start=fold[1],
                end=fold[2],
                fee_bps=fee_bps,
                initial_capital=capital,
                max_positions=MAX_POSITIONS,
                allocation_per_position=ALLOCATION_PER_POSITION,
                min_order_usd=MIN_ORDER_USD,
                volatility=volatility,
                volatility_target=volatility_target,
                volatility_floor=VOLATILITY_FLOOR,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        for fold in folds
    }


def portfolio_development_pass(normal, stressed, *, capital=50.0):
    checks = []
    for fold in normal + stressed:
        result = fold["portfolio"][str(capital)]
        checks.append(
            result["strategy_return_pct"] > 0.0
            and result["strategy_minus_equal_weight_buy_hold_pct"] > 0.0
            and result["skipped_entries_below_min_order"] == 0
        )
    return all(checks)


def holdout_review(holdout_result, extra_cost_sensitivity, *, capital=50.0):
    normal = holdout_result["normal"][0]["portfolio"][str(capital)]
    stressed = holdout_result["stressed"][0]["portfolio"][str(capital)]
    issues = []
    if min(normal["strategy_return_pct"], stressed["strategy_return_pct"]) <= 0.0:
        issues.append("portfolio_return_not_positive_under_10bps_stress")
    if min(normal["max_drawdown_pct"], stressed["max_drawdown_pct"]) <= -25.0:
        issues.append("portfolio_drawdown_exceeds_25pct")
    if max(normal["positive_pnl_top2_share_pct"], stressed["positive_pnl_top2_share_pct"]) >= 80.0:
        issues.append("positive_pnl_concentrated_in_top_two_coins")
    if any(
        result[str(capital)]["strategy_return_pct"] <= 0.0
        for result in extra_cost_sensitivity["development"].values()
    ):
        issues.append("development_not_positive_at_15bps")
    return issues


def _rank_key(row):
    stress_folds = [fold["portfolio"]["50.0"] for fold in row["stressed"]]
    stress_return = float(np.mean([fold["strategy_return_pct"] for fold in stress_folds]))
    worst_drawdown = min(fold["max_drawdown_pct"] for fold in stress_folds)
    return (
        row["development_pass"],
        row["portfolio_development_pass"],
        worst_drawdown > -25.0,
        stress_return,
        -abs(worst_drawdown),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args(argv)

    frames = load_frames(args.data_path)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    needed = BARS_PER_FOLD * 4
    if len(closes) < needed:
        raise ValueError(f"4h fixture needs at least {needed} common bars")
    folds = [
        ("development_1", 0, BARS_PER_FOLD),
        ("development_2", BARS_PER_FOLD, BARS_PER_FOLD * 2),
        ("development_3", BARS_PER_FOLD * 2, BARS_PER_FOLD * 3),
    ]
    holdout = ("holdout", BARS_PER_FOLD * 3, BARS_PER_FOLD * 4)
    candidates = [
        {
            "name": "ma_3_24_btc252_top2_vol015",
            "fast_bars": 3,
            "slow_bars": 24,
            "regime_bars": 252,
            "top_n": 2,
            "volatility_target": 0.015,
        },
        {
            "name": "ma_3_42_btc252_top2_vol015",
            "fast_bars": 3,
            "slow_bars": 42,
            "regime_bars": 252,
            "top_n": 2,
            "volatility_target": 0.015,
        },
        {
            "name": "ma_6_24_btc252_top1_vol015",
            "fast_bars": 6,
            "slow_bars": 24,
            "regime_bars": 252,
            "top_n": 1,
            "volatility_target": 0.015,
        },
        {
            "name": "ma_3_24_btc252_top2_vol010",
            "fast_bars": 3,
            "slow_bars": 24,
            "regime_bars": 252,
            "top_n": 2,
            "volatility_target": 0.010,
        },
        {
            "name": "ma_12_24_btc84_top2_vol015",
            "fast_bars": 12,
            "slow_bars": 24,
            "regime_bars": 84,
            "top_n": 2,
            "volatility_target": 0.015,
        },
    ]

    evaluated = []
    for candidate in candidates:
        normal = evaluate_candidate(candidate, frames, closes, volatility, folds, fee_bps=DEFAULT_FEE_BPS)
        stressed = evaluate_candidate(candidate, frames, closes, volatility, folds, fee_bps=DEFAULT_STRESS_FEE_BPS)
        evaluated.append(
            {
                "candidate": candidate,
                "normal": normal,
                "stressed": stressed,
                "development_pass": all(
                    fold["summary"]["mean_strategy_return_pct"] > 0.0
                    and fold["summary"]["mean_strategy_minus_buy_hold_pct"] > 0.0
                    for fold in normal + stressed
                ),
                "portfolio_development_pass": portfolio_development_pass(normal, stressed),
            }
        )
    evaluated.sort(key=_rank_key, reverse=True)
    selected = evaluated[0]
    holdout_result = None
    extra_cost_sensitivity = None
    review = []
    if args.unlock_holdout and selected["development_pass"] and selected["portfolio_development_pass"]:
        candidate = selected["candidate"]
        holdout_result = {
            "normal": evaluate_candidate(candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_FEE_BPS),
            "stressed": evaluate_candidate(
                candidate, frames, closes, volatility, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS
            ),
        }
        extra_cost_sensitivity = {
            "fee_bps": EXTRA_STRESS_FEE_BPS,
            "development": evaluate_portfolio_only(
                candidate, frames, closes, volatility, folds, fee_bps=EXTRA_STRESS_FEE_BPS
            ),
            "holdout": evaluate_portfolio_only(
                candidate, frames, closes, volatility, [holdout], fee_bps=EXTRA_STRESS_FEE_BPS
            ),
        }
        review = holdout_review(holdout_result, extra_cost_sensitivity)

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
        "volatility": {
            "lookback_bars": VOLATILITY_LOOKBACK,
            "candidate_targets_per_4h_bar": [0.010, 0.015],
            "scale_floor": VOLATILITY_FLOOR,
        },
        "holding_rule": "no minimum or maximum holding duration; state changes and volatility sizing control exposure",
        "comparison": (
            "backtesting.py Buy & Hold Return [%] per coin and fold plus "
            "executable equal-weight portfolio Buy & Hold"
        ),
        "development_folds": folds,
        "holdout": holdout,
        "candidates": evaluated,
        "selected": selected,
        "holdout_result": holdout_result,
        "extra_cost_sensitivity": extra_cost_sensitivity,
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
    print(
        json.dumps(
            {key: artifact[key] for key in ("decision", "selected", "holdout_result", "holdout_review")},
            indent=2,
        )
    )
    return artifact


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
