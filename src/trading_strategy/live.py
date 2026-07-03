#!/usr/bin/env python3
"""
live.py - 獨立可移植的 FVG + 趨勢實盤策略
版本: 2026-06-30
1000天回測最佳參數：5x + 8% + 趨勢反轉檢測

使用方式:
  Live runner:  python apps/runners/live_runner.py --live
  持續執行:     python apps/runners/live_runner.py --live --loop
  重置狀態:     python apps/fvg_live_strategy.py --reset

實盤前置:
  1. export HL_PRIVATE_KEY="0x你的私鑰"
  2. export HL_ACCOUNT_ADDRESS="0x你的主帳戶地址"
     (相容舊名: HL_WALLET_ADDRESS)
  3. export HL_API_URL="https://api.hyperliquid.xyz" (可自訂)
"""
import sys, os, json, statistics, time, hashlib
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
import threading
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

from trading_strategy.core.risk import calc_position_size, check_circuit_breaker, is_cooldown
from trading_strategy.core.signals import generate_trend_signal, get_btc_direction_from_klines
from trading_strategy.core.state import get_state_path
from trading_strategy.core.state import load_state as load_state_file
from trading_strategy.core.state import save_state as save_state_file
from trading_strategy.hyperliquid import choose_limit_price
try:
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
except ImportError:
    Account = None
    Exchange = None
    Info = None

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

MODE = "paper"  # "paper" 或 "live"

# 環境變數
PRIVATE_KEY = os.environ.get("HL_PRIVATE_KEY", "")
ACCOUNT_ADDRESS = os.environ.get("HL_ACCOUNT_ADDRESS", "") or os.environ.get("HL_WALLET_ADDRESS", "")
HL_API_URL = os.environ.get("HL_API_URL", "https://api.hyperliquid.xyz")
MARKET_DATA_SOURCE = os.environ.get("MARKET_DATA_SOURCE", "auto").lower()
DEBUG_API = os.environ.get("DEBUG_API", "").lower() in ("1", "true", "yes", "on")

# 數據來源
BINANCE_API = "https://api.binance.com"

# 策略參數（1000天回測最佳）
STRATEGY = {
    "leverage": 5,
    "risk_per_trade": 0.08,
    "max_positions": 3,
    "max_hold_days": 30,
    "min_score": 3,
    "tp_mult": 1.5,  # Best 1000d variant: conservative TP
    "sl_mult": 1.0,  # Best 1000d variant: conservative SL
    "entry_order_type": "post_only",
}

# 風控
CIRCUIT = {
    "max_daily_loss_pct": 15.0,
    "max_consecutive_losses": 5,
    "cooldown_hours": 24,
}

# 數據
STATE_DIR = os.path.join(PROJECT_ROOT, 'data', 'paper_strategies_live')
os.makedirs(STATE_DIR, exist_ok=True)
API_LOG_PATH = os.path.join(STATE_DIR, 'live_api_debug.log')
TRADE_LOG_PATH = os.path.join(STATE_DIR, 'live_trading_records.jsonl')

# ══════════════════════════════════════════════════════════════
# 依賴：最小化（不需外部庫）
# ══════════════════════════════════════════════════════════════

import urllib.request

_HL_INFO_CLIENT = None
_HL_EXCHANGE_CLIENT = None
_HL_CLIENT_ERROR = None
_HL_PERP_META = None
_IO_LOCK = threading.RLock()

def api_get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None

