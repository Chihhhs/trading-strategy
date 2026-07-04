import json
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR

from trading_strategy.hyperliquid import (
    choose_limit_price,
    get_best_bid_ask,
    infer_price_tick,
)

from . import config
from .account import (
    Exchange,
    get_hl_account_address,
    get_hl_exchange_client,
    get_hl_info_client,
    get_hl_size_decimals,
)
from .io import debug_api_log


def round_down_value(value, decimals):
    decimals = max(int(decimals if decimals is not None else 8), 0)
    quant = Decimal("1").scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_DOWN))


def normalize_hl_order_params(coin, size, price):
    size_decimals = get_hl_size_decimals(coin)
    return {
        "size": round_down_value(size, size_decimals if size_decimals is not None else 8),
        "price": round_down_value(price, 8),
        "size_decimals": size_decimals,
    }


def get_position_entry_oid(pos):
    return pos.get("entry_oid") or pos.get("order_oid")


def build_order_ref(order_meta, fallback_status="unknown"):
    if not isinstance(order_meta, dict):
        return None
    return {
        "oid": order_meta.get("oid"),
        "status": order_meta.get("status", fallback_status),
        "requested_trigger_px": order_meta.get("requested_trigger_px"),
        "trigger_px": order_meta.get("trigger_px"),
        "requested_limit_px": order_meta.get("requested_limit_px"),
        "limit_px": order_meta.get("limit_px"),
        "size": order_meta.get("size"),
        "is_trigger": order_meta.get("is_trigger", False),
        "reduce_only": order_meta.get("reduce_only", False),
        "tpsl": order_meta.get("tpsl"),
        "message": order_meta.get("message"),
        "verify_status": order_meta.get("verify_status"),
        "normalized_status": order_meta.get("normalized_status"),
        "rejection_reason": order_meta.get("rejection_reason"),
        "tick_size": order_meta.get("tick_size"),
        "order_side": order_meta.get("order_side"),
        "price_source": order_meta.get("price_source"),
        "raw_trigger_px": order_meta.get("raw_trigger_px"),
        "normalized_trigger_px": order_meta.get("normalized_trigger_px"),
        "raw_limit_px": order_meta.get("raw_limit_px"),
        "normalized_limit_px": order_meta.get("normalized_limit_px"),
    }


def normalize_order_status(order_summary, verified_summary=None):
    raw_status = str((order_summary or {}).get("order_status") or "").lower()
    verify_status = str((verified_summary or {}).get("verify_status") or "").lower()
    if raw_status == "filled" or verify_status == "filled":
        return "filled"
    if raw_status in ("resting", "open") or verify_status == "open":
        return "resting"
    if raw_status in ("rejected", "error") or verify_status in ("rejected", "error"):
        return "rejected"
    if raw_status == "canceled" or verify_status == "canceled":
        return "canceled"
    if raw_status == "unknown" and not (order_summary or {}).get("oid"):
        return "unknown"
    if (order_summary or {}).get("oid"):
        return "submitted"
    return raw_status or "unknown"


def summarize_single_order_status(item):
    summary = {
        "order_status": "unknown",
        "oid": None,
        "filled": False,
        "resting": False,
        "message": None,
    }
    if not isinstance(item, dict):
        summary["message"] = str(item)
        return summary
    for key in ("filled", "resting"):
        if key in item and isinstance(item[key], dict):
            summary["order_status"] = key
            summary[key] = True
            summary["oid"] = item[key].get("oid")
            summary["message"] = json.dumps(item[key], ensure_ascii=False)
            return summary
    if "error" in item:
        message = str(item.get("error"))
        summary["order_status"] = (
            "rejected" if "reject" in message.lower() or "margin" in message.lower() else "error"
        )
        summary["message"] = message
        return summary
    summary["message"] = json.dumps(item, ensure_ascii=False)
    return summary


def summarize_hl_order_result(result):
    summary = {
        "api_status": None,
        "order_status": "unknown",
        "oid": None,
        "filled": False,
        "resting": False,
        "message": None,
    }
    if not isinstance(result, dict):
        summary["message"] = "non-dict response"
        return summary
    summary["api_status"] = result.get("status")
    statuses = (((result.get("response") or {}).get("data") or {}).get("statuses"))
    if not isinstance(statuses, list) or not statuses:
        summary["message"] = result.get("message")
        return summary
    summary.update(summarize_single_order_status(statuses[0]))
    return summary


def verify_hl_order(oid):
    address = get_hl_account_address()
    client = get_hl_info_client()
    if not address or client is None or oid is None:
        return None
    try:
        result = client.query_order_by_oid(address, int(oid))
        debug_api_log("hl_order_verify", {"oid": oid, "user": address, "raw_response": result})
        return result
    except Exception as exc:
        return {"error": str(exc)}


