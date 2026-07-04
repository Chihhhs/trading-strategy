from datetime import datetime

from trading_strategy.core.exit_policy import build_exit_policy

from .. import config
from ..account import get_hl_frontend_open_orders, get_hl_perp_user_state
from ..io import record_trade_event
from ..orders import get_position_entry_oid
from .helpers import _safe_float


def extract_open_order_map(frontend_open_orders):
    order_map = {}
    for order in frontend_open_orders or []:
        if isinstance(order, dict) and order.get("oid") is not None:
            order_map[int(order["oid"])] = order
        for child in (order.get("children") or []) if isinstance(order, dict) else []:
            if isinstance(child, dict) and child.get("oid") is not None:
                order_map[int(child["oid"])] = child
    return order_map


def extract_live_position_map(perp_state):
    positions = {}
    for item in (perp_state or {}).get("assetPositions") or []:
        position = (item or {}).get("position") or {}
        if position.get("coin"):
            positions[position["coin"]] = position
    return positions


def build_position_from_exchange(coin, position_state, existing=None):
    existing = dict(existing or {})
    exit_policy = build_exit_policy(position=existing)
    size = abs(_safe_float(position_state.get("szi")))
    direction = "long" if _safe_float(position_state.get("szi")) >= 0 else "short"
    entry = _safe_float(position_state.get("entryPx"))
    adopted_at = datetime.now().isoformat()
    default_protection_status = "missing_tpsl" if exit_policy.get("requires_tp") else "missing_sl"
    return {
        **existing,
        "coin": coin,
        "direction": existing.get("direction") or direction,
        "entry": existing.get("entry") or entry,
        "size": existing.get("size") or size,
        "current_price": existing.get("current_price", entry),
        "pnl_pnl": existing.get("pnl_pnl", 0),
        "entry_time": existing.get("entry_time") or adopted_at,
        "entry_time_source": existing.get("entry_time_source") or ("local_state" if existing else "exchange_adopted"),
        "position_source": existing.get("position_source") or ("local_state" if existing else "exchange_adopted"),
        "adopted_at": existing.get("adopted_at") or (adopted_at if not existing else None),
        "protection_status": existing.get("protection_status", default_protection_status),
        "exit_policy": existing.get("exit_policy") or exit_policy,
        "initial_risk": existing.get("initial_risk"),
        "sl_stage": existing.get("sl_stage"),
        "best_price": existing.get("best_price"),
        "exchange_position_state": {
            "coin": coin,
            "entryPx": position_state.get("entryPx"),
            "szi": position_state.get("szi"),
        },
    }


def normalize_managed_order(order, *, order_role, adopted_at=None, status="open", source="exchange"):
    order = dict(order or {})
    return {
        "oid": order.get("oid"),
        "coin": order.get("coin"),
        "reduce_only": bool(order.get("reduceOnly")),
        "tpsl": str(order.get("tpsl") or "").lower() or None,
        "side": order.get("side"),
        "size": _safe_float(order.get("sz") or order.get("size") or order.get("origSz")),
        "trigger_px": _safe_float(order.get("triggerPx") or order.get("trigger_px")),
        "limit_px": _safe_float(order.get("limitPx") or order.get("limit_px") or order.get("limitPxRaw")),
        "status": status,
        "source": source,
        "adopted_at": adopted_at or datetime.now().isoformat(),
        "order_role": order_role,
        "raw_order": order,
    }


def _position_by_coin(positions):
    return {pos.get("coin"): pos for pos in positions if pos.get("coin")}


def _protection_order_oid(pos, tpsl_kind):
    order_ref = (pos or {}).get(f"{tpsl_kind}_order") or {}
    oid = order_ref.get("oid")
    return int(oid) if oid is not None else None


def _extract_order_trigger_px(order):
    return _safe_float((order or {}).get("trigger_px") or (order or {}).get("triggerPx"), default=None)


def _order_trigger_matches(order, candidate_order, fallback_target=None):
    order_trigger = _extract_order_trigger_px(order)
    candidate_trigger = _extract_order_trigger_px(candidate_order)
    if order_trigger is None:
        return False
    for target in (
        candidate_trigger,
        _safe_float((candidate_order or {}).get("requested_trigger_px"), default=None),
        fallback_target,
    ):
        if target is None:
            continue
        tolerance = max(abs(float(target)) * 0.0005, 1e-9)
        if abs(order_trigger - float(target)) <= tolerance:
            return True
    return False


def _infer_reduce_only_protection_role(order, positions_by_coin):
    coin = str(order.get("coin") or "")
    pos = positions_by_coin.get(coin)
    if pos is None or not order.get("reduceOnly"):
        return (None, None, False)
    oid = order.get("oid")
    if oid is not None:
        oid = int(oid)
        if _protection_order_oid(pos, "sl") == oid:
            return ("protection_sl", pos, False)
        if _protection_order_oid(pos, "tp") == oid:
            return ("protection_tp", pos, False)
    if _order_trigger_matches(order, pos.get("sl_order"), pos.get("sl")):
        return ("protection_sl", pos, False)
    if _order_trigger_matches(order, pos.get("tp_order"), pos.get("tp")):
        return ("protection_tp", pos, False)
    exit_policy = build_exit_policy(position=pos)
    if exit_policy.get("name") == "trend_sl_only" and _extract_order_trigger_px(order) is not None:
        return ("protection_sl", pos, False)
    return (None, pos, True)


