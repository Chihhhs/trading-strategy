from trading_strategy.shared.risk import calc_position_size
from trading_strategy.shared.trade_history import apply_closed_trade
from trading_strategy.strategies.base import StrategyContext, signal_value

from .types import BacktestConfig, BacktestStrategy


def _append_equity(equity_curve, state, peak_balance):
    current_balance = float(state.get("balance") or 0.0)
    equity_curve.append(current_balance)
    return max(peak_balance, current_balance)


def _build_position(coin, signal, current_price, current_bar, state, config, strategy, window):
    size = calc_position_size(
        state["balance"],
        current_price,
        signal_value(signal, "sl"),
        leverage=config.leverage,
        risk_pct=config.risk_pct,
    )
    if size <= 0:
        return None
    position = {
        "coin": coin,
        "direction": signal_value(signal, "direction"),
        "entry": current_price,
        "size": size,
        "tp": signal_value(signal, "tp"),
        "sl": signal_value(signal, "sl"),
        "entry_time": str(current_bar.get("time") or current_bar.get("timestamp") or current_bar.get("date") or ""),
        "entry_reason": signal_value(signal, "reason", ""),
        "signal_reason": signal_value(signal, "reason", ""),
        "signal_score": signal_value(signal, "score"),
        "risk_pct": config.risk_pct,
        "entry_bar_index": int(state.get("_bar_index") or 0),
        "strategy_name": getattr(strategy, "name", config.strategy),
    }
    position["exit_policy"] = strategy.build_exit_policy(signal=signal, position=position)
    return strategy.initialize_position(
        position,
        signal,
        StrategyContext(
            coin=coin,
            window=window,
            current_bar=current_bar,
            btc_window=None,
            balance=float(state.get("balance") or 0.0),
            open_positions=tuple(state.get("positions", [])),
            config=config,
            mode="backtest",
            price=current_price,
        ),
    )


def _estimate_transaction_cost(position, exit_price, config):
    fee_bps = float(getattr(config, "fee_bps", 0.0) or 0.0)
    slippage_bps = float(getattr(config, "slippage_bps", 0.0) or 0.0)
    rate = (fee_bps + slippage_bps) / 10000.0
    if rate <= 0:
        return 0.0
    size = abs(float(position.get("size") or 0.0))
    entry = abs(float(position.get("entry") or 0.0))
    exit_px = abs(float(exit_price or 0.0))
    return (entry * size + exit_px * size) * rate


def _close_position(state, position, exit_price, exit_reason, *, exit_time=None):
    trade = apply_closed_trade(
        state,
        position,
        exit_price,
        exit_reason,
        exit_time=exit_time,
        update_balance=True,
        exit_context={"close_status": "simulated"},
        transaction_cost=_estimate_transaction_cost(position, exit_price, state.get("_config")),
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
        if position.get("tp") is not None and current_price >= position["tp"]:
            return current_price, "TP"
        if position.get("sl") is not None and current_price <= position["sl"]:
            return current_price, "SL"
        return None
    if position.get("tp") is not None and current_price <= position["tp"]:
        return current_price, "TP"
    if position.get("sl") is not None and current_price >= position["sl"]:
        return current_price, "SL"
    return None


def _resolve_strategy_exit(position, current_price, config, current_index, window, strategy, current_bar, state):
    position["current_price"] = current_price
    bars_since_entry = max(int(current_index or 0) - int(position.get("entry_bar_index") or 0), 0)
    position["bars_since_entry"] = bars_since_entry
    context = StrategyContext(
        coin=position.get("coin", ""),
        window=window,
        current_bar=current_bar,
        btc_window=None,
        balance=float(state.get("balance") or 0.0),
        open_positions=tuple(state.get("positions", [])),
        config=config,
        mode="backtest",
        price=current_price,
    )
    trail = strategy.resolve_stop_target(
        position,
        context,
    )
    if trail and trail.get("should_update") and trail.get("sl") is not None:
        if trail.get("source") == "dynamic_stage":
            position["sl"] = trail["sl"]
        else:
            position["atr_trailing_stop"] = trail["sl"]
        dynamic_target = trail.get("dynamic_target") or {}
        if dynamic_target.get("stage") is not None:
            position["sl_stage"] = dynamic_target.get("stage")
    evaluation = strategy.evaluate_open_position(position, context)
    if evaluation.get("exit_reason"):
        return current_price, evaluation["exit_reason"]
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
                resolved_exit = _resolve_strategy_exit(
                    active_position,
                    current_price,
                    self.config,
                    len(window) - 1,
                    window,
                    self.strategy,
                    current_bar,
                    state,
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
        max_positions = getattr(self.config, "max_positions", None)
        if max_positions is not None and len(open_positions) >= int(max_positions):
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
        position = _build_position(
            coin,
            signal,
            current_price,
            current_bar,
            state,
            self.config,
            self.strategy,
            window,
        )
        if position is None:
            return None
        open_positions.append(position)
        return position
