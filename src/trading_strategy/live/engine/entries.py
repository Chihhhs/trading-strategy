from collections import Counter
from datetime import datetime

from trading_strategy.shared.risk import calc_position_size, check_circuit_breaker, is_cooldown
from trading_strategy.strategies.base import signal_value

from .. import config
from ..io import record_trade_event, save_state
from ..market import get_btc_direction, get_current_prices, get_klines
from ..orders import (
    classify_order_rejection,
    normalize_hl_order_params,
    place_hl_order,
)
from .helpers import (
    build_strategy_context,
    calc_atr,
    generate_signal,
    get_active_strategy,
    get_available_entry_balance,
)
from .execution_guard import evaluate_microstructure_guard
from .protection import submit_position_protection
from .summary import (
    build_entry_context,
    build_run_summary,
    build_strategy_snapshot,
    bump_summary_blocker,
    finalize_run_summary,
    log_entry_skipped,
)


def _base_entry_context(state, sig, entry, target_tp, risk_pct, available_balance):
    return {
        "signal_direction": signal_value(sig, "direction"),
        "signal_score": signal_value(sig, "score"),
        "entry": entry,
        "sl": signal_value(sig, "sl"),
        "tp": target_tp,
        "risk_pct": risk_pct,
        "available_balance": available_balance,
    }


def _build_order_context(order_meta):
    return {
        "order_status": (order_meta or {}).get("normalized_status"),
        "verify_status": ((order_meta or {}).get("verified_summary") or {}).get("verify_status"),
        "message": (order_meta or {}).get("message"),
        "resolved_price": (order_meta or {}).get("resolved_price"),
        "raw_price": (order_meta or {}).get("raw_price"),
        "normalized_price": (order_meta or {}).get("normalized_price"),
        "best_bid": (order_meta or {}).get("best_bid"),
        "best_ask": (order_meta or {}).get("best_ask"),
        "price_source": (order_meta or {}).get("price_source"),
    }


