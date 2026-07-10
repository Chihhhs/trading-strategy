import json
import os
import time

from trading_strategy.strategies import get_btc_direction_from_klines

from . import config
from .io import api_get, hl_info_post


def _interval_to_millis(interval):
    raw = str(interval or "1d").strip()
    if not raw:
        raw = "1d"
    unit = raw[-1]
    try:
        amount = int(raw[:-1])
    except ValueError:
        return 24 * 60 * 60 * 1000
    multipliers = {
        "m": 60 * 1000,
        "h": 60 * 60 * 1000,
        "d": 24 * 60 * 60 * 1000,
        "w": 7 * 24 * 60 * 60 * 1000,
        "M": 30 * 24 * 60 * 60 * 1000,
    }
    return amount * multipliers.get(unit, 24 * 60 * 60 * 1000)


def get_market_interval():
    return str(config.STRATEGY.get("timeframe") or "1d")


def get_klines(symbol, limit=60, interval=None):
    interval = interval or get_market_interval()
    if config.get_market_data_source() == "hyperliquid":
        coin = symbol.replace("USDT", "")
        end_time = int(time.time() * 1000)
        start_time = end_time - max(limit, 1) * _interval_to_millis(interval)
        data = hl_info_post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": start_time,
                    "endTime": end_time,
                },
            }
        )
        if data and isinstance(data, list):
            return [
                {
                    "open": float(d["o"]),
                    "high": float(d["h"]),
                    "low": float(d["l"]),
                    "close": float(d["c"]),
                    "volume": float(d.get("v", 0)),
                }
                for d in data[-limit:]
            ]
        return None
    url = f"{config.BINANCE_API}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = api_get(url)
    if data and isinstance(data, list):
        return [
            {
                "open": float(d[1]),
                "high": float(d[2]),
                "low": float(d[3]),
                "close": float(d[4]),
                "volume": float(d[5]),
            }
            for d in data
        ]
    return None


def get_ticker(symbol):
    if config.get_market_data_source() == "hyperliquid":
        coin = symbol.replace("USDT", "")
        mids = hl_info_post({"type": "allMids"})
        if isinstance(mids, dict) and coin in mids:
            price = float(mids[coin])
            return {
                "price": price,
                "change_pct": 0.0,
                "volume": (get_klines(symbol, 1) or [{"volume": 0}])[-1]["volume"],
            }
        return None
    data = api_get(f"{config.BINANCE_API}/api/v3/ticker/24hr?symbol={symbol}")
    if data:
        return {
            "price": float(data.get("lastPrice", 0)),
            "change_pct": float(data.get("priceChangePercent", 0)),
            "volume": float(data.get("quoteVolume", 0)),
        }
    return None


def _get_coin_cache_metadata():
    return {
        "mode": config.MODE,
        "market_data_source": config.get_market_data_source(),
    }


def _is_coin_cache_valid(payload):
    if not isinstance(payload, dict):
        return False
    if "coins" not in payload or not isinstance(payload["coins"], list):
        return False
    metadata = payload.get("metadata") or {}
    expected = _get_coin_cache_metadata()
    return all(metadata.get(key) == value for key, value in expected.items())


def _write_coin_cache(path, coins):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "metadata": _get_coin_cache_metadata(),
                "coins": coins,
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )


def _load_hyperliquid_coin_list():
    data = hl_info_post({"type": "meta"})
    if data and "universe" in data:
        return [
            {"name": s["name"], "symbol": f'{s["name"]}USDT'}
            for s in data["universe"]
            if s.get("name") and not s.get("isDelisted")
        ]
    return None


def _load_binance_coin_list():
    data = api_get(f"{config.BINANCE_API}/api/v3/exchangeInfo")
    if data and "symbols" in data:
        return [
            {"name": s["symbol"].replace("USDT", ""), "symbol": s["symbol"]}
            for s in data["symbols"]
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
        ]
    return None


def load_coin_list():
    cache = os.path.join(config.STATE_DIR, "coin_list.json")
    if os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if _is_coin_cache_valid(payload):
            return payload["coins"]

    if config.MODE == "live" or config.get_market_data_source() == "hyperliquid":
        coins = _load_hyperliquid_coin_list()
        if coins:
            _write_coin_cache(cache, coins)
            return coins

    coins = _load_binance_coin_list()
    if coins:
        _write_coin_cache(cache, coins)
        return coins

    names = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT"]
    return [{"name": name, "symbol": f"{name}USDT"} for name in names]


def get_current_prices(coins):
    prices = {}
    for coin in coins:
        ticker = get_ticker(coin["symbol"])
        if ticker:
            prices[coin["name"]] = ticker["price"]
        time.sleep(0.1)
    return prices


def get_btc_direction():
    return get_btc_direction_from_klines(get_klines("BTCUSDT", 30))
