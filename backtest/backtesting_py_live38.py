"""Run backtesting.py research on the frozen live 38-coin universe.

The strategy is deliberately small and state-driven: rank 38 coins by recent
return, use BTC's longer regime to choose long-best or short-worst exposure,
and hold until the next daily state change.  The backtesting.py report exposes
its built-in ``Buy & Hold Return [%]`` value for every coin and fold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.live_config import LIVE_UNIVERSE

try:
    import backtesting
    from backtesting import Strategy
    from backtesting.lib import FractionalBacktest
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("backtesting.py 0.6.5 is required; install requirements.txt") from exc


DEFAULT_DATA_PATH = Path("data/historical_prices/binance_1d_300d_live_38coins.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/backtesting_py_live38.json")
DEFAULT_FEE_BPS = 6.5
DEFAULT_STRESS_FEE_BPS = 10.0
EXTRA_STRESS_FEE_BPS = 15.0
INITIAL_CAPITAL = 100.0
FOLD_DAYS = 80
MAX_PORTFOLIO_POSITIONS = 2
ALLOCATION_PER_POSITION = 0.5
MIN_ORDER_USD = 10.0
PORTFOLIO_CAPITALS = (20.0, 25.0, 50.0, 100.0)


def _frame(bars):
    frame = pd.DataFrame(bars)
    frame["Date"] = pd.to_datetime(frame["time"], unit="ms", utc=True)
    frame = frame.set_index("Date")[["open", "high", "low", "close", "volume"]]
    frame.columns = ["Open", "High", "Low", "Close", "Volume"]
    return frame.astype(float)


def load_frames(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(set(LIVE_UNIVERSE) - set(payload))
    if missing:
        raise ValueError(f"fixture is missing live-universe coins: {', '.join(missing)}")
    frames = {coin: _frame(payload[coin]) for coin in LIVE_UNIVERSE}
    common_index = sorted(set.intersection(*(set(frame.index) for frame in frames.values())))
    if len(common_index) < FOLD_DAYS * 3:
        raise ValueError(
            f"live 38 fixture has only {len(common_index)} common daily bars; "
            f"need {FOLD_DAYS * 3}"
        )
    return {coin: frame.loc[common_index].copy() for coin, frame in frames.items()}


def build_regime_rank_signals(closes, *, momentum_days, regime_days, top_n):
    """Build causal daily target states for every coin.

    At a signal bar, only completed prices through that bar are used.  A
    positive BTC regime selects the strongest positive-return coins; a
    non-positive regime selects the weakest negative-return coins.  Zeros are
    explicit flat states, not missing values, so a coin cannot silently retain
    an old position after a rebalance.
    """

    signals = pd.DataFrame(index=closes.index, columns=closes.columns, dtype=float)
    momentum = closes / closes.shift(momentum_days) - 1.0
    btc_regime = closes["BTC"] / closes["BTC"].shift(regime_days) - 1.0
    warmup = max(momentum_days, regime_days)
    for index in range(warmup, len(closes)):
        ranked = momentum.iloc[index].dropna().sort_values(ascending=False)
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
    return signals.ffill().fillna(0.0)


def build_strategy():
    class RegimeRankStrategy(Strategy):
        def init(self):
            pass

        def next(self):
            target = int(self.data.Signal[-1])
            size = float(self.data.PositionSize[-1]) if hasattr(self.data, "PositionSize") else 0.5
            if not self.position:
                if target > 0:
                    self.buy(size=size, tag="regime_rank_long")
                elif target < 0:
                    self.sell(size=size, tag="regime_rank_short")
            elif self.position.is_long and target <= 0:
                self.position.close()
            elif self.position.is_short and target >= 0:
                self.position.close()

    RegimeRankStrategy.__name__ = "RegimeRankStrategy"
    return RegimeRankStrategy


def _buy_hold_net_return(raw_return_pct, fee_bps):
    gross_ratio = 1.0 + float(raw_return_pct) / 100.0
    fee = float(fee_bps) / 10_000.0
    return (gross_ratio * (1.0 - fee) ** 2 - 1.0) * 100.0


def run_coin(frame, signal, *, start, end, fee_bps, position_size=None):
    data = frame.iloc[start:end].copy()
    data["Signal"] = signal.iloc[start:end].astype(int).to_numpy()
    if position_size is not None:
        data["PositionSize"] = position_size.iloc[start:end].astype(float).to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stats = FractionalBacktest(
            data,
            build_strategy(),
            cash=INITIAL_CAPITAL,
            commission=float(fee_bps) / 10_000.0,
            exclusive_orders=True,
            finalize_trades=True,
        ).run()
    raw_buy_hold = float(stats["Buy & Hold Return [%]"])
    return {
        "strategy_return_pct": float(stats["Return [%]"]),
        "buy_hold_return_pct": raw_buy_hold,
        "buy_hold_net_return_pct": _buy_hold_net_return(raw_buy_hold, fee_bps),
        "strategy_minus_buy_hold_pct": float(stats["Return [%]"]) - raw_buy_hold,
        "max_drawdown_pct": float(stats["Max. Drawdown [%]"]),
        "exposure_time_pct": float(stats["Exposure Time [%]"]),
        "trades": int(stats["# Trades"]),
        "win_rate_pct": float(stats["Win Rate [%]"]) if pd.notna(stats["Win Rate [%]"]) else None,
    }


def summarize(rows):
    if not rows:
        return {}
    active_rows = [row for row in rows if row["trades"] > 0]
    return {
        "mean_strategy_return_pct": float(np.mean([row["strategy_return_pct"] for row in rows])),
        "median_strategy_return_pct": float(np.median([row["strategy_return_pct"] for row in rows])),
        "mean_buy_hold_return_pct": float(np.mean([row["buy_hold_return_pct"] for row in rows])),
        "mean_buy_hold_net_return_pct": float(np.mean([row["buy_hold_net_return_pct"] for row in rows])),
        "mean_strategy_minus_buy_hold_pct": float(
            np.mean([row["strategy_minus_buy_hold_pct"] for row in rows])
        ),
        "median_strategy_minus_buy_hold_pct": float(
            np.median([row["strategy_minus_buy_hold_pct"] for row in rows])
        ),
        "coins_outperforming_buy_hold": sum(
            row["strategy_minus_buy_hold_pct"] > 0.0 for row in rows
        ),
        "coins_with_positive_strategy_return": sum(
            row["strategy_return_pct"] > 0.0 for row in rows
        ),
        "active_coins": len(active_rows),
        "active_coins_with_positive_strategy_return": sum(
            row["strategy_return_pct"] > 0.0 for row in active_rows
        ),
        "mean_max_drawdown_pct": float(np.mean([row["max_drawdown_pct"] for row in rows])),
        "worst_coin_max_drawdown_pct": float(min(row["max_drawdown_pct"] for row in rows)),
        "mean_exposure_time_pct": float(np.mean([row["exposure_time_pct"] for row in rows])),
        "total_trades": sum(row["trades"] for row in rows),
    }


def _max_drawdown_pct(equity_curve):
    values = np.asarray(equity_curve, dtype=float)
    if len(values) == 0:
        return 0.0
    peaks = np.maximum.accumulate(values)
    return float(np.min((values / peaks - 1.0) * 100.0))


def simulate_portfolio(
    frames,
    signals,
    *,
    start,
    end,
    fee_bps,
    initial_capital,
    max_positions=MAX_PORTFOLIO_POSITIONS,
    allocation_per_position=ALLOCATION_PER_POSITION,
    min_order_usd=MIN_ORDER_USD,
    volatility=None,
    volatility_target=None,
    volatility_floor=0.5,
):
    """Replay the same states as an executable small-account portfolio.

    A state observed at a daily close is executed at the next bar's open.  No
    time-based exit is used.  Positions are capped and each new position is
    allocated a fixed fraction of current equity, which makes the $20/$50/$100
    feasibility checks explicit rather than inferring them from an equal-weight
    average of isolated coin backtests.
    """

    coins = list(LIVE_UNIVERSE)
    opens = pd.DataFrame({coin: frames[coin]["Open"] for coin in coins})
    closes = pd.DataFrame({coin: frames[coin]["Close"] for coin in coins})
    fee_rate = float(fee_bps) / 10_000.0
    cash = float(initial_capital)
    positions = {}
    realized_by_coin = {coin: 0.0 for coin in coins}
    equity_curve = [cash]
    entries = 0
    skipped_entries = 0
    total_fees = 0.0
    exposed_bars = 0
    traded_coins = set()

    def mark(price_row):
        return cash + sum(
            position["side"] * position["qty"] * float(price_row[coin])
            for coin, position in positions.items()
        )

    def close_position(coin, price):
        nonlocal cash, total_fees
        position = positions.pop(coin)
        notional = position["qty"] * float(price)
        fee = notional * fee_rate
        if position["side"] > 0:
            cash += notional
            pnl = position["qty"] * (float(price) - position["entry_price"])
        else:
            cash -= notional
            pnl = position["qty"] * (position["entry_price"] - float(price))
        cash -= fee
        total_fees += fee
        realized_by_coin[coin] += pnl - fee - position["entry_fee"]

    def open_position(coin, side, price):
        nonlocal cash, total_fees, entries, skipped_entries
        equity = mark(opens.iloc[current_bar])
        scale = 1.0
        if volatility is not None and volatility_target is not None:
            observed_vol = float(volatility.iloc[current_bar][coin])
            if np.isfinite(observed_vol) and observed_vol > 0.0:
                scale = max(volatility_floor, min(1.0, volatility_target / observed_vol))
        # The exchange minimum is checked on order notional; fees are charged
        # separately.  A $20 account therefore correctly surfaces the tiny
        # fee-buffer shortfall instead of silently placing a sub-minimum order.
        notional = equity * allocation_per_position * scale
        if notional < min_order_usd:
            skipped_entries += 1
            return
        price = float(price)
        qty = notional / price
        entry_fee = notional * fee_rate
        if side > 0:
            cash -= notional + entry_fee
        else:
            cash += notional - entry_fee
        total_fees += entry_fee
        positions[coin] = {
            "side": int(side),
            "qty": qty,
            "entry_price": price,
            "entry_fee": entry_fee,
        }
        entries += 1
        traded_coins.add(coin)

    pending = {coin: 0 for coin in coins}
    if start > 0:
        pending = signals.iloc[start - 1].astype(int).to_dict()
    for current_bar in range(start, end):
        price_row = opens.iloc[current_bar]
        desired = {
            coin: int(side)
            for coin, side in pending.items()
            if int(side) != 0
        }
        desired = dict(list(desired.items())[:max_positions])

        # Close removed or reversed states before opening replacements.
        for coin in list(positions):
            if coin not in desired or desired[coin] != positions[coin]["side"]:
                close_position(coin, price_row[coin])
        for coin, side in desired.items():
            if coin not in positions:
                open_position(coin, side, price_row[coin])

        if positions:
            exposed_bars += 1
        equity_curve.append(mark(closes.iloc[current_bar]))
        if current_bar < end - 1:
            pending = signals.iloc[current_bar].astype(int).to_dict()

    # Liquidate at the final close so returns include the exit cost.
    final_prices = closes.iloc[end - 1]
    for coin in list(positions):
        close_position(coin, final_prices[coin])
    equity_curve.append(cash)

    start_open = opens.iloc[start]
    end_close = closes.iloc[end - 1]
    equal_weight_buy_hold = float(np.mean(end_close.to_numpy() / start_open.to_numpy() - 1.0) * 100.0)
    positive_pnl = sorted((value for value in realized_by_coin.values() if value > 0.0), reverse=True)
    total_positive_pnl = sum(positive_pnl)
    top2_share = (
        float(sum(positive_pnl[:2]) / total_positive_pnl * 100.0)
        if total_positive_pnl > 0.0
        else 0.0
    )
    active_coins = sorted(traded_coins)
    strategy_return = (cash / initial_capital - 1.0) * 100.0
    return {
        "initial_capital": float(initial_capital),
        "final_equity": float(cash),
        "strategy_return_pct": float(strategy_return),
        "equal_weight_buy_hold_return_pct": equal_weight_buy_hold,
        "strategy_minus_equal_weight_buy_hold_pct": strategy_return - equal_weight_buy_hold,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "exposure_time_pct": float(exposed_bars / max(1, end - start) * 100.0),
        "entries": entries,
        "skipped_entries_below_min_order": skipped_entries,
        "total_fees": float(total_fees),
        "active_coins": len(active_coins),
        "positive_pnl_coins": sum(value > 0.0 for value in realized_by_coin.values()),
        "positive_pnl_top2_share_pct": top2_share,
        "realized_pnl_by_coin": {
            coin: round(float(value), 8) for coin, value in realized_by_coin.items() if abs(value) > 1e-12
        },
    }


def evaluate_candidate(candidate, frames, closes, folds, *, fee_bps):
    parameters = {key: value for key, value in candidate.items() if key != "name"}
    signals = build_regime_rank_signals(closes, **parameters)
    evaluations = []
    for name, start, end in folds:
        rows = [
            {"coin": coin, **run_coin(frames[coin], signals[coin], start=start, end=end, fee_bps=fee_bps)}
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


def evaluate_portfolio_costs(candidate, frames, closes, folds, *, fee_bps):
    parameters = {key: value for key, value in candidate.items() if key != "name"}
    signals = build_regime_rank_signals(closes, **parameters)
    return {
        name: {
            str(capital): simulate_portfolio(
                frames,
                signals,
                start=start,
                end=end,
                fee_bps=fee_bps,
                initial_capital=capital,
            )
            for capital in PORTFOLIO_CAPITALS
        }
        for name, start, end in folds
    }


def portfolio_holdout_review(holdout_result, *, capital=25.0):
    issues = []
    normal = holdout_result["normal"][0]["portfolio"][str(capital)]
    stressed = holdout_result["stressed"][0]["portfolio"][str(capital)]
    if min(normal["strategy_return_pct"], stressed["strategy_return_pct"]) <= 0.0:
        issues.append("portfolio_return_not_positive_under_10bps_stress")
    if min(normal["max_drawdown_pct"], stressed["max_drawdown_pct"]) <= -20.0:
        issues.append("portfolio_drawdown_exceeds_20pct")
    if max(normal["positive_pnl_top2_share_pct"], stressed["positive_pnl_top2_share_pct"]) >= 80.0:
        issues.append("positive_pnl_concentrated_in_top_two_coins")
    return issues


def portfolio_development_pass(normal, stressed, *, capital=25.0):
    checks = []
    for fold in normal + stressed:
        result = fold["portfolio"][str(capital)]
        checks.append(
            result["strategy_return_pct"] > 0.0
            and result["strategy_minus_equal_weight_buy_hold_pct"] > 0.0
            and result["skipped_entries_below_min_order"] == 0
        )
    return all(checks)


def development_pass(normal, stressed):
    normal_summaries = [fold["summary"] for fold in normal]
    stressed_summaries = [fold["summary"] for fold in stressed]
    return all(
        summary["mean_strategy_return_pct"] > 0.0
        and summary["mean_strategy_minus_buy_hold_pct"] > 0.0
        and summary["coins_outperforming_buy_hold"] >= 20
        for summary in normal_summaries + stressed_summaries
    )


def rank_key(row):
    stressed = row["stressed"][0]["summary"]
    normal = row["normal"][0]["summary"]
    return (
        row["development_pass"],
        stressed["mean_strategy_return_pct"],
        normal["mean_strategy_minus_buy_hold_pct"],
        -stressed["mean_max_drawdown_pct"],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--unlock-holdout", action="store_true")
    args = parser.parse_args(argv)

    frames = load_frames(args.data_path)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    if len(closes) < FOLD_DAYS * 3:
        raise ValueError("live 38 fixture needs at least three development/holdout folds")
    folds = [
        ("development_1", 0, FOLD_DAYS),
        ("development_2", FOLD_DAYS, FOLD_DAYS * 2),
    ]
    holdout = ("holdout", FOLD_DAYS * 2, FOLD_DAYS * 3)
    candidates = [
        {"name": "regime_rank_14d_btc7d_top1", "momentum_days": 14, "regime_days": 7, "top_n": 1},
        {"name": "regime_rank_14d_btc7d_top2", "momentum_days": 14, "regime_days": 7, "top_n": 2},
        {"name": "regime_rank_21d_btc7d_top1", "momentum_days": 21, "regime_days": 7, "top_n": 1},
        {"name": "regime_rank_28d_btc14d_top1", "momentum_days": 28, "regime_days": 14, "top_n": 1},
        {"name": "regime_rank_7d_btc42d_top2", "momentum_days": 7, "regime_days": 42, "top_n": 2},
    ]

    evaluated = []
    for candidate in candidates:
        normal = evaluate_candidate(candidate, frames, closes, folds, fee_bps=DEFAULT_FEE_BPS)
        stressed = evaluate_candidate(candidate, frames, closes, folds, fee_bps=DEFAULT_STRESS_FEE_BPS)
        evaluated.append(
            {
                "candidate": candidate,
                "normal": normal,
                "stressed": stressed,
                "development_pass": development_pass(normal, stressed),
                "portfolio_development_pass": portfolio_development_pass(normal, stressed),
            }
        )
    evaluated.sort(key=rank_key, reverse=True)
    selected = evaluated[0]
    holdout_result = None
    extra_cost_sensitivity = None
    portfolio_review = []
    if args.unlock_holdout and selected["development_pass"]:
        candidate = selected["candidate"]
        holdout_result = {
            "normal": evaluate_candidate(candidate, frames, closes, [holdout], fee_bps=DEFAULT_FEE_BPS),
            "stressed": evaluate_candidate(candidate, frames, closes, [holdout], fee_bps=DEFAULT_STRESS_FEE_BPS),
        }
        extra_cost_sensitivity = {
            "fee_bps": EXTRA_STRESS_FEE_BPS,
            "development": evaluate_portfolio_costs(
                candidate, frames, closes, folds, fee_bps=EXTRA_STRESS_FEE_BPS
            ),
            "holdout": evaluate_portfolio_costs(
                candidate, frames, closes, [holdout], fee_bps=EXTRA_STRESS_FEE_BPS
            ),
        }
        portfolio_review = portfolio_holdout_review(holdout_result)
        if any(
            result["25.0"]["strategy_return_pct"] <= 0.0
            for result in extra_cost_sensitivity["development"].values()
        ):
            portfolio_review.append("development_not_positive_at_15bps")

    artifact = {
        "schema_version": 2,
        "execution_authorized": False,
        "backtesting_py_version": getattr(backtesting, "__version__", "unknown"),
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "universe": list(LIVE_UNIVERSE),
        "universe_size": len(LIVE_UNIVERSE),
        "timeframe": "1d",
        "initial_capital": INITIAL_CAPITAL,
        "normal_fee_bps": DEFAULT_FEE_BPS,
        "stress_fee_bps": DEFAULT_STRESS_FEE_BPS,
        "extra_stress_fee_bps": EXTRA_STRESS_FEE_BPS,
        "minimum_order_usd": MIN_ORDER_USD,
        "portfolio_max_positions": MAX_PORTFOLIO_POSITIONS,
        "portfolio_allocation_per_position": ALLOCATION_PER_POSITION,
        "portfolio_capitals_tested": list(PORTFOLIO_CAPITALS),
        "holding_rule": "no minimum or maximum holding duration; state changes alone control exits",
        "comparison": "backtesting.py Buy & Hold Return [%] per coin and fold",
        "development_folds": folds,
        "holdout": holdout,
        "candidates": evaluated,
        "selected": selected,
        "holdout_result": holdout_result,
        "extra_cost_sensitivity": extra_cost_sensitivity,
        "portfolio_holdout_review": portfolio_review,
        "decision": (
            "holdout_pass_but_portfolio_review_required"
            if holdout_result and portfolio_review
            else "holdout_pass_candidate"
            if holdout_result
            else "development_pass_holdout_locked"
            if selected["development_pass"]
            else "rejected_in_development"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: artifact[key] for key in ("decision", "selected", "holdout_result")}, indent=2))
    return artifact


if __name__ == "__main__":
    main()