def api_post(url, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None


def get_market_data_source():
    if MARKET_DATA_SOURCE in ("binance", "hyperliquid"):
        return MARKET_DATA_SOURCE
    return "hyperliquid" if MODE == "live" else "binance"


def hl_info_post(data):
    return api_post(f"{HL_API_URL}/info", data)


def debug_api_log(event, payload):
    if not DEBUG_API:
        return
    record = {
        "ts": datetime.now().isoformat(),
        "event": event,
        "payload": payload,
    }
    try:
        with open(API_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def append_trade_record(record):
    try:
        with _IO_LOCK:
            with open(TRADE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def get_api_wallet_address():
    if not PRIVATE_KEY or Account is None:
        return None
    try:
        return Account.from_key(PRIVATE_KEY).address
    except Exception:
        return None


def get_hl_account_address():
    if ACCOUNT_ADDRESS:
        return ACCOUNT_ADDRESS
    if PRIVATE_KEY and Account is not None:
        try:
            return Account.from_key(PRIVATE_KEY).address
        except Exception:
            return None
    return None


def is_probably_api_wallet_mode():
    return bool(PRIVATE_KEY) and not bool(ACCOUNT_ADDRESS)


def get_hl_info_client():
    global _HL_INFO_CLIENT, _HL_CLIENT_ERROR
    if _HL_INFO_CLIENT is not None:
        return _HL_INFO_CLIENT
    if Info is None:
        _HL_CLIENT_ERROR = "未安裝 hyperliquid-python-sdk"
        return None
    try:
        _HL_INFO_CLIENT = Info(HL_API_URL, skip_ws=True)
        return _HL_INFO_CLIENT
    except Exception as exc:
        _HL_CLIENT_ERROR = str(exc)
        return None


def get_hl_client_error():
    return _HL_CLIENT_ERROR


def get_hl_perp_meta():
    global _HL_PERP_META
    if _HL_PERP_META is not None:
        return _HL_PERP_META
    client = get_hl_info_client()
    if client is not None:
        try:
            _HL_PERP_META = client.meta()
            return _HL_PERP_META
        except Exception:
            pass
    data = hl_info_post({"type": "meta"})
    if isinstance(data, dict):
        _HL_PERP_META = data
        return _HL_PERP_META
    return None


def get_hl_size_decimals(coin):
    meta = get_hl_perp_meta()
    if not isinstance(meta, dict):
        return None
    for item in meta.get("universe", []):
        if isinstance(item, dict) and item.get("name") == coin:
            value = item.get("szDecimals")
            return int(value) if value is not None else None
    return None


def round_down_value(value, decimals):
    if decimals is None:
        decimals = 8
    decimals = max(int(decimals), 0)
    quant = Decimal("1").scaleb(-decimals)
    rounded = Decimal(str(value)).quantize(quant, rounding=ROUND_DOWN)
    return float(rounded)


def normalize_hl_order_params(coin, size, price):
    size_decimals = get_hl_size_decimals(coin)
    normalized_size = round_down_value(size, size_decimals if size_decimals is not None else 8)
    normalized_price = round_down_value(price, 8)
    return {
        "size": normalized_size,
        "price": normalized_price,
        "size_decimals": size_decimals,
    }


def summarize_hl_order_result(result):
    summary = {
        "api_status": None,
        "order_status": "unknown",
        "oid": None,
        "filled": False,
        "resting": False,
        "message": None,
    }
    if not isinstance(result, dict):
        summary["message"] = "non-dict response"
        return summary

    summary["api_status"] = result.get("status")
    response = result.get("response")
    if not isinstance(response, dict):
        summary["message"] = result.get("message")
        return summary

    data = response.get("data")
    if not isinstance(data, dict):
        summary["message"] = result.get("message")
        return summary

    statuses = data.get("statuses")
    if not isinstance(statuses, list) or not statuses:
        summary["message"] = result.get("message")
        return summary

    first = statuses[0]
    if not isinstance(first, dict):
        summary["message"] = str(first)
        return summary

    if "filled" in first and isinstance(first["filled"], dict):
        filled = first["filled"]
        summary["order_status"] = "filled"
        summary["filled"] = True
        summary["oid"] = filled.get("oid")
        summary["message"] = json.dumps(filled, ensure_ascii=False)
        return summary

    if "resting" in first and isinstance(first["resting"], dict):
        resting = first["resting"]
        summary["order_status"] = "resting"
        summary["resting"] = True
        summary["oid"] = resting.get("oid")
        summary["message"] = json.dumps(resting, ensure_ascii=False)
        return summary

    if "error" in first:
        summary["order_status"] = "error"
        summary["message"] = str(first.get("error"))
        return summary

    summary["message"] = json.dumps(first, ensure_ascii=False)
    return summary


def verify_hl_order(oid):
    address = get_hl_account_address()
    client = get_hl_info_client()
    if not address or client is None or oid is None:
        return None
    try:
        result = client.query_order_by_oid(address, int(oid))
        debug_api_log("hl_order_verify", {
            "oid": oid,
            "user": address,
            "raw_response": result,
        })
        return result
    except Exception as exc:
        debug_api_log("hl_order_verify_error", {
            "oid": oid,
            "user": address,
            "error": str(exc),
        })
        return {"error": str(exc)}


def classify_verified_order(result):
    if not isinstance(result, dict):
        return {"verify_status": "unknown", "message": None}

    if result.get("error"):
        return {"verify_status": "error", "message": str(result.get("error"))}

    status = result.get("status")
    if isinstance(status, str):
        lowered = status.lower()
        if "filled" in lowered:
            return {"verify_status": "filled", "message": status}
        if "open" in lowered or "resting" in lowered:
            return {"verify_status": "open", "message": status}
        if "cancel" in lowered:
            return {"verify_status": "canceled", "message": status}
        if "reject" in lowered or "margin" in lowered:
            return {"verify_status": "rejected", "message": status}
        return {"verify_status": lowered, "message": status}

    return {"verify_status": "unknown", "message": json.dumps(result, ensure_ascii=False)}


def get_min_balance_for_one_unit(entry, sl, risk_pct):
    sl_distance = abs(entry - sl)
    if sl_distance <= 0 or risk_pct <= 0:
        return None
    return sl_distance / risk_pct


def get_hl_exchange_client():
    global _HL_EXCHANGE_CLIENT, _HL_CLIENT_ERROR
    if _HL_EXCHANGE_CLIENT is not None:
        return _HL_EXCHANGE_CLIENT
    if not PRIVATE_KEY:
        _HL_CLIENT_ERROR = "未設定私鑰"
        return None
    if Account is None or Exchange is None:
        _HL_CLIENT_ERROR = "未安裝 hyperliquid-python-sdk"
        return None
    try:
        wallet = Account.from_key(PRIVATE_KEY)
        account_address = ACCOUNT_ADDRESS or wallet.address
        _HL_EXCHANGE_CLIENT = Exchange(
            wallet,
            base_url=HL_API_URL,
            account_address=account_address,
        )
        return _HL_EXCHANGE_CLIENT
    except Exception as exc:
        _HL_CLIENT_ERROR = str(exc)
        return None

# ══════════════════════════════════════════════════════════════
# 指標計算（純 Python，不需 pandas/numpy）
# ══════════════════════════════════════════════════════════════

def calc_ema(closes, period):
    if len(closes) < period: return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema

def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period: return 0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr

def calc_adx(highs, lows, closes, period=14):
    """簡化 ADX（只回傳趨勢強度）"""
    if len(highs) < period + 1: return 20
    plus_dm = []
    minus_dm = []
    trs = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
    
    if len(plus_dm) < period: return 20
    
    atr = sum(trs[:period]) / period if trs else 1
    if atr == 0: return 20
    
    plus_di = sum(plus_dm[-period:]) / (period * atr) * 100
    minus_di = sum(minus_dm[-period:]) / (period * atr) * 100
    
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return dx

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
    gains = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0: return 100
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)

# ══════════════════════════════════════════════════════════════
# 數據獲取
# ══════════════════════════════════════════════════════════════

def get_klines(symbol, limit=60):
    """從 Binance 取得 K 線數據"""
    if get_market_data_source() == "hyperliquid":
        coin = symbol.replace("USDT", "")
        end_time = int(time.time() * 1000)
        start_time = end_time - max(limit, 1) * 24 * 60 * 60 * 1000
        data = hl_info_post({
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": "1d",
                "startTime": start_time,
                "endTime": end_time,
            },
        })
        if data and isinstance(data, list):
            return [{
                "open": float(d["o"]),
                "high": float(d["h"]),
                "low": float(d["l"]),
                "close": float(d["c"]),
                "volume": float(d.get("v", 0)),
            } for d in data[-limit:]]
        return None

    url = f"{BINANCE_API}/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    data = api_get(url)
    if data and isinstance(data, list):
        return [{
            "open": float(d[1]),
            "high": float(d[2]),
            "low": float(d[3]),
            "close": float(d[4]),
            "volume": float(d[5]),
        } for d in data]
    return None

def get_ticker(symbol):
    """取得即時價格"""
    if get_market_data_source() == "hyperliquid":
        coin = symbol.replace("USDT", "")
        mids = hl_info_post({"type": "allMids"})
        if isinstance(mids, dict) and coin in mids:
            price = float(mids[coin])
            change_pct = 0.0
            volume = 0.0
            klines = get_klines(symbol, 2)
            if klines and len(klines) >= 2:
                prev = klines[-2]["close"]
                if prev:
                    change_pct = (price / prev - 1) * 100
                volume = klines[-1].get("volume", 0)
            return {
                "price": price,
                "change_pct": change_pct,
                "volume": volume,
            }
        return None

    url = f"{BINANCE_API}/api/v3/ticker/24hr?symbol={symbol}"
    data = api_get(url)
    if data:
        return {
            "price": float(data.get("lastPrice", 0)),
            "change_pct": float(data.get("priceChangePercent", 0)),
            "volume": float(data.get("quoteVolume", 0)),
        }
    return None

def load_coin_list():
    """載入幣種列表"""
    cache = os.path.join(STATE_DIR, 'coin_list.json')
    if os.path.exists(cache):
        with open(cache, 'r') as f:
            return json.load(f)

    if get_market_data_source() == "hyperliquid":
        data = hl_info_post({"type": "meta"})
        if data and "universe" in data:
            coins = []
            for s in data["universe"]:
                name = s.get("name")
                if not name or s.get("isDelisted"):
                    continue
                coins.append({"name": name, "symbol": f"{name}USDT"})
            coins = coins[:50]
            with open(cache, 'w') as f:
                json.dump(coins, f, indent=2)
            return coins
    
    url = f"{BINANCE_API}/api/v3/exchangeInfo"
    data = api_get(url)
    if data and "symbols" in data:
        coins = []
        for s in data["symbols"]:
            if s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING":
                coins.append({"name": s["symbol"].replace("USDT", ""), "symbol": s["symbol"]})
        coins = coins[:50]
        with open(cache, 'w') as f:
            json.dump(coins, f, indent=2)
        return coins
    
    # 備用列表
    names = ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","LINK","DOT",
             "MATIC","LTC","UNI","ATOM","ETC","FIL","APT","ARB","OP","NEAR",
             "FTM","AAVE","MKR","INJ","SUI","SEI","TIA","JUP","WLD","PEPE",
             "SHIB","BCH","ICP","ALGO","HBAR","VET","MANA","SAND","AXS",
             "THETA","KAVA","RUNE","NEO","XTZ","ZIL","ZEC","XLM","QTUM","IOST"]
    return [{"name": n, "symbol": n+"USDT"} for n in names[:50]]

