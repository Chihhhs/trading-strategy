import os
import shutil
import sys
from datetime import datetime, timedelta

from trading_strategy.core.risk import (
    calc_position_size,
    check_circuit_breaker,
    is_cooldown,
)
from trading_strategy.core.signals import generate_fvg_signal
from trading_strategy.core.state import load_state as load_shared_state
from trading_strategy.core.state import save_state as save_shared_state
from trading_strategy.market_data import WATCHLIST, get_binance_klines, get_current_prices


STRATEGIES = {
    "A_fvg_conservative": {
        "initial_balance": 1000.0,
        "max_positions": 2,
        "max_hold_days": 7,
        "leverage": 3,
        "risk_per_trade": 0.08,
        "strategy_type": "fvg",
        "max_daily_loss_pct": 15.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
    "B_fvg_aggressive": {
        "initial_balance": 1000.0,
        "max_positions": 3,
        "max_hold_days": 14,
        "leverage": 5,
        "risk_per_trade": 0.10,
        "strategy_type": "fvg",
        "max_daily_loss_pct": 15.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
    "C_trend_conservative": {
        "initial_balance": 1000.0,
        "max_positions": 2,
        "max_hold_days": 14,
        "leverage": 3,
        "risk_per_trade": 0.05,
        "strategy_type": "trend",
        "max_daily_loss_pct": 10.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
    "D_trend_aggressive": {
        "initial_balance": 1000.0,
        "max_positions": 3,
        "max_hold_days": 30,
        "leverage": 5,
        "risk_per_trade": 0.08,
        "strategy_type": "trend",
        "max_daily_loss_pct": 10.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
    "E_dual_conservative": {
        "initial_balance": 1000.0,
        "max_positions": 2,
        "max_hold_days": 7,
        "leverage": 3,
        "risk_per_trade": 0.08,
        "strategy_type": "both",
        "max_daily_loss_pct": 15.0,
        "max_consecutive_losses": 5,
        "cooldown_hours": 24,
    },
    "F_dual_aggressive": {
        "initial_balance": 1000.0,
        "max_positions": 3,
        "max_hold_days": 14,
        "leverage": 5,
        "risk_per_trade": 0.10,
        "strategy_type": "both",
        "max_daily_loss_pct": 15.0,
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
    if pos["direction"] == "long":
        pnl = (close_price - pos["entry"]) * pos["size"]
    else:
        pnl = (pos["entry"] - close_price) * pos["size"]

    state["balance"] += pnl
    stats = state["stats"]
    stats["total_trades"] += 1
    stats["total_pnl"] += pnl
    if pnl > 0:
        stats["wins"] += 1
        stats["max_win"] = max(stats["max_win"], pnl)
    else:
        stats["losses"] += 1
        stats["max_loss"] = min(stats["max_loss"], pnl)

    state["history"].append(
        {
            "coin": pos["coin"],
            "direction": pos["direction"],
            "entry": pos["entry"],
            "exit": close_price,
            "size": pos["size"],
            "pnl": round(pnl, 4),
            "reason": reason,
            "entry_time": pos["entry_time"],
            "exit_time": datetime.now().isoformat(),
            "signal_reason": pos.get("signal_reason", ""),
        }
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

        signal = generate_fvg_signal(data, strategy_type=params["strategy_type"])
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
                "signal_reason": signal.get("reason", ""),
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


def reset_states():
    if os.path.exists(MULTI_STATE_DIR):
        shutil.rmtree(MULTI_STATE_DIR)
    os.makedirs(MULTI_STATE_DIR, exist_ok=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
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
    "generate_fvg_signal",
    "get_binance_klines",
    "load_state",
    "main",
    "reset_states",
    "run_all",
    "run_once",
    "save_state",
]
