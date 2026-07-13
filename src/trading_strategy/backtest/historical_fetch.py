import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from .exit_replay import HOUR_MS, normalize_hourly_data


BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


def _request_json(url):
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_binance_hourly_klines(coin, start_ms, end_ms, *, request_json=None, limit=1000):
    request_json = request_json or _request_json
    rows = []
    cursor = int(start_ms)
    while cursor < int(end_ms):
        query = urlencode(
            {
                "symbol": f"{str(coin).upper()}USDT",
                "interval": "1h",
                "startTime": cursor,
                "endTime": int(end_ms) - 1,
                "limit": int(limit),
            }
        )
        page = request_json(f"{BINANCE_KLINES_URL}?{query}")
        if not page:
            break
        for item in page:
            open_time = int(item[0])
            rows.append(
                {
                    "open_time": open_time,
                    "time": datetime.fromtimestamp(open_time / 1000, tz=timezone.utc).isoformat(),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
            )
        next_cursor = int(page[-1][0]) + HOUR_MS
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(page) < int(limit):
            break
    return normalize_hourly_data({str(coin).upper(): rows}).get(str(coin).upper(), [])


def build_hourly_fixture(coins, days, *, now_ms=None, request_json=None):
    end_ms = int(now_ms or datetime.now(tz=timezone.utc).timestamp() * 1000)
    end_ms -= end_ms % HOUR_MS
    start_ms = end_ms - int(days) * 24 * HOUR_MS
    data = {
        str(coin).upper(): fetch_binance_hourly_klines(
            coin,
            start_ms,
            end_ms,
            request_json=request_json,
        )
        for coin in coins
    }
    diagnostics = {
        coin: {
            "expected_bars": int(days) * 24,
            "available_bars": len(bars),
            "coverage_pct": round(len(bars) / (int(days) * 24) * 100, 2) if days else 0.0,
        }
        for coin, bars in data.items()
    }
    return data, diagnostics

