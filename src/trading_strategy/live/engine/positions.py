from datetime import datetime, timedelta

from trading_strategy.shared.trade_history import apply_closed_trade
from trading_strategy.strategies import build_exit_policy

from .. import config
from ..io import record_trade_event
from ..orders import close_hl_position
from .helpers import evaluate_open_position, prepare_position_klines
from .reconcile import sync_state_with_exchange_positions


def _paper_exit_triggered(pos, current):
    exit_policy = build_exit_policy(position=pos)
    tp = pos.get("tp")
    sl = pos.get("sl")
    direction = pos.get("direction")
    requires_tp = exit_policy.get("requires_tp")
    tp_enabled = tp is not None if requires_tp is None else (bool(requires_tp) and tp is not None)

    tp_hit = False
    sl_hit = False
    if direction == "long":
        tp_hit = tp_enabled and current >= tp
        sl_hit = sl is not None and current <= sl
    else:
        tp_hit = tp_enabled and current <= tp
        sl_hit = sl is not None and current >= sl
    return tp_hit, sl_hit


def _reduction_size(pos, adjustment):
    size = float(pos.get("size") or 0.0)
    fraction = float((adjustment or {}).get("fraction") or 0.0)
    fraction = min(max(fraction, 0.0), 1.0)
    reduce_size = size * fraction
    if size <= 0 or reduce_size <= 0 or reduce_size >= size:
        return 0.0
    return reduce_size


def _mark_reduction_applied(pos, adjustment):
    reduction_key = (adjustment or {}).get("reduction_key")
    if not reduction_key:
        return
    reductions = list(pos.get("derivatives_crowding_reductions") or [])
    if reduction_key not in reductions:
        reductions.append(reduction_key)
    pos["derivatives_crowding_reductions"] = reductions


def _paper_reduce_position(state, pos, current, adjustment):
    reduce_size = _reduction_size(pos, adjustment)
    if reduce_size <= 0:
        return False
    reduced_pos = dict(pos)
    reduced_pos["size"] = reduce_size
    reason = (adjustment or {}).get("reason") or "POSITION_REDUCE"
    apply_closed_trade(
        state,
        reduced_pos,
        current,
        reason,
        exit_context={
            "close_status": "paper_reduced",
            "close_reason_source": "strategy_adjustment",
        },
    )
    pos["size"] = round(float(pos.get("size") or 0.0) - reduce_size, 12)
    _mark_reduction_applied(pos, adjustment)
    return True


def _submit_live_reduce(pos, adjustment):
    reduce_size = _reduction_size(pos, adjustment)
    if reduce_size <= 0:
        return False
    reduced_pos = dict(pos)
    reduced_pos["size"] = reduce_size
    reason = (adjustment or {}).get("reason") or "POSITION_REDUCE"
    result = close_hl_position(reduced_pos, reason)
    if result.get("status") != "ok":
        record_trade_event(
            "position_reduce_failed",
            coin=pos["coin"],
            exit_reason=reason,
            reduce_size=reduce_size,
            message=result.get("message"),
        )
        return False
    pos["reduce_pending"] = True
    pos["pending_reduce_reason"] = reason
    pos["pending_reduce_size"] = reduce_size
    pos["reduce_submitted_at"] = datetime.now().isoformat()
    pos["reduce_order_summary"] = result.get("order_summary")
    pos["reduce_verify_summary"] = result.get("verified_summary")
    _mark_reduction_applied(pos, adjustment)
    record_trade_event(
        "position_reduce_submitted",
        coin=pos["coin"],
        exit_reason=reason,
        reduce_size=reduce_size,
        remaining_size=max(float(pos.get("size") or 0.0) - reduce_size, 0.0),
        bars_since_entry=pos.get("bars_since_entry"),
        order_status=((result.get("order_summary") or {}).get("order_status")),
        verify_status=((result.get("verified_summary") or {}).get("verify_status")),
    )
    return True


