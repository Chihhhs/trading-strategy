from collections import Counter
from hashlib import sha256
import json

from .. import config
from ..io import record_trade_event


def build_run_summary():
    return {
        "schema_version": 3,
        "coins_scanned": 0,
        "priced_coins": 0,
        "valid_klines": 0,
        "signals_found": 0,
        "derivatives_context_observed": 0,
        "derivatives_context_missing": 0,
        "signals_observed": 0,
        "outcomes_observed": 0,
        "pending_observations": 0,
        "minimum_signals": 0,
        "remaining_signals": 0,
        "btc_filtered": 0,
        "size_zero": 0,
        "orders_attempted": 0,
        "positions_opened": 0,
        "positions_count": 0,
        "protected_positions_count": 0,
        "has_unprotected_positions": False,
        "max_positions": config.STRATEGY.get("max_positions"),
        "daily_loss_limit_hit": False,
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
        "stale_positions_count": 0,
        "unknown_orders_count": 0,
        "sl_replaced_count": 0,
        "protection_missing_count": 0,
        "tpsl_missing_count": 0,
        "protection_repaired_count": 0,
        "tpsl_repaired_count": 0,
        "protection_checked_count": 0,
        "ambiguous_protection_count": 0,
        "verification_unknown_count": 0,
        "protection_repair_failed_count": 0,
        "protection_update_failed_count": 0,
        "unprotected_positions_count": 0,
        "position_status_counts": {},
        "position_snapshots": [],
        "decisions_observed": 0,
        "decision_action_counts": {},
        "decision_reason_counts": {},
        "market_context_observed_count": 0,
        "market_context_would_block_count": 0,
        "market_context_regime_counts": {},
    }


def build_strategy_snapshot():
    return {
        "name": config.STRATEGY.get("name", "trend"),
        "coin_universe": config.STRATEGY.get("coin_universe"),
        "entry_order_type": config.STRATEGY["entry_order_type"],
        "leverage": config.STRATEGY["leverage"],
        "risk_per_trade": config.STRATEGY["risk_per_trade"],
        "max_positions": config.STRATEGY["max_positions"],
        "market_data_source": config.get_market_data_source(),
        "derivatives_crowding_exit_enabled": config.STRATEGY.get("derivatives_crowding_exit_enabled", False),
        "derivatives_crowding_action": config.STRATEGY.get("derivatives_crowding_action"),
        "derivatives_crowding_reduce_fraction": config.STRATEGY.get("derivatives_crowding_reduce_fraction"),
        "derivatives_monitor_enabled": config.STRATEGY.get("derivatives_monitor_enabled", False),
        "signal_observation_enabled": config.STRATEGY.get("signal_observation_enabled", False),
        "signal_observation_min_samples": config.STRATEGY.get("signal_observation_min_samples", 30),
        "signal_observation_horizons": config.STRATEGY.get("signal_observation_horizons", (1, 3, 6)),
        "microstructure_guard_enabled": config.STRATEGY.get("microstructure_guard_enabled", False),
        "microstructure_guard_observe_only": config.STRATEGY.get("microstructure_guard_observe_only", False),
        "microstructure_max_spread_bps": config.STRATEGY.get("microstructure_max_spread_bps"),
        "microstructure_min_top_depth_usd": config.STRATEGY.get("microstructure_min_top_depth_usd"),
        "microstructure_max_opposing_imbalance": config.STRATEGY.get("microstructure_max_opposing_imbalance"),
    }


def strategy_fingerprint(snapshot):
    """Return a stable identifier for the runtime configuration being observed."""
    payload = json.dumps(snapshot or {}, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def build_history_metrics(history, start_index=0):
    """Summarize only exits produced during this run without redefining PnL truth."""
    rows = list(history or [])[max(int(start_index or 0), 0) :]
    exit_reasons = Counter(str(row.get("exit_reason") or "unknown") for row in rows)
    turnover = 0.0
    mfe = []
    mae = []
    for row in rows:
        size = float(row.get("size") or 0.0)
        turnover += abs(float(row.get("entry") or 0.0) * size)
        turnover += abs(float(row.get("exit_price", row.get("exit")) or 0.0) * size)
        if row.get("mfe_r") is not None:
            mfe.append(float(row["mfe_r"]))
        if row.get("mae_r") is not None:
            mae.append(float(row["mae_r"]))
    return {
        "run_closed_trades": len(rows),
        "run_turnover_notional": round(turnover, 8),
        "run_exit_reason_counts": dict(exit_reasons),
        "run_avg_mfe_r": round(sum(mfe) / len(mfe), 6) if mfe else None,
        "run_avg_mae_r": round(sum(mae) / len(mae), 6) if mae else None,
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
        "spread_bps": None,
        "top_depth_usd": None,
        "book_imbalance": None,
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


def observe_decision_summary(summary, decision):
    """Add observe-only decision evidence without changing entry eligibility."""
    summary["decisions_observed"] += 1
    action_counts = Counter(summary.get("decision_action_counts") or {})
    action_counts[decision.action] += 1
    summary["decision_action_counts"] = dict(action_counts)
    reason_counts = Counter(summary.get("decision_reason_counts") or {})
    reason_counts.update(decision.reason_codes)
    summary["decision_reason_counts"] = dict(reason_counts)
    context = decision.market_context or {}
    if context:
        summary["market_context_observed_count"] += 1
        regime_counts = Counter(summary.get("market_context_regime_counts") or {})
        regime_counts[context.get("regime", "unknown")] += 1
        summary["market_context_regime_counts"] = dict(regime_counts)
        if not context.get("hypothetical_allowed", True):
            summary["market_context_would_block_count"] += 1
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
