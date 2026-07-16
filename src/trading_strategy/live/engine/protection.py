from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from trading_strategy.strategies import build_exit_policy

from .. import config
from ..io import record_trade_event
from ..orders import cancel_hl_order, place_hl_sl_order, place_hl_tpsl_orders
from .helpers import _safe_float, compute_trend_stop_target, ensure_position_targets
from .reconcile import extract_open_order_map, match_existing_protection_order_with_meta


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


def _infer_trigger_side(direction):
    return "sell" if direction == "long" else "buy"


def _normalize_trigger_px_for_order(pos, order, trigger_px):
    trigger_px = _safe_float(trigger_px, default=None)
    tick_size = _safe_float((order or {}).get("tick_size"), default=None)
    if trigger_px is None or tick_size is None or tick_size <= 0:
        return trigger_px
    rounding = ROUND_CEILING if _infer_trigger_side(pos.get("direction")) == "buy" else ROUND_FLOOR
    normalized = (
        Decimal(str(trigger_px)) / Decimal(str(tick_size))
    ).to_integral_value(rounding=rounding) * Decimal(str(tick_size))
    return float(normalized.normalize())


def _is_more_protective_trigger(direction, desired_trigger, current_trigger):
    if desired_trigger is None or current_trigger is None:
        return False
    if direction == "long":
        return desired_trigger > current_trigger
    return desired_trigger < current_trigger


def _is_same_trigger(desired_trigger, current_trigger):
    if desired_trigger is None or current_trigger is None:
        return False
    return abs(desired_trigger - current_trigger) <= 1e-9


def evaluate_sl_replacement(pos, current_order, desired_sl, stop_target=None):
    desired_sl = _safe_float(desired_sl, default=None)
    current_trigger = _extract_order_trigger_px(current_order)
    source = (stop_target or {}).get("source")
    dynamic_target = (stop_target or {}).get("dynamic_target") or {}
    current_stage = int((pos or {}).get("sl_stage") or 0)
    desired_stage = int(dynamic_target.get("stage") or current_stage)
    normalized_trigger = _normalize_trigger_px_for_order(pos, current_order, desired_sl)

    decision = {
        "should_replace": False,
        "reason": None,
        "source": source,
        "desired_sl": desired_sl,
        "normalized_trigger_px": normalized_trigger,
        "current_trigger_px": current_trigger,
        "current_stage": current_stage,
        "desired_stage": desired_stage,
    }

    if desired_sl is None or current_trigger is None:
        return decision

    if source == "dynamic_stage" and desired_stage <= current_stage:
        decision["reason"] = "stage_not_advanced"
        return decision

    if _is_same_trigger(normalized_trigger, current_trigger):
        decision["reason"] = "normalized_trigger_unchanged"
        return decision

    if not _is_more_protective_trigger(pos.get("direction"), normalized_trigger, current_trigger):
        decision["reason"] = "not_more_protective_after_normalization"
        return decision

    decision["should_replace"] = True
    return decision


