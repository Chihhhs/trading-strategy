from datetime import datetime

from trading_strategy.core.exit_policy import build_exit_policy

from .. import config
from ..io import record_trade_event
from ..orders import cancel_hl_order, place_hl_sl_order, place_hl_tpsl_orders
from .helpers import _safe_float, compute_dynamic_sl_target, ensure_position_targets
from .reconcile import extract_open_order_map, match_existing_protection_order


def submit_position_protection(pos, tp, sl):
    exit_policy = build_exit_policy(position=pos)
    if exit_policy.get("requires_tp"):
        return place_hl_tpsl_orders(pos["coin"], pos["direction"], pos["size"], tp, sl)
    return place_hl_sl_order(pos["coin"], pos["direction"], pos["size"], sl)


def cancel_orphan_orders(state):
    orphan_orders = list(state.get("_orphan_orders") or [])
    summary = {
        "orphan_orders_detected_count": len(orphan_orders),
        "orphan_orders_canceled_count": 0,
        "orphan_order_cancel_failures": 0,
    }
    if not orphan_orders:
        return summary
    canceled_oids = set()
    for order in orphan_orders:
        oid = order.get("oid")
        coin = order.get("coin")
        record_trade_event(
            "orphan_order_cancel_attempted",
            oid=oid,
            coin=coin,
            order_role=order.get("order_role"),
        )
        result = cancel_hl_order(coin, oid)
        if result.get("status") == "ok":
            canceled_oids.add(oid)
            summary["orphan_orders_canceled_count"] += 1
            record_trade_event(
                "orphan_order_canceled",
                oid=oid,
                coin=coin,
                message=result.get("message"),
            )
        else:
            summary["orphan_order_cancel_failures"] += 1
            record_trade_event(
                "orphan_order_cancel_failed",
                oid=oid,
                coin=coin,
                message=result.get("message"),
            )
    if canceled_oids:
        state["managed_orders"] = [
            order for order in (state.get("managed_orders") or []) if order.get("oid") not in canceled_oids
        ]
        state["_frontend_open_orders"] = [
            order
            for order in (state.get("_frontend_open_orders") or [])
            if order.get("oid") not in canceled_oids
        ]
        state["_orphan_orders"] = [
            order for order in orphan_orders if order.get("oid") not in canceled_oids
        ]
        state["_exchange_open_orders_count"] = len(state.get("managed_orders") or [])
    return summary


def _extract_order_trigger_px(order):
    return _safe_float((order or {}).get("trigger_px") or (order or {}).get("triggerPx"), default=None)


def should_replace_sl_order(pos, current_order, desired_sl):
    current_trigger = _extract_order_trigger_px(current_order)
    if current_trigger is None or desired_sl is None:
        return False
    if pos.get("direction") == "long":
        return desired_sl > current_trigger
    return desired_sl < current_trigger


def replace_sl_order(pos, desired_sl):
    current_order = pos.get("sl_order") or {}
    oid = current_order.get("oid")
    coin = pos.get("coin")
    record_trade_event(
        "sl_replace_attempted",
        coin=coin,
        oid=oid,
        previous_trigger_px=_extract_order_trigger_px(current_order),
        new_trigger_px=desired_sl,
    )
    cancel_result = cancel_hl_order(coin, oid)
    if cancel_result.get("status") != "ok":
        record_trade_event(
            "sl_replace_failed",
            coin=coin,
            oid=oid,
            message=cancel_result.get("message"),
        )
        return {"ok": False, "message": cancel_result.get("message"), "cancel_result": cancel_result}
    replacement = place_hl_sl_order(coin, pos["direction"], pos["size"], desired_sl)
    if replacement.get("ok"):
        pos["sl"] = desired_sl
        pos["sl_order"] = replacement.get("sl_order")
        record_trade_event(
            "sl_replaced",
            coin=coin,
            canceled_oid=oid,
            new_oid=((replacement.get("sl_order") or {}).get("oid")),
            new_trigger_px=desired_sl,
        )
        return {"ok": True, "replacement": replacement}
    record_trade_event(
        "sl_replace_failed",
        coin=coin,
        oid=oid,
        message=replacement.get("message"),
    )
    return {"ok": False, "message": replacement.get("message"), "replacement": replacement}


