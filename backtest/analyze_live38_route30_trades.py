"""Produce trade-level attribution for the fixed Route30 selector."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.backtesting_py_live38 import LIVE_UNIVERSE, MIN_ORDER_USD
from backtest.backtesting_py_live38_4h import VOLATILITY_FLOOR, build_volatility, load_frames
from backtest.backtesting_py_live38_4h_single_selector import build_selector_signals


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/live38_route30_trade_attribution.json")
FEE_BPS = 10.0
INITIAL_CAPITAL = 50.0
ALLOCATION = 0.5
VOLATILITY_TARGET = 0.015
SELECTOR = {
    "momentum_bars": 12,
    "trend_bars": 42,
    "score_mode": "raw",
    "min_trend": 0.01,
    "min_score": 0.0,
    "switch_margin": 0.01,
}


def _metric(frame, coin, index, bars):
    return float(frame.iloc[index][coin] / frame.iloc[index - bars][coin] - 1.0) if index >= bars else None


def _rank(momentum, coin):
    ranked = momentum.dropna().sort_values(ascending=False)
    positions = {name: index + 1 for index, name in enumerate(ranked.index)}
    return positions.get(coin)


def replay_fold(frames, closes, volatility, signals, *, name, start, end):
    opens = pd.DataFrame({coin: frames[coin]["Open"] for coin in LIVE_UNIVERSE})
    fee_rate = FEE_BPS / 10_000.0
    cash = INITIAL_CAPITAL
    position = None
    trades = []
    pending = signals.iloc[start - 1].astype(int).to_dict() if start else {coin: 0 for coin in LIVE_UNIVERSE}

    def close(coin, price, execution_bar, reason):
        nonlocal cash, position
        exit_notional = position["qty"] * float(price)
        exit_fee = exit_notional * fee_rate
        cash += exit_notional - exit_fee
        decision_bar = max(0, execution_bar - 1)
        exit_momentum = closes.iloc[decision_bar] / closes.iloc[max(0, decision_bar - 12)] - 1.0
        gross_return = float(price) / position["entry_price"] - 1.0
        net_pnl = exit_notional - exit_fee - position["notional"] - position["entry_fee"]
        mfe = position["max_price"] / position["entry_price"] - 1.0
        mae = position["min_price"] / position["entry_price"] - 1.0
        if net_pnl < 0 and mfe >= 0.02:
            failure_class = "giveback_loss"
        elif net_pnl < 0:
            failure_class = "initial_failure"
        elif mfe - gross_return >= 0.02:
            failure_class = "giveback_winner"
        else:
            failure_class = "clean_winner"
        trades.append(
            {
                **position["entry_context"],
                "fold": name,
                "coin": coin,
                "entry_bar": position["entry_bar"],
                "exit_bar": execution_bar,
                "hold_bars": execution_bar - position["entry_bar"],
                "entry_price": position["entry_price"],
                "exit_price": float(price),
                "gross_return_pct": gross_return * 100.0,
                "net_pnl_usd": net_pnl,
                "mfe_pct": mfe * 100.0,
                "mae_pct": mae * 100.0,
                "giveback_pct_points": max(0.0, (mfe - gross_return) * 100.0),
                "exit_reason": reason,
                "exit_momentum_3": _metric(closes, coin, decision_bar, 3),
                "exit_momentum_6": _metric(closes, coin, decision_bar, 6),
                "exit_momentum_12": _metric(closes, coin, decision_bar, 12),
                "exit_trend_42": _metric(closes, coin, decision_bar, 42),
                "exit_rank_12": _rank(exit_momentum, coin),
                "rank_deterioration": (_rank(exit_momentum, coin) or 0) - (position["entry_context"]["entry_rank_12"] or 0),
                "failure_class": failure_class,
            }
        )
        position = None

    for current_bar in range(start, end):
        desired = next((coin for coin, side in pending.items() if int(side) > 0), None)
        if position and desired != position["coin"]:
            decision_bar = max(0, current_bar - 1)
            trend = _metric(closes, position["coin"], decision_bar, 42)
            reason = "trend_failure" if trend is None or trend < SELECTOR["min_trend"] else "stronger_selector" if desired else "cash_state"
            close(position["coin"], opens.iloc[current_bar][position["coin"]], current_bar, reason)
        if position is None and desired:
            observed_vol = float(volatility.iloc[current_bar][desired])
            scale = max(VOLATILITY_FLOOR, min(1.0, VOLATILITY_TARGET / observed_vol)) if math.isfinite(observed_vol) and observed_vol > 0 else 1.0
            notional = cash * ALLOCATION * scale
            if notional >= MIN_ORDER_USD:
                price = float(opens.iloc[current_bar][desired])
                fee = notional * fee_rate
                cash -= notional + fee
                decision_bar = max(0, current_bar - 1)
                momentum = closes.iloc[decision_bar] / closes.iloc[max(0, decision_bar - 12)] - 1.0
                position = {
                    "coin": desired,
                    "entry_bar": current_bar,
                    "entry_price": price,
                    "qty": notional / price,
                    "notional": notional,
                    "entry_fee": fee,
                    "max_price": price,
                    "min_price": price,
                    "entry_context": {
                        "entry_momentum_3": _metric(closes, desired, decision_bar, 3),
                        "entry_momentum_6": _metric(closes, desired, decision_bar, 6),
                        "entry_momentum_12": _metric(closes, desired, decision_bar, 12),
                        "entry_momentum_24": _metric(closes, desired, decision_bar, 24),
                        "entry_trend_42": _metric(closes, desired, decision_bar, 42),
                        "entry_rank_12": _rank(momentum, desired),
                        "entry_volatility_42": observed_vol,
                        "positive_trend_breadth": float(((closes.iloc[decision_bar] / closes.iloc[decision_bar - 42] - 1.0) >= 0.01).mean()) if decision_bar >= 42 else None,
                    },
                }
        if position:
            close_price = float(closes.iloc[current_bar][position["coin"]])
            position["max_price"] = max(position["max_price"], close_price)
            position["min_price"] = min(position["min_price"], close_price)
        if current_bar < end - 1:
            pending = signals.iloc[current_bar].astype(int).to_dict()

    if position:
        close(position["coin"], closes.iloc[end - 1][position["coin"]], end - 1, "fold_end")
    return trades


def summarize(trades):
    groups = defaultdict(list)
    for trade in trades:
        groups[trade["failure_class"]].append(trade)
    by_class = {
        name: {
            "trades": len(rows),
            "net_pnl_usd": sum(row["net_pnl_usd"] for row in rows),
            "mean_return_pct": statistics.fmean(row["gross_return_pct"] for row in rows),
            "mean_mfe_pct": statistics.fmean(row["mfe_pct"] for row in rows),
            "mean_giveback_pct_points": statistics.fmean(row["giveback_pct_points"] for row in rows),
        }
        for name, rows in sorted(groups.items())
    }
    losses = [trade for trade in trades if trade["net_pnl_usd"] < 0]
    giveback_losses = [trade for trade in losses if trade["failure_class"] == "giveback_loss"]
    negative_pnl = -sum(trade["net_pnl_usd"] for trade in losses)
    giveback_negative_pnl = -sum(trade["net_pnl_usd"] for trade in giveback_losses)
    exit_reasons = defaultdict(list)
    for trade in trades:
        exit_reasons[trade["exit_reason"]].append(trade)
    return {
        "trades": len(trades),
        "winners": sum(trade["net_pnl_usd"] > 0 for trade in trades),
        "losers": len(losses),
        "net_pnl_usd": sum(trade["net_pnl_usd"] for trade in trades),
        "loss_pnl_from_giveback_pct": giveback_negative_pnl / negative_pnl * 100.0 if negative_pnl else 0.0,
        "trades_with_mfe_at_least_2pct": sum(trade["mfe_pct"] >= 2.0 for trade in trades),
        "trades_giving_back_at_least_2_points": sum(trade["giveback_pct_points"] >= 2.0 for trade in trades),
        "by_failure_class": by_class,
        "by_exit_reason": {
            name: {"trades": len(rows), "net_pnl_usd": sum(row["net_pnl_usd"] for row in rows)}
            for name, rows in sorted(exit_reasons.items())
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)
    frames = load_frames(args.data_path, bars_per_fold=300)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    signals = build_selector_signals(closes, **SELECTOR)
    folds = [("development_1", 0, 300), ("development_2", 300, 600), ("development_3", 600, 900), ("known_oos_benchmark", 900, 1200)]
    fold_trades = {name: replay_fold(frames, closes, volatility, signals, name=name, start=start, end=end) for name, start, end in folds}
    all_trades = [trade for rows in fold_trades.values() for trade in rows]
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "data_path": str(args.data_path),
        "fee_bps": FEE_BPS,
        "capital": INITIAL_CAPITAL,
        "selector": SELECTOR,
        "fold_role": {"development_1": "development", "development_2": "development", "development_3": "development", "known_oos_benchmark": "diagnostic_only_not_sealed"},
        "summary": summarize(all_trades),
        "folds": {name: {"summary": summarize(rows), "trades": rows} for name, rows in fold_trades.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
    return artifact


if __name__ == "__main__":
    main()
