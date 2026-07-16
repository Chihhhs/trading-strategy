import json
import os
import time

from trading_strategy.strategies import get_btc_direction_from_klines

from . import config
from .io import api_get, debug_api_log, hl_info_post


_DERIVATIVES_CONTEXT_CACHE = {}


def _market_data_cache_source(source=None):
    source = source or config.get_market_data_source()
    return "binance_usdm" if source == "binance" and config.MODE == "paper" else source


def _market_data_cache_path(symbol, interval):
    safe_symbol = "".join(char for char in str(symbol).upper() if char.isalnum() or char in ("-", "_"))
    safe_interval = "".join(char for char in str(interval).lower() if char.isalnum() or char in ("-", "_"))
    return os.path.join(config.get_state_dir(), "market_data", f"{safe_symbol}_{safe_interval}.json")


def _load_cached_klines(symbol, interval, source=None):
    """Return paper-only cached bars from the same configured market-data source."""
    if config.MODE != "paper":
        return None
    path = _market_data_cache_path(symbol, interval)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    metadata = payload.get("metadata") or {}
    cached_source = metadata.get("market_data_source")
    if metadata.get("interval") != interval:
        return None
    if source and cached_source != _market_data_cache_source(source):
        return None
    if cached_source not in ("hyperliquid", "binance_usdm"):
        return None
    bars = payload.get("klines")
    return bars if isinstance(bars, list) else None


def _save_cached_klines(symbol, interval, klines, source):
    """Merge completed paper bars by timestamp; never write a live-data fallback."""
    if config.MODE != "paper" or not klines:
        return
    timestamped = [bar for bar in klines if isinstance(bar, dict) and bar.get("time") is not None]
    if not timestamped:
        return
    cache_source = _market_data_cache_source(source)
    existing = _load_cached_klines(symbol, interval, source=source) or []
    merged = {
        bar["time"]: dict(bar)
        for bar in [*existing, *timestamped]
        if isinstance(bar, dict) and bar.get("time") is not None
    }
    path = _market_data_cache_path(symbol, interval)
    payload = {
        "metadata": {
            "interval": interval,
            "market_data_source": cache_source,
        },
        "klines": [merged[key] for key in sorted(merged)],
    }
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


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
    data = None
    source = config.get_market_data_source()
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
            data = [
                {
                    "time": d.get("t") or d.get("T"),
                    "open": float(d["o"]),
                    "high": float(d["h"]),
                    "low": float(d["l"]),
                    "close": float(d["c"]),
                    "volume": float(d.get("v", 0)),
                }
                for d in data[-limit:]
            ]
        if not data and config.MODE == "paper":
            source = "binance"
            url = f"{config.BINANCE_FUTURES_API}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
            data = api_get(url)
            if data and isinstance(data, list):
                data = [
                    {
                        "time": d[0],
                        "open": float(d[1]),
                        "high": float(d[2]),
                        "low": float(d[3]),
                        "close": float(d[4]),
                        "volume": float(d[5]),
                    }
                    for d in data
                ]
    else:
        api_base = config.BINANCE_FUTURES_API if config.MODE == "paper" else config.BINANCE_API
        endpoint = "/fapi/v1/klines" if config.MODE == "paper" else "/api/v3/klines"
        url = f"{api_base}{endpoint}?symbol={symbol}&interval={interval}&limit={limit}"
        data = api_get(url)
        if data and isinstance(data, list):
            data = [
                {
                    "time": d[0],
                    "open": float(d[1]),
                    "high": float(d[2]),
                    "low": float(d[3]),
                    "close": float(d[4]),
                    "volume": float(d[5]),
                }
                for d in data
            ]
    if data:
        _save_cached_klines(symbol, interval, data, source)
        return data
    cached = _load_cached_klines(symbol, interval)
    return cached[-limit:] if cached else None


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_premium_index(payload):
    if not isinstance(payload, dict):
        return None
    mark = _safe_float(payload.get("markPrice"))
    index = _safe_float(payload.get("indexPrice"))
    funding = _safe_float(payload.get("lastFundingRate"))
    basis_pct = None
    if mark is not None and index not in (None, 0):
        basis_pct = (mark / index - 1.0) * 100.0
    return {
        "funding_rate": funding,
        "basis_pct": basis_pct,
        "mark_price": mark,
        "index_price": index,
    }


def _normalize_funding_history(payload):
    if not isinstance(payload, list):
        return []
    history = []
    for item in payload:
        funding = _safe_float((item or {}).get("fundingRate"))
        if funding is None:
            continue
        history.append(funding)
    return history


