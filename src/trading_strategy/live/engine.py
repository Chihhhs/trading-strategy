from collections import Counter
from datetime import datetime, timedelta

from trading_strategy.core.risk import calc_position_size, check_circuit_breaker, is_cooldown
from trading_strategy.core.signals import generate_trend_signal

from . import config
from .account import (
    extract_hl_account_value,
    extract_hl_account_values,
    get_hl_frontend_open_orders,
    get_hl_perp_user_state,
)
from .io import load_state, record_trade_event, save_state
from .market import get_btc_direction, get_current_prices, get_klines
from .orders import (
    classify_order_rejection,
    classify_verified_order,
    close_hl_position,
    get_position_entry_oid,
    normalize_hl_order_params,
    place_hl_order,
    place_hl_tpsl_orders,
    verify_hl_order,
)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    ema = sum(closes[:period]) / period
    weight = 2 / (period + 1)
    for close in closes[period:]:
        ema = close * weight + ema * (1 - weight)
    return ema


def calc_atr(highs, lows, closes, period=14):
    trs = [
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, len(highs))
    ]
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def generate_signal(klines, min_score=4):
    return generate_trend_signal(
        klines,
        min_score=min_score,
        tp_mult=config.STRATEGY["tp_mult"],
        sl_mult=config.STRATEGY["sl_mult"],
    )


def check_trend_reversal(pos, klines):
    if not klines or len(klines) < 30:
        return False
    closes = [d["close"] for d in klines]
    e20, e50 = calc_ema(closes, 20), calc_ema(closes, 50)
    e20_prev = calc_ema(closes[:-1], 20)
    e50_prev = calc_ema(closes[:-1], 50) if len(closes) > 50 else e50
    cur = closes[-1]
    if pos["direction"] == "long":
        return cur < e20 and e20 < e50 and e20_prev >= e50_prev
    return cur > e20 and e20 > e50 and e20_prev <= e50_prev


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


def build_run_summary():
    return {
        "coins_scanned": 0,
        "priced_coins": 0,
        "valid_klines": 0,
        "signals_found": 0,
        "btc_filtered": 0,
        "size_zero": 0,
        "orders_attempted": 0,
        "positions_opened": 0,
        "entry_rejected_count": 0,
        "entry_rejected_reasons": {},
        "missing_price_count": 0,
        "missing_price_coins_sample": [],
        "no_signal_count": 0,
        "priced_ratio": 0.0,
        "top_blockers": [],
        "adopted_positions_count": 0,
        "tpsl_missing_count": 0,
        "tpsl_repaired_count": 0,
        "unprotected_positions_count": 0,
    }


def build_strategy_snapshot():
    return {
        "entry_order_type": config.STRATEGY["entry_order_type"],
        "leverage": config.STRATEGY["leverage"],
        "risk_per_trade": config.STRATEGY["risk_per_trade"],
        "max_positions": config.STRATEGY["max_positions"],
        "market_data_source": config.get_market_data_source(),
    }


def build_entry_context(state, coin_name, btc_dir, entry_order_type, **fields):
    context = {
        "coin": coin_name,
        "mode": config.MODE,
        "balance": state.get("balance"),
        "entry_order_type": entry_order_type,
        "btc_dir": btc_dir,
        "signal_direction": None,
        "signal_score": None,
        "entry": None,
        "sl": None,
        "tp": None,
        "risk_pct": None,
        "raw_size": None,
        "normalized_size": None,
        "order_status": None,
        "verify_status": None,
        "message": None,
        "resolved_price": None,
        "raw_price": None,
        "normalized_price": None,
        "best_bid": None,
        "best_ask": None,
        "price_source": None,
        "strategy_snapshot": build_strategy_snapshot(),
    }
    context.update(fields)
    return context


def bump_summary_blocker(summary, reason, coin_name=None):
    blockers = summary.setdefault("_blockers", Counter())
    blockers[reason] += 1
    if reason == "missing_price":
        summary["missing_price_count"] += 1
        if coin_name and len(summary["missing_price_coins_sample"]) < 10:
            summary["missing_price_coins_sample"].append(coin_name)
    elif reason == "no_signal":
        summary["no_signal_count"] += 1
    elif reason in ("size_zero", "normalized_size_zero"):
        summary["size_zero"] += 1
    elif reason == "btc_filter":
        summary["btc_filtered"] += 1


