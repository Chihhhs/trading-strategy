from datetime import datetime, timedelta

from trading_strategy.core.risk import calc_position_size, check_circuit_breaker, is_cooldown
from trading_strategy.core.signals import generate_trend_signal

from . import config
from .account import get_hl_frontend_open_orders, get_hl_perp_user_state
from .io import append_trade_record, load_state, save_state
from .market import get_btc_direction, get_current_prices, get_klines
from .orders import build_order_ref, classify_verified_order, close_hl_position, get_position_entry_oid, normalize_hl_order_params, place_hl_order, place_hl_tpsl_orders, verify_hl_order


def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    ema = sum(closes[:period]) / period
    weight = 2 / (period + 1)
    for close in closes[period:]:
        ema = close * weight + ema * (1 - weight)
    return ema


def calc_atr(highs, lows, closes, period=14):
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(highs))]
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def generate_signal(klines, min_score=4):
    return generate_trend_signal(klines, min_score=min_score, tp_mult=config.STRATEGY["tp_mult"], sl_mult=config.STRATEGY["sl_mult"])


def check_trend_reversal(pos, klines):
    if not klines or len(klines) < 30:
        return False
    closes = [d["close"] for d in klines]
    e20, e50 = calc_ema(closes, 20), calc_ema(closes, 50)
    e20_prev = calc_ema(closes[:-1], 20)
    e50_prev = calc_ema(closes[:-1], 50) if len(closes) > 50 else e50
    cur = closes[-1]
    if pos["direction"] == "long":
        return cur < e20 and e20 < e50 and e20_prev >= e50_prev
    return cur > e20 and e20 > e50 and e20_prev <= e50_prev


def extract_open_order_map(frontend_open_orders):
    order_map = {}
    for order in frontend_open_orders or []:
        if isinstance(order, dict) and order.get("oid") is not None:
            order_map[int(order["oid"])] = order
        for child in (order.get("children") or []) if isinstance(order, dict) else []:
            if isinstance(child, dict) and child.get("oid") is not None:
                order_map[int(child["oid"])] = child
    return order_map


def extract_live_position_map(perp_state):
    positions = {}
    for item in (perp_state or {}).get("assetPositions") or []:
        position = (item or {}).get("position") or {}
        if position.get("coin"):
            positions[position["coin"]] = position
    return positions


def sync_state_with_exchange_positions(state, perp_state=None, frontend_open_orders=None):
    if config.MODE != "live":
        return state
    perp_state = perp_state if perp_state is not None else get_hl_perp_user_state()
    frontend_open_orders = frontend_open_orders if frontend_open_orders is not None else get_hl_frontend_open_orders()
    live_positions = extract_live_position_map(perp_state)
    open_orders = extract_open_order_map(frontend_open_orders)
    state["positions"] = [
        {**pos, "exchange_position_state": {"coin": pos["coin"], "entryPx": live_positions[pos["coin"]].get("entryPx"), "szi": live_positions[pos["coin"]].get("szi")}}
        for pos in state.get("positions", [])
        if pos.get("coin") in live_positions or (get_position_entry_oid(pos) is not None and open_orders.get(int(get_position_entry_oid(pos))) and not open_orders[int(get_position_entry_oid(pos))].get("reduceOnly"))
    ]
    state["_stale_positions"] = [pos.get("coin") for pos in state.get("positions", []) if pos.get("coin") not in live_positions]
    state["_frontend_open_orders"] = frontend_open_orders
    return state


def update_positions(state, prices, data_cache):
    if config.MODE == "live":
        state = sync_state_with_exchange_positions(state)
        still_open = []
        for pos in state["positions"]:
            if pos["coin"] in prices:
                pos["current_price"] = prices[pos["coin"]]
                pos["pnl_pnl"] = (prices[pos["coin"]] - pos["entry"]) * pos["size"] if pos["direction"] == "long" else (pos["entry"] - prices[pos["coin"]]) * pos["size"]
            should_close = check_trend_reversal(pos, data_cache.get(pos["coin"])) if pos["coin"] in data_cache else False
            if not should_close:
                try:
                    should_close = datetime.now() - datetime.fromisoformat(pos["entry_time"]) > timedelta(days=config.STRATEGY["max_hold_days"])
                except Exception:
                    should_close = False
            if should_close and close_hl_position(pos, "REVERSAL").get("status") == "ok":
                append_trade_record({"ts": datetime.now().isoformat(), "event": "position_close_submitted", "coin": pos["coin"]})
                continue
            still_open.append(pos)
        state["positions"] = still_open
        return
    still_open = []
    for pos in state["positions"]:
        current = prices.get(pos["coin"])
        if current is None:
            still_open.append(pos)
            continue
        pos["current_price"] = current
        pos["pnl_pnl"] = (current - pos["entry"]) * pos["size"] if pos["direction"] == "long" else (pos["entry"] - current) * pos["size"]
        should_close = (current >= pos["tp"] or current <= pos["sl"]) if pos["direction"] == "long" else (current <= pos["tp"] or current >= pos["sl"])
        if should_close:
            state["balance"] += pos["pnl_pnl"]
            state["stats"]["total_trades"] += 1
            state["stats"]["total_pnl"] += pos["pnl_pnl"]
            state["history"].append({"coin": pos["coin"], "dir": pos["direction"], "entry": pos["entry"], "exit": current, "pnl": round(pos["pnl_pnl"], 4), "exit_time": datetime.now().isoformat()})
        else:
            still_open.append(pos)
    state["positions"] = still_open