def _latest_bybit_open_interest(symbol):
    payload = api_get(
        f"{config.BYBIT_API}/v5/market/open-interest?category=linear&symbol={symbol}&intervalTime=5min&limit=1"
    )
    rows = ((payload or {}).get("result") or {}).get("list") or []
    if not rows:
        return None
    return _safe_float((rows[0] or {}).get("openInterest"))


def get_derivatives_context(symbol, lookback=31, include_open_interest=False):
    symbol = symbol if str(symbol).endswith("USDT") else f"{symbol}USDT"
    lookback = max(int(lookback or 31), 2)
    cache_key = (symbol, lookback, bool(include_open_interest))
    now_bucket = int(time.time() // 300)
    cached = _DERIVATIVES_CONTEXT_CACHE.get(cache_key)
    if cached and cached.get("bucket") == now_bucket:
        return cached.get("context")

    funding_url = (
        f"{config.BINANCE_FUTURES_API}/fapi/v1/fundingRate"
        f"?symbol={symbol}&limit={min(max(lookback, 2), 1000)}"
    )
    premium_url = f"{config.BINANCE_FUTURES_API}/fapi/v1/premiumIndex?symbol={symbol}"
    funding_history = _normalize_funding_history(api_get(funding_url))
    premium = _normalize_premium_index(api_get(premium_url)) or {}
    context = {
        "funding_history": funding_history,
        "funding_rate": premium.get("funding_rate"),
        "basis_pct": premium.get("basis_pct"),
        "mark_price": premium.get("mark_price"),
        "index_price": premium.get("index_price"),
        "open_interest": _latest_bybit_open_interest(symbol) if include_open_interest else None,
        "source": "binance_futures+bybit_oi" if include_open_interest else "binance_futures",
    }
    _DERIVATIVES_CONTEXT_CACHE[cache_key] = {"bucket": now_bucket, "context": context}
    if not funding_history or context.get("basis_pct") is None:
        debug_api_log(
            "derivatives_context_missing",
            {
                "symbol": symbol,
                "funding_count": len(funding_history),
                "has_basis": context.get("basis_pct") is not None,
            },
        )
    return context


def enrich_klines_with_derivatives_context(coin, klines, lookback=31):
    if not klines:
        return klines
    context = get_derivatives_context(coin, lookback=lookback)
    funding_history = list((context or {}).get("funding_history") or [])
    if not funding_history and (context or {}).get("funding_rate") is None:
        return klines

    enriched = [dict(bar) for bar in klines]
    tail_count = min(len(enriched), len(funding_history))
    if tail_count:
        for bar, funding in zip(enriched[-tail_count:], funding_history[-tail_count:]):
            bar["funding_rate"] = funding
    if context.get("funding_rate") is not None:
        enriched[-1]["funding_rate"] = context["funding_rate"]
    if context.get("basis_pct") is not None:
        enriched[-1]["basis_pct"] = context["basis_pct"]
    return enriched


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
        if config.MODE != "paper":
            return None
        data = api_get(f"{config.BINANCE_FUTURES_API}/fapi/v1/ticker/24hr?symbol={symbol}")
        if not data:
            return None
        return {
            "price": float(data.get("lastPrice", 0)),
            "change_pct": float(data.get("priceChangePercent", 0)),
            "volume": float(data.get("quoteVolume", 0)),
        }
    api_base = config.BINANCE_FUTURES_API if config.MODE == "paper" else config.BINANCE_API
    endpoint = "/fapi/v1/ticker/24hr" if config.MODE == "paper" else "/api/v3/ticker/24hr"
    data = api_get(f"{api_base}{endpoint}?symbol={symbol}")
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
    configured_universe = config.STRATEGY.get("coin_universe")
    if configured_universe:
        names = [str(name).upper() for name in configured_universe]
        return [{"name": name, "symbol": f"{name}USDT"} for name in names]

    cache = os.path.join(config.get_state_dir(), "coin_list.json")
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
    if config.get_market_data_source() == "hyperliquid":
        mids = hl_info_post({"type": "allMids"})
        if isinstance(mids, dict):
            prices = {
                coin["name"]: float(mids[coin["name"]])
                for coin in coins
                if coin["name"] in mids
            }
            if config.MODE == "paper":
                for coin in coins:
                    if coin["name"] in prices:
                        continue
                    data = api_get(f"{config.BINANCE_FUTURES_API}/fapi/v1/ticker/24hr?symbol={coin['symbol']}")
                    if data:
                        prices[coin["name"]] = float(data.get("lastPrice", 0))
            return prices
    prices = {}
    for coin in coins:
        ticker = get_ticker(coin["symbol"])
        if ticker:
            prices[coin["name"]] = ticker["price"]
        time.sleep(0.1)
    return prices


def get_btc_direction():
    return get_btc_direction_from_klines(get_klines("BTCUSDT", 30))
