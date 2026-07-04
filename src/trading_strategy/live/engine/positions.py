from datetime import datetime, timedelta

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
            if not should_close:
                try:
                    should_close = datetime.now() - datetime.fromisoformat(
                        pos["entry_time"]
                    ) > timedelta(days=config.STRATEGY["max_hold_days"])
                except Exception:
                    should_close = False
            if should_close and close_hl_position(pos, "REVERSAL").get("status") == "ok":
                record_trade_event("position_close_submitted", coin=pos["coin"])
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
            state["balance"] += pos["pnl_pnl"]
            state["stats"]["total_trades"] += 1
            state["stats"]["total_pnl"] += pos["pnl_pnl"]
            state["history"].append(
                {
                    "coin": pos["coin"],
                    "dir": pos["direction"],
                    "entry": pos["entry"],
                    "exit": current,
                    "pnl": round(pos["pnl_pnl"], 4),
                    "exit_time": datetime.now().isoformat(),
                }
            )
        else:
            still_open.append(pos)
    state["positions"] = still_open
