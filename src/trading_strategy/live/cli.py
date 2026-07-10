import os
import sys
import time
from datetime import datetime

from trading_strategy.positions import build_position_snapshots, build_position_status_counts
from trading_strategy.shared.state import get_state_path

from . import config
from .account import sync_state_with_hl_balance
from .engine.entries import check_entries
from .engine.positions import update_positions
from .engine.protection import cancel_orphan_orders, ensure_position_protection
from .engine.reporting import print_debug_account, print_report, verify_saved_orders
from .engine.summary import build_run_summary, build_strategy_snapshot
from .io import load_state, record_trade_event, save_state
from .market import get_current_prices, load_coin_list


def ensure_live_perp_balance(state):
    if config.MODE != "live":
        return
    perp_balance = state.get("_perp_account_value")
    if perp_balance is None:
        raise RuntimeError("Unable to determine Hyperliquid perp account value for live trading")
    if perp_balance <= 0:
        raise RuntimeError("Hyperliquid perp tradable balance is 0; fund perp margin before live trading")


def maybe_log_config_mismatch(state):
    saved_params = state.get("params")
    runtime_snapshot = build_strategy_snapshot()
    if not isinstance(saved_params, dict):
        return
    mismatches = {
        key: {"saved": saved_params.get(key), "runtime": runtime_snapshot.get(key)}
        for key in ("entry_order_type", "leverage", "risk_per_trade", "max_positions")
        if saved_params.get(key) != runtime_snapshot.get(key)
    }
    if mismatches:
        record_trade_event(
            "config_mismatch",
            saved_params=saved_params,
            strategy_snapshot=runtime_snapshot,
            mismatches=mismatches,
        )


def run_once():
    state = load_state()
    try:
        if config.MODE == "live" or config.get_account_address():
            state = sync_state_with_hl_balance(state)
        ensure_live_perp_balance(state)
        maybe_log_config_mismatch(state)
        coins = load_coin_list()
        prices = get_current_prices(coins)
        for pos in state.get("positions", []):
            if pos.get("coin") in prices:
                pos["current_price"] = prices[pos["coin"]]
        cancel_summary = cancel_orphan_orders(state) if config.MODE == "live" else {
            "orphan_orders_detected_count": 0,
            "orphan_orders_canceled_count": 0,
            "orphan_order_cancel_failures": 0,
        }
        protection_summary = ensure_position_protection(state) if config.MODE == "live" else {
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

        strategy_snapshot = build_strategy_snapshot()
        record_trade_event(
            "run_started",
            mode=config.MODE,
            entry_order_type=config.STRATEGY["entry_order_type"],
            balance=state.get("balance"),
            balance_source=state.get("_balance_source"),
            positions=len(state.get("positions", [])),
            strategy_snapshot=strategy_snapshot,
        )
        record_trade_event(
            "account_snapshot",
            mode=config.MODE,
            entry_order_type=config.STRATEGY["entry_order_type"],
            balance=state.get("balance"),
            balance_source=state.get("_balance_source"),
            perp_account_value=state.get("_perp_account_value"),
            spot_account_value=state.get("_spot_account_value"),
            balance_warning=state.get("_balance_warning"),
            positions=len(state.get("positions", [])),
            strategy_snapshot=strategy_snapshot,
        )

        print(
            f'\n[{datetime.now().strftime("%Y-%m-%d %H:%M")}] '
            f'balance: ${state["balance"]:.2f} | positions: {len(state["positions"])}'
        )
        print(f"  market data source: {config.get_market_data_source()}")
        print(f'  balance source: {state.get("_balance_source", "local_state")}')
        print(f'  perp account value: {state.get("_perp_account_value")}')
        print(f'  spot account value: {state.get("_spot_account_value")}')

        update_positions(state, prices, state.get("_data_cache", {}))

        today = datetime.now().strftime("%Y-%m-%d")
        today_pnl = sum(
            h.get("pnl", 0)
            for h in state.get("history", [])
            if h.get("exit_time", "").startswith(today)
        )
        if today_pnl < -state["balance"] * 0.05:
            print(f"  daily loss limit hit: {today_pnl:.2f}")
            entry_summary = build_run_summary()
            entry_summary["coins_scanned"] = len(coins)
            entry_summary["priced_coins"] = len(prices)
            if entry_summary["coins_scanned"]:
                entry_summary["priced_ratio"] = round(
                    entry_summary["priced_coins"] / entry_summary["coins_scanned"], 4
                )
            entry_summary["top_blockers"] = [{"reason": "daily_loss_limit", "count": 1}]
        elif protection_summary["unprotected_positions_count"] > 0:
            print("  unprotected positions detected; skipping new entries")
            entry_summary = build_run_summary()
            entry_summary["coins_scanned"] = len(coins)
            entry_summary["priced_coins"] = len(prices)
            if entry_summary["coins_scanned"]:
                entry_summary["priced_ratio"] = round(
                    entry_summary["priced_coins"] / entry_summary["coins_scanned"], 4
                )
            entry_summary["top_blockers"] = [{"reason": "unprotected_positions", "count": protection_summary["unprotected_positions_count"]}]
        else:
            entry_summary = check_entries(state, coins)

        entry_summary.setdefault("exchange_open_orders_count", state.get("_exchange_open_orders_count", 0))
        entry_summary.setdefault("managed_orders_count", len(state.get("managed_orders") or []))
        entry_summary.update(cancel_summary)
        entry_summary.update(protection_summary)
        entry_summary["position_status_counts"] = build_position_status_counts(
            state.get("positions", []),
            mode=config.MODE,
        )
        entry_summary["position_snapshots"] = build_position_snapshots(
            state.get("positions", []),
            mode=config.MODE,
        )

        for pos in state["positions"]:
            if pos["coin"] in prices:
                pos["current_price"] = prices[pos["coin"]]

        record_trade_event("run_summary", strategy_snapshot=strategy_snapshot, **entry_summary)
        print_report(state)
        return state
    finally:
        save_state(state)


def run_loop(interval_minutes=5):
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            record_trade_event("loop_stopped", reason="keyboard_interrupt")
            print("\nLoop stopped")
            break
        except Exception as exc:
            record_trade_event("loop_error", reason=str(exc))
            print(f"\n[ERROR] {exc}")
        print(f"\nSleeping {interval_minutes} minute(s) before next run...")
        time.sleep(max(interval_minutes, 1) * 60)


def main():
    args = sys.argv[1:]
    interval_minutes = next(
        (int(arg.split("=", 1)[1]) for arg in args if arg.startswith("--interval-minutes=")),
        5,
    )
    if "--live" in args:
        config.set_mode("live")
        if not config.get_private_key():
            print("Missing HL_PRIVATE_KEY")
            sys.exit(1)
        if not config.get_account_address():
            print("Live mode requires HL_ACCOUNT_ADDRESS")
            sys.exit(1)
        print("Running in live mode")
    if "--reset" in args:
        path = get_state_path(config.STATE_DIR)
        if os.path.exists(path):
            os.remove(path)
        print("State reset")
        return
    if "--report" in args:
        state = load_state()
        if config.MODE == "live" or config.get_account_address():
            state = sync_state_with_hl_balance(state)
        print_report(state)
        return
    if "--debug-account" in args:
        print_debug_account()
        return
    if "--verify-orders" in args:
        verify_saved_orders()
        return
    if "--loop" in args:
        run_loop(interval_minutes)
    else:
        run_once()
