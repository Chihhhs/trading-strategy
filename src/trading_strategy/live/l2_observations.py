"""Append-only Hyperliquid L2 observations for research and replay only."""

from datetime import datetime, timezone
import json
from pathlib import Path

from trading_strategy.hyperliquid import get_best_bid_ask

from . import config


_LAST_CAPTURE_BUCKET = set()


def _bucket(now):
    return now.strftime("%Y-%m-%dT%H:%M")[:-1] + "0Z"


def _levels(levels, limit=5):
    return [
        {"price": row.get("price"), "size": row.get("size")}
        for row in (levels or [])[:limit]
        if row.get("price") is not None and row.get("size") is not None
    ]


def _metrics(summary):
    bid = (summary or {}).get("best_bid") or {}
    ask = (summary or {}).get("best_ask") or {}
    bid_px, ask_px = bid.get("price"), ask.get("price")
    bid_size, ask_size = float(bid.get("size") or 0.0), float(ask.get("size") or 0.0)
    if not bid_px or not ask_px:
        return {}
    mid = (float(bid_px) + float(ask_px)) / 2.0
    depth = bid_size + ask_size
    return {
        "mid": mid,
        "spread_bps": (float(ask_px) - float(bid_px)) / mid * 10000.0 if mid else None,
        "top_depth_usd": float(bid_px) * bid_size + float(ask_px) * ask_size,
        "book_imbalance": (bid_size - ask_size) / depth if depth else 0.0,
    }


def record_l2_observation(coin, *, signal_direction=None, guard=None, correlation_id=None, now=None, book_summary=None):
    """Capture at most one read-only book snapshot per coin and five-minute bucket."""
    now = now or datetime.now(timezone.utc)
    bucket = _bucket(now)
    key = (str(coin).upper(), bucket)
    if key in _LAST_CAPTURE_BUCKET:
        return None
    _LAST_CAPTURE_BUCKET.add(key)
    summary = book_summary or get_best_bid_ask(str(coin).upper(), base_url=config.get_api_url())
    record = {
        "schema_version": 1,
        "timestamp": now.isoformat(),
        "coin": str(coin).upper(),
        "source": "hyperliquid",
        "signal_direction": signal_direction,
        "correlation_id": correlation_id,
        "guard_outcome": dict(guard or {}),
    }
    if not summary:
        record["capture_status"] = "missing_l2"
    else:
        record.update({"capture_status": "ok", "bids": _levels(summary.get("bids")), "asks": _levels(summary.get("asks"))})
        record.update(_metrics(summary))
    target = Path(config.PROJECT_ROOT) / "data" / "l2_observations" / f"{now:%Y-%m-%d}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record
