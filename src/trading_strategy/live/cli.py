import os
import sys
import time
from datetime import datetime

from trading_strategy.core.state import get_state_path

from . import config
from .account import sync_state_with_hl_balance
from .engine import check_entries, print_debug_account, print_report, update_positions, verify_saved_orders
from .io import append_trade_record, load_state, save_state
from .market import get_current_prices, load_coin_list


def run_once():
    state = load_state()
    try:
        if config.MODE == "live" or config.get_account_address():
            state = sync_state_with_hl_balance(state)
        if config.MODE == "live" and state.get("balance", 0) <= 0:
            raise RuntimeError("Hyperliquid perp 可用資金為 0，停止 live 下單")
        coins = load_coin_list()
        print(f'\n[{datetime.now().strftime("%Y-%m-%d %H:%M")}] 餘額: ${state["balance"]:.2f} | 持倉: {len(state["positions"])}')
        print(f"  市場資料來源: {config.get_market_data_source()}")
        print(f'  餘額來源: {state.get("_balance_source", "local_state")}')
        prices = get_current_prices(coins)
        update_positions(state, prices, state.get("_data_cache", {}))
        today = datetime.now().strftime("%Y-%m-%d")
        today_pnl = sum(h.get("pnl", 0) for h in state.get("history", []) if h.get("exit_time", "").startswith(today))
        if today_pnl < -state["balance"] * 0.05:
            print(f"  🔴 每日虧損已達 5%（${today_pnl:.2f}），停止開倉")
        else:
            check_entries(state, coins)
        for pos in state["positions"]:
            if pos["coin"] in prices:
                pos["current_price"] = prices[pos["coin"]]
        print_report(state)
        return state
    finally:
        save_state(state)


def run_loop(interval_minutes=5):
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            append_trade_record({"ts": datetime.now().isoformat(), "event": "loop_stopped", "reason": "keyboard_interrupt"})
            print("\n已停止")
            break
        except Exception as exc:
            append_trade_record({"ts": datetime.now().isoformat(), "event": "loop_error", "reason": str(exc)})
            print(f"\n[ERROR] {exc}")
        print(f"\n等待 {interval_minutes} 分鐘後再次執行...")
        time.sleep(max(interval_minutes, 1) * 60)


def main():
    args = sys.argv[1:]
    interval_minutes = next((int(arg.split("=", 1)[1]) for arg in args if arg.startswith("--interval-minutes=")), 5)
    if "--live" in args:
        config.set_mode("live")
        if not config.get_private_key():
            print("❌ 請設定 HL_PRIVATE_KEY 環境變數")
            sys.exit(1)
        if not config.get_account_address():
            print("❌ live 模式需要 HL_ACCOUNT_ADDRESS 指向實際主帳戶")
            sys.exit(1)
        print("⚠️ 實盤模式！")
    if "--reset" in args:
        path = get_state_path(config.STATE_DIR)
        if os.path.exists(path):
            os.remove(path)
        print("✅ 已重置")
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