def build_protection_event_context(repaired):
    tp_order = (repaired or {}).get("tp_order") or {}
    sl_order = (repaired or {}).get("sl_order") or {}
    return {
        "order_side": (repaired or {}).get("order_side"),
        "price_source": (repaired or {}).get("price_source"),
        "tp_requested_trigger_px": tp_order.get("requested_trigger_px"),
        "tp_trigger_px": tp_order.get("trigger_px"),
        "tp_requested_limit_px": tp_order.get("requested_limit_px"),
        "tp_limit_px": tp_order.get("limit_px"),
        "tp_tick_size": tp_order.get("tick_size"),
        "tp_rejection_reason": tp_order.get("rejection_reason"),
        "sl_requested_trigger_px": sl_order.get("requested_trigger_px"),
        "sl_trigger_px": sl_order.get("trigger_px"),
        "sl_requested_limit_px": sl_order.get("requested_limit_px"),
        "sl_limit_px": sl_order.get("limit_px"),
        "sl_tick_size": sl_order.get("tick_size"),
        "sl_rejection_reason": sl_order.get("rejection_reason"),
    }


def ensure_position_protection(state):
    open_orders = extract_open_order_map(state.get("_frontend_open_orders") or [])
    summary = {
        "adopted_positions_count": len(state.get("_adopted_positions") or []),
        "exchange_open_orders_count": state.get("_exchange_open_orders_count", 0),
        "managed_orders_count": len(state.get("managed_orders") or []),
        "protection_missing_count": 0,
        "tpsl_missing_count": 0,
        "protection_repaired_count": 0,
        "tpsl_repaired_count": 0,
        "sl_replaced_count": 0,
        "unprotected_positions_count": 0,
    }
    for pos in state.get("positions", []):
        exit_policy = build_exit_policy(position=pos)
        prefix = exit_policy.get("protection_event_prefix", "tpsl")
        tp_open = match_existing_protection_order(pos, open_orders, "tp")
        sl_open = match_existing_protection_order(pos, open_orders, "sl")
        pos["tp_order"] = tp_open if tp_open else pos.get("tp_order")
        pos["sl_order"] = sl_open if sl_open else pos.get("sl_order")
        tp, sl = ensure_position_targets(pos, state.setdefault("_data_cache", {}))
        dynamic_target = compute_dynamic_sl_target(pos)
        if dynamic_target and dynamic_target.get("sl") is not None:
            sl = dynamic_target.get("sl")
        if exit_policy.get("name") == "trend_sl_only" and sl_open and should_replace_sl_order(pos, sl_open, sl):
            replaced = replace_sl_order(pos, sl)
            if replaced.get("ok"):
                summary["sl_replaced_count"] += 1
                pos["sl_stage"] = dynamic_target.get("stage") if dynamic_target else pos.get("sl_stage")
                pos["protection_status"] = "protected"
                continue
            pos["protection_status"] = "update_failed"
            summary["unprotected_positions_count"] += 1
            continue
        is_protected = bool(sl_open) and (not exit_policy.get("requires_tp") or bool(tp_open))
        if is_protected:
            pos["protection_status"] = "protected"
            continue
        missing_status = "missing_tpsl" if exit_policy.get("requires_tp") else "missing_sl"
        summary["protection_missing_count"] += 1
        summary["tpsl_missing_count"] += 1
        pos["protection_status"] = missing_status
        record_trade_event(
            f"{prefix}_missing_detected",
            coin=pos.get("coin"),
            tp_present=bool(tp_open),
            sl_present=bool(sl_open),
            tp=tp,
            sl=sl,
            position_source=pos.get("position_source"),
        )
        repaired = submit_position_protection(pos, tp, sl)
        protection_context = build_protection_event_context(repaired)
        record_trade_event(
            f"{prefix}_repair_attempted",
            coin=pos.get("coin"),
            size=pos.get("size"),
            direction=pos.get("direction"),
            tp=tp,
            sl=sl,
            **protection_context,
        )
        if repaired.get("ok"):
            pos["sl"] = sl
            if dynamic_target:
                pos["sl_stage"] = dynamic_target.get("stage")
            pos["tp_order"] = repaired.get("tp_order")
            pos["sl_order"] = repaired.get("sl_order")
            pos["protection_status"] = "protected"
            summary["protection_repaired_count"] += 1
            summary["tpsl_repaired_count"] += 1
            record_trade_event(
                f"{prefix}_repaired",
                coin=pos.get("coin"),
                tp_order=repaired.get("tp_order"),
                sl_order=repaired.get("sl_order"),
                **protection_context,
            )
        else:
            pos["tp_order"] = repaired.get("tp_order")
            pos["sl_order"] = repaired.get("sl_order")
            pos["protection_status"] = "repair_failed"
            summary["unprotected_positions_count"] += 1
            record_trade_event(
                f"{prefix}_repair_failed",
                coin=pos.get("coin"),
                tp_order=repaired.get("tp_order"),
                sl_order=repaired.get("sl_order"),
                message=repaired.get("message"),
                **protection_context,
            )
    return summary
