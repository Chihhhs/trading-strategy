"""Compare Route30 against entry-quality research routes 38-44.

This is a diagnostic-only replay on the existing fixed live-38 4h contract.
It does not select a winner for paper/live and never changes paper state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.live_config import LIVE_UNIVERSE  # noqa: E402


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path(
    "data/research_artifacts/backtesting_py_live38_4h_entry_quality_routes_2026-07-24.json"
)
NORMAL_FEE_BPS = 10.0
STRESS_FEE_BPS = 15.0
CAPITAL = 50.0
BARS_PER_FOLD = 300
MIN_ORDER_USD = 10.0
ALLOCATION_PER_POSITION = 0.5
VOLATILITY_LOOKBACK = 42
VOLATILITY_FLOOR = 0.5

ROUTES = {
    "30": {
        "name": "route30_baseline",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.0,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
    },
    "38": {
        "name": "route38_leader_persistence_2bar",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.0,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 2,
        "volatility_target": 0.015,
    },
    "39": {
        "name": "route39_switch_margin_2pct",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.0,
        "switch_margin": 0.02,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
    },
    "40": {
        "name": "route40_trend_84bar",
        "momentum_bars": 12,
        "trend_bars": 84,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.0,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
    },
    "41": {
        "name": "route41_momentum_floor_1pct",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.01,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
    },
    "42": {
        "name": "route42_momentum_floor_2pct",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.02,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
    },
    "43": {
        "name": "route43_volatility_normalized_rank",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "vol_normalized",
        "min_trend": 0.01,
        "min_score": 0.0,
        "switch_margin": 0.25,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
    },
    "44": {
        "name": "route44_reentry_cooldown_2bars",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_trend": 0.01,
        "min_score": 0.0,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 1,
        "reentry_cooldown_bars": 2,
        "volatility_target": 0.015,
    },
}


def _folds(bars_per_fold: int):
    return [
        ("development_1", 0, bars_per_fold),
        ("development_2", bars_per_fold, bars_per_fold * 2),
        ("development_3", bars_per_fold * 2, bars_per_fold * 3),
    ]


def _frame(bars):
    frame = pd.DataFrame(bars)
    frame["Date"] = pd.to_datetime(frame["time"], unit="ms", utc=True)
    frame = frame.set_index("Date")[["open", "high", "low", "close", "volume"]]
    frame.columns = ["Open", "High", "Low", "Close", "Volume"]
    return frame.astype(float)


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


def load_frames(path: Path, *, bars_per_fold=BARS_PER_FOLD):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "coins" in payload and isinstance(payload["coins"], dict):
        payload = payload["coins"]
    missing = sorted(set(LIVE_UNIVERSE) - set(payload))
    if missing:
        raise ValueError(f"fixture is missing live-universe coins: {', '.join(missing)}")
    frames = {
        coin: _resample_4h(_frame(payload[coin]))
        for coin in LIVE_UNIVERSE
    }
    common_index = sorted(set.intersection(*(set(frame.index) for frame in frames.values())))
    needed = bars_per_fold * 4
    if len(common_index) < needed:
        raise ValueError(f"4h fixture has only {len(common_index)} common bars; need {needed}")
    return {coin: frame.loc[common_index].copy() for coin, frame in frames.items()}


def build_volatility(closes):
    return closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()


def build_selector_signals(closes, candidate):
    momentum_bars = int(candidate["momentum_bars"])
    trend_bars = int(candidate["trend_bars"])
    momentum = closes / closes.shift(momentum_bars) - 1.0
    trend = closes / closes.shift(trend_bars) - 1.0
    volatility = closes.pct_change().rolling(VOLATILITY_LOOKBACK).std()
    if candidate["score_mode"] == "vol_normalized":
        score = momentum / volatility
    elif candidate["score_mode"] == "raw":
        score = momentum
    else:
        raise ValueError(f"unsupported score_mode: {candidate['score_mode']}")
    signals = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    warmup = max(momentum_bars, trend_bars, VOLATILITY_LOOKBACK)
    confirmation_bars = max(1, int(candidate.get("entry_confirmation_bars", 1)))
    incumbent = None
    pending_candidate = None
    pending_streak = 0
    cooldowns = {coin: 0 for coin in closes.columns}
    cooldown_bars = max(0, int(candidate.get("reentry_cooldown_bars", 0)))
    for index in range(warmup, len(closes)):
        scores = score.iloc[index]
        trends = trend.iloc[index]
        eligible = (
            scores.notna()
            & trends.notna()
            & (trends >= float(candidate["min_trend"]))
            & (scores >= float(candidate["min_score"]))
        )
        if cooldown_bars:
            eligible &= pd.Series(
                {coin: cooldowns[coin] <= 0 for coin in closes.columns}
            )
        previous_incumbent = incumbent
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
            if lead >= float(candidate["switch_margin"]):
                incumbent = confirmed_best
        if cooldown_bars and previous_incumbent and previous_incumbent != incumbent:
            cooldowns[previous_incumbent] = cooldown_bars
        if incumbent is not None:
            signals.iloc[index, signals.columns.get_loc(incumbent)] = 1.0
        if cooldown_bars:
            cooldowns = {
                coin: max(0, remaining - 1)
                for coin, remaining in cooldowns.items()
            }
    return signals


def _max_drawdown_pct(equity_curve):
    values = np.asarray(equity_curve, dtype=float)
    peaks = np.maximum.accumulate(values)
    drawdowns = np.divide(values, peaks, out=np.ones_like(values), where=peaks != 0) - 1.0
    return float(drawdowns.min() * 100.0)


def simulate_portfolio(frames, signals, *, start, end, fee_bps, initial_capital, volatility, volatility_target):
    opens = pd.DataFrame({coin: frames[coin]["Open"] for coin in LIVE_UNIVERSE})
    closes = pd.DataFrame({coin: frames[coin]["Close"] for coin in LIVE_UNIVERSE})
    fee_rate = float(fee_bps) / 10_000.0
    cash = float(initial_capital)
    positions = {}
    realized_by_coin = {coin: 0.0 for coin in LIVE_UNIVERSE}
    equity_curve = [cash]
    entries = 0
    skipped_entries = 0
    total_fees = 0.0
    exposed_bars = 0

    def mark(price_row):
        return cash + sum(
            position["qty"] * float(price_row[coin])
            for coin, position in positions.items()
        )

    def close_position(coin, price):
        nonlocal cash, total_fees
        position = positions.pop(coin)
        notional = position["qty"] * float(price)
        fee = notional * fee_rate
        cash += notional - fee
        pnl = position["qty"] * (float(price) - position["entry_price"])
        cash -= 0.0
        total_fees += fee
        realized_by_coin[coin] += pnl - fee - position["entry_fee"]

    def open_position(coin, price, current_bar):
        nonlocal cash, total_fees, entries, skipped_entries
        equity = mark(opens.iloc[current_bar])
        observed_vol = float(volatility.iloc[current_bar][coin])
        scale = 1.0
        if np.isfinite(observed_vol) and observed_vol > 0.0:
            scale = max(VOLATILITY_FLOOR, min(1.0, volatility_target / observed_vol))
        notional = equity * ALLOCATION_PER_POSITION * scale
        if notional < MIN_ORDER_USD:
            skipped_entries += 1
            return
        entry_fee = notional * fee_rate
        cash -= notional + entry_fee
        total_fees += entry_fee
        positions[coin] = {
            "qty": notional / float(price),
            "entry_price": float(price),
            "entry_fee": entry_fee,
        }
        entries += 1

    pending = {coin: 0 for coin in LIVE_UNIVERSE}
    if start > 0:
        pending = signals.iloc[start - 1].astype(int).to_dict()
    for current_bar in range(start, end):
        desired = {coin for coin, side in pending.items() if int(side) != 0}
        for coin in list(positions):
            if coin not in desired:
                close_position(coin, opens.iloc[current_bar][coin])
        for coin in desired:
            if coin not in positions:
                open_position(coin, opens.iloc[current_bar][coin], current_bar)
        if positions:
            exposed_bars += 1
        equity_curve.append(mark(closes.iloc[current_bar]))
        if current_bar < end - 1:
            pending = signals.iloc[current_bar].astype(int).to_dict()

    final_prices = closes.iloc[end - 1]
    for coin in list(positions):
        close_position(coin, final_prices[coin])
    equity_curve.append(cash)
    start_open = opens.iloc[start]
    end_close = closes.iloc[end - 1]
    equal_weight = float(np.mean(end_close.to_numpy() / start_open.to_numpy() - 1.0) * 100.0)
    strategy_return = (cash / initial_capital - 1.0) * 100.0
    return {
        "strategy_return_pct": float(strategy_return),
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "entries": entries,
        "skipped_entries_below_min_order": skipped_entries,
        "total_fees": float(total_fees),
        "exposure_time_pct": exposed_bars / max(1, end - start) * 100.0,
        "equal_weight_buy_hold_return_pct": equal_weight,
    }


def evaluate_portfolio(candidate, frames, closes, volatility, folds, *, fee_bps):
    signals = build_selector_signals(closes, candidate)
    return {
        name: {
            str(CAPITAL): simulate_portfolio(
                frames,
                signals,
                start=start,
                end=end,
                fee_bps=fee_bps,
                initial_capital=CAPITAL,
                volatility=volatility,
                volatility_target=float(candidate["volatility_target"]),
            )
        }
        for name, start, end in folds
    }


def _metric(result):
    return {
        "strategy_return_pct": result["strategy_return_pct"],
        "max_drawdown_pct": result["max_drawdown_pct"],
        "entries": result["entries"],
        "skipped_entries_below_min_order": result["skipped_entries_below_min_order"],
        "total_fees": result["total_fees"],
        "exposure_time_pct": result["exposure_time_pct"],
        "equal_weight_buy_hold_return_pct": result["equal_weight_buy_hold_return_pct"],
    }


def run(data_path: Path, *, bars_per_fold: int = BARS_PER_FOLD):
    frames = load_frames(data_path, bars_per_fold=bars_per_fold)
    import pandas as pd

    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volatility = build_volatility(closes)
    folds = _folds(bars_per_fold)
    holdout = [("holdout", bars_per_fold * 3, bars_per_fold * 4)]
    output = {
        "schema_version": 1,
        "execution_authorized": False,
        "data_path": str(data_path),
        "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "decision_timeframe": "4h",
        "universe_size": len(frames),
        "bars_per_fold": bars_per_fold,
        "capital": CAPITAL,
        "normal_fee_bps": NORMAL_FEE_BPS,
        "stress_fee_bps": STRESS_FEE_BPS,
        "routes": {},
        "decision": "diagnostic_only_no_promotion",
    }
    for route_id, candidate in ROUTES.items():
        normal = evaluate_portfolio(
            candidate, frames, closes, volatility, folds, fee_bps=NORMAL_FEE_BPS
        )
        stressed = evaluate_portfolio(
            candidate, frames, closes, volatility, folds, fee_bps=STRESS_FEE_BPS
        )
        normal_holdout = evaluate_portfolio(
            candidate, frames, closes, volatility, holdout, fee_bps=NORMAL_FEE_BPS
        )
        stressed_holdout = evaluate_portfolio(
            candidate, frames, closes, volatility, holdout, fee_bps=STRESS_FEE_BPS
        )
        output["routes"][route_id] = {
            "candidate": candidate,
            "development": {
                "normal": {
                    name: _metric(result[str(CAPITAL)])
                    for name, result in normal.items()
                },
                "stressed": {
                    name: _metric(result[str(CAPITAL)])
                    for name, result in stressed.items()
                },
            },
            "holdout": {
                "normal": _metric(normal_holdout["holdout"][str(CAPITAL)]),
                "stressed": _metric(stressed_holdout["holdout"][str(CAPITAL)]),
            },
        }
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=BARS_PER_FOLD)
    args = parser.parse_args(argv)
    if args.bars_per_fold <= 0:
        raise SystemExit("--bars-per-fold must be positive")
    result = run(args.data_path, bars_per_fold=args.bars_per_fold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