def classify_verified_order(result):
    if not isinstance(result, dict):
        return {"verify_status": "unknown", "message": None}
    if result.get("error"):
        return {"verify_status": "error", "message": str(result["error"])}
    status = str(result.get("status") or "")
    lowered = status.lower()
    if "filled" in lowered:
        return {"verify_status": "filled", "message": status}
    if "open" in lowered or "resting" in lowered:
        return {"verify_status": "open", "message": status}
    if "cancel" in lowered:
        return {"verify_status": "canceled", "message": status}
    if "reject" in lowered or "margin" in lowered:
        return {"verify_status": "rejected", "message": status}
    return {
        "verify_status": lowered or "unknown",
        "message": status or json.dumps(result, ensure_ascii=False),
    }


def infer_trigger_side(direction):
    return "sell" if direction == "long" else "buy"


def get_trigger_limit_price(exchange, coin, is_buy, trigger_px):
    try:
        return exchange._slippage_price(coin, is_buy, Exchange.DEFAULT_SLIPPAGE, px=trigger_px)
    except Exception:
        return round_down_value(float(trigger_px) * (1.05 if is_buy else 0.95), 8)


def normalize_trigger_order_prices(coin, side, trigger_px, limit_px):
    raw_trigger = float(trigger_px)
    raw_limit = float(limit_px)
    summary = get_best_bid_ask(coin, base_url=config.get_api_url())
    tick_size = infer_price_tick(summary) if summary else Decimal("0.00000001")
    trigger_rounding = ROUND_CEILING if side == "buy" else ROUND_FLOOR
    limit_rounding = ROUND_CEILING if side == "buy" else ROUND_FLOOR
    normalized_trigger = (_to_decimal(raw_trigger) / tick_size).to_integral_value(rounding=trigger_rounding) * tick_size
    normalized_limit = (_to_decimal(raw_limit) / tick_size).to_integral_value(rounding=limit_rounding) * tick_size
    return {
        "requested_trigger_px": raw_trigger,
        "trigger_px": float(normalized_trigger.normalize()),
        "requested_limit_px": raw_limit,
        "limit_px": float(normalized_limit.normalize()),
        "raw_trigger_px": raw_trigger,
        "normalized_trigger_px": float(normalized_trigger.normalize()),
        "raw_limit_px": raw_limit,
        "normalized_limit_px": float(normalized_limit.normalize()),
        "tick_size": float(tick_size),
        "price_source": "l2_book" if summary else "fallback",
        "best_bid": (summary or {}).get("best_bid", {}).get("price") if summary else None,
        "best_ask": (summary or {}).get("best_ask", {}).get("price") if summary else None,
    }


def _to_decimal(value):
    return Decimal(str(value))


def classify_order_rejection(message):
    lowered = str(message or "").lower()
    if "invalid price" in lowered:
        return "invalid_price"
    if "size" in lowered and "invalid" in lowered:
        return "size_invalid"
    if "margin" in lowered or "insufficient" in lowered:
        return "margin_insufficient"
    return "unknown_exchange_reject"


def place_hl_trigger_order(coin, side, size, trigger_px, tpsl):
    exchange = get_hl_exchange_client()
    if exchange is None:
        return {"status": "error", "message": "missing Hyperliquid SDK"}
    price_context = normalize_trigger_order_prices(
        coin,
        side,
        trigger_px,
        get_trigger_limit_price(exchange, coin, side == "buy", trigger_px),
    )
    normalized = normalize_hl_order_params(coin, size, price_context["limit_px"])
    if normalized["size"] <= 0:
        return {"status": "error", "message": f"{coin} TP/SL normalized size is 0"}
    result = exchange.order(
        coin,
        side == "buy",
        normalized["size"],
        price_context["limit_px"],
        {"trigger": {"triggerPx": price_context["trigger_px"], "isMarket": True, "tpsl": tpsl}},
        reduce_only=True,
    )
    summary = summarize_hl_order_result(result)
    verified = verify_hl_order(summary.get("oid")) if summary.get("oid") is not None else None
    verified_summary = classify_verified_order(verified) if verified is not None else None
    normalized_status = normalize_order_status(summary, verified_summary)
    message = summary.get("message")
    debug_api_log(
        "hl_trigger_order_submit",
        {
            "coin": coin,
            "side": side,
            "tpsl": tpsl,
            "raw_response": result,
            "normalized_status": normalized_status,
            "price_context": price_context,
        },
    )
    return {
        "status": "ok" if normalized_status in ("filled", "resting", "submitted") else "error",
        "oid": summary.get("oid"),
        "size": normalized["size"],
        "requested_trigger_px": price_context["requested_trigger_px"],
        "trigger_px": price_context["trigger_px"],
        "requested_limit_px": price_context["requested_limit_px"],
        "limit_px": price_context["limit_px"],
        "is_trigger": True,
        "reduce_only": True,
        "tpsl": tpsl,
        "message": message,
        "verify_status": (verified_summary or {}).get("verify_status"),
        "normalized_status": normalized_status,
        "rejection_reason": classify_order_rejection(message),
        "tick_size": price_context["tick_size"],
        "order_side": side,
        "price_source": price_context["price_source"],
        "raw_trigger_px": price_context["raw_trigger_px"],
        "normalized_trigger_px": price_context["normalized_trigger_px"],
        "raw_limit_px": price_context["raw_limit_px"],
        "normalized_limit_px": price_context["normalized_limit_px"],
        "best_bid": price_context["best_bid"],
        "best_ask": price_context["best_ask"],
    }


