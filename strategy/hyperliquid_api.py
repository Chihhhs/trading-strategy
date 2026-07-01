#!/usr/bin/env python3
"""
hyperliquid_api.py - Hyperliquid 市場資料輔助工具
"""
import json
import urllib.request


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


def _parse_book_side(levels):
    parsed = []
    for level in levels or []:
        try:
            price = float(level["px"])
            size = float(level["sz"])
        except (KeyError, TypeError, ValueError):
            continue
        parsed.append({"price": price, "size": size, "n": level.get("n")})
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


def choose_limit_price(coin, side, base_url=HL_API_URL, passive=False, price_pad_bps=5):
    summary = get_best_bid_ask(coin, base_url=base_url)
    if not summary:
        return None

    best_bid = summary["best_bid"]
    best_ask = summary["best_ask"]
    if not best_bid or not best_ask:
        return None

    if passive:
        if side == "buy":
            price = best_bid["price"] * (1 - price_pad_bps / 10000)
        else:
            price = best_ask["price"] * (1 + price_pad_bps / 10000)
    else:
        if side == "buy":
            price = best_ask["price"] * (1 + price_pad_bps / 10000)
        else:
            price = best_bid["price"] * (1 - price_pad_bps / 10000)

    return {
        "price": price,
        "best_bid": best_bid["price"],
        "best_ask": best_ask["price"],
        "book": summary["book"],
    }
