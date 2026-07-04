#!/usr/bin/env python3
import json
import urllib.request
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


HL_API_URL = "https://api.hyperliquid.xyz"


def api_post(path, data, base_url=HL_API_URL, timeout=10):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_l2_book(coin, base_url=HL_API_URL):
    return api_post("/info", {"type": "l2Book", "coin": coin}, base_url=base_url)


def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _parse_book_side(levels):
    parsed = []
    for level in levels or []:
        try:
            raw_price = str(level["px"])
            price_decimal = _to_decimal(raw_price)
            size = float(level["sz"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        parsed.append(
            {
                "price": float(price_decimal),
                "price_decimal": price_decimal,
                "raw_price": raw_price,
                "size": size,
                "n": level.get("n"),
            }
        )
    return parsed


def extract_best_bid_ask(book):
    if not isinstance(book, dict):
        return None

    levels = book.get("levels") or []
    bids = _parse_book_side(levels[0] if len(levels) > 0 else [])
    asks = _parse_book_side(levels[1] if len(levels) > 1 else [])

    best_bid = bids[0] if bids else None
    best_ask = asks[0] if asks else None
    return {
        "bids": bids,
        "asks": asks,
        "best_bid": best_bid,
        "best_ask": best_ask,
    }


def get_best_bid_ask(coin, base_url=HL_API_URL):
    book = get_l2_book(coin, base_url=base_url)
    summary = extract_best_bid_ask(book)
    if not summary:
        return None
    return {
        "book": book,
        **summary,
    }


def infer_price_tick(summary):
    candidates = []
    for side_name in ("bids", "asks"):
        side = summary.get(side_name) or []
        for level in side[:6]:
            price_decimal = level.get("price_decimal")
            if price_decimal is None:
                continue
            exponent = price_decimal.as_tuple().exponent
            if exponent < 0:
                candidates.append(Decimal("1").scaleb(exponent))
        for idx in range(1, min(len(side), 6)):
            current_price = side[idx - 1].get("price_decimal")
            next_price = side[idx].get("price_decimal")
            if current_price is None or next_price is None:
                continue
            diff = abs(current_price - next_price)
            if diff > 0:
                candidates.append(diff.normalize())
    if not candidates:
        return Decimal("0.00000001")
    return min(candidate for candidate in candidates if candidate > 0)


def round_to_tick(price, tick_size, *, is_buy, passive):
    if tick_size <= 0:
        return _to_decimal(price)
    rounding = ROUND_FLOOR if (is_buy or not passive) else ROUND_CEILING
    if passive:
        rounding = ROUND_FLOOR if is_buy else ROUND_CEILING
    units = (_to_decimal(price) / tick_size).to_integral_value(rounding=rounding)
    normalized = units * tick_size
    return normalized.normalize()


def choose_limit_price(coin, side, base_url=HL_API_URL, passive=False, price_pad_bps=5):
    summary = get_best_bid_ask(coin, base_url=base_url)
    if not summary:
        return None

    best_bid = summary["best_bid"]
    best_ask = summary["best_ask"]
    if not best_bid or not best_ask:
        return None

    is_buy = side == "buy"
    reference_decimal = (
        best_bid["price_decimal"] if passive and is_buy else
        best_ask["price_decimal"] if passive and not is_buy else
        best_ask["price_decimal"] if is_buy else
        best_bid["price_decimal"]
    )
    pad_multiplier = Decimal(str(price_pad_bps)) / Decimal("10000")
    if passive:
        raw_price = reference_decimal * (Decimal("1") - pad_multiplier if is_buy else Decimal("1") + pad_multiplier)
    else:
        raw_price = reference_decimal * (Decimal("1") + pad_multiplier if is_buy else Decimal("1") - pad_multiplier)

    tick_size = infer_price_tick(summary)
    normalized_price = round_to_tick(raw_price, tick_size, is_buy=is_buy, passive=passive)

    return {
        "price": float(normalized_price),
        "normalized_price": float(normalized_price),
        "raw_price": float(raw_price),
        "tick_size": float(tick_size),
        "price_source": "l2_book",
        "best_bid": best_bid["price"],
        "best_ask": best_ask["price"],
        "best_bid_raw": best_bid["raw_price"],
        "best_ask_raw": best_ask["raw_price"],
        "book": summary["book"],
    }
