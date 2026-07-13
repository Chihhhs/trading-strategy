from datetime import datetime, timezone


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def build_trade_record(pos, exit_price, exit_reason, *, exit_time=None, exit_context=None):
    exit_context = dict(exit_context or {})
    entry = _safe_float((pos or {}).get("entry"), default=0.0) or 0.0
    size = _safe_float((pos or {}).get("size"), default=0.0) or 0.0
    exit_px = _safe_float(exit_price, default=entry)
    direction = (pos or {}).get("direction")
    pnl = (exit_px - entry) * size if direction == "long" else (entry - exit_px) * size

    entry_time = (pos or {}).get("entry_time")
    resolved_exit_time = exit_time or ""
    entry_dt = _parse_iso_datetime(entry_time)
    exit_dt = _parse_iso_datetime(resolved_exit_time)
    hold_minutes = None
    if entry_dt is not None and exit_dt is not None:
        hold_minutes = round(max((exit_dt - entry_dt).total_seconds(), 0) / 60.0, 2)

    notional = abs(entry * size)
    pnl_pct = round((pnl / notional) * 100, 4) if notional > 0 else 0.0
    if pnl > 0:
        outcome = "win"
    elif pnl < 0:
        outcome = "loss"
    else:
        outcome = "breakeven"

    favorable = _safe_float((pos or {}).get("max_favorable_price"), default=entry)
    adverse = _safe_float((pos or {}).get("max_adverse_price"), default=entry)
    if direction == "long":
        mfe_pct = ((favorable - entry) / entry * 100) if entry else 0.0
        mae_pct = ((adverse - entry) / entry * 100) if entry else 0.0
    else:
        mfe_pct = ((entry - favorable) / entry * 100) if entry else 0.0
        mae_pct = ((entry - adverse) / entry * 100) if entry else 0.0

    initial_risk = _safe_float((pos or {}).get("initial_risk"), default=None)
    initial_risk_pct = (initial_risk / entry * 100) if initial_risk is not None and entry else None
    mfe_r = (mfe_pct / initial_risk_pct) if initial_risk_pct not in (None, 0) else None
    mae_r = (mae_pct / initial_risk_pct) if initial_risk_pct not in (None, 0) else None
    best_close = _safe_float((pos or {}).get("best_price"), default=None)
    if initial_risk in (None, 0) or best_close is None:
        best_close_r = None
    elif direction == "long":
        best_close_r = (best_close - entry) / initial_risk
    elif direction == "short":
        best_close_r = (entry - best_close) / initial_risk
    else:
        best_close_r = None

    return {
        "coin": (pos or {}).get("coin"),
        "direction": direction,
        "entry": entry,
        "exit": exit_px,
        "size": size,
        "pnl": round(pnl, 4),
        "pnl_pct": pnl_pct,
        "outcome": outcome,
        "entry_time": entry_time,
        "exit_time": resolved_exit_time,
        "hold_minutes": hold_minutes,
        "hold_bars": (pos or {}).get("bars_since_entry"),
        "entry_reason": (pos or {}).get("entry_reason") or (pos or {}).get("signal_reason") or (pos or {}).get("sig") or "",
        "signal_reason": (pos or {}).get("signal_reason") or (pos or {}).get("sig") or "",
        "signal_score": (pos or {}).get("signal_score"),
        "btc_dir_at_entry": (pos or {}).get("btc_dir_at_entry"),
        "risk_pct": (pos or {}).get("risk_pct"),
        "entry_order_type": (pos or {}).get("entry_order_type"),
        "exit_reason": exit_reason,
        "exit_policy": ((pos or {}).get("exit_policy") or {}).get("name"),
        "position_source": (pos or {}).get("position_source"),
        "position_id": (pos or {}).get("position_id"),
        "is_partial": bool(exit_context.get("is_partial")),
        "close_status": exit_context.get("close_status"),
        "close_reason_source": exit_context.get("close_reason_source"),
        "close_submitted_at": (pos or {}).get("close_submitted_at"),
        "mfe_pct": round(mfe_pct, 4),
        "mae_pct": round(mae_pct, 4),
        "initial_risk": round(initial_risk, 8) if initial_risk is not None else None,
        "initial_risk_pct": round(initial_risk_pct, 4) if initial_risk_pct is not None else None,
        "mfe_r": round(mfe_r, 4) if mfe_r is not None else None,
        "mae_r": round(mae_r, 4) if mae_r is not None else None,
        "best_close_r": round(best_close_r, 4) if best_close_r is not None else None,
    }


def apply_closed_trade(
    state,
    pos,
    exit_price,
    exit_reason,
    *,
    exit_time=None,
    update_balance=True,
    exit_context=None,
    transaction_cost=0.0,
):
    trade = build_trade_record(
        pos,
        exit_price,
        exit_reason,
        exit_time=exit_time,
        exit_context=exit_context,
    )
    cost = round(max(_safe_float(transaction_cost, default=0.0) or 0.0, 0.0), 4)
    if cost:
        gross_pnl = trade["pnl"]
        trade["gross_pnl"] = gross_pnl
        trade["cost"] = cost
        trade["pnl"] = round(gross_pnl - cost, 4)
        notional = abs((_safe_float((pos or {}).get("entry"), default=0.0) or 0.0) * (_safe_float((pos or {}).get("size"), default=0.0) or 0.0))
        trade["pnl_pct"] = round((trade["pnl"] / notional) * 100, 4) if notional > 0 else 0.0
        if trade["pnl"] > 0:
            trade["outcome"] = "win"
        elif trade["pnl"] < 0:
            trade["outcome"] = "loss"
        else:
            trade["outcome"] = "breakeven"
    else:
        trade["cost"] = 0.0

    if update_balance:
        state["balance"] = (state.get("balance") or 0.0) + trade["pnl"]

    stats = state.setdefault("stats", {})
    stats["total_trades"] = int(stats.get("total_trades") or 0) + 1
    stats["total_pnl"] = round(float(stats.get("total_pnl") or 0.0) + trade["pnl"], 4)
    stats.setdefault("wins", 0)
    stats.setdefault("losses", 0)
    stats.setdefault("max_win", 0.0)
    stats.setdefault("max_loss", 0.0)
    if trade["outcome"] == "win":
        stats["wins"] += 1
        stats["max_win"] = max(float(stats.get("max_win") or 0.0), trade["pnl"])
    elif trade["outcome"] == "loss":
        stats["losses"] += 1
        stats["max_loss"] = min(float(stats.get("max_loss") or 0.0), trade["pnl"])

    state.setdefault("history", []).append(trade)
    return trade
