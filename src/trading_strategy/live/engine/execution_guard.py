from trading_strategy.hyperliquid import get_best_bid_ask
from trading_strategy.strategies.base import signal_value

from .. import config


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _book_metrics(summary):
    best_bid = (summary or {}).get("best_bid") or {}
    best_ask = (summary or {}).get("best_ask") or {}
    bid_px = _safe_float(best_bid.get("price"))
    ask_px = _safe_float(best_ask.get("price"))
    bid_size = _safe_float(best_bid.get("size"), 0.0) or 0.0
    ask_size = _safe_float(best_ask.get("size"), 0.0) or 0.0
    if bid_px is None or ask_px is None or bid_px <= 0 or ask_px <= 0:
        return None
    mid = (bid_px + ask_px) / 2.0
    depth_usd = bid_px * bid_size + ask_px * ask_size
    depth = bid_size + ask_size
    return {
        "best_bid": bid_px,
        "best_ask": ask_px,
        "spread_bps": (ask_px - bid_px) / mid * 10000.0 if mid else None,
        "top_depth_usd": depth_usd,
        "book_imbalance": (bid_size - ask_size) / depth if depth else 0.0,
    }


def evaluate_microstructure_guard(coin, signal, *, strategy_config=None, book_summary=None):
    strategy_config = strategy_config or config.STRATEGY
    if not bool(strategy_config.get("microstructure_guard_enabled", False)):
        return {"allowed": True, "reason": "disabled"}

    if book_summary is None:
        book_summary = get_best_bid_ask(coin, base_url=config.get_api_url())
    metrics = _book_metrics(book_summary)
    if not metrics:
        return {"allowed": False, "reason": "microstructure_missing_l2"}

    max_spread = float(strategy_config.get("microstructure_max_spread_bps", 8.0) or 8.0)
    min_depth = float(strategy_config.get("microstructure_min_top_depth_usd", 1000.0) or 0.0)
    max_opposing = float(strategy_config.get("microstructure_max_opposing_imbalance", 0.65) or 0.65)
    direction = str(signal_value(signal, "direction", "") or "").lower()

    if metrics["spread_bps"] is not None and metrics["spread_bps"] > max_spread:
        return {"allowed": False, "reason": "microstructure_spread_too_wide", **metrics}
    if metrics["top_depth_usd"] < min_depth:
        return {"allowed": False, "reason": "microstructure_depth_too_thin", **metrics}
    if direction == "long" and metrics["book_imbalance"] < -max_opposing:
        return {"allowed": False, "reason": "microstructure_opposing_imbalance", **metrics}
    if direction == "short" and metrics["book_imbalance"] > max_opposing:
        return {"allowed": False, "reason": "microstructure_opposing_imbalance", **metrics}
    return {"allowed": True, "reason": "microstructure_ok", **metrics}
