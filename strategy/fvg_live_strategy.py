#!/usr/bin/env python3
"""
fvg_live_strategy.py - 獨立可移植的 FVG + 趨勢實盤策略
版本: 2026-06-30
1000天回測最佳參數：5x + 8% + 趨勢反轉檢測

使用方式:
  Paper trade:  python3 fvg_live_strategy.py
  實盤交易:    python3 fvg_live_strategy.py --live
  重置狀態:    python3 fvg_live_strategy.py --reset

實盤前置:
  1. export HL_PRIVATE_KEY="0x你的私鑰"
  2. export HL_WALLET_ADDRESS="0x你的錢包地址"
  3. export HL_API_URL="https://api.hyperliquid.xyz" (可自訂)
"""
import sys, os, json, statistics, time, hashlib
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from hyperliquid_api import choose_limit_price

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

MODE = "paper"  # "paper" 或 "live"

# 環境變數
PRIVATE_KEY = os.environ.get("HL_PRIVATE_KEY", "")
WALLET_ADDRESS = os.environ.get("HL_WALLET_ADDRESS", "")
HL_API_URL = os.environ.get("HL_API_URL", "https://api.hyperliquid.xyz")

# 數據來源
BINANCE_API = "https://api.binance.com"

# 策略參數（1000天回測最佳）
STRATEGY = {
    "leverage": 5,
    "risk_per_trade": 0.08,
    "max_positions": 3,
    "max_hold_days": 30,
    "min_score": 4,
    "tp_mult": 2.0,  # TP = ATR × 2.0
    "sl_mult": 1.5,  # SL = ATR × 1.5
    "entry_order_type": "post_only",
}

# 風控
CIRCUIT = {
    "max_daily_loss_pct": 15.0,
    "max_consecutive_losses": 5,
    "cooldown_hours": 24,
}

