from collections import Counter


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def resolve_position_lifecycle_status(position, *, mode="paper"):
    if (position or {}).get("close_pending"):
        return "close_pending"

    protection_status = str((position or {}).get("protection_status") or "")
    if mode == "live":
        if protection_status in {"missing_tpsl", "missing_sl", "repair_failed", "update_failed"}:
            return "open_unprotected"
        if protection_status == "protected":
            return "open_protected"
    return "open"


def build_position_snapshot(position, *, mode="paper"):
    pos = dict(position or {})
    entry = _safe_float(pos.get("entry"), default=None)
    current_price = _safe_float(pos.get("current_price"), default=None)
    size = _safe_float(pos.get("size"), default=None)
    direction = pos.get("direction")

    pnl = None
    pnl_source = "calculated"
    exchange_pnl = _safe_float(pos.get("exchange_unrealized_pnl"), default=None)
    if exchange_pnl is not None:
        pnl = exchange_pnl
        pnl_source = "exchange"
    if entry is not None and current_price is not None and size is not None:
        if exchange_pnl is None:
            pnl = (current_price - entry) * size if direction == "long" else (entry - current_price) * size

    pnl_pct = None
    notional = abs(entry * size) if entry is not None and size is not None else None
    if pnl is not None and notional:
        pnl_pct = round((pnl / notional) * 100, 4)

    return {
        "coin": pos.get("coin"),
        "direction": direction,
        "size": size,
        "entry": entry,
        "current_price": current_price,
        "pnl": round(pnl, 4) if pnl is not None else None,
        "pnl_pct": pnl_pct,
        "pnl_source": pnl_source if pnl is not None else None,
        "lifecycle_status": resolve_position_lifecycle_status(pos, mode=mode),
        "pending_exit_reason": pos.get("pending_exit_reason"),
        "protection_status": pos.get("protection_status"),
        "exit_policy": ((pos.get("exit_policy") or {}).get("name")),
        "strategy_name": pos.get("strategy_name"),
        "position_source": pos.get("position_source"),
        "entry_reason": pos.get("entry_reason") or pos.get("signal_reason") or pos.get("sig"),
        "signal_score": pos.get("signal_score"),
        "tp": _safe_float(pos.get("tp"), default=None),
        "sl": _safe_float(pos.get("sl"), default=None),
        "entry_status": pos.get("entry_status"),
        "entry_oid": pos.get("entry_oid"),
        "tp_order_oid": ((pos.get("tp_order") or {}).get("oid")),
        "sl_order_oid": ((pos.get("sl_order") or {}).get("oid")),
        "bars_since_entry": pos.get("bars_since_entry"),
        "sl_stage": pos.get("sl_stage"),
        "best_price": _safe_float(pos.get("best_price"), default=None),
    }


def build_position_snapshots(positions, *, mode="paper"):
    return [build_position_snapshot(position, mode=mode) for position in positions or []]


def build_position_status_counts(positions, *, mode="paper"):
    counts = Counter()
    for snapshot in build_position_snapshots(positions, mode=mode):
        counts[snapshot["lifecycle_status"]] += 1
    return dict(counts)
