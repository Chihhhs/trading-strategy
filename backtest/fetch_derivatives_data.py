#!/usr/bin/env python3
import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DEFAULT_PRICE_PATH = os.path.join(PROJECT_ROOT, "data", "historical_prices", "1000d_50coins.json")
DEFAULT_OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "derivatives", "binance_futures_derivatives.json")
BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_FUTURES_DATA = "https://fapi.binance.com/futures/data"


def _request_json(base_url, path, params):
    query = urllib.parse.urlencode(params)
    url = f"{base_url}{path}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "trading-strategy-research/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        body = getattr(exc, "read", lambda: b"")()
        message = body.decode("utf-8", errors="replace") if body else str(exc)
        raise RuntimeError(message) from exc


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar_ts(bar):
    for key in ("ts", "open_time", "time", "timestamp", "date"):
        value = bar.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _load_price_windows(path, coins, max_days):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    windows = {}
    for coin in coins:
        bars = list((payload or {}).get(coin, []))
        if max_days is not None:
            bars = bars[-max_days:]
        timestamps = [_bar_ts(bar) for bar in bars if _bar_ts(bar) is not None]
        if timestamps:
            windows[coin] = {
                "bars": bars,
                "start": min(timestamps),
                "end": max(timestamps) + 24 * 60 * 60 * 1000 - 1,
            }
    return windows


def _daily_key(ts):
    return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _fetch_funding(symbol, start, end):
    rows = _request_json(
        BINANCE_FAPI,
        "/fapi/v1/fundingRate",
        {
            "symbol": symbol,
            "startTime": start,
            "endTime": end,
            "limit": 1000,
        },
    )
    by_day = {}
    for row in rows if isinstance(rows, list) else []:
        key = _daily_key(row.get("fundingTime"))
        by_day.setdefault(key, []).append(_safe_float(row.get("fundingRate")))
    return {
        key: sum(value for value in values if value is not None) / len([value for value in values if value is not None])
        for key, values in by_day.items()
        if any(value is not None for value in values)
    }


def _fetch_open_interest(symbol, start, end):
    params = {"symbol": symbol, "period": "1d", "limit": 500}
    try:
        rows = _request_json(
            BINANCE_FUTURES_DATA,
            "/openInterestHist",
            {
                **params,
                "startTime": start,
                "endTime": end,
            },
        )
    except RuntimeError:
        rows = _request_json(BINANCE_FUTURES_DATA, "/openInterestHist", params)
    return {
        _daily_key(row.get("timestamp")): _safe_float(row.get("sumOpenInterest"))
        for row in rows if isinstance(row, dict) and row.get("timestamp") is not None
    }


def _fetch_basis(symbol, start, end):
    rows = _request_json(
        BINANCE_FAPI,
        "/fapi/v1/premiumIndexKlines",
        {
            "symbol": symbol,
            "interval": "1d",
            "startTime": start,
            "endTime": end,
            "limit": 500,
        },
    )
    result = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, list) or len(row) < 5:
            continue
        # Binance premium index kline close is mark/index - 1, represented as a decimal ratio.
        premium_close = _safe_float(row[4])
        if premium_close is not None:
            result[_daily_key(row[0])] = premium_close * 100.0
    return result


def fetch_coin_derivatives(coin, window):
    symbol = f"{coin}USDT"
    funding = {}
    open_interest = {}
    basis = {}
    errors = []
    try:
        funding = _fetch_funding(symbol, window["start"], window["end"])
    except RuntimeError as exc:
        errors.append(f"funding={exc}")
    time.sleep(0.25)
    try:
        open_interest = _fetch_open_interest(symbol, window["start"], window["end"])
    except RuntimeError as exc:
        errors.append(f"open_interest={exc}")
    time.sleep(0.25)
    try:
        basis = _fetch_basis(symbol, window["start"], window["end"])
    except RuntimeError as exc:
        errors.append(f"basis={exc}")
    rows = []
    for bar in window["bars"]:
        ts = _bar_ts(bar)
        key = _daily_key(ts) if ts is not None else None
        item = {"time": ts}
        if key in funding:
            item["funding_rate"] = funding[key]
        if key in open_interest:
            item["open_interest"] = open_interest[key]
        if key in basis:
            item["basis_pct"] = basis[key]
        rows.append(item)
    return rows, errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", default="BTC,ETH,BNB,SOL")
    parser.add_argument("--price-path", default=DEFAULT_PRICE_PATH)
    parser.add_argument("--max-days", type=int, default=240)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    coins = tuple(coin.strip().upper() for coin in args.coins.split(",") if coin.strip())
    windows = _load_price_windows(args.price_path, coins, args.max_days)
    output = {}
    for coin in coins:
        if coin not in windows:
            print(f"{coin}: missing price window")
            continue
        try:
            output[coin], errors = fetch_coin_derivatives(coin, windows[coin])
            filled = sum(
                1
                for row in output[coin]
                if row.get("funding_rate") is not None
                or row.get("open_interest") is not None
                or row.get("basis_pct") is not None
            )
            print(f"{coin}: derivative_bars={filled}/{len(output[coin])}")
            for error in errors:
                print(f"{coin}: partial fetch warning: {error}")
        except Exception as exc:
            print(f"{coin}: fetch failed: {exc}")
        time.sleep(0.5)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
    print(args.output)


if __name__ == "__main__":
    main()
