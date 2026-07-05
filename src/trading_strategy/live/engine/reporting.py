from datetime import datetime

from .. import config
from ..account import extract_hl_account_value, extract_hl_account_values
from ..io import load_state
from ..orders import classify_verified_order, get_position_entry_oid, verify_hl_order
from .reconcile import extract_live_position_map


def print_report(state):
    total = state["stats"]["total_trades"]
    print(f'\nStatus Report | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   balance: ${state["balance"]:.2f} | source: {state.get("_balance_source", "local_state")}')
    print(f'   positions: {len(state["positions"])}')
    print(f'   trades: {total} | WR: {(state["stats"]["wins"] / total * 100 if total else 0):.0f}%')


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