def get_current_prices(coins):
    """取得所有幣種即時價格"""
    prices = {}
    for coin in coins:
        t = get_ticker(coin["symbol"])
        if t:
            prices[coin["name"]] = t["price"]
        time.sleep(0.1)  # rate limit
    return prices

def get_btc_direction():
    """BTC 7 天趨勢"""
    klines = get_klines("BTCUSDT", 30)
    return get_btc_direction_from_klines(klines)

# ══════════════════════════════════════════════════════════════
# 信號生成
# ══════════════════════════════════════════════════════════════

def generate_signal(klines, min_score=4):
    return generate_trend_signal(
        klines,
        min_score=min_score,
        tp_mult=STRATEGY["tp_mult"],
        sl_mult=STRATEGY["sl_mult"],
    )

def check_trend_reversal(pos, klines):
    """趨勢反轉檢測：EMA20 穿 EMA50"""
    if not klines or len(klines) < 30: return False
    closes = [d["close"] for d in klines]
    e20 = calc_ema(closes, 20)
    e50 = calc_ema(closes, 50)
    
    if len(closes) > 20:
        e20_prev = calc_ema(closes[:-1], 20)
        e50_prev = calc_ema(closes[:-1], 50) if len(closes) > 50 else e50
    else:
        e20_prev, e50_prev = e20, e50
    
    cur = closes[-1]
    
    if pos['direction'] == 'long':
        # 多頭：價格跌破 EMA20 且 EMA20 下穿 EMA50
        if cur < e20 and e20 < e50 and e20_prev >= e50_prev:
            return True
    else:
        # 空頭：價格站上 EMA20 且 EMA20 上穿 EMA50
        if cur > e20 and e20 > e50 and e20_prev <= e50_prev:
            return True
    return False