def finalize_run_summary(summary):
    blockers = summary.pop("_blockers", Counter())
    summary["entry_rejected_reasons"] = dict(summary.get("_rejected_reasons", {}))
    summary.pop("_rejected_reasons", None)
    total = summary["coins_scanned"] or 0
    summary["priced_ratio"] = round(summary["priced_coins"] / total, 4) if total else 0.0
    summary["top_blockers"] = [
        {"reason": reason, "count": count}
        for reason, count in blockers.most_common(5)
    ]
    return summary


def log_entry_skipped(state, coin_name, btc_dir, reason, **fields):
    record_trade_event(
        "entry_skipped",
        reason=reason,
        **build_entry_context(
            state,
            coin_name,
            btc_dir,
            config.STRATEGY["entry_order_type"],
            **fields,
        ),
    )


def build_position_from_exchange(coin, position_state, existing=None):
    existing = dict(existing or {})
    size = abs(_safe_float(position_state.get("szi")))
    direction = "long" if _safe_float(position_state.get("szi")) >= 0 else "short"
    entry = _safe_float(position_state.get("entryPx"))
    adopted_at = datetime.now().isoformat()
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
        "protection_status": existing.get("protection_status", "missing_tpsl"),
        "exchange_position_state": {
            "coin": coin,
            "entryPx": position_state.get("entryPx"),
            "szi": position_state.get("szi"),
        },
    }


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
    return None


def build_tpsl_event_context(repaired):
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


def ensure_position_targets(pos, data_cache=None):
    if pos.get("tp") is not None and pos.get("sl") is not None:
        return pos.get("tp"), pos.get("sl")
    klines = None
    if isinstance(data_cache, dict):
        klines = data_cache.get(pos["coin"])
    if not klines:
        klines = get_klines(f'{pos["coin"]}USDT', 60)
        if isinstance(data_cache, dict) and klines:
            data_cache[pos["coin"]] = klines
    entry = _safe_float(pos.get("entry"))
    atr = None
    if klines and len(klines) >= 2:
        atr = calc_atr(
            [d["high"] for d in klines],
            [d["low"] for d in klines],
            [d["close"] for d in klines],
        )
    if not atr:
        atr = entry * 0.03
    if pos.get("direction") == "long":
        tp = pos.get("tp") or (entry + atr * config.STRATEGY["tp_mult"])
        sl = pos.get("sl") or (entry - atr * config.STRATEGY["sl_mult"])
    else:
        tp = pos.get("tp") or (entry - atr * config.STRATEGY["tp_mult"])
        sl = pos.get("sl") or (entry + atr * config.STRATEGY["sl_mult"])
    pos["tp"] = tp
    pos["sl"] = sl
    return tp, sl


def ensure_position_protection(state):
    open_orders = extract_open_order_map(state.get("_frontend_open_orders") or [])
    summary = {
        "adopted_positions_count": len(state.get("_adopted_positions") or []),
        "tpsl_missing_count": 0,
        "tpsl_repaired_count": 0,
        "unprotected_positions_count": 0,
    }
    for pos in state.get("positions", []):
        tp_open = match_existing_protection_order(pos, open_orders, "tp")
        sl_open = match_existing_protection_order(pos, open_orders, "sl")
        if tp_open and sl_open:
            pos["protection_status"] = "protected"
            continue
        summary["tpsl_missing_count"] += 1
        pos["protection_status"] = "missing_tpsl"
        tp, sl = ensure_position_targets(pos, state.setdefault("_data_cache", {}))
        record_trade_event(
            "tpsl_missing_detected",
            coin=pos.get("coin"),
            tp_present=bool(tp_open),
            sl_present=bool(sl_open),
            tp=tp,
            sl=sl,
            position_source=pos.get("position_source"),
        )
        repaired = place_hl_tpsl_orders(pos["coin"], pos["direction"], pos["size"], tp, sl)
        tpsl_context = build_tpsl_event_context(repaired)
        record_trade_event(
            "tpsl_repair_attempted",
            coin=pos.get("coin"),
            size=pos.get("size"),
            direction=pos.get("direction"),
            tp=tp,
            sl=sl,
            **tpsl_context,
        )
        if repaired.get("ok"):
            pos["tp_order"] = repaired.get("tp_order")
            pos["sl_order"] = repaired.get("sl_order")
            pos["protection_status"] = "protected"
            summary["tpsl_repaired_count"] += 1
            record_trade_event(
                "tpsl_repaired",
                coin=pos.get("coin"),
                tp_order=repaired.get("tp_order"),
                sl_order=repaired.get("sl_order"),
                **tpsl_context,
            )
        else:
            pos["tp_order"] = repaired.get("tp_order")
            pos["sl_order"] = repaired.get("sl_order")
            pos["protection_status"] = "repair_failed"
            summary["unprotected_positions_count"] += 1
            record_trade_event(
                "tpsl_repair_failed",
                coin=pos.get("coin"),
                tp_order=repaired.get("tp_order"),
                sl_order=repaired.get("sl_order"),
                message=repaired.get("message"),
                **tpsl_context,
            )
    return summary