# 數據
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
STATE_DIR = os.path.join(PROJECT_ROOT, 'data', 'paper_strategies_live')
os.makedirs(STATE_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 依賴：最小化（不需外部庫）
# ══════════════════════════════════════════════════════════════

import urllib.request

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
    if klines and len(klines) >= 7:
        closes = [d["close"] for d in klines]
        chg = (closes[-1] / closes[-7] - 1) * 100
        if chg > 3: return "bull"
        elif chg < -3: return "bear"
    return "neutral"

# ══════════════════════════════════════════════════════════════
# 信號生成
# ══════════════════════════════════════════════════════════════

def generate_signal(klines, min_score=4):
    """生成趨勢信號"""
    if not klines or len(klines) < 50: return None
    
    closes = [d["close"] for d in klines]
    highs = [d["high"] for d in klines]
    lows = [d["low"] for d in klines]
    vols = [d.get("volume", 0) for d in klines]
    
    i = len(klines) - 1
    current = closes[i]
    
    adx_val = calc_adx(highs, lows, closes)
    atr_val = calc_atr(highs, lows, closes)
    if not atr_val or atr_val == 0: atr_val = current * 0.03
    
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    
    # 只交易趨勢市場
    if adx_val < 25: return None
    
    # 趨勢評分
    ts = 0
    
    # 動量加速
    if i >= 20:
        roc_5 = (closes[i] - closes[i-5]) / closes[i-5] * 100
        roc_20 = (closes[i] - closes[i-20]) / closes[i-20] * 100
        momentum_accel = roc_5 - roc_20 * 0.3
        if momentum_accel > 3: ts += 3
        elif momentum_accel > 1: ts += 1
        elif momentum_accel < -3: ts -= 3
        elif momentum_accel < -1: ts -= 1
    
    # 波動率擴張
    if i >= 20:
        atr5 = calc_atr(highs[-5:], lows[-5:], closes[-5:])
        vr = atr5 / atr_val if atr_val > 0 else 1
        if vr > 1.5: ts += 2
        elif vr < 0.7: ts -= 1
    
    # 成交量
    if i >= 20:
        va = statistics.mean(vols[max(0,i-5):i+1])
        vb = statistics.mean(vols[max(0,i-20):i+1])
        if vb > 0:
            vr = va / vb
            if vr > 1.5: ts += 2
            elif vr < 0.6: ts -= 1
    
    # 價格突破
    if i >= 20 and current > max(highs[i-20:i]): ts += 2
    
    # EMA 趨勢
    if current > ema20 and ema20 > ema50: ts += 1
    elif current < ema20 and ema20 < ema50: ts -= 1
    
    if ts >= min_score:
        return {
            "direction": "long", "score": ts,
            "tp": current + atr_val * STRATEGY["tp_mult"],
            "sl": current - atr_val * STRATEGY["sl_mult"],
            "reason": "TREND_BUY", "adx": adx_val
        }
    elif ts <= -min_score:
        return {
            "direction": "short", "score": ts,
            "tp": current - atr_val * STRATEGY["tp_mult"],
            "sl": current + atr_val * STRATEGY["sl_mult"],
            "reason": "TREND_SELL", "adx": adx_val
        }
    return None

# ══════════════════════════════════════════════════════════════
# 倉位管理
# ══════════════════════════════════════════════════════════════

def calc_position_size(balance, entry, sl, leverage, risk_pct):
    risk_amount = balance * risk_pct
    sl_distance = abs(entry - sl)
    if sl_distance == 0: return 0
    size = risk_amount / sl_distance
    notional = size * entry
    margin = notional / leverage
    max_margin = balance * 0.95
    if margin > max_margin:
        size = (max_margin * leverage) / entry
    return size

def check_circuit_breaker(state):
    today = datetime.now().strftime('%Y-%m-%d')
    today_pnl = sum(h.get('pnl', 0) for h in state.get('history', [])
                    if h.get('exit_time', '').startswith(today))
    if today_pnl < -state['balance'] * CIRCUIT['max_daily_loss_pct'] / 100:
        return False, 'daily_loss'
    
    recent = [h for h in state.get('history', [])
              if h.get('exit_time', '') >= (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')]
    cons = sum(1 for h in reversed(recent) if h.get('pnl', 0) < 0)
    if cons >= CIRCUIT['max_consecutive_losses']:
        return False, 'consecutive_losses'
    
    return True, ''

def is_cooldown(state, coin):
    cutoff = datetime.now() - timedelta(hours=CIRCUIT['cooldown_hours'])
    for h in reversed(state.get('history', [])):
        if h.get('coin') == coin:
            try:
                if datetime.fromisoformat(h.get('exit_time', '')) > cutoff:
                    return True
            except: pass
            break
    return False

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
        else:
            still_open.append(pos)
    
    state['positions'] = still_open

def check_entries(state, coins):
    """檢查新倉位"""
    p = STRATEGY
    if len(state['positions']) >= p['max_positions']: return
    
    ok, reason = check_circuit_breaker(state)
    if not ok:
        print(f'  🔴 熔斷: {reason}')
        return
    
    btc_dir = get_btc_direction()
    prices = get_current_prices(coins)
    
    for coin in coins:
        if len(state['positions']) >= p['max_positions']: break
        cn = coin['name']
        if any(pos['coin'] == cn for pos in state['positions']): continue
        if is_cooldown(state, cn): continue
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
        
        order_meta = None
        order_side = 'buy' if sig['direction'] == 'long' else 'sell'
        if MODE == "live":
            order_meta = place_hl_order(cn, order_side, round(size, 6), order_type=p.get('entry_order_type', 'post_only'))
            if not order_meta or order_meta.get('status') == 'error':
                print(f'  ❌ 下單失敗: {cn} {order_side} | {order_meta.get("message", "unknown") if order_meta else "unknown"}')
                continue
            entry = order_meta.get('resolved_price', entry)

        state['positions'].append({
            'coin': cn, 'direction': sig['direction'],
            'entry': entry, 'tp': sig['tp'], 'sl': sig['sl'],
            'size': round(size, 6), 'current_price': entry,
            'pnl_pnl': 0, 'entry_time': datetime.now().isoformat(),
            'sig': sig.get('reason', ''),
            'order_type': p.get('entry_order_type', 'post_only'),
            'order_meta': order_meta,
        })
        print(
            f'  ✅ 建倉: {cn} {sig["direction"]} @ ${entry:,.2f}'
            f' | {sig["reason"]} | score={sig["score"]}'
            f' | mode={"live" if MODE == "live" else "paper"}'
        )
    
    return prices

# ══════════════════════════════════════════════════════════════
# 實盤接口
# ══════════════════════════════════════════════════════════════

def place_hl_order(coin, side, size, price=None, order_type="post_only"):
    """Hyperliquid 下單（需要 PRIVATE_KEY）"""
    if not PRIVATE_KEY:
        return {"status": "error", "message": "未設定私鑰"}

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
    
    # EIP-712 簽名邏輯（待接入）
    # 參考: hyperliquid Python SDK
    payload = {
        "action": {
            "type": "order",
            "orders": [{
                "coin": coin,
                "is_buy": side == "buy",
                "sz": str(size),
                "limitPx": str(resolved_price),
                "orderType": {"limit": {"tif": tif}},
                "reduceOnly": False,
            }],
            "grouping": "na",
        },
        "nonce": int(time.time() * 1000),
        "signature": "0x" + "0" * 130,  # 需要真實簽名
    }
    
    result = api_post(f"{HL_API_URL}/exchange", payload)
    if result:
        result["resolved_price"] = resolved_price
        result["order_type"] = order_type
        if orderbook_ref:
            result["best_bid"] = orderbook_ref["best_bid"]
            result["best_ask"] = orderbook_ref["best_ask"]
    return result or {
        "status": "error",
        "message": "API 失敗",
        "resolved_price": resolved_price,
        "order_type": order_type,
        "best_bid": orderbook_ref["best_bid"] if orderbook_ref else None,
        "best_ask": orderbook_ref["best_ask"] if orderbook_ref else None,
    }

def get_hl_balance():
    """查詢 Hyperliquid 帳戶"""
    if not WALLET_ADDRESS: return None
    return api_post(f"{HL_API_URL}/info", {
        "type": "clearinghouseState",
        "user": WALLET_ADDRESS
    })

# ══════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════

def load_state():
    path = os.path.join(STATE_DIR, 'live_state.json')
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return {
        'balance': 1000.0, 'positions': [], 'history': [],
        'params': STRATEGY,
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0,
                  'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }

def save_state(state):
    path = os.path.join(STATE_DIR, 'live_state.json')
    with open(path, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def print_report(state):
    s = state['stats']
    total = s['total_trades']
    wr = s['wins'] / total * 100 if total > 0 else 0
    pct = (state['balance'] / 1000 - 1) * 100
    print(f'\n🏦 帳戶報告 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'   餘額: ${state["balance"]:.2f} ({pct:+.1f}%)')
    print(f'   持倉: {len(state["positions"])}')
    print(f'   交易: {total} 筆 | WR: {wr:.0f}%')
    if total > 0:
        print(f'   平均 PnL: ${s["total_pnl"]/total:+.4f}')
        print(f'   最大盈: ${s["max_win"]:+.4f} | 最大虧: ${s["max_loss"]:+.4f}')
    
    if state['positions']:
        print(f'\n   當前持倉:')
        for pos in state['positions']:
            pnl = pos.get('pnl_pnl', 0)
            emoji = '🟢' if pnl >= 0 else '🔴'
            print(f'   {emoji} {pos["coin"]} {pos["direction"]} @ ${pos["entry"]:,.2f} | PnL: ${pnl:+.4f} | TP: ${pos["tp"]:,.2f} | SL: ${pos["sl"]:,.2f}')

def run_once():
    state = load_state()
    coins = load_coin_list()
    
    print(f'\n[{datetime.now().strftime("%Y-%m-%d %H:%M")}] 餘額: ${state["balance"]:.2f} | 持倉: {len(state["positions"])}')
    
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
    
    save_state(state)
    print_report(state)
    return state

def main():
    global MODE
    args = sys.argv[1:]
    
    if '--live' in args:
        MODE = "live"
        if not PRIVATE_KEY:
            print('❌ 請設定 HL_PRIVATE_KEY 環境變數')
            sys.exit(1)
        print('⚠️ 實盤模式！')
    elif '--reset' in args:
        path = os.path.join(STATE_DIR, 'live_state.json')
        if os.path.exists(path): os.remove(path)
        print('✅ 已重置')
        return
    elif '--report' in args:
        state = load_state()
        print_report(state)
        return
    
    run_once()

if __name__ == '__main__':
    main()