# ══════════════════════════════════════════════════════════════
# 交易引擎
# ══════════════════════════════════════════════════════════════

def update_positions(state, prices, data_cache):
    """更新持倉：TP/SL + 趨勢反轉 + Break-even + Daily Risk Limit"""
    still_open = []
    for pos in state['positions']:
        c = pos['coin']
        if c not in prices:
            still_open.append(pos)
            continue
        
        cur = prices[c]
        pos['current_price'] = cur
        pnl = (cur - pos['entry']) * pos['size'] if pos['direction'] == 'long' else (pos['entry'] - cur) * pos['size']
        pos['pnl_pnl'] = pnl
        
        close = False
        reason = ''
        
        # TP/SL
        if pos['direction'] == 'long':
            if cur >= pos['tp']: close, reason = True, 'TP'
            elif cur <= pos['sl']: close, reason = True, 'SL'
        else:
            if cur <= pos['tp']: close, reason = True, 'TP'
            elif cur >= pos['sl']: close, reason = True, 'SL'
        
        # Break-even Stop：獲利達 1R 時，SL 移到 entry
        if not close and pnl > 0:
            entry = pos['entry']
            risk_amt = abs(entry - pos['sl'])
            if pos['direction'] == 'long' and cur >= entry + risk_amt:
                new_sl = entry * 1.005  # break-even + 0.5% fee buffer
                if new_sl > pos['sl']:
                    pos['sl'] = new_sl
                    if cur <= pos['sl']:
                        close, reason = True, 'BREAKEVEN'
            elif pos['direction'] == 'short' and cur <= entry - risk_amt:
                new_sl = entry * 0.995
                if new_sl < pos['sl']:
                    pos['sl'] = new_sl
                    if cur >= pos['sl']:
                        close, reason = True, 'BREAKEVEN'
        
        # 趨勢反轉
        if not close and c in data_cache:
            if check_trend_reversal(pos, data_cache[c]):
                close, reason = True, 'REVERSAL'
        
        # 超時
        if not close:
            try:
                if datetime.now() - datetime.fromisoformat(pos['entry_time']) > timedelta(days=STRATEGY['max_hold_days']):
                    close, reason = True, 'TIME'
            except: pass
        
        if close:
            state['balance'] += pnl
            st = state['stats']
            st['total_trades'] += 1
            st['total_pnl'] += pnl
            if pnl > 0:
                st['wins'] += 1
                st['max_win'] = max(st['max_win'], pnl)
            else:
                st['losses'] += 1
                st['max_loss'] = min(st['max_loss'], pnl)
            state['history'].append({
                'coin': c, 'dir': pos['direction'], 'entry': pos['entry'],
                'exit': cur, 'pnl': round(pnl, 4), 'reason': reason,
                'exit_time': datetime.now().isoformat(),
                'sig': pos.get('sig', ''),
            })
            if MODE == "live":
                append_trade_record({
                    "ts": datetime.now().isoformat(),
                    "event": "position_closed",
                    "coin": c,
                    "side": pos['direction'],
                    "entry": pos['entry'],
                    "exit": cur,
                    "size": pos.get('size'),
                    "tp": pos.get('tp'),
                    "sl": pos.get('sl'),
                    "pnl": round(pnl, 4),
                    "reason": reason,
                    "order_oid": pos.get('order_oid'),
                    "order_status": pos.get('order_status'),
                })
        else:
            still_open.append(pos)
    
    state['positions'] = still_open