def sync_state_with_exchange_positions(state, perp_state=None, frontend_open_orders=None):
    if config.MODE != "live":
        return state
    perp_state = perp_state if perp_state is not None else get_hl_perp_user_state()
    frontend_open_orders = (
        frontend_open_orders
        if frontend_open_orders is not None
        else get_hl_frontend_open_orders()
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
    state["positions"] = synced_positions + pending_local_positions
    state["_adopted_positions"] = adopted_positions
    state["_stale_positions"] = stale_positions
    state["_frontend_open_orders"] = frontend_open_orders
    if adopted_positions or stale_positions:
        record_trade_event(
            "state_exchange_mismatch",
            adopted_positions=adopted_positions,
            stale_positions=stale_positions,
        )
    return state


def update_positions(state, prices, data_cache):
    if config.MODE == "live":
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


def check_entries(state, coins):
    summary = build_run_summary()
    summary["coins_scanned"] = len(coins)
    if len(state["positions"]) >= config.STRATEGY["max_positions"]:
        bump_summary_blocker(summary, "max_positions_reached")
        record_trade_event(
            "entry_skipped",
            reason="max_positions_reached",
            mode=config.MODE,
            balance=state.get("balance"),
            entry_order_type=config.STRATEGY["entry_order_type"],
            strategy_snapshot=build_strategy_snapshot(),
        )
        return finalize_run_summary(summary)

    ok, reason = check_circuit_breaker(state, config.CIRCUIT)
    if not ok:
        print(f"  circuit breaker: {reason}")
        bump_summary_blocker(summary, "circuit_breaker")
        record_trade_event(
            "entry_skipped",
            reason="circuit_breaker",
            mode=config.MODE,
            balance=state.get("balance"),
            entry_order_type=config.STRATEGY["entry_order_type"],
            message=reason,
            strategy_snapshot=build_strategy_snapshot(),
        )
        return finalize_run_summary(summary)

    btc_dir, prices = get_btc_direction(), get_current_prices(coins)
    summary["priced_coins"] = len(prices)

    for coin in coins:
        if len(state["positions"]) >= config.STRATEGY["max_positions"]:
            bump_summary_blocker(summary, "max_positions_reached")
            log_entry_skipped(state, coin["name"], btc_dir, "max_positions_reached")
            break

        name = coin["name"]
        if any(pos["coin"] == name for pos in state["positions"]):
            bump_summary_blocker(summary, "existing_position")
            log_entry_skipped(state, name, btc_dir, "existing_position")
            continue
        if is_cooldown(state, name, config.CIRCUIT):
            bump_summary_blocker(summary, "cooldown_active")
            log_entry_skipped(state, name, btc_dir, "cooldown_active")
            continue
        if name not in prices:
            bump_summary_blocker(summary, "missing_price", name)
            log_entry_skipped(state, name, btc_dir, "missing_price")
            continue

        klines = get_klines(coin["symbol"], 60)
        if not klines or len(klines) < 50:
            bump_summary_blocker(summary, "insufficient_klines")
            log_entry_skipped(state, name, btc_dir, "insufficient_klines")
            continue
        summary["valid_klines"] += 1
        state.setdefault("_data_cache", {})[name] = klines

        sig = generate_signal(klines, config.STRATEGY["min_score"])
        if not sig:
            bump_summary_blocker(summary, "no_signal")
            log_entry_skipped(state, name, btc_dir, "no_signal")
            continue
        summary["signals_found"] += 1

        if (btc_dir == "bull" and sig["direction"] == "short") or (
            btc_dir == "bear" and sig["direction"] == "long"
        ):
            bump_summary_blocker(summary, "btc_filter")
            log_entry_skipped(
                state,
                name,
                btc_dir,
                "btc_filter",
                signal_direction=sig.get("direction"),
                signal_score=sig.get("score"),
                sl=sig.get("sl"),
                tp=sig.get("tp"),
            )
            continue

        entry = prices[name]
        atr = calc_atr(
            [d["high"] for d in klines],
            [d["low"] for d in klines],
            [d["close"] for d in klines],
        )
        risk_pct = (
            0.05
            if atr and entry and atr / entry * 100 > 5
            else 0.10
            if atr and entry and atr / entry * 100 < 2
            else config.STRATEGY["risk_per_trade"]
        )
        size = calc_position_size(
            state["balance"],
            entry,
            sig["sl"],
            config.STRATEGY["leverage"],
            risk_pct,
        )
        preview = normalize_hl_order_params(name, size, entry)
        base_context = {
            "signal_direction": sig.get("direction"),
            "signal_score": sig.get("score"),
            "entry": entry,
            "sl": sig.get("sl"),
            "tp": sig.get("tp"),
            "risk_pct": risk_pct,
            "raw_size": size,
            "normalized_size": preview["size"],
        }

        if size <= 0:
            bump_summary_blocker(summary, "size_zero")
            log_entry_skipped(state, name, btc_dir, "size_zero", **base_context)
            continue
        if preview["size"] <= 0:
            bump_summary_blocker(summary, "normalized_size_zero")
            log_entry_skipped(state, name, btc_dir, "normalized_size_zero", **base_context)
            continue

        order_meta, tpsl_meta = None, {"tp_order": None, "sl_order": None}
        if config.MODE == "live":
            summary["orders_attempted"] += 1
            record_trade_event(
                "entry_order_attempted",
                **build_entry_context(
                    state,
                    name,
                    btc_dir,
                    config.STRATEGY["entry_order_type"],
                    **base_context,
                ),
            )
            order_meta = place_hl_order(
                name,
                "buy" if sig["direction"] == "long" else "sell",
                round(size, 6),
                order_type=config.STRATEGY["entry_order_type"],
            )
            order_status = (order_meta or {}).get("normalized_status")
            verify_status = ((order_meta or {}).get("verified_summary") or {}).get("verify_status")
            message = (order_meta or {}).get("message")
            order_context = {
                "order_status": order_status,
                "verify_status": verify_status,
                "message": message,
                "resolved_price": (order_meta or {}).get("resolved_price"),
                "raw_price": (order_meta or {}).get("raw_price"),
                "normalized_price": (order_meta or {}).get("normalized_price"),
                "best_bid": (order_meta or {}).get("best_bid"),
                "best_ask": (order_meta or {}).get("best_ask"),
                "price_source": (order_meta or {}).get("price_source"),
            }
            if not order_meta or order_meta.get("status") == "error":
                rejection_reason = (order_meta or {}).get("rejection_reason") or classify_order_rejection(message)
                summary["entry_rejected_count"] += 1
                rejected = summary.setdefault("_rejected_reasons", Counter())
                rejected[rejection_reason] += 1
                bump_summary_blocker(summary, rejection_reason)
                record_trade_event(
                    "entry_order_rejected",
                    rejection_reason=rejection_reason,
                    **build_entry_context(
                        state,
                        name,
                        btc_dir,
                        config.STRATEGY["entry_order_type"],
                        **base_context,
                        **order_context,
                    ),
                )
                continue
            if order_status != "filled":
                bump_summary_blocker(summary, "entry_order_not_filled")
                record_trade_event(
                    "entry_order_not_filled",
                    **build_entry_context(
                        state,
                        name,
                        btc_dir,
                        config.STRATEGY["entry_order_type"],
                        **base_context,
                        **order_context,
                    ),
                )
                log_entry_skipped(
                    state,
                    name,
                    btc_dir,
                    "entry_order_not_filled",
                    **base_context,
                    **order_context,
                )
                continue
            entry = order_meta.get("resolved_price", entry)
            tpsl_meta = place_hl_tpsl_orders(
                name,
                sig["direction"],
                order_meta.get("size"),
                sig["tp"],
                sig["sl"],
            )
            if not tpsl_meta.get("ok"):
                bump_summary_blocker(summary, "tpsl_submit_failed")
                tpsl_context = dict(order_context)
                tpsl_context["message"] = tpsl_meta.get("message")
                record_trade_event(
                    "tpsl_submit_failed",
                    **build_entry_context(
                        state,
                        name,
                        btc_dir,
                        config.STRATEGY["entry_order_type"],
                        **base_context,
                        **tpsl_context,
                    ),
                )
                log_entry_skipped(
                    state,
                    name,
                    btc_dir,
                    "tpsl_submit_failed",
                    **base_context,
                    **tpsl_context,
                )
                continue

        state["positions"].append(
            {
                "coin": name,
                "direction": sig["direction"],
                "entry": entry,
                "tp": sig["tp"],
                "sl": sig["sl"],
                "size": preview["size"] if config.MODE == "live" else round(size, 6),
                "current_price": entry,
                "pnl_pnl": 0,
                "entry_time": datetime.now().isoformat(),
                "sig": sig.get("reason", ""),
                "entry_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"),
                "entry_status": (order_meta or {}).get("normalized_status"),
                "entry_filled_size": (order_meta or {}).get("size"),
                "order_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"),
                "order_status": ((order_meta or {}).get("order_summary") or {}).get("order_status"),
                "tp_order": tpsl_meta.get("tp_order"),
                "sl_order": tpsl_meta.get("sl_order"),
                "exchange_position_state": None,
                "position_source": "local_state",
                "protection_status": "protected" if config.MODE == "live" else None,
            }
        )
        summary["positions_opened"] += 1
        if config.MODE == "live":
            record_trade_event(
                "position_opened",
                coin=name,
                entry_oid=((order_meta or {}).get("order_summary") or {}).get("oid"),
                order_status=(order_meta or {}).get("normalized_status"),
                verify_status=((order_meta or {}).get("verified_summary") or {}).get("verify_status"),
                strategy_snapshot=build_strategy_snapshot(),
            )
            save_state(state)
        print(
            f'  opened: {name} {sig["direction"]} @ ${entry:,.2f} | {sig["reason"]} | '
            f'score={sig["score"]} | mode={"live" if config.MODE == "live" else "paper"} | '
            f'order_status={((order_meta or {}).get("order_summary") or {}).get("order_status", "paper")} | '
            f'verify={((order_meta or {}).get("verified_summary") or {}).get("verify_status", "n/a")}'
        )

    return finalize_run_summary(summary)


