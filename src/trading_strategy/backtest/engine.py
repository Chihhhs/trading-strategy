from trading_strategy.core.exit_policy import build_exit_policy
from trading_strategy.core.risk import calc_position_size
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
    }
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


class BacktestEngine:
    def __init__(self, *, config: BacktestConfig, strategy: BacktestStrategy):
        self.config = config
        self.strategy = strategy

    def step(self, coin, current_bar, window, btc_window, state):
        open_positions = state.setdefault("positions", [])
        current_price = float(current_bar["close"])
        active_position = next((pos for pos in open_positions if pos.get("coin") == coin), None)

        if active_position is not None:
            resolved_exit = _resolve_exit(active_position, current_price)
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