def check_entries(state, coins):
    """檢查新倉位"""
    p = STRATEGY
    if len(state['positions']) >= p['max_positions']: return
    
    ok, reason = check_circuit_breaker(state, CIRCUIT)
    if not ok:
        print(f'  🔴 熔斷: {reason}')
        return
    
    btc_dir = get_btc_direction()
    prices = get_current_prices(coins)
    
    for coin in coins:
        if len(state['positions']) >= p['max_positions']: break
        cn = coin['name']
        if any(pos['coin'] == cn for pos in state['positions']): continue
        if is_cooldown(state, cn, CIRCUIT): continue
        if cn not in prices: continue
        
        # 取得 K 線
        klines = get_klines(coin['symbol'], 60)
        if not klines or len(klines) < 50: continue
        
        # 存 cache
        if '_data_cache' not in state: state['_data_cache'] = {}
        state['_data_cache'][cn] = klines
        
        sig = generate_signal(klines, p['min_score'])
        if not sig: continue
        
        # BTC 方向過濾
        if btc_dir == "bull" and sig['direction'] == "short": continue
        if btc_dir == "bear" and sig['direction'] == "long": continue
        
        entry = prices[cn]
        
        # Dynamic Position Size：根據波動率調整風險
        actual_risk = p['risk_per_trade']
        closes = [d['close'] for d in klines]
        highs = [d['high'] for d in klines]
        lows = [d['low'] for d in klines]
        atr_val = calc_atr(highs, lows, closes)
        if atr_val and entry > 0:
            atr_pct = atr_val / entry * 100
            if atr_pct > 5:
                actual_risk = 0.05  # 波動大 → 降風險
            elif atr_pct < 2:
                actual_risk = 0.10  # 波動小 → 提高風險
        
        size = calc_position_size(state['balance'], entry, sig['sl'], p['leverage'], actual_risk)
        if size <= 0: continue

        normalized_preview = normalize_hl_order_params(cn, size, entry)
        if normalized_preview["size"] <= 0:
            min_balance = get_min_balance_for_one_unit(entry, sig['sl'], actual_risk)
            min_balance_text = f"${min_balance:,.2f}" if min_balance is not None else "unknown"
            print(
                f'  ⏭️ 跳過: {cn} {sig["direction"]}'
                f' | size 過小，依精度規則取整後為 0'
                f' | raw_size={size:.6f}'
                f' | szDecimals={normalized_preview["size_decimals"]}'
                f' | 估計至少需餘額 {min_balance_text}'
            )
            continue
        
        order_meta = None
        order_side = 'buy' if sig['direction'] == 'long' else 'sell'
        if MODE == "live":
            order_meta = place_hl_order(cn, order_side, round(size, 6), order_type=p.get('entry_order_type', 'post_only'))
            order_summary = (order_meta or {}).get("order_summary", {})
            append_trade_record({
                "ts": datetime.now().isoformat(),
                "event": "entry_order_submitted",
                "coin": cn,
                "side": order_side,
                "signal_direction": sig["direction"],
                "signal_reason": sig.get("reason"),
                "entry_order_type": p.get('entry_order_type', 'post_only'),
                "requested_size": round(size, 6),
                "normalized_size": (order_meta or {}).get("size"),
                "resolved_price": (order_meta or {}).get("resolved_price"),
                "signal_entry_price": entry,
                "tp": sig.get("tp"),
                "sl": sig.get("sl"),
                "api_status": (order_meta or {}).get("status"),
                "order_status": order_summary.get("order_status"),
                "oid": order_summary.get("oid"),
                "verified_order_status": ((order_meta or {}).get("verified_summary") or {}).get("verify_status"),
                "verified_order_message": ((order_meta or {}).get("verified_summary") or {}).get("message"),
                "message": (order_meta or {}).get("message"),
                "order_meta": order_meta,
            })
            if not order_meta or order_meta.get('status') == 'error':
                print(f'  ❌ 下單失敗: {cn} {order_side} | {order_meta.get("message", "unknown") if order_meta else "unknown"}')
                continue
            if order_summary.get("order_status") not in ("filled", "resting"):
                print(f'  ❌ 下單未確認: {cn} {order_side} | {order_summary.get("message", "unknown")}')
                continue
            verified_summary = (order_meta or {}).get("verified_summary") or {}
            if verified_summary.get("verify_status") in ("rejected", "canceled", "error"):
                print(f'  ❌ 下單回查失敗: {cn} {order_side} | {verified_summary.get("message", "unknown")}')
                continue
            entry = order_meta.get('resolved_price', entry)

        state['positions'].append({
            'coin': cn, 'direction': sig['direction'],
            'entry': entry, 'tp': sig['tp'], 'sl': sig['sl'],
            'size': normalized_preview["size"] if MODE == "live" else round(size, 6), 'current_price': entry,
            'pnl_pnl': 0, 'entry_time': datetime.now().isoformat(),
            'sig': sig.get('reason', ''),
            'order_type': p.get('entry_order_type', 'post_only'),
            'order_meta': order_meta,
            'order_oid': ((order_meta or {}).get("order_summary") or {}).get("oid"),
            'order_status': ((order_meta or {}).get("order_summary") or {}).get("order_status"),
            'verified_order_status': ((order_meta or {}).get("verified_summary") or {}).get("verify_status"),
        })
        if MODE == "live":
            append_trade_record({
                "ts": datetime.now().isoformat(),
                "event": "position_opened",
                "coin": cn,
                "side": sig["direction"],
                "entry": entry,
                "tp": sig.get("tp"),
                "sl": sig.get("sl"),
                "size": normalized_preview["size"],
                "order_oid": ((order_meta or {}).get("order_summary") or {}).get("oid"),
                "order_status": ((order_meta or {}).get("order_summary") or {}).get("order_status"),
                "verified_order_status": ((order_meta or {}).get("verified_summary") or {}).get("verify_status"),
            })
            save_state(state)
        print(
            f'  ✅ 建倉: {cn} {sig["direction"]} @ ${entry:,.2f}'
            f' | {sig["reason"]} | score={sig["score"]}'
            f' | mode={"live" if MODE == "live" else "paper"}'
            f' | order_status={((order_meta or {}).get("order_summary") or {}).get("order_status", "paper")}'
            f' | verify={((order_meta or {}).get("verified_summary") or {}).get("verify_status", "n/a")}'
        )
    
    return prices

# ══════════════════════════════════════════════════════════════
# 實盤接口
# ══════════════════════════════════════════════════════════════