def check_entries(state, coins):
    strategy = get_active_strategy()
    summary = build_run_summary()
    summary["coins_scanned"] = len(coins)
    if len(state["positions"]) >= config.STRATEGY["max_positions"]:
        bump_summary_blocker(summary, "max_positions_reached")
        record_trade_event(
            "entry_skipped",
            reason="max_positions_reached",
            mode=config.MODE,
            balance=state.get("balance"),
            entry_order_type=config.STRATEGY["entry_order_type"],
            strategy_snapshot=build_strategy_snapshot(),
        )
        return finalize_run_summary(summary)

    ok, reason = check_circuit_breaker(state, config.CIRCUIT)
    if not ok:
        print(f"  circuit breaker: {reason}")
        bump_summary_blocker(summary, "circuit_breaker")
        record_trade_event(
            "entry_skipped",
            reason="circuit_breaker",
            mode=config.MODE,
            balance=state.get("balance"),
            entry_order_type=config.STRATEGY["entry_order_type"],
            message=reason,
            strategy_snapshot=build_strategy_snapshot(),
        )
        return finalize_run_summary(summary)

    btc_dir, prices = get_btc_direction(), get_current_prices(coins)
    summary["priced_coins"] = len(prices)

    for coin in coins:
        if len(state["positions"]) >= config.STRATEGY["max_positions"]:
            bump_summary_blocker(summary, "max_positions_reached")
            log_entry_skipped(state, coin["name"], btc_dir, "max_positions_reached")
            break

        name = coin["name"]
        if any(pos["coin"] == name for pos in state["positions"]):
            bump_summary_blocker(summary, "existing_position")
            log_entry_skipped(state, name, btc_dir, "existing_position")
            continue
        if is_cooldown(state, name, config.CIRCUIT):
            bump_summary_blocker(summary, "cooldown_active")
            log_entry_skipped(state, name, btc_dir, "cooldown_active")
            continue
        if name not in prices:
            bump_summary_blocker(summary, "missing_price", name)
            log_entry_skipped(state, name, btc_dir, "missing_price")
            continue

        klines = get_klines(coin["symbol"], 60)
        if not klines or len(klines) < 50:
            bump_summary_blocker(summary, "insufficient_klines")
            log_entry_skipped(state, name, btc_dir, "insufficient_klines")
            continue
        summary["valid_klines"] += 1
        state.setdefault("_data_cache", {})[name] = klines

        sig = generate_signal(klines, config.STRATEGY["min_score"])
        if not sig:
            bump_summary_blocker(summary, "no_signal")
            log_entry_skipped(state, name, btc_dir, "no_signal")
            continue
        summary["signals_found"] += 1
        exit_policy = strategy.build_exit_policy(signal=sig)
        target_tp = signal_value(sig, "tp") if exit_policy.get("requires_tp") else None

        if (btc_dir == "bull" and signal_value(sig, "direction") == "short") or (
            btc_dir == "bear" and signal_value(sig, "direction") == "long"
        ):
            bump_summary_blocker(summary, "btc_filter")
            log_entry_skipped(
                state,
                name,
                btc_dir,
                "btc_filter",
                signal_direction=signal_value(sig, "direction"),
                signal_score=signal_value(sig, "score"),
                sl=signal_value(sig, "sl"),
                tp=target_tp,
            )
            continue

        if config.MODE == "live":
            guard = evaluate_microstructure_guard(name, sig)
            if not guard.get("allowed", True):
                reason = guard.get("reason") or "microstructure_guard"
                if config.STRATEGY.get("microstructure_guard_observe_only", False):
                    record_trade_event(
                        "microstructure_guard_observed",
                        **build_entry_context(
                            state,
                            name,
                            btc_dir,
                            config.STRATEGY["entry_order_type"],
                            signal_direction=signal_value(sig, "direction"),
                            signal_score=signal_value(sig, "score"),
                            sl=signal_value(sig, "sl"),
                            tp=target_tp,
                            would_block_reason=reason,
                            spread_bps=guard.get("spread_bps"),
                            top_depth_usd=guard.get("top_depth_usd"),
                            book_imbalance=guard.get("book_imbalance"),
                        ),
                    )
                else:
                    bump_summary_blocker(summary, reason)
                    log_entry_skipped(
                        state,
                        name,
                        btc_dir,
                        reason,
                        signal_direction=signal_value(sig, "direction"),
                        signal_score=signal_value(sig, "score"),
                        sl=signal_value(sig, "sl"),
                        tp=target_tp,
                        spread_bps=guard.get("spread_bps"),
                        top_depth_usd=guard.get("top_depth_usd"),
                        book_imbalance=guard.get("book_imbalance"),
                    )
                    continue

        entry = prices[name]
        atr = calc_atr(
            [d["high"] for d in klines],
            [d["low"] for d in klines],
            [d["close"] for d in klines],
        )
        risk_pct = (
            0.05
            if atr and entry and atr / entry * 100 > 5
            else 0.10
            if atr and entry and atr / entry * 100 < 2
            else config.STRATEGY["risk_per_trade"]
        )
        available_balance = (
            get_available_entry_balance(state, config.STRATEGY["leverage"])
            if config.MODE == "live"
            else state["balance"]
        )
        base_context = _base_entry_context(state, sig, entry, target_tp, risk_pct, available_balance)
        if available_balance <= 0:
            bump_summary_blocker(summary, "reserved_margin_exhausted")
            log_entry_skipped(state, name, btc_dir, "reserved_margin_exhausted", **base_context)
            continue
        size = calc_position_size(
            available_balance,
            entry,
            signal_value(sig, "sl"),
            config.STRATEGY["leverage"],
            risk_pct,
        )
        preview = normalize_hl_order_params(name, size, entry)
        base_context["raw_size"] = size
        base_context["normalized_size"] = preview["size"]

        if size <= 0:
            bump_summary_blocker(summary, "size_zero")
            log_entry_skipped(state, name, btc_dir, "size_zero", **base_context)
            continue
        if preview["size"] <= 0:
            bump_summary_blocker(summary, "normalized_size_zero")
            log_entry_skipped(state, name, btc_dir, "normalized_size_zero", **base_context)
            continue

        order_meta, protection_meta = None, {"tp_order": None, "sl_order": None}
        if config.MODE == "live":
            summary["orders_attempted"] += 1
            record_trade_event(
                "entry_order_attempted",
                **build_entry_context(
                    state,
                    name,
                    btc_dir,
                    config.STRATEGY["entry_order_type"],
                    **base_context,
                ),
            )
            order_meta = place_hl_order(
                name,
                "buy" if signal_value(sig, "direction") == "long" else "sell",
                round(size, 6),
                order_type=config.STRATEGY["entry_order_type"],
            )
            order_context = _build_order_context(order_meta)
            if not order_meta or order_meta.get("status") == "error":
                rejection_reason = (order_meta or {}).get("rejection_reason") or classify_order_rejection(
                    order_context["message"]
                )
                summary["entry_rejected_count"] += 1
                rejected = summary.setdefault("_rejected_reasons", Counter())
                rejected[rejection_reason] += 1
                bump_summary_blocker(summary, rejection_reason)
                record_trade_event(
                    "entry_order_rejected",
                    rejection_reason=rejection_reason,
                    **build_entry_context(
                        state,
                        name,
                        btc_dir,
                        config.STRATEGY["entry_order_type"],
                        **base_context,
                        **order_context,
                    ),
                )
                continue
            if order_context["order_status"] != "filled":
                bump_summary_blocker(summary, "entry_order_not_filled")
                record_trade_event(
                    "entry_order_not_filled",
                    **build_entry_context(
                        state,
                        name,
                        btc_dir,
                        config.STRATEGY["entry_order_type"],
                        **base_context,
                        **order_context,
                    ),
                )
                log_entry_skipped(
                    state,
                    name,
                    btc_dir,
                    "entry_order_not_filled",
                    **base_context,
                    **order_context,
                )
                continue
            entry = order_meta.get("resolved_price", entry)
            position_stub = {
                "coin": name,
                "direction": signal_value(sig, "direction"),
                "size": order_meta.get("size"),
                "exit_policy": exit_policy,
            }
            protection_meta = submit_position_protection(position_stub, target_tp, signal_value(sig, "sl"))
            if not protection_meta.get("ok"):
                failure_reason = "tpsl_submit_failed" if exit_policy.get("requires_tp") else "sl_submit_failed"
                bump_summary_blocker(summary, failure_reason)
                protection_context = dict(order_context)
                protection_context["message"] = protection_meta.get("message")
                record_trade_event(
                    failure_reason,
                    **build_entry_context(
                        state,
                        name,
                        btc_dir,
                        config.STRATEGY["entry_order_type"],
                        **base_context,
                        **protection_context,
                    ),
                )
                log_entry_skipped(
                    state,
                    name,
                    btc_dir,
                    failure_reason,
                    **base_context,
                    **protection_context,
                )
                continue

        position = {
            "coin": name,
            "direction": signal_value(sig, "direction"),
            "entry": entry,
            "tp": target_tp,
            "sl": signal_value(sig, "sl"),
            "size": preview["size"] if config.MODE == "live" else round(size, 6),
            "current_price": entry,
            "pnl_pnl": 0,
            "entry_time": datetime.now().isoformat(),
            "sig": signal_value(sig, "reason", ""),
            "signal_reason": signal_value(sig, "reason", ""),
            "signal_score": signal_value(sig, "score"),
            "entry_reason": signal_value(sig, "reason", ""),
            "btc_dir_at_entry": btc_dir,
            "risk_pct": risk_pct,
            "entry_order_type": config.STRATEGY["entry_order_type"],
            "exit_policy": exit_policy,
            "strategy_name": strategy.name,
            "entry_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"),
            "entry_status": (order_meta or {}).get("normalized_status"),
            "entry_filled_size": (order_meta or {}).get("size"),
            "order_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"),
            "order_status": ((order_meta or {}).get("order_summary") or {}).get("order_status"),
            "tp_order": protection_meta.get("tp_order"),
            "sl_order": protection_meta.get("sl_order"),
            "exchange_position_state": None,
            "position_source": "local_state",
            "protection_status": "protected" if config.MODE == "live" else None,
        }
        position = strategy.initialize_position(
            position,
            sig,
            build_strategy_context(
                name,
                klines,
                price=entry,
                balance=available_balance,
                open_positions=state.get("positions", []),
            ),
        )
        state["positions"].append(position)
        summary["positions_opened"] += 1
        if config.MODE == "live":
            record_trade_event(
                "position_opened",
                coin=name,
                entry_oid=((order_meta or {}).get("order_summary") or {}).get("oid"),
                order_status=(order_meta or {}).get("normalized_status"),
                verify_status=((order_meta or {}).get("verified_summary") or {}).get("verify_status"),
                entry_reason=position.get("entry_reason"),
                signal_score=position.get("signal_score"),
                strategy_snapshot=build_strategy_snapshot(),
            )
            save_state(state)
        print(
            f'  opened: {name} {signal_value(sig, "direction")} @ ${entry:,.2f} | {signal_value(sig, "reason")} | '
            f'score={signal_value(sig, "score")} | mode={"live" if config.MODE == "live" else "paper"} | '
            f'order_status={((order_meta or {}).get("order_summary") or {}).get("order_status", "paper")} | '
            f'verify={((order_meta or {}).get("verified_summary") or {}).get("verify_status", "n/a")}'
        )

    return finalize_run_summary(summary)
