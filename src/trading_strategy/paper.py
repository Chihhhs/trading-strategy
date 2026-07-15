import os
import json
import shutil
import sys
from datetime import datetime, timedelta

from trading_strategy.core.risk import (
    calc_position_size,
    check_circuit_breaker,
    is_cooldown,
)
from trading_strategy.core.signals import generate_trend_signal
from trading_strategy.core.state import load_state as load_shared_state
from trading_strategy.core.state import save_state as save_shared_state
from trading_strategy.core.trade_history import apply_closed_trade
from trading_strategy.market_data import WATCHLIST, get_binance_klines, get_current_prices
from trading_strategy.strategies import StrategyContext, get_strategy, get_strategy_definition
from trading_strategy.strategies.base import signal_value


STRATEGIES = {
    "A_trend_conservative": {
        "initial_balance": 1000.0,
        "max_positions": 2,
        "max_hold_days": 14,
        "leverage": 3,
        "risk_per_trade": 0.05,
        "max_daily_loss_pct": 10.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
    "B_trend_aggressive": {
        "initial_balance": 1000.0,
        "max_positions": 3,
        "max_hold_days": 30,
        "leverage": 5,
        "risk_per_trade": 0.08,
        "max_daily_loss_pct": 10.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
}


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
MULTI_STATE_DIR = os.path.join(PROJECT_ROOT, "data", "paper_strategies")
os.makedirs(MULTI_STATE_DIR, exist_ok=True)


def _to_circuit(params):
    return {
        "max_daily_loss_pct": params["max_daily_loss_pct"],
        "max_consecutive_losses": params["max_consecutive_losses"],
        "cooldown_hours": params["cooldown_hours"],
    }


def load_state(name):
    params = STRATEGIES[name]
    return load_shared_state(
        MULTI_STATE_DIR,
        params,
        name=name,
        initial_balance=params["initial_balance"],
    )


def save_state(name, state):
    save_shared_state(MULTI_STATE_DIR, state, name=name)


def is_in_cooldown(state, coin_name):
    return is_cooldown(state, coin_name, _to_circuit(state["params"]))


def close_pos(state, pos, close_price, reason):
    apply_closed_trade(
        state,
        pos,
        close_price,
        reason,
        exit_context={
            "close_status": "paper_closed",
            "close_reason_source": "strategy_rule",
        },
    )


def update_positions(state, prices):
    params = state["params"]
    still_open = []
    for pos in state["positions"]:
        coin = pos["coin"]
        current = prices.get(coin)
        if current is None:
            still_open.append(pos)
            continue

        pos["current_price"] = current
        if pos["direction"] == "long":
            pnl = (current - pos["entry"]) * pos["size"]
        else:
            pnl = (pos["entry"] - current) * pos["size"]
        pos["pnl_pnl"] = pnl
        pos["pnl_pct"] = pnl / max(state["balance"], 1e-9) * 100 * params["leverage"]

        should_close = False
        reason = ""
        if pos["direction"] == "long":
            if current >= pos["tp"]:
                should_close, reason = True, "TP"
            elif current <= pos["sl"]:
                should_close, reason = True, "SL"
        else:
            if current <= pos["tp"]:
                should_close, reason = True, "TP"
            elif current >= pos["sl"]:
                should_close, reason = True, "SL"

        if not should_close:
            try:
                entry_time = datetime.fromisoformat(pos["entry_time"])
                if datetime.now() - entry_time > timedelta(days=params["max_hold_days"]):
                    should_close, reason = True, "TIME"
            except Exception:
                pass

        if should_close:
            close_pos(state, pos, current, reason)
        else:
            still_open.append(pos)

    state["positions"] = still_open


def check_new_entries(state):
    params = state["params"]
    if len(state["positions"]) >= params["max_positions"]:
        return

    circuit_ok, _ = check_circuit_breaker(state, _to_circuit(params))
    if not circuit_ok:
        return

    prices = get_current_prices(WATCHLIST)
    for coin in WATCHLIST:
        if len(state["positions"]) >= params["max_positions"]:
            break
        if any(p["coin"] == coin["name"] for p in state["positions"]):
            continue
        if is_in_cooldown(state, coin["name"]):
            continue

        data = get_binance_klines(coin["symbol"], limit=60)
        if not data or len(data) < 50:
            continue

        signal = generate_trend_signal(data, min_score=4, tp_mult=2.0, sl_mult=1.5)
        if signal is None:
            continue

        entry = prices.get(coin["name"])
        if entry is None:
            continue

        size = calc_position_size(
            state["balance"],
            entry,
            signal["sl"],
            params["leverage"],
            params["risk_per_trade"],
        )
        if size <= 0:
            continue

        state["positions"].append(
            {
                "coin": coin["name"],
                "direction": signal["direction"],
                "entry": entry,
                "tp": signal["tp"],
                "sl": signal["sl"],
                "size": round(size, 6),
                "current_price": entry,
                "pnl_pnl": 0,
                "pnl_pct": 0,
                "entry_time": datetime.now().isoformat(),
                "entry_reason": signal.get("reason", ""),
                "signal_reason": signal.get("reason", ""),
                "signal_score": signal.get("score"),
                "risk_pct": params["risk_per_trade"],
                "entry_order_type": "paper",
            }
        )


def run_once(name):
    state = load_state(name)
    prices = get_current_prices(WATCHLIST)
    update_positions(state, prices)
    check_new_entries(state)

    for pos in state["positions"]:
        if pos["coin"] in prices:
            pos["current_price"] = prices[pos["coin"]]

    save_state(name, state)
    return state


def run_all():
    return {name: run_once(name) for name in STRATEGIES}


def _experiment_params(session):
    return {
        "experiment_name": session.experiment_name,
        "manifest_fingerprint": session.manifest_fingerprint,
        "strategy_name": session.strategy_name,
        "timeframe": session.timeframe,
        "initial_balance": session.initial_capital,
        "max_positions": session.max_positions or len(session.coins),
        "max_hold_days": 30,
        "leverage": session.leverage,
        "risk_per_trade": session.risk_pct,
        "fee_bps": session.fee_bps,
        "slippage_bps": session.slippage_bps,
        "max_daily_loss_pct": 10.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
        **session.strategy_parameters,
    }


def _load_experiment_state(session):
    params = _experiment_params(session)
    return load_shared_state(
        session.state_dir or MULTI_STATE_DIR,
        params,
        name=session.state_id,
        initial_balance=session.initial_capital,
    )


def _experiment_transaction_cost(pos, exit_price, params):
    rate = (float(params.get("fee_bps", 0.0)) + float(params.get("slippage_bps", 0.0))) / 10000.0
    return (
        (abs(float(pos.get("entry") or 0.0)) + abs(float(exit_price or 0.0)))
        * abs(float(pos.get("size") or 0.0))
        * rate
    )


def _close_experiment_position(state, pos, exit_price, reason, params, *, is_partial=False):
    return apply_closed_trade(
        state,
        pos,
        exit_price,
        reason,
        exit_context={
            "close_status": "paper_reduced" if is_partial else "paper_closed",
            "close_reason_source": "strategy_adjustment" if is_partial else "strategy_rule",
            "is_partial": bool(is_partial),
        },
        transaction_cost=_experiment_transaction_cost(pos, exit_price, params),
    )


def _update_experiment_positions(state, prices, data_cache, strategy, params):
    still_open = []
    for pos in state["positions"]:
        current = prices.get(pos["coin"])
        if current is None:
            still_open.append(pos)
            continue
        pos["current_price"] = current
        current_bar = (data_cache.get(pos["coin"]) or [None])[-1]
        bar_identity = (current_bar or {}).get("ts") or (current_bar or {}).get("open_time") or (current_bar or {}).get("time")
        if bar_identity is not None and bar_identity != pos.get("last_evaluated_bar"):
            pos["bars_since_entry"] = int(pos.get("bars_since_entry") or 0) + 1
            pos["last_evaluated_bar"] = bar_identity
        context = StrategyContext(
            coin=pos["coin"],
            window=list(data_cache.get(pos["coin"], [])),
            current_bar=current_bar,
            balance=float(state.get("balance") or 0.0),
            open_positions=tuple(state.get("positions", [])),
            config=params,
            mode="paper",
            price=current,
        )
        stop_target = strategy.resolve_stop_target(pos, context)
        if stop_target and stop_target.get("should_update") and stop_target.get("sl") is not None:
            pos["sl"] = float(stop_target["sl"])
        evaluation = strategy.evaluate_open_position(pos, context)
        reason = evaluation.get("exit_reason")
        adjustment = evaluation.get("position_adjustment") or {}
        if adjustment.get("action") == "reduce":
            fraction = max(0.0, min(float(adjustment.get("fraction") or 0.0), 1.0))
            reduce_size = float(pos.get("size") or 0.0) * fraction
            if 0 < reduce_size < float(pos.get("size") or 0.0):
                partial = dict(pos)
                partial["size"] = reduce_size
                _close_experiment_position(
                    state,
                    partial,
                    current,
                    adjustment.get("reason") or "POSITION_REDUCE",
                    params,
                    is_partial=True,
                )
                pos["size"] = round(float(pos["size"]) - reduce_size, 12)
                reduction_key = adjustment.get("reduction_key")
                if reduction_key:
                    reductions = list(pos.get("derivatives_crowding_reductions") or [])
                    if reduction_key not in reductions:
                        reductions.append(reduction_key)
                    pos["derivatives_crowding_reductions"] = reductions
        if not reason:
            try:
                if datetime.now() - datetime.fromisoformat(pos["entry_time"]) > timedelta(
                    days=int(params.get("max_hold_days", 30))
                ):
                    reason = "TIME"
            except (TypeError, ValueError):
                pass
        if reason:
            _close_experiment_position(state, pos, current, reason, params)
            continue
        requires_tp = strategy.build_exit_policy(position=pos).get("requires_tp", True)
        if pos["direction"] == "long":
            tp_hit = requires_tp and pos.get("tp") is not None and current >= pos["tp"]
            sl_hit = pos.get("sl") is not None and current <= pos["sl"]
        else:
            tp_hit = requires_tp and pos.get("tp") is not None and current <= pos["tp"]
            sl_hit = pos.get("sl") is not None and current >= pos["sl"]
        if tp_hit or sl_hit:
            _close_experiment_position(state, pos, current, "TP" if tp_hit else "SL", params)
        else:
            still_open.append(pos)
    state["positions"] = still_open


def _check_experiment_entries(state, session, prices, data_cache, strategy, params):
    if len(state["positions"]) >= params["max_positions"]:
        return
    circuit_ok, _ = check_circuit_breaker(state, _to_circuit(params))
    if not circuit_ok:
        return
    for coin in session.coins:
        if len(state["positions"]) >= params["max_positions"]:
            break
        if any(pos["coin"] == coin for pos in state["positions"]) or is_cooldown(
            state,
            coin,
            _to_circuit(params),
        ):
            continue
        window = data_cache.get(coin) or []
        if len(window) < get_strategy_definition(session.strategy_name).min_bars:
            continue
        signal = strategy.generate_signal(
            StrategyContext(
                coin=coin,
                window=list(window),
                current_bar=window[-1],
                balance=float(state.get("balance") or 0.0),
                open_positions=tuple(state.get("positions", [])),
                config=params,
                mode="paper",
                price=prices.get(coin),
            )
        )
        if strategy.should_block_for_btc(coin, signal, data_cache.get("BTC") or []):
            continue
        entry = prices.get(coin)
        if signal is None or entry is None:
            continue
        size = calc_position_size(
            state["balance"],
            entry,
            signal_value(signal, "sl"),
            params["leverage"],
            params["risk_per_trade"],
        )
        if size <= 0:
            continue
        position = {
            "coin": coin,
            "direction": signal_value(signal, "direction"),
            "entry": entry,
            "tp": signal_value(signal, "tp"),
            "sl": signal_value(signal, "sl"),
            "size": round(size, 6),
            "current_price": entry,
            "entry_time": datetime.now().isoformat(),
            "entry_reason": signal_value(signal, "reason", ""),
            "signal_reason": signal_value(signal, "reason", ""),
            "signal_score": signal_value(signal, "score"),
            "risk_pct": params["risk_per_trade"],
            "strategy_name": session.strategy_name,
            "entry_order_type": "paper",
        }
        position["exit_policy"] = strategy.build_exit_policy(signal=signal, position=position)
        strategy.initialize_position(
            position,
            signal,
            StrategyContext(
                coin=coin,
                window=list(window),
                current_bar=window[-1],
                balance=float(state.get("balance") or 0.0),
                open_positions=tuple(state.get("positions", [])),
                config=params,
                mode="paper",
                price=entry,
            ),
        )
        current_bar = window[-1]
        position["last_evaluated_bar"] = current_bar.get("ts") or current_bar.get("open_time") or current_bar.get("time")
        state["positions"].append(position)


def run_experiment_once(session):
    from trading_strategy.experiments import update_paper_session_progress

    params = _experiment_params(session)
    strategy = get_strategy(session.strategy_name)
    market_context_coins = set(session.coins) | {"BTC"}
    watchlist = [coin for coin in WATCHLIST if coin["name"] in market_context_coins]
    state = _load_experiment_state(session)
    prices = get_current_prices(watchlist)
    min_bars = get_strategy_definition(session.strategy_name).min_bars
    data_cache = {
        coin["name"]: get_binance_klines(
            coin["symbol"],
            interval=session.timeframe,
            limit=max(min_bars + 10, 90),
        )
        or []
        for coin in watchlist
    }
    _update_experiment_positions(state, prices, data_cache, strategy, params)
    _check_experiment_entries(state, session, prices, data_cache, strategy, params)
    save_shared_state(session.state_dir or MULTI_STATE_DIR, state, name=session.state_id)
    update_paper_session_progress(session, state)
    return state


def reset_states():
    if os.path.exists(MULTI_STATE_DIR):
        shutil.rmtree(MULTI_STATE_DIR)
    os.makedirs(MULTI_STATE_DIR, exist_ok=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--experiment" in argv:
        import argparse

        from trading_strategy.experiments import ExperimentSpec, PaperExperimentAdapter, PromotionDecision, load_experiment

        parser = argparse.ArgumentParser(prog="paper_runner")
        parser.add_argument("--experiment", required=True)
        parser.add_argument("--approval-result", required=True)
        args = parser.parse_args(argv)
        spec = load_experiment(args.experiment)
        with open(args.approval_result, "r", encoding="utf-8") as handle:
            decision = PromotionDecision.from_mapping(json.load(handle))
        session = PaperExperimentAdapter().start(
            spec,
            decision,
            session_root=os.path.join(PROJECT_ROOT, "data", "paper_candidates"),
        )
        state = run_experiment_once(session)
        print(
            f"{session.experiment_name}: balance=${state['balance']:.2f}, "
            f"positions={len(state['positions'])}, strategy={session.strategy_name}"
        )
        return state
    if "--reset" in argv:
        reset_states()
        print("reset complete")
        return

    results = run_all()
    for name, state in results.items():
        stats = state["stats"]
        total = stats["total_trades"]
        wr = stats["wins"] / total * 100 if total else 0
        print(f"{name}: balance=${state['balance']:.2f}, trades={total}, win_rate={wr:.1f}%")


__all__ = [
    "MULTI_STATE_DIR",
    "STRATEGIES",
    "WATCHLIST",
    "calc_position_size",
    "generate_trend_signal",
    "get_binance_klines",
    "load_state",
    "main",
    "reset_states",
    "run_all",
    "run_once",
    "save_state",
]
