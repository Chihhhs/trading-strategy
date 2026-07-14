from datetime import datetime

from trading_strategy.positions import build_position_snapshots, build_position_status_counts

from .. import config
from ..account import extract_hl_account_value, extract_hl_account_values
from ..io import load_state
from ..orders import classify_verified_order, get_position_entry_oid, verify_hl_order
from .reconcile import extract_live_position_map


def print_report(state):
    total = state["stats"]["total_trades"]
    position_counts = build_position_status_counts(state.get("positions", []), mode=config.MODE)
    position_snapshots = build_position_snapshots(state.get("positions", []), mode=config.MODE)
    print(f'\nStatus Report | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   balance: ${state["balance"]:.2f} | source: {state.get("_balance_source", "local_state")}')
    print(f'   positions: {len(state["positions"])}')
    print(f'   trades: {total} | WR: {(state["stats"]["wins"] / total * 100 if total else 0):.0f}%')
    if position_counts:
        counts_text = ", ".join(f"{key}={value}" for key, value in sorted(position_counts.items()))
        print(f"   position states: {counts_text}")
    for snapshot in position_snapshots:
        pnl_text = "n/a" if snapshot["pnl"] is None else f'{snapshot["pnl"]:+.2f}'
        pnl_pct_text = "n/a" if snapshot["pnl_pct"] is None else f'{snapshot["pnl_pct"]:+.2f}%'
        entry_text = "n/a" if snapshot["entry"] is None else f'{snapshot["entry"]:.4f}'
        price_text = "n/a" if snapshot["current_price"] is None else f'{snapshot["current_price"]:.4f}'
        print(
            f'   - {snapshot["coin"]} {snapshot["direction"]} '
            f'entry={entry_text} current={price_text} pnl={pnl_text} ({pnl_pct_text}) '
            f'status={snapshot["lifecycle_status"]} protection={snapshot["protection_status"] or "n/a"}'
        )
        detail_parts = []
        if snapshot.get("strategy_name"):
            detail_parts.append(f'strategy={snapshot["strategy_name"]}')
        if snapshot.get("pending_exit_reason"):
            detail_parts.append(f'pending_exit={snapshot["pending_exit_reason"]}')
        if snapshot.get("entry_reason"):
            detail_parts.append(f'entry_reason={snapshot["entry_reason"]}')
        if snapshot.get("signal_score") is not None:
            detail_parts.append(f'score={snapshot["signal_score"]}')
        if snapshot.get("position_source"):
            detail_parts.append(f'source={snapshot["position_source"]}')
        if snapshot.get("bars_since_entry") is not None:
            detail_parts.append(f'bars={snapshot["bars_since_entry"]}')
        if snapshot.get("sl_stage") is not None:
            detail_parts.append(f'sl_stage={snapshot["sl_stage"]}')
        if snapshot.get("best_price") is not None:
            detail_parts.append(f'best={snapshot["best_price"]:.4f}')
        if snapshot.get("sl_order_oid") is not None or snapshot.get("tp_order_oid") is not None:
            detail_parts.append(
                f'sl_oid={snapshot.get("sl_order_oid")} tp_oid={snapshot.get("tp_order_oid")}'
            )
        if detail_parts:
            print(f'     {" | ".join(detail_parts)}')


def print_debug_account():
    from ..account import (
        get_api_wallet_address,
        get_hl_account_address,
        get_hl_balance,
        get_hl_client_error,
    )

    balance_info = get_hl_balance()
    account_values = extract_hl_account_values(balance_info)
    print("\nAccount Debug")
    print(f'   HL_PRIVATE_KEY: {"set" if config.get_private_key() else "missing"}')
    print(f'   HL_ACCOUNT_ADDRESS: {config.get_account_address() or "(missing)"}')
    print(f'   derived_api_wallet_address: {get_api_wallet_address() or "(unavailable)"}')
    print(f'   query_address: {get_hl_account_address() or "(missing)"}')
    print(f'   hl_client_error: {get_hl_client_error() or "(none)"}')
    print(f'   effective_balance: {extract_hl_account_value(balance_info)}')
    print(f'   perp_account_value: {account_values.get("perp_account_value")}')
    print(f'   spot_account_value: {account_values.get("spot_account_value")}')


def verify_saved_orders():
    from ..account import sync_state_with_hl_balance

    state = sync_state_with_hl_balance(load_state())
    print("\nOrder Verify")
    print(
        f'   live positions: {len(extract_live_position_map(((state.get("_hl_balance_info") or {}).get("perp"))))}'
    )
    print(f'   open orders: {len((state.get("_frontend_open_orders") or []))}')
    for pos in state.get("positions", []):
        oid = get_position_entry_oid(pos)
        if oid is None:
            print(f'   {pos.get("coin")}: missing oid')
            continue
        summary = classify_verified_order(verify_hl_order(oid))
        print(
            f'   {pos.get("coin")}: oid={oid} | '
            f'local={pos.get("entry_status", pos.get("order_status", "unknown"))} | '
            f'verify={summary.get("verify_status", "unknown")} | '
            f'msg={summary.get("message", "")}'
        )