def check_entries(state, coins):
    if len(state["positions"]) >= config.STRATEGY["max_positions"]:
        return
    ok, reason = check_circuit_breaker(state, config.CIRCUIT)
    if not ok:
        print(f"  🔴 熔斷: {reason}")
        return
    btc_dir, prices = get_btc_direction(), get_current_prices(coins)
    for coin in coins:
        if len(state["positions"]) >= config.STRATEGY["max_positions"]:
            break
        name = coin["name"]
        if any(pos["coin"] == name for pos in state["positions"]) or is_cooldown(state, name, config.CIRCUIT) or name not in prices:
            continue
        klines = get_klines(coin["symbol"], 60)
        if not klines or len(klines) < 50:
            continue
        state.setdefault("_data_cache", {})[name] = klines
        sig = generate_signal(klines, config.STRATEGY["min_score"])
        if not sig or (btc_dir == "bull" and sig["direction"] == "short") or (btc_dir == "bear" and sig["direction"] == "long"):
            continue
        entry = prices[name]
        atr = calc_atr([d["high"] for d in klines], [d["low"] for d in klines], [d["close"] for d in klines])
        risk_pct = 0.05 if atr and entry and atr / entry * 100 > 5 else 0.10 if atr and entry and atr / entry * 100 < 2 else config.STRATEGY["risk_per_trade"]
        size = calc_position_size(state["balance"], entry, sig["sl"], config.STRATEGY["leverage"], risk_pct)
        preview = normalize_hl_order_params(name, size, entry)
        if size <= 0 or preview["size"] <= 0:
            continue
        order_meta, tpsl_meta = None, {"tp_order": None, "sl_order": None}
        if config.MODE == "live":
            order_meta = place_hl_order(name, "buy" if sig["direction"] == "long" else "sell", round(size, 6), order_type=config.STRATEGY["entry_order_type"])
            if not order_meta or order_meta.get("status") == "error" or order_meta.get("normalized_status") != "filled":
                continue
            entry = order_meta.get("resolved_price", entry)
            tpsl_meta = place_hl_tpsl_orders(name, sig["direction"], order_meta.get("size"), sig["tp"], sig["sl"])
            if not tpsl_meta.get("ok"):
                continue
        state["positions"].append({
            "coin": name, "direction": sig["direction"], "entry": entry, "tp": sig["tp"], "sl": sig["sl"], "size": preview["size"] if config.MODE == "live" else round(size, 6),
            "current_price": entry, "pnl_pnl": 0, "entry_time": datetime.now().isoformat(), "sig": sig.get("reason", ""),
            "entry_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"), "entry_status": (order_meta or {}).get("normalized_status"), "entry_filled_size": (order_meta or {}).get("size"),
            "order_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"), "order_status": ((order_meta or {}).get("order_summary") or {}).get("order_status"),
            "tp_order": tpsl_meta.get("tp_order"), "sl_order": tpsl_meta.get("sl_order"), "exchange_position_state": None,
        })
        if config.MODE == "live":
            append_trade_record({"ts": datetime.now().isoformat(), "event": "position_opened", "coin": name, "entry_oid": ((order_meta or {}).get("order_summary") or {}).get("oid")})
            save_state(state)
        print(f'  ✅ 建倉: {name} {sig["direction"]} @ ${entry:,.2f} | {sig["reason"]} | score={sig["score"]} | mode={"live" if config.MODE == "live" else "paper"} | order_status={((order_meta or {}).get("order_summary") or {}).get("order_status", "paper")} | verify={((order_meta or {}).get("verified_summary") or {}).get("verify_status", "n/a")}')


def print_report(state):
    total = state["stats"]["total_trades"]
    print(f'\n帳戶報告 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   餘額: ${state["balance"]:.2f} | 來源: {state.get("_balance_source", "local_state")}')
    print(f'   持倉: {len(state["positions"])}')
    print(f'   交易: {total} 筆 | WR: {(state["stats"]["wins"] / total * 100 if total else 0):.0f}%')


def print_debug_account():
    from .account import get_api_wallet_address, get_hl_account_address, get_hl_balance, get_hl_client_error, extract_hl_account_value

    balance_info = get_hl_balance()
    print("\nAccount Debug")
    print(f'   HL_PRIVATE_KEY: {"set" if config.get_private_key() else "missing"}')
    print(f'   HL_ACCOUNT_ADDRESS: {config.get_account_address() or "(missing)"}')
    print(f'   derived_api_wallet_address: {get_api_wallet_address() or "(unavailable)"}')
    print(f'   query_address: {get_hl_account_address() or "(missing)"}')
    print(f'   hl_client_error: {get_hl_client_error() or "(none)"}')
    print(f'   extracted_account_value: {extract_hl_account_value(balance_info)}')


def verify_saved_orders():
    from .account import sync_state_with_hl_balance

    state = sync_state_with_hl_balance(load_state())
    print("\nOrder Verify")
    print(f'   真實持倉數: {len(extract_live_position_map(((state.get("_hl_balance_info") or {}).get("perp"))))}')
    print(f'   真實開單數: {len((state.get("_frontend_open_orders") or []))}')
    for pos in state.get("positions", []):
        oid = get_position_entry_oid(pos)
        if oid is None:
            print(f'   {pos.get("coin")}: 無 oid，無法回查')
            continue
        summary = classify_verified_order(verify_hl_order(oid))
        print(f'   {pos.get("coin")}: oid={oid} | local={pos.get("entry_status", pos.get("order_status", "unknown"))} | verify={summary.get("verify_status", "unknown")} | msg={summary.get("message", "")}')