def replace_sl_order(pos, desired_sl):
    current_order = pos.get("sl_order") or {}
    oid = current_order.get("oid")
    coin = pos.get("coin")
    previous_trigger_px = _extract_order_trigger_px(current_order)
    record_trade_event(
        "sl_replace_attempted",
        coin=coin,
        oid=oid,
        previous_trigger_px=previous_trigger_px,
        desired_trigger_px=desired_sl,
        new_trigger_px=desired_sl,
    )
    cancel_result = cancel_hl_order(coin, oid)
    if cancel_result.get("status") != "ok":
        record_trade_event(
            "sl_replace_failed",
            coin=coin,
            oid=oid,
            previous_trigger_px=previous_trigger_px,
            desired_trigger_px=desired_sl,
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
        previous_trigger_px=previous_trigger_px,
        desired_trigger_px=desired_sl,
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


def build_protection_match_context(tp_match, sl_match):
    return {
        "tp_match_source": (tp_match or {}).get("match_source"),
        "sl_match_source": (sl_match or {}).get("match_source"),
        "tp_match_confidence": (tp_match or {}).get("match_confidence"),
        "sl_match_confidence": (sl_match or {}).get("match_confidence"),
        "tp_candidates": (tp_match or {}).get("candidate_count", 0),
        "sl_candidates": (sl_match or {}).get("candidate_count", 0),
        "tp_verify_status": (
            ((tp_match or {}).get("order") or {}).get("status")
            or ((tp_match or {}).get("order") or {}).get("verify_status")
        ),
        "sl_verify_status": (
            ((sl_match or {}).get("order") or {}).get("status")
            or ((sl_match or {}).get("order") or {}).get("verify_status")
        ),
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
        "protection_checked_count": 0,
        "ambiguous_protection_count": 0,
        "verification_unknown_count": 0,
        "protection_repair_failed_count": 0,
        "protection_update_failed_count": 0,
    }
    for pos in state.get("positions", []):
        summary["protection_checked_count"] += 1
        exit_policy = build_exit_policy(position=pos)
        prefix = exit_policy.get("protection_event_prefix", "tpsl")
        tp_match = match_existing_protection_order_with_meta(pos, open_orders, "tp") or {}
        sl_match = match_existing_protection_order_with_meta(pos, open_orders, "sl") or {}
        tp_open = tp_match.get("order")
        sl_open = sl_match.get("order")
        pos["tp_order"] = tp_open if tp_open else pos.get("tp_order")
        pos["sl_order"] = sl_open if sl_open else pos.get("sl_order")
        pos["protection_match_source"] = {
            "tp": tp_match.get("match_source"),
            "sl": sl_match.get("match_source"),
        }
        pos["protection_match_confidence"] = {
            "tp": tp_match.get("match_confidence"),
            "sl": sl_match.get("match_confidence"),
        }
        tp, sl = ensure_position_targets(pos, state.setdefault("_data_cache", {}))
        stop_target = compute_trend_stop_target(pos, state.setdefault("_data_cache", {}).get(pos.get("coin")))
        dynamic_target = stop_target.get("dynamic_target") if isinstance(stop_target, dict) else None
        if stop_target and stop_target.get("sl") is not None:
            sl = stop_target.get("sl")
        ambiguous = bool(tp_match.get("ambiguous") or sl_match.get("ambiguous"))
        if ambiguous:
            pos["protection_status"] = "ambiguous_protection"
            pos["protection_failure_reason"] = "multiple_matching_orders"
            summary["ambiguous_protection_count"] += 1
            summary["unprotected_positions_count"] += 1
            record_trade_event(
                f"{prefix}_ambiguous_detected",
                coin=pos.get("coin"),
                failure_reason=pos["protection_failure_reason"],
                position_source=pos.get("position_source"),
                **build_protection_match_context(tp_match, sl_match),
            )
            continue

        required_orders = [("sl", sl_open, exit_policy.get("requires_sl"))]
        if exit_policy.get("requires_tp"):
            required_orders.append(("tp", tp_open, True))
        unknown = any(
            required and order is not None and str(order.get("status") or order.get("verify_status") or "").lower()
            in {"unknown", "error", "verification_unknown"}
            for _, order, required in required_orders
        )
        if unknown:
            pos["protection_status"] = "verification_unknown"
            pos["protection_failure_reason"] = "order_status_unknown"
            summary["verification_unknown_count"] += 1
            summary["unprotected_positions_count"] += 1
            record_trade_event(
                f"{prefix}_verification_unknown",
                coin=pos.get("coin"),
                failure_reason=pos["protection_failure_reason"],
                tp_present=bool(tp_open),
                sl_present=bool(sl_open),
                position_source=pos.get("position_source"),
                **build_protection_match_context(tp_match, sl_match),
            )
            continue
        if exit_policy.get("name") == "trend_sl_only" and sl_open:
            replacement_decision = evaluate_sl_replacement(pos, sl_open, sl, stop_target)
            if replacement_decision.get("should_replace"):
                replaced = replace_sl_order(pos, sl)
                if replaced.get("ok"):
                    summary["sl_replaced_count"] += 1
                    pos["sl_stage"] = dynamic_target.get("stage") if dynamic_target else pos.get("sl_stage")
                    pos["protection_status"] = "protected"
                    continue
                pos["protection_status"] = "update_failed"
                pos["protection_failure_reason"] = "sl_replace_failed"
                summary["unprotected_positions_count"] += 1
                summary["protection_update_failed_count"] += 1
                continue
            if replacement_decision.get("reason") and replacement_decision.get("source") in ("dynamic_stage", "atr_trail"):
                record_trade_event(
                    "sl_replace_skipped",
                    coin=pos.get("coin"),
                    source=replacement_decision.get("source"),
                    current_trigger_px=replacement_decision.get("current_trigger_px"),
                    desired_sl=replacement_decision.get("desired_sl"),
                    normalized_trigger_px=replacement_decision.get("normalized_trigger_px"),
                    current_stage=replacement_decision.get("current_stage"),
                    desired_stage=replacement_decision.get("desired_stage"),
                    reason=replacement_decision.get("reason"),
                )
        is_protected = bool(sl_open) and (not exit_policy.get("requires_tp") or bool(tp_open))
        if is_protected:
            pos["protection_status"] = "protected"
            continue
        missing_status = "missing_tpsl" if exit_policy.get("requires_tp") else "missing_sl"
        summary["protection_missing_count"] += 1
        summary["tpsl_missing_count"] += 1
        pos["protection_status"] = missing_status
        pos["protection_failure_reason"] = None
        record_trade_event(
            f"{prefix}_missing_detected",
            coin=pos.get("coin"),
            tp_present=bool(tp_open),
            sl_present=bool(sl_open),
            tp=tp,
            sl=sl,
            position_source=pos.get("position_source"),
            **build_protection_match_context(tp_match, sl_match),
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
            **build_protection_match_context(tp_match, sl_match),
        )
        repaired_orders_identified = bool(
            (repaired.get("sl_order") or {}).get("oid")
            and (not exit_policy.get("requires_tp") or (repaired.get("tp_order") or {}).get("oid"))
        )
        if repaired.get("ok") and repaired_orders_identified:
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
                **build_protection_match_context(tp_match, sl_match),
            )
        else:
            pos["tp_order"] = repaired.get("tp_order")
            pos["sl_order"] = repaired.get("sl_order")
            pos["protection_status"] = "repair_failed"
            pos["protection_failure_reason"] = (
                repaired.get("message") or "protection_order_identity_unconfirmed"
            )
            summary["unprotected_positions_count"] += 1
            summary["protection_repair_failed_count"] += 1
            record_trade_event(
                f"{prefix}_repair_failed",
                coin=pos.get("coin"),
                tp_order=repaired.get("tp_order"),
                sl_order=repaired.get("sl_order"),
                message=repaired.get("message"),
                **protection_context,
                **build_protection_match_context(tp_match, sl_match),
            )
    return summary
