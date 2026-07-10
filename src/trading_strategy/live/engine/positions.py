from datetime import datetime, timedelta

from trading_strategy.core.trade_history import apply_closed_trade
from trading_strategy.strategies import build_exit_policy

from .. import config
from ..io import record_trade_event
from ..orders import close_hl_position
from .helpers import check_atr_trailing_exit, check_trend_failure_exit, check_trend_reversal
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
            klines = data_cache.get(pos["coin"])
            if pos.get("entry_klines_len") and klines:
                pos["bars_since_entry"] = max(len(klines) - int(pos.get("entry_klines_len") or 0), 0)
            atr_trail_result = check_atr_trailing_exit(pos, klines) if klines else {"triggered": False}
            failure_exit = check_trend_failure_exit(pos, klines) if klines else {"triggered": False}
            reversal_close = (
                check_trend_reversal(pos, data_cache.get(pos["coin"]))
                if klines
                else False
            )
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
