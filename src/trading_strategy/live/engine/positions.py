from datetime import datetime, timedelta

from trading_strategy.core.trade_history import apply_closed_trade

from .. import config
from ..io import record_trade_event
from ..orders import close_hl_position
from .helpers import check_trend_reversal
from .reconcile import sync_state_with_exchange_positions


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
            should_close = (
                check_trend_reversal(pos, data_cache.get(pos["coin"]))
                if pos["coin"] in data_cache
                else False
            )
            exit_reason = None
            if not should_close:
                try:
                    should_close = datetime.now() - datetime.fromisoformat(
                        pos["entry_time"]
                    ) > timedelta(days=config.STRATEGY["max_hold_days"])
                    if should_close:
                        exit_reason = "TIME"
                except Exception:
                    should_close = False
            elif should_close:
                exit_reason = "REVERSAL"
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
        should_close = (
            (current >= pos["tp"] or current <= pos["sl"])
            if pos["direction"] == "long"
            else (current <= pos["tp"] or current >= pos["sl"])
        )
        if should_close:
            exit_reason = (
                "TP"
                if (pos["direction"] == "long" and current >= pos["tp"])
                or (pos["direction"] == "short" and current <= pos["tp"])
                else "SL"
            )
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