def classify_exchange_order(order, positions_by_coin, pending_positions_by_oid):
    coin = str(order.get("coin") or "")
    reduce_only = bool(order.get("reduceOnly"))
    tpsl = str(order.get("tpsl") or "").lower()
    if reduce_only and tpsl == "sl":
        pos = positions_by_coin.get(coin)
        return ("protection_sl", pos, pos is None)
    if reduce_only and tpsl == "tp":
        pos = positions_by_coin.get(coin)
        return ("protection_tp", pos, pos is None)
    inferred_role, inferred_pos, inferred_orphan = _infer_reduce_only_protection_role(order, positions_by_coin)
    if inferred_role is not None:
        return (inferred_role, inferred_pos, inferred_orphan)
    oid = order.get("oid")
    if oid is not None and pending_positions_by_oid.get(int(oid)):
        return ("entry_pending", pending_positions_by_oid[int(oid)], False)
    return ("orphan_unknown", None, True)


def _is_pending_entry_order(pos, open_orders):
    entry_oid = get_position_entry_oid(pos)
    if entry_oid is None:
        return False
    order = open_orders.get(int(entry_oid))
    return bool(order) and not order.get("reduceOnly")


def match_existing_protection_order(pos, open_orders, tpsl_kind):
    local_order = pos.get(f"{tpsl_kind}_order") or {}
    oid = local_order.get("oid")
    if oid is not None and open_orders.get(int(oid)):
        return open_orders[int(oid)]
    for order in open_orders.values():
        if not isinstance(order, dict):
            continue
        if str(order.get("coin") or "") != str(pos.get("coin")):
            continue
        if not order.get("reduceOnly"):
            continue
        order_tpsl = str(order.get("tpsl") or "").lower()
        if order_tpsl == tpsl_kind:
            return order
        fallback_target = pos.get(tpsl_kind)
        if _order_trigger_matches(order, local_order, fallback_target):
            return order
    return None


def reconcile_exchange_state(state, perp_state=None, frontend_open_orders=None):
    if config.MODE != "live":
        return state
    perp_state = perp_state if perp_state is not None else get_hl_perp_user_state()
    frontend_open_orders = (
        frontend_open_orders if frontend_open_orders is not None else get_hl_frontend_open_orders()
    )
    live_positions = extract_live_position_map(perp_state)
    open_orders = extract_open_order_map(frontend_open_orders)
    original_positions = list(state.get("positions", []))
    original_by_coin = {pos.get("coin"): pos for pos in original_positions if pos.get("coin")}
    adopted_positions = []
    synced_positions = []
    for coin, position_state in live_positions.items():
        existing = original_by_coin.pop(coin, None)
        synced = build_position_from_exchange(coin, position_state, existing)
        if existing is None:
            adopted_positions.append(coin)
            record_trade_event(
                "untracked_exchange_position_detected",
                coin=coin,
                exchange_position_state=synced.get("exchange_position_state"),
            )
            record_trade_event(
                "position_adopted",
                coin=coin,
                entry=synced.get("entry"),
                size=synced.get("size"),
                direction=synced.get("direction"),
                adopted_at=synced.get("adopted_at"),
            )
        synced_positions.append(synced)
    pending_local_positions = [
        pos for pos in original_by_coin.values() if _is_pending_entry_order(pos, open_orders)
    ]
    stale_positions = [
        pos.get("coin")
        for pos in original_by_coin.values()
        if not _is_pending_entry_order(pos, open_orders)
    ]
    reconciled_positions = synced_positions + pending_local_positions
    positions_by_coin = _position_by_coin(reconciled_positions)
    pending_positions_by_oid = {
        int(get_position_entry_oid(pos)): pos
        for pos in pending_local_positions
        if get_position_entry_oid(pos) is not None
    }

    managed_orders = []
    orphan_orders = []
    for order in frontend_open_orders or []:
        order_role, pos, is_orphan = classify_exchange_order(order, positions_by_coin, pending_positions_by_oid)
        normalized = normalize_managed_order(order, order_role=order_role)
        managed_orders.append(normalized)
        if pos is not None:
            if order_role == "protection_tp":
                pos["tp_order"] = normalized
            elif order_role == "protection_sl":
                pos["sl_order"] = normalized
        if is_orphan:
            orphan_orders.append(normalized)
            record_trade_event(
                "orphan_order_detected",
                oid=normalized.get("oid"),
                coin=normalized.get("coin"),
                order_role=normalized.get("order_role"),
            )

    for pos in reconciled_positions:
        exit_policy = build_exit_policy(position=pos)
        if exit_policy.get("name") == "trend_sl_only" and pos.get("sl_order") and not pos.get("sig"):
            pos["exit_policy"] = {
                "name": "trend_sl_only",
                "requires_tp": False,
                "requires_sl": True,
                "protection_event_prefix": "sl",
            }
        elif pos.get("sl_order") and pos.get("tp_order") and not pos.get("sig"):
            pos["exit_policy"] = {
                "name": "fixed_tpsl",
                "requires_tp": True,
                "requires_sl": True,
                "protection_event_prefix": "tpsl",
            }
    state["positions"] = reconciled_positions
    state["managed_orders"] = managed_orders
    state["_adopted_positions"] = adopted_positions
    state["_stale_positions"] = stale_positions
    state["_orphan_orders"] = orphan_orders
    state["_frontend_open_orders"] = frontend_open_orders
    state["_exchange_open_orders_count"] = len(managed_orders)
    state["_reconciled_at"] = datetime.now().isoformat()
    record_trade_event(
        "open_orders_synced",
        exchange_open_orders_count=len(managed_orders),
        managed_orders_count=len(managed_orders),
        orphan_orders_detected_count=len(orphan_orders),
    )
    if adopted_positions or stale_positions:
        record_trade_event(
            "state_exchange_mismatch",
            adopted_positions=adopted_positions,
            stale_positions=stale_positions,
        )
    return state


def sync_state_with_exchange_positions(state, perp_state=None, frontend_open_orders=None):
    return reconcile_exchange_state(state, perp_state=perp_state, frontend_open_orders=frontend_open_orders)