def place_hl_order(coin, side, size, price=None, order_type="post_only"):
    """Hyperliquid 下單（使用官方 SDK 簽名與送單）"""
    exchange = get_hl_exchange_client()
    if exchange is None:
        return {"status": "error", "message": _HL_CLIENT_ERROR or "無法初始化 Hyperliquid SDK"}

    tif = "Alo" if order_type == "post_only" else "Ioc"
    orderbook_ref = choose_limit_price(
        coin,
        side,
        base_url=HL_API_URL,
        passive=(order_type == "post_only"),
    )
    resolved_price = price
    if resolved_price is None and orderbook_ref:
        resolved_price = orderbook_ref["price"]
    if resolved_price is None:
        return {"status": "error", "message": f"無法取得 {coin} 的 HL order book 價格"}

    normalized = normalize_hl_order_params(coin, size, resolved_price)
    normalized_size = normalized["size"]
    normalized_price = normalized["price"]
    if normalized_size <= 0:
        return {
            "status": "error",
            "message": f"下單數量太小，依 {coin} 精度規則取整後為 0",
            "resolved_price": normalized_price,
            "order_type": order_type,
            "size": normalized_size,
            "size_decimals": normalized["size_decimals"],
            "best_bid": orderbook_ref["best_bid"] if orderbook_ref else None,
            "best_ask": orderbook_ref["best_ask"] if orderbook_ref else None,
        }

    try:
        result = exchange.order(
            coin,
            side == "buy",
            normalized_size,
            normalized_price,
            {"limit": {"tif": tif}},
            reduce_only=False,
        )
    except Exception as exc:
        return {
            "status": "error",
            "message": f"下單例外: {exc}",
            "resolved_price": normalized_price,
            "order_type": order_type,
            "size": normalized_size,
            "size_decimals": normalized["size_decimals"],
            "best_bid": orderbook_ref["best_bid"] if orderbook_ref else None,
            "best_ask": orderbook_ref["best_ask"] if orderbook_ref else None,
        }

    if isinstance(result, dict):
        result["resolved_price"] = normalized_price
        result["order_type"] = order_type
        result["size"] = normalized_size
        result["size_decimals"] = normalized["size_decimals"]
        if orderbook_ref:
            result["best_bid"] = orderbook_ref["best_bid"]
            result["best_ask"] = orderbook_ref["best_ask"]
        result["order_summary"] = summarize_hl_order_result(result)
        oid = (result.get("order_summary") or {}).get("oid")
        verified = verify_hl_order(oid) if oid is not None else None
        result["verified_order"] = verified
        result["verified_summary"] = classify_verified_order(verified) if verified is not None else None
        status = result.get("status")
        if status == "ok":
            return result
        return {
            **result,
            "status": "error",
            "message": json.dumps(result, ensure_ascii=False),
        }

    return {
        "status": "error",
        "message": "SDK 回傳格式異常",
        "resolved_price": normalized_price,
        "order_type": order_type,
        "size": normalized_size,
        "size_decimals": normalized["size_decimals"],
        "best_bid": orderbook_ref["best_bid"] if orderbook_ref else None,
        "best_ask": orderbook_ref["best_ask"] if orderbook_ref else None,
    }

def get_hl_balance():
    """查詢 Hyperliquid 帳戶"""
    address = get_hl_account_address()
    if not address:
        debug_api_log("hl_balance_skipped", {
            "reason": "no_account_address",
            "has_private_key": bool(PRIVATE_KEY),
            "api_wallet_address": get_api_wallet_address(),
            "account_address": ACCOUNT_ADDRESS or None,
        })
        return None

    client = get_hl_info_client()
    if client is None:
        result = {
            "perp": api_post(f"{HL_API_URL}/info", {
                "type": "clearinghouseState",
                "user": address
            }),
            "spot": api_post(f"{HL_API_URL}/info", {
                "type": "spotClearinghouseState",
                "user": address
            }),
            "abstraction": api_post(f"{HL_API_URL}/info", {
                "type": "userAbstraction",
                "user": address
            }),
            "dex_abstraction": api_post(f"{HL_API_URL}/info", {
                "type": "userDexAbstraction",
                "user": address
            }),
        }
        debug_api_log("hl_balance_fallback", {
            "request_user": address,
            "response_keys": sorted(result.keys()) if isinstance(result, dict) else None,
            "account_value": extract_hl_account_value(result),
            "client_error": get_hl_client_error(),
            "raw_response": result,
        })
        return result

    try:
        perp_result = client.user_state(address)
        spot_result = None
        abstraction_result = None
        dex_abstraction_result = None
        try:
            spot_result = client.spot_user_state(address)
        except Exception:
            spot_result = None
        try:
            abstraction_result = client.query_user_abstraction_state(address)
        except Exception:
            abstraction_result = None
        try:
            dex_abstraction_result = client.query_user_dex_abstraction_state(address)
        except Exception:
            dex_abstraction_result = None
        result = {
            "perp": perp_result,
            "spot": spot_result,
            "abstraction": abstraction_result,
            "dex_abstraction": dex_abstraction_result,
        }
        debug_api_log("hl_balance_sdk", {
            "request_user": address,
            "response_keys": sorted(result.keys()) if isinstance(result, dict) else None,
            "account_value": extract_hl_account_value(result),
            "client_error": get_hl_client_error(),
            "raw_response": result,
        })
        return result
    except Exception as exc:
        result = api_post(f"{HL_API_URL}/info", {
            "type": "clearinghouseState",
            "user": address
        })
        debug_api_log("hl_balance_sdk_error", {
            "request_user": address,
            "error": str(exc),
            "response_keys": sorted(result.keys()) if isinstance(result, dict) else None,
            "account_value": extract_hl_account_value(result),
            "client_error": get_hl_client_error(),
            "raw_response": result,
        })
        return result


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_spot_stable_value(balance_info):
    if not isinstance(balance_info, dict):
        return None
    balances = balance_info.get("balances") or []
    stable_total = 0.0
    found = False
    stable_coins = {"USDC", "USDT", "USDT0", "USDE", "USDH"}
    for item in balances:
        if not isinstance(item, dict):
            continue
        if item.get("coin") not in stable_coins:
            continue
        total = _safe_float(item.get("total"))
        if total is None:
            continue
        stable_total += total
        found = True
    return stable_total if found else None


