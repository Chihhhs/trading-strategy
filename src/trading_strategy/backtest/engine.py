from trading_strategy.core.exit_policy import build_exit_policy
from trading_strategy.core.risk import calc_position_size
from trading_strategy.core.signals import get_atr_value
from trading_strategy.core.trend_trade import resolve_trend_stop_target
from trading_strategy.core.trade_history import apply_closed_trade

from .types import BacktestConfig, BacktestStrategy, StrategyContext


def _append_equity(equity_curve, state, peak_balance):
    current_balance = float(state.get("balance") or 0.0)
    equity_curve.append(current_balance)
    return max(peak_balance, current_balance)


def _build_position(coin, signal, current_price, current_bar, state, config):
    size = calc_position_size(
        state["balance"],
        current_price,
        signal.sl,
        leverage=config.leverage,
        risk_pct=config.risk_pct,
    )
    if size <= 0:
        return None
    position = {
        "coin": coin,
        "direction": signal.direction,
        "entry": current_price,
        "size": size,
        "tp": signal.tp,
        "sl": signal.sl,
        "entry_time": str(current_bar.get("time") or current_bar.get("timestamp") or current_bar.get("date") or ""),
        "entry_reason": signal.reason,
        "signal_reason": signal.reason,
        "signal_score": signal.score,
        "risk_pct": config.risk_pct,
        "entry_bar_index": int(state.get("_bar_index") or 0),
        "bars_since_entry": 0,
        "best_price": current_price,
        "entry_atr": (signal.raw or {}).get("atr"),
        "entry_breakout_level": (signal.raw or {}).get("breakout_level"),
        "entry_ema20": (signal.raw or {}).get("ema20"),
        "entry_ema50": (signal.raw or {}).get("ema50"),
    }
    position["initial_risk"] = abs(current_price - signal.sl) if signal.sl is not None else None
    position["exit_policy"] = build_exit_policy(signal={"reason": signal.reason}, position=position)
    return position


def _close_position(state, position, exit_price, exit_reason, *, exit_time=None):
    trade = apply_closed_trade(
        state,
        position,
        exit_price,
        exit_reason,
        exit_time=exit_time,
        update_balance=True,
        exit_context={"close_status": "simulated"},
    )
    return trade


def close_position_at_bar(state, position, current_bar, exit_reason="EOD"):
    return _close_position(
        state,
        position,
        float(current_bar["close"]),
        exit_reason,
        exit_time=str(current_bar.get("time") or current_bar.get("timestamp") or current_bar.get("date") or ""),
    )


def _resolve_exit(position, current_price):
    if position["direction"] == "long":
        if current_price >= position["tp"]:
            return current_price, "TP"
        if current_price <= position["sl"]:
            return current_price, "SL"
        return None
    if current_price <= position["tp"]:
        return current_price, "TP"
    if current_price >= position["sl"]:
        return current_price, "SL"
    return None


def _resolve_atr_trail_exit(position, current_price, config, current_index, window):
    position["current_price"] = current_price
    bars_since_entry = max(int(current_index or 0) - int(position.get("entry_bar_index") or 0), 0)
    position["bars_since_entry"] = bars_since_entry
    highs = [bar["high"] for bar in window]
    lows = [bar["low"] for bar in window]
    closes = [bar["close"] for bar in window]
    current_atr = get_atr_value(highs, lows, closes, default=current_price * 0.03)
    trail = resolve_trend_stop_target(
        position,
        current_atr=current_atr,
        atr_trailing_enabled=config.atr_trailing_enabled,
        atr_activation_r=config.atr_activation_r,
        atr_trailing_mult=config.atr_trailing_mult,
    )
    if trail.get("should_update") and trail.get("sl") is not None:
        if trail.get("source") == "atr_trail":
            position["atr_trailing_stop"] = trail["sl"]
        else:
            position["sl"] = trail["sl"]
        dynamic_target = trail.get("dynamic_target") or {}
        if dynamic_target.get("stage") is not None:
            position["sl_stage"] = dynamic_target.get("stage")
    atr_result = trail.get("atr_result") or {}
    if atr_result.get("triggered"):
        return current_price, "ATR_TRAIL"
    return None


class BacktestEngine:
    def __init__(self, *, config: BacktestConfig, strategy: BacktestStrategy):
        self.config = config
        self.strategy = strategy

    def step(self, coin, current_bar, window, btc_window, state):
        open_positions = state.setdefault("positions", [])
        state["_bar_index"] = len(window) - 1
        current_price = float(current_bar["close"])
        active_position = next((pos for pos in open_positions if pos.get("coin") == coin), None)

        if active_position is not None:
            resolved_exit = _resolve_exit(active_position, current_price)
            if resolved_exit is None:
                resolved_exit = _resolve_atr_trail_exit(
                    active_position,
                    current_price,
                    self.config,
                    len(window) - 1,
                    window,
                )
            if resolved_exit is not None:
                exit_price, exit_reason = resolved_exit
                _close_position(
                    state,
                    active_position,
                    exit_price,
                    exit_reason,
                    exit_time=str(current_bar.get("time") or current_bar.get("timestamp") or current_bar.get("date") or ""),
                )
                open_positions.remove(active_position)
                active_position = None

        if active_position is not None:
            return None

        context = StrategyContext(
            coin=coin,
            window=window,
            current_bar=current_bar,
            btc_window=btc_window,
            balance=float(state.get("balance") or 0.0),
            open_positions=tuple(open_positions),
            config=self.config,
        )
        signal = self.strategy.generate_signal(context)
        if signal is None:
            return None
        position = _build_position(coin, signal, current_price, current_bar, state, self.config)
        if position is None:
            return None
        open_positions.append(position)
        return position