def place_hl_tpsl_orders(coin, direction, size, tp_px, sl_px):
    side = infer_trigger_side(direction)
    sl_order = place_hl_trigger_order(coin, side, size, sl_px, "sl")
    tp_order = place_hl_trigger_order(coin, side, size, tp_px, "tp")
    return {
        "sl_order": build_order_ref(sl_order),
        "tp_order": build_order_ref(tp_order),
        "ok": sl_order.get("status") == "ok" and tp_order.get("status") == "ok",
        "message": "; ".join(part for part in (sl_order.get("message"), tp_order.get("message")) if part),
        "order_side": side,
        "price_source": tp_order.get("price_source") or sl_order.get("price_source"),
    }


def place_hl_order(coin, side, size, price=None, order_type="ioc"):
    exchange = get_hl_exchange_client()
    if exchange is None:
        return {"status": "error", "message": "missing Hyperliquid SDK"}
    orderbook_ref = choose_limit_price(
        coin,
        side,
        base_url=config.get_api_url(),
        passive=(order_type == "post_only"),
    )
    resolved_price = price if price is not None else (orderbook_ref or {}).get("normalized_price")
    if resolved_price is None:
        return {"status": "error", "message": f"unable to resolve HL order book price for {coin}"}
    normalized = normalize_hl_order_params(coin, size, resolved_price)
    if normalized["size"] <= 0:
        return {"status": "error", "message": f"normalized size is 0 for {coin}"}
    result = exchange.order(
        coin,
        side == "buy",
        normalized["size"],
        normalized["price"],
        {"limit": {"tif": "Alo" if order_type == "post_only" else "Ioc"}},
        reduce_only=False,
    )
    order_summary = summarize_hl_order_result(result)
    verified = verify_hl_order(order_summary.get("oid")) if order_summary.get("oid") is not None else None
    verified_summary = classify_verified_order(verified) if verified is not None else None
    normalized_status = normalize_order_status(order_summary, verified_summary)
    debug_api_log(
        "hl_order_submit",
        {
            "coin": coin,
            "side": side,
            "raw_response": result,
            "normalized_status": normalized_status,
            "orderbook_ref": orderbook_ref,
        },
    )
    message = order_summary.get("message") or json.dumps(result, ensure_ascii=False)
    return {
        "status": "ok" if normalized_status in ("filled", "resting", "submitted") else "error",
        "message": message,
        "resolved_price": normalized["price"],
        "order_type": order_type,
        "size": normalized["size"],
        "size_decimals": normalized["size_decimals"],
        "order_summary": order_summary,
        "verified_summary": verified_summary,
        "normalized_status": normalized_status,
        "raw_price": (orderbook_ref or {}).get("raw_price"),
        "normalized_price": (orderbook_ref or {}).get("normalized_price"),
        "best_bid": (orderbook_ref or {}).get("best_bid"),
        "best_ask": (orderbook_ref or {}).get("best_ask"),
        "price_source": (orderbook_ref or {}).get("price_source"),
        "tick_size": (orderbook_ref or {}).get("tick_size"),
        "rejection_reason": classify_order_rejection(message),
    }


def close_hl_position(pos, reason):
    exchange = get_hl_exchange_client()
    if exchange is None:
        return {"status": "error", "message": "missing Hyperliquid SDK"}
    result = exchange.market_close(pos["coin"], sz=pos.get("size"))
    summary = summarize_hl_order_result(result)
    verified = verify_hl_order(summary.get("oid")) if summary.get("oid") is not None else None
    verified_summary = classify_verified_order(verified) if verified is not None else None
    return {
        "status": "ok" if normalize_order_status(summary, verified_summary) in ("filled", "resting", "submitted") else "error",
        "reason": reason,
        "order_summary": summary,
        "verified_summary": verified_summary,
        "message": summary.get("message"),
    }