def extract_hl_account_value(balance_info):
    if not isinstance(balance_info, dict):
        return None

    if any(key in balance_info for key in ("perp", "spot", "abstraction", "dex_abstraction")):
        values = []
        abstraction_value = extract_hl_account_value(balance_info.get("abstraction"))
        if abstraction_value is not None:
            values.append(abstraction_value)
        dex_abstraction_value = extract_hl_account_value(balance_info.get("dex_abstraction"))
        if dex_abstraction_value is not None:
            values.append(dex_abstraction_value)
        spot_value = extract_hl_account_value(balance_info.get("spot"))
        if spot_value is not None:
            values.append(spot_value)
        perp_value = extract_hl_account_value(balance_info.get("perp"))
        if perp_value is not None:
            values.append(perp_value)
        positive_values = [value for value in values if value > 0]
        if positive_values:
            return max(positive_values)
        if values:
            return values[0]
        return None

    candidates = [
        balance_info.get("accountValue"),
        (balance_info.get("marginSummary") or {}).get("accountValue"),
        (balance_info.get("crossMarginSummary") or {}).get("accountValue"),
        (balance_info.get("withdrawable")),
        (balance_info.get("portfolio") or {}).get("accountValue"),
        (balance_info.get("portfolio") or {}).get("totalValue"),
        (balance_info.get("portfolio") or {}).get("withdrawable"),
        (balance_info.get("portfolio") or {}).get("usdc"),
        (balance_info.get("summary") or {}).get("accountValue"),
        (balance_info.get("summary") or {}).get("totalValue"),
        balance_info.get("totalValue"),
        balance_info.get("equity"),
        balance_info.get("balance"),
        (balance_info.get("balances") or [{}])[0].get("total"),
        (balance_info.get("balances") or [{}])[0].get("hold"),
        (balance_info.get("balances") or [{}])[0].get("entryNtl"),
        (balance_info.get("usdc") or {}).get("total"),
        (balance_info.get("usdc") or {}).get("hold"),
        (balance_info.get("usdc") or {}).get("entryNtl"),
        extract_spot_stable_value(balance_info),
    ]
    for candidate in candidates:
        numeric = _safe_float(candidate)
        if numeric is not None:
            return numeric
    return None


def sync_state_with_hl_balance(state):
    balance_info = get_hl_balance()
    account_value = extract_hl_account_value(balance_info)
    state["_hl_balance_info"] = balance_info
    if account_value is not None:
        state["balance"] = account_value
        state["_balance_source"] = "hyperliquid"
    else:
        state["_balance_source"] = "local_state"
    if is_probably_api_wallet_mode():
        state["_balance_warning"] = "目前只看到 HL_PRIVATE_KEY，若這是 API wallet，請另外設定 HL_ACCOUNT_ADDRESS=主帳戶地址（舊名 HL_WALLET_ADDRESS 也可），否則餘額查詢可能是 0。"
    else:
        state.pop("_balance_warning", None)
    return state

# ══════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════

def load_state():
    return load_state_file(STATE_DIR, STRATEGY)

def save_state(state):
    save_state_file(STATE_DIR, state, _IO_LOCK)

def print_report(state):
    s = state['stats']
    total = s['total_trades']
    wr = s['wins'] / total * 100 if total > 0 else 0
    balance_source = state.get("_balance_source", "local_state")
    print(f'\n帳戶報告 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   餘額: ${state["balance"]:.2f} | 來源: {balance_source}')
    print(f'   持倉: {len(state["positions"])}')
    print(f'   交易: {total} 筆 | WR: {wr:.0f}%')
    if balance_source != "hyperliquid":
        print('   注意: 目前顯示的是本地 state 餘額，不是真實交易所帳戶餘額')
    if state.get("_balance_warning"):
        print(f'   注意: {state["_balance_warning"]}')
    if total > 0:
        print(f'   平均 PnL: ${s["total_pnl"]/total:+.4f}')
        print(f'   最大盈: ${s["max_win"]:+.4f} | 最大虧: ${s["max_loss"]:+.4f}')
    
    if state['positions']:
        print(f'\n   當前持倉:')
        for pos in state['positions']:
            pnl = pos.get('pnl_pnl', 0)
            emoji = '+' if pnl >= 0 else '-'
            print(f'   {emoji} {pos["coin"]} {pos["direction"]} @ ${pos["entry"]:,.2f} | PnL: ${pnl:+.4f} | TP: ${pos["tp"]:,.2f} | SL: ${pos["sl"]:,.2f}')


