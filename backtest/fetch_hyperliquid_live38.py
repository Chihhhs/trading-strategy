"""Fetch a completed-candle Hyperliquid 1h fixture for the frozen live 38."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.live_config import LIVE_UNIVERSE


INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_OUTPUT = Path("data/research_artifacts/hyperliquid_live38_1h.json")


def _parse_end(value):
    if value is None:
        now = datetime.now(timezone.utc)
        return now.replace(minute=0, second=0, microsecond=0)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _request_candles(coin, start_ms, end_ms):
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": "1h",
            "startTime": start_ms,
            "endTime": end_ms,
        },
    }
    request = Request(
        INFO_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, list):
        raise ValueError(f"unexpected Hyperliquid response for {coin}: {result!r}")
    return [
        {
            "time": int(row["t"]),
            "open": float(row["o"]),
            "high": float(row["h"]),
            "low": float(row["l"]),
            "close": float(row["c"]),
            "volume": float(row["v"]),
        }
        for row in result
        if start_ms <= int(row["t"]) < end_ms
    ]


def fetch_fixture(*, end_time, days):
    end_ms = int(end_time.timestamp() * 1000)
    start_ms = int((end_time - timedelta(days=days)).timestamp() * 1000)
    data = {}
    for coin in LIVE_UNIVERSE:
        last_error = None
        for attempt in range(3):
            try:
                data[coin] = _request_candles(coin, start_ms, end_ms)
                break
            except HTTPError as exc:  # pragma: no cover - exchange throttle path
                last_error = exc
                retry_after = exc.headers.get("Retry-After")
                delay = max(5.0, float(retry_after)) if retry_after else 5.0
                time.sleep(delay * (attempt + 1))
            except Exception as exc:  # pragma: no cover - network retry path
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
        else:
            raise RuntimeError(f"failed to fetch {coin}") from last_error
        if not data[coin]:
            raise ValueError(f"Hyperliquid returned no completed 1h candles for {coin}")
        time.sleep(1.0)
    return data, start_ms, end_ms


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-time", help="UTC ISO timestamp, floored to an hour")
    parser.add_argument("--days", type=int, default=240)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.days <= 0:
        raise SystemExit("--days must be positive")
    end_time = _parse_end(args.end_time)
    data, start_ms, end_ms = fetch_fixture(end_time=end_time, days=args.days)
    artifact = {
        "schema_version": 1,
        "source": "hyperliquid_public_info_candleSnapshot",
        "interval": "1h",
        "start_time_ms": start_ms,
        "end_time_exclusive_ms": end_ms,
        "end_time_exclusive": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat(),
        "universe": list(LIVE_UNIVERSE),
        "universe_size": len(LIVE_UNIVERSE),
        "coins": data,
    }
    serialized = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    artifact["payload_sha256"] = hashlib.sha256(serialized).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "end_time_exclusive": artifact["end_time_exclusive"],
                "coins": len(data),
                "min_bars": min(len(rows) for rows in data.values()),
                "max_bars": max(len(rows) for rows in data.values()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
