from collections import Counter

from .. import config
from ..io import record_trade_event


def build_run_summary():
    return {
        "coins_scanned": 0,
        "priced_coins": 0,
        "valid_klines": 0,
        "signals_found": 0,
        "btc_filtered": 0,
        "size_zero": 0,
        "orders_attempted": 0,
        "positions_opened": 0,
        "entry_rejected_count": 0,
        "entry_rejected_reasons": {},
        "missing_price_count": 0,
        "missing_price_coins_sample": [],
        "no_signal_count": 0,
        "priced_ratio": 0.0,
        "top_blockers": [],
        "adopted_positions_count": 0,
        "exchange_open_orders_count": 0,
        "managed_orders_count": 0,
        "orphan_orders_detected_count": 0,
        "orphan_orders_canceled_count": 0,
        "orphan_order_cancel_failures": 0,
        "sl_replaced_count": 0,
        "protection_missing_count": 0,
        "tpsl_missing_count": 0,
        "protection_repaired_count": 0,
        "tpsl_repaired_count": 0,
        "unprotected_positions_count": 0,
    }


def build_strategy_snapshot():
    return {
        "entry_order_type": config.STRATEGY["entry_order_type"],
        "leverage": config.STRATEGY["leverage"],
        "risk_per_trade": config.STRATEGY["risk_per_trade"],
        "max_positions": config.STRATEGY["max_positions"],
        "market_data_source": config.get_market_data_source(),
    }


def build_entry_context(state, coin_name, btc_dir, entry_order_type, **fields):
    context = {
        "coin": coin_name,
        "mode": config.MODE,
        "balance": state.get("balance"),
        "available_balance": None,
        "entry_order_type": entry_order_type,
        "btc_dir": btc_dir,
        "signal_direction": None,
        "signal_score": None,
        "entry": None,
        "sl": None,
        "tp": None,
        "risk_pct": None,
        "raw_size": None,
        "normalized_size": None,
        "order_status": None,
        "verify_status": None,
        "message": None,
        "resolved_price": None,
        "raw_price": None,
        "normalized_price": None,
        "best_bid": None,
        "best_ask": None,
        "price_source": None,
        "strategy_snapshot": build_strategy_snapshot(),
    }
    context.update(fields)
    return context


def bump_summary_blocker(summary, reason, coin_name=None):
    blockers = summary.setdefault("_blockers", Counter())
    blockers[reason] += 1
    if reason == "missing_price":
        summary["missing_price_count"] += 1
        if coin_name and len(summary["missing_price_coins_sample"]) < 10:
            summary["missing_price_coins_sample"].append(coin_name)
    elif reason == "no_signal":
        summary["no_signal_count"] += 1
    elif reason in ("size_zero", "normalized_size_zero"):
        summary["size_zero"] += 1
    elif reason == "btc_filter":
        summary["btc_filtered"] += 1


def finalize_run_summary(summary):
    blockers = summary.pop("_blockers", Counter())
    summary["entry_rejected_reasons"] = dict(summary.get("_rejected_reasons", {}))
    summary.pop("_rejected_reasons", None)
    total = summary["coins_scanned"] or 0
    summary["priced_ratio"] = round(summary["priced_coins"] / total, 4) if total else 0.0
    summary["top_blockers"] = [
        {"reason": reason, "count": count}
        for reason, count in blockers.most_common(5)
    ]
    return summary


def log_entry_skipped(state, coin_name, btc_dir, reason, **fields):
    record_trade_event(
        "entry_skipped",
        reason=reason,
        **build_entry_context(
            state,
            coin_name,
            btc_dir,
            config.STRATEGY["entry_order_type"],
            **fields,
        ),
    )