def print_report(state):
    total = state["stats"]["total_trades"]
    print(f'\nStatus Report | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   balance: ${state["balance"]:.2f} | source: {state.get("_balance_source", "local_state")}')
    print(f'   positions: {len(state["positions"])}')
    print(f'   trades: {total} | WR: {(state["stats"]["wins"] / total * 100 if total else 0):.0f}%')


def print_debug_account():
    from .account import (
        get_api_wallet_address,
        get_hl_account_address,
        get_hl_balance,
        get_hl_client_error,
    )

    balance_info = get_hl_balance()
    account_values = extract_hl_account_values(balance_info)
    print("\nAccount Debug")
    print(f'   HL_PRIVATE_KEY: {"set" if config.get_private_key() else "missing"}')
    print(f'   HL_ACCOUNT_ADDRESS: {config.get_account_address() or "(missing)"}')
    print(f'   derived_api_wallet_address: {get_api_wallet_address() or "(unavailable)"}')
    print(f'   query_address: {get_hl_account_address() or "(missing)"}')
    print(f'   hl_client_error: {get_hl_client_error() or "(none)"}')
    print(f'   effective_balance: {extract_hl_account_value(balance_info)}')
    print(f'   perp_account_value: {account_values.get("perp_account_value")}')
    print(f'   spot_account_value: {account_values.get("spot_account_value")}')


def verify_saved_orders():
    from .account import sync_state_with_hl_balance

    state = sync_state_with_hl_balance(load_state())
    print("\nOrder Verify")
    print(
        f'   live positions: {len(extract_live_position_map(((state.get("_hl_balance_info") or {}).get("perp"))))}'
    )
    print(f'   open orders: {len((state.get("_frontend_open_orders") or []))}')
    for pos in state.get("positions", []):
        oid = get_position_entry_oid(pos)
        if oid is None:
            print(f'   {pos.get("coin")}: missing oid')
            continue
        summary = classify_verified_order(verify_hl_order(oid))
        print(
            f'   {pos.get("coin")}: oid={oid} | '
            f'local={pos.get("entry_status", pos.get("order_status", "unknown"))} | '
            f'verify={summary.get("verify_status", "unknown")} | '
            f'msg={summary.get("message", "")}'
        )