def _evaluate_position_exit(pos, klines):
    evaluation = evaluate_open_position(pos, klines) if klines else {}
    atr_trail_result = evaluation.get("atr_trail_result") or {"triggered": False}
    failure_exit = evaluation.get("failure_exit") or {"triggered": False}
    reversal_close = bool(evaluation.get("reversal_detected"))
    exit_reason = None
    should_close = False
    if reversal_close:
        should_close = True
        exit_reason = "REVERSAL"
    elif atr_trail_result.get("triggered"):
        should_close = True
        exit_reason = "ATR_TRAIL"
    elif failure_exit.get("triggered"):
        should_close = True
        exit_reason = "FAILURE"
    elif evaluation.get("exit_reason") == "DERIVATIVES_CROWDING":
        should_close = True
        exit_reason = "DERIVATIVES_CROWDING"
    return should_close, exit_reason, evaluation


def update_positions(state, prices, data_cache):
    if config.MODE == "live":
        if not state.get("_reconciled_at"):
            state = sync_state_with_exchange_positions(state)
        still_open = []
        for pos in state["positions"]:
            if pos.get("close_pending"):
                still_open.append(pos)
                continue
            if pos["coin"] in prices:
                pos["current_price"] = prices[pos["coin"]]
                pos["pnl_pnl"] = (
                    (prices[pos["coin"]] - pos["entry"]) * pos["size"]
                    if pos["direction"] == "long"
                    else (pos["entry"] - prices[pos["coin"]]) * pos["size"]
                )
            klines = prepare_position_klines(pos, data_cache.get(pos["coin"]))
            if pos.get("entry_klines_len") and klines:
                pos["bars_since_entry"] = max(len(klines) - int(pos.get("entry_klines_len") or 0), 0)
            should_close, exit_reason, evaluation = _evaluate_position_exit(pos, klines)
            if not should_close:
                try:
                    should_close = datetime.now() - datetime.fromisoformat(
                        pos["entry_time"]
                    ) > timedelta(days=config.STRATEGY["max_hold_days"])
                    if should_close:
                        exit_reason = "TIME"
                except Exception:
                    should_close = False
            if should_close:
                exit_reason = exit_reason or "REVERSAL"
                result = close_hl_position(pos, exit_reason)
                if result.get("status") == "ok":
                    pos["close_pending"] = True
                    pos["pending_exit_reason"] = exit_reason
                    pos["close_submitted_at"] = datetime.now().isoformat()
                    pos["close_order_summary"] = result.get("order_summary")
                    pos["close_verify_summary"] = result.get("verified_summary")
                    record_trade_event(
                        "position_close_submitted",
                        coin=pos["coin"],
                        exit_reason=exit_reason,
                        bars_since_entry=pos.get("bars_since_entry"),
                        order_status=((result.get("order_summary") or {}).get("order_status")),
                        verify_status=((result.get("verified_summary") or {}).get("verify_status")),
                    )
                    still_open.append(pos)
                    continue
            adjustment = evaluation.get("position_adjustment") if klines else None
            if adjustment and not pos.get("reduce_pending"):
                _submit_live_reduce(pos, adjustment)
            still_open.append(pos)
        state["positions"] = still_open
        return

    still_open = []
    for pos in state["positions"]:
        current = prices.get(pos["coin"])
        if current is None:
            still_open.append(pos)
            continue
        pos["current_price"] = current
        pos["pnl_pnl"] = (
            (current - pos["entry"]) * pos["size"]
            if pos["direction"] == "long"
            else (pos["entry"] - current) * pos["size"]
        )
        klines = prepare_position_klines(pos, data_cache.get(pos["coin"]))
        if klines:
            should_close, exit_reason, evaluation = _evaluate_position_exit(pos, klines)
            if should_close:
                apply_closed_trade(
                    state,
                    pos,
                    current,
                    exit_reason or "STRATEGY_EXIT",
                    exit_context={
                        "close_status": "paper_closed",
                        "close_reason_source": "strategy_exit",
                    },
                )
                continue
            if evaluation.get("position_adjustment"):
                _paper_reduce_position(state, pos, current, evaluation["position_adjustment"])
        tp_hit, sl_hit = _paper_exit_triggered(pos, current)
        if tp_hit or sl_hit:
            exit_reason = "TP" if tp_hit else "SL"
            apply_closed_trade(
                state,
                pos,
                current,
                exit_reason,
                exit_context={
                    "close_status": "paper_closed",
                    "close_reason_source": "price_rule",
                },
            )
        else:
            still_open.append(pos)
    state["positions"] = still_open