def print_debug_account():
    account_address = get_hl_account_address()
    api_wallet_address = get_api_wallet_address()
    balance_info = get_hl_balance()
    account_value = extract_hl_account_value(balance_info)
    print('\nAccount Debug')
    print(f'   HL_PRIVATE_KEY: {"set" if PRIVATE_KEY else "missing"}')
    print(f'   HL_ACCOUNT_ADDRESS: {ACCOUNT_ADDRESS or "(missing)"}')
    print(f'   derived_api_wallet_address: {api_wallet_address or "(unavailable)"}')
    print(f'   query_address: {account_address or "(missing)"}')
    print(f'   hl_client_error: {get_hl_client_error() or "(none)"}')
    print(f'   extracted_account_value: {account_value}')
    if isinstance(balance_info, dict):
        print(f'   response_keys: {", ".join(sorted(balance_info.keys()))}')
        if isinstance(balance_info.get("perp"), dict):
            print(f'   perp_keys: {", ".join(sorted(balance_info["perp"].keys()))}')
        if isinstance(balance_info.get("spot"), dict):
            print(f'   spot_keys: {", ".join(sorted(balance_info["spot"].keys()))}')
        if isinstance(balance_info.get("abstraction"), dict):
            print(f'   abstraction_keys: {", ".join(sorted(balance_info["abstraction"].keys()))}')
        if isinstance(balance_info.get("dex_abstraction"), dict):
            print(f'   dex_abstraction_keys: {", ".join(sorted(balance_info["dex_abstraction"].keys()))}')
    else:
        print('   response_keys: (no response)')
    print(f'   api_log: {API_LOG_PATH}')


def verify_saved_orders():
    state = load_state()
    positions = state.get("positions", [])
    if not positions:
        print("目前沒有持倉可回查")
        return

    print("\nOrder Verify")
    for pos in positions:
        oid = pos.get("order_oid")
        coin = pos.get("coin")
        if oid is None:
            print(f'   {coin}: 無 oid，無法回查')
            continue
        verified = verify_hl_order(oid)
        summary = classify_verified_order(verified)
        print(
            f'   {coin}: oid={oid}'
            f' | local={pos.get("order_status", "unknown")}'
            f' | verify={summary.get("verify_status", "unknown")}'
            f' | msg={summary.get("message", "")}'
        )
        append_trade_record({
            "ts": datetime.now().isoformat(),
            "event": "order_verified",
            "coin": coin,
            "order_oid": oid,
            "local_order_status": pos.get("order_status"),
            "verified_order_status": summary.get("verify_status"),
            "verified_order_message": summary.get("message"),
            "verified_raw": verified,
        })

def run_once():
    state = load_state()
    try:
        if MODE == "live" or ACCOUNT_ADDRESS:
            state = sync_state_with_hl_balance(state)
        coins = load_coin_list()
        
        print(f'\n[{datetime.now().strftime("%Y-%m-%d %H:%M")}] 餘額: ${state["balance"]:.2f} | 持倉: {len(state["positions"])}')
        print(f'  市場資料來源: {get_market_data_source()}')
        print(f'  餘額來源: {state.get("_balance_source", "local_state")}')
        
        # 取得價格
        prices = get_current_prices(coins)
        
        # 更新持倉
        update_positions(state, prices, state.get('_data_cache', {}))
        
        # 每日虧損上限：今天已虧 5% 不再開新倉
        today = datetime.now().strftime('%Y-%m-%d')
        today_pnl = sum(h.get('pnl', 0) for h in state.get('history', [])
                        if h.get('exit_time', '').startswith(today))
        
        if today_pnl < -state['balance'] * 0.05:
            print(f'  🔴 每日虧損已達 5%（${today_pnl:.2f}），停止開倉')
        else:
            # 檢查新倉位
            check_entries(state, coins)
        
        # 更新現價
        for pos in state['positions']:
            if pos['coin'] in prices:
                pos['current_price'] = prices[pos['coin']]
        
        print_report(state)
        return state
    finally:
        save_state(state)


def run_loop(interval_minutes=5):
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            append_trade_record({
                "ts": datetime.now().isoformat(),
                "event": "loop_stopped",
                "reason": "keyboard_interrupt",
            })
            print('\n已停止')
            break
        except Exception as exc:
            append_trade_record({
                "ts": datetime.now().isoformat(),
                "event": "loop_error",
                "reason": str(exc),
            })
            print(f'\n[ERROR] {exc}')
        print(f'\n等待 {interval_minutes} 分鐘後再次執行...')
        time.sleep(max(interval_minutes, 1) * 60)

def main():
    global MODE
    args = sys.argv[1:]
    loop_mode = '--loop' in args
    interval_minutes = 5
    for arg in args:
        if arg.startswith('--interval-minutes='):
            try:
                interval_minutes = int(arg.split('=', 1)[1])
            except ValueError:
                pass
    
    if '--live' in args:
        MODE = "live"
        if not PRIVATE_KEY:
            print('❌ 請設定 HL_PRIVATE_KEY 環境變數')
            sys.exit(1)
        print('⚠️ 實盤模式！')
        if is_probably_api_wallet_mode():
            print('⚠️ 偵測到未設定 HL_ACCOUNT_ADDRESS。若你用的是 API wallet，請填主帳戶地址，否則餘額查詢可能會是 0。')
    elif '--reset' in args:
        path = get_state_path(STATE_DIR)
        if os.path.exists(path): os.remove(path)
        print('✅ 已重置')
        return
    elif '--report' in args:
        state = load_state()
        if MODE == "live" or ACCOUNT_ADDRESS:
            state = sync_state_with_hl_balance(state)
        print_report(state)
        return
    elif '--debug-account' in args:
        print_debug_account()
        return
    elif '--verify-orders' in args:
        verify_saved_orders()
        return
    
    if loop_mode:
        run_loop(interval_minutes=interval_minutes)
    else:
        run_once()

if __name__ == '__main__':
    main()
