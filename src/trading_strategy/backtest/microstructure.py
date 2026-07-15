import json


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top_level(levels):
    if not levels:
        return None
    first = levels[0]
    if isinstance(first, dict):
        price = _safe_float(first.get("price") or first.get("px"))
        size = _safe_float(first.get("size") or first.get("sz"))
        return price, size
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        return _safe_float(first[0]), _safe_float(first[1])
    return None


def normalize_l2_snapshots(payload):
    normalized = {}
    for coin, snapshots in (payload or {}).items():
        if not isinstance(snapshots, list):
            continue
        rows = []
        for item in snapshots:
            if not isinstance(item, dict):
                continue
            bids = item.get("bids") or []
            asks = item.get("asks") or []
            bid = _top_level(bids)
            ask = _top_level(asks)
            if not bid or not ask or bid[0] is None or ask[0] is None:
                continue
            bid_size = bid[1] or 0.0
            ask_size = ask[1] or 0.0
            depth = bid_size + ask_size
            rows.append(
                {
                    "timestamp": item.get("timestamp") or item.get("time") or item.get("ts"),
                    "bid_px": bid[0],
                    "bid_size": bid_size,
                    "ask_px": ask[0],
                    "ask_size": ask_size,
                    "mid": (bid[0] + ask[0]) / 2.0,
                    "spread": ask[0] - bid[0],
                    "spread_bps": ((ask[0] - bid[0]) / ((ask[0] + bid[0]) / 2.0) * 10000.0)
                    if (ask[0] + bid[0])
                    else 0.0,
                    "book_imbalance": ((bid_size - ask_size) / depth) if depth else 0.0,
                    "top_depth_usd": bid[0] * bid_size + ask[0] * ask_size,
                    "signal_direction": item.get("signal_direction"),
                }
            )
        normalized[str(coin).upper()] = rows
    return normalized


def load_l2_observation_jsonl(path):
    """Load append-only live observation rows into the existing replay shape."""
    snapshots = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict) or item.get("capture_status") != "ok":
                continue
            coin = str(item.get("coin") or "").upper()
            if not coin:
                continue
            snapshots.setdefault(coin, []).append(item)
    return normalize_l2_snapshots(snapshots)


def build_microstructure_diagnostic_report(snapshots_by_coin):
    rows = []
    for coin, snapshots in (snapshots_by_coin or {}).items():
        spreads = [float(item.get("spread_bps") or 0.0) for item in snapshots]
        imbalances = [float(item.get("book_imbalance") or 0.0) for item in snapshots]
        rows.append(
            {
                "coin": coin,
                "snapshots": len(snapshots),
                "avg_spread_bps": round(sum(spreads) / len(spreads), 2) if spreads else 0.0,
                "max_spread_bps": round(max(spreads), 2) if spreads else 0.0,
                "avg_abs_imbalance": round(sum(abs(value) for value in imbalances) / len(imbalances), 3)
                if imbalances
                else 0.0,
            }
        )
    return rows


def build_microstructure_guard_outcome_report(
    snapshots_by_coin,
    *,
    max_spread_bps=8.0,
    min_top_depth_usd=1000.0,
    max_opposing_imbalance=0.65,
    forward_steps=(1, 3),
):
    rows = []
    for coin, snapshots in (snapshots_by_coin or {}).items():
        for forward_step in forward_steps:
            blocked_returns = []
            allowed_returns = []
            for index, snapshot in enumerate(snapshots):
                if index + forward_step >= len(snapshots):
                    continue
                direction = str(snapshot.get("signal_direction") or "").lower()
                if direction not in ("long", "short") or not snapshot.get("mid"):
                    continue
                imbalance = float(snapshot.get("book_imbalance") or 0.0)
                opposing = (direction == "long" and imbalance < -max_opposing_imbalance) or (
                    direction == "short" and imbalance > max_opposing_imbalance
                )
                would_block = (
                    float(snapshot.get("spread_bps") or 0.0) > max_spread_bps
                    or float(snapshot.get("top_depth_usd") or 0.0) < min_top_depth_usd
                    or opposing
                )
                forward_return = (float(snapshots[index + forward_step]["mid"]) / float(snapshot["mid"]) - 1.0) * 100.0
                if direction == "short":
                    forward_return = -forward_return
                (blocked_returns if would_block else allowed_returns).append(forward_return)
            rows.append(
                {
                    "coin": coin,
                    "forward_steps": forward_step,
                    "would_block_events": len(blocked_returns),
                    "allowed_events": len(allowed_returns),
                    "would_block_forward_return_pct": round(sum(blocked_returns) / len(blocked_returns), 4) if blocked_returns else 0.0,
                    "allowed_forward_return_pct": round(sum(allowed_returns) / len(allowed_returns), 4) if allowed_returns else 0.0,
                }
            )
    return rows


def format_microstructure_guard_outcome_lines(rows):
    lines = ["Microstructure guard outcome report"]
    for row in rows:
        lines.append(
            "{coin} forward={forward_steps}: would_block={would_block_events} return={would_block_forward_return_pct:+.4f}% | allowed={allowed_events} return={allowed_forward_return_pct:+.4f}%".format(
                **row
            )
        )
    return lines
