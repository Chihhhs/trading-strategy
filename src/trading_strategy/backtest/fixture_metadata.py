"""Provenance and completeness checks for immutable replay fixtures."""

from datetime import datetime, timezone
from hashlib import sha256
import json


HOUR_MS = 60 * 60 * 1000


def build_fixture_metadata(data, *, venue, market_type, interval, start_ms, end_ms, request_parameters=None):
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    expected = max(0, (int(end_ms) - int(start_ms)) // HOUR_MS) if interval == "1h" else 0
    coverage = {}
    gaps = {}
    for coin, bars in sorted((data or {}).items()):
        timestamps = sorted({int(bar.get("open_time", bar.get("t"))) for bar in bars if bar.get("open_time", bar.get("t")) is not None})
        coverage[coin] = len(timestamps)
        gaps[coin] = [right for left, right in zip(timestamps, timestamps[1:]) if right - left != HOUR_MS]
    complete = bool(coverage) and all(count >= expected for count in coverage.values()) and not any(gaps.values())
    return {
        "schema_version": 1,
        "venue": venue,
        "market_type": market_type,
        "interval": interval,
        "start_ms": int(start_ms),
        "end_ms": int(end_ms),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_parameters": dict(request_parameters or {}),
        "coverage_bars": coverage,
        "gap_after_open_times": gaps,
        "expected_bars_per_coin": expected,
        "complete": complete,
        "checksum_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def require_complete_fixture(metadata):
    if not isinstance(metadata, dict) or not metadata.get("complete"):
        raise ValueError("replay fixture is incomplete; cannot use it as promotion evidence")
    return metadata
