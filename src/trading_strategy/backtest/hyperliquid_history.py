"""Read-only Hyperliquid candle collection for research fixtures."""

from urllib.request import Request, urlopen
import json

from .fixture_metadata import HOUR_MS, build_fixture_metadata


INFO_URL = "https://api.hyperliquid.xyz/info"


def _post(payload):
    request = Request(INFO_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_hourly_candles(coin, start_ms, end_ms, *, request_json=None):
    request_json = request_json or _post
    rows = request_json({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": int(start_ms), "endTime": int(end_ms)}})
    return [
        {"open_time": int(row["t"]), "time": int(row["t"]), "open": float(row["o"]), "high": float(row["h"]), "low": float(row["l"]), "close": float(row["c"]), "volume": float(row.get("v") or 0.0)}
        for row in (rows or []) if isinstance(row, dict) and row.get("t") is not None
    ]


def build_hourly_fixture(coins, start_ms, end_ms, *, request_json=None):
    data = {coin: fetch_hourly_candles(coin, start_ms, end_ms, request_json=request_json) for coin in coins}
    return data, build_fixture_metadata(data, venue="hyperliquid", market_type="perpetual", interval="1h", start_ms=start_ms, end_ms=end_ms, request_parameters={"type": "candleSnapshot", "limit_note": "most recent 5000 candles"})
