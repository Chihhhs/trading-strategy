from trading_strategy.shared.risk import calc_position_size
from trading_strategy.shared.trade_history import apply_closed_trade
from trading_strategy.strategies.base import StrategyContext, signal_value

from .types import BacktestConfig, BacktestStrategy
from .exit_replay import effective_stop, resolve_hourly_stop_fill


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
            diagnostics=state.get("_diagnostics"),
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


def _reduce_position(state, position, current_price, adjustment, *, exit_time=None):
    fraction = float((adjustment or {}).get("fraction") or 0.0)
    fraction = max(0.0, min(fraction, 1.0))
    current_size = abs(float(position.get("size") or 0.0))
    if fraction <= 0 or current_size <= 0:
        return None
    reduce_size = current_size * fraction
    if reduce_size <= 0:
        return None
    partial = dict(position)
    partial["size"] = reduce_size
    reason = (adjustment or {}).get("reason") or "POSITION_REDUCE"
    trade = _close_position(
        state,
        partial,
        current_price,
        reason,
        exit_time=exit_time,
    )
    remaining_size = max(current_size - reduce_size, 0.0)
    position["size"] = remaining_size
    if (adjustment or {}).get("reduction_key"):
        reductions = set(position.get("derivatives_crowding_reductions") or [])
        reductions.add(adjustment["reduction_key"])
        position["derivatives_crowding_reductions"] = sorted(reductions)
    return trade


def close_position_at_bar(state, position, current_bar, exit_reason="EOD"):
    return _close_position(
        state,
        position,
        float(current_bar["close"]),
        exit_reason,
        exit_time=str(current_bar.get("time") or current_bar.get("timestamp") or current_bar.get("date") or ""),
    )


def _intrabar_exit(position, current_bar, config):
    if not bool(getattr(config, "intrabar_exit_enabled", False)):
        return None
    high = float(current_bar.get("high", current_bar.get("close")))
    low = float(current_bar.get("low", current_bar.get("close")))
    tp = position.get("tp")
    sl = position.get("sl")
    policy = str(getattr(config, "intrabar_fill_policy", "stop_first") or "stop_first")

    if position["direction"] == "long":
        sl_hit = sl is not None and low <= float(sl)
        tp_hit = tp is not None and high >= float(tp)
    else:
        sl_hit = sl is not None and high >= float(sl)
        tp_hit = tp is not None and low <= float(tp)

    if sl_hit and tp_hit:
        if policy == "target_first":
            return float(tp), "TP"
        return float(sl), "SL"
    if sl_hit:
        return float(sl), "SL"
    if tp_hit:
        return float(tp), "TP"
    return None


def _resolve_exit(position, current_price, current_bar, config):
    intrabar_exit = _intrabar_exit(position, current_bar, config)
    if intrabar_exit is not None:
        return intrabar_exit
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


def _resolve_strategy_exit(
    position,
    current_price,
    config,
    current_index,
    window,
    strategy,
    current_bar,
    state,
    *,
    defer_trailing_exit=False,
):
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
        diagnostics=state.get("_diagnostics"),
    )
    trail = strategy.resolve_stop_target(
        position,
        context,
    )
    if trail and trail.get("should_update") and trail.get("sl") is not None:
        if trail.get("source") == "dynamic_stage":
            position["sl"] = trail["sl"]
        else:
            next_stop = float(trail["sl"])
            previous_stop = position.get("atr_trailing_stop")
            if defer_trailing_exit and previous_stop is not None:
                if position.get("direction") == "short":
                    next_stop = min(float(previous_stop), next_stop)
                else:
                    next_stop = max(float(previous_stop), next_stop)
            position["atr_trailing_stop"] = next_stop
        dynamic_target = trail.get("dynamic_target") or {}
        if dynamic_target.get("stage") is not None:
            position["sl_stage"] = dynamic_target.get("stage")
    evaluation = strategy.evaluate_open_position(position, context)
    adjustment = evaluation.get("position_adjustment")
    if adjustment and adjustment.get("action") == "reduce":
        _reduce_position(
            state,
            position,
            current_price,
            adjustment,
            exit_time=str(current_bar.get("time") or current_bar.get("timestamp") or current_bar.get("date") or ""),
        )
    if evaluation.get("exit_reason") and not (
        defer_trailing_exit and evaluation.get("exit_reason") in ("ATR_TRAIL", "SL")
    ):
        return current_price, evaluation["exit_reason"]
    return None


def _update_trade_excursions(position, current_bar):
    entry = float(position.get("entry") or 0.0)
    if entry <= 0:
        return
    high = float(current_bar.get("high", current_bar.get("close", entry)))
    low = float(current_bar.get("low", current_bar.get("close", entry)))
    if position.get("direction") == "long":
        position["max_favorable_price"] = max(float(position.get("max_favorable_price") or entry), high)
        position["max_adverse_price"] = min(float(position.get("max_adverse_price") or entry), low)
    else:
        position["max_favorable_price"] = min(float(position.get("max_favorable_price") or entry), low)
        position["max_adverse_price"] = max(float(position.get("max_adverse_price") or entry), high)


class BacktestEngine:
    def __init__(self, *, config: BacktestConfig, strategy: BacktestStrategy):
        self.config = config
        self.strategy = strategy

    def replay_hourly_exits(self, coin, hourly_bars, state, *, mode="strict"):
        open_positions = state.setdefault("positions", [])
        position = next((item for item in open_positions if item.get("coin") == coin), None)
        if position is None:
            return None
        diagnostics = state.setdefault("_diagnostics", {})
        for bar in hourly_bars:
            _update_trade_excursions(position, bar)
            stop_price = effective_stop(position)
            fill = resolve_hourly_stop_fill(position, bar, mode=mode)
            if fill is None:
                continue
            event = {
                "coin": coin,
                "direction": position.get("direction"),
                "stop_source": fill["reason"],
                "stop_price": stop_price,
                "fill_price": fill["price"],
                "fill_type": fill["fill_type"],
                "open_time": bar.get("open_time"),
                "initial_risk": position.get("initial_risk"),
                "entry": position.get("entry"),
                "entry_atr": position.get("entry_atr"),
            }
            diagnostics.setdefault("exit_replay_events", []).append(event)
            _close_position(
                state,
                position,
                fill["price"],
                fill["reason"],
                exit_time=str(bar.get("time") or bar.get("open_time") or ""),
            )
            open_positions.remove(position)
            key = f"exit_replay_{fill['fill_type']}_fills"
            diagnostics[key] = int(diagnostics.get(key) or 0) + 1
            return fill
        return None

    def step(self, coin, current_bar, window, btc_window, state, *, defer_stop_exits=False):
        open_positions = state.setdefault("positions", [])
        state["_bar_index"] = len(window) - 1
        current_price = float(current_bar["close"])
        active_position = next((pos for pos in open_positions if pos.get("coin") == coin), None)

        if active_position is not None:
            _update_trade_excursions(active_position, current_bar)
            resolved_exit = None
            if not defer_stop_exits:
                resolved_exit = _resolve_exit(active_position, current_price, current_bar, self.config)
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
                    defer_trailing_exit=defer_stop_exits,
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
            diagnostics=state.get("_diagnostics"),
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
