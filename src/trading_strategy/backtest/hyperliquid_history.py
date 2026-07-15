"""Read-only Hyperliquid candle collection for research fixtures."""

from datetime import datetime, timezone
import json
from urllib.request import Request, urlopen

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


def collect_hourly_candles(coin, *, start_ms, end_ms, fetch=None, page_hours=4800):
    """Collect a bounded history in pages and remove duplicate timestamps."""
    rows = {}
    cursor = int(start_ms)
    while cursor < int(end_ms):
        page_end = min(cursor + int(page_hours) * HOUR_MS, int(end_ms))
        try:
            page = fetch_hourly_candles(coin, cursor, page_end, request_json=fetch or _post)
        except Exception:
            return None
        if not page:
            return None
        rows.update({row["time"]: row for row in page})
        cursor = page_end
    return [rows[key] for key in sorted(rows)]


def collect_fixture(coins, *, days=240, now_ms=None, fetch=None):
    end_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - int(days) * 24 * HOUR_MS
    data, missing = {}, []
    for coin in coins:
        name = str(coin).upper()
        rows = collect_hourly_candles(name, start_ms=start_ms, end_ms=end_ms, fetch=fetch)
        if not rows:
            missing.append(name)
        else:
            data[name] = rows
    return {"schema_version": 1, "source": "hyperliquid", "interval": "1h", "start_ms": start_ms, "end_ms": end_ms, "requested_coins": [str(coin).upper() for coin in coins], "missing_coins": missing, "data": data}
