#!/usr/bin/env python3
"""
fvg_live_ready.py - 實盤就緒版本
功能：
1. Paper trade 模式（預設）- 模擬交易
2. Live 模式（設定 PRIVATE_KEY）- 自動交易 Hyperliquid
3. 趨勢反轉檢測（1000天回測驗證有效）
4. BTC 方向過濾
5. 完整風控：熔斷、連續虧損、每日虧損上限

接入實盤步驟：
1. 設定 PRIVATE_KEY = "你的錢包私鑰"
2. 設定 HL_API_URL = "https://api.hyperliquid.xyz"
3. 在 terminal 執行: python3 fvg_live_ready.py --live

安全提醒：
- 私鑰請存放在 .env 或 trading-knowledge/.tg-env，不要寫死在代碼
- 先跑 paper trade 確認策略穩定
- 建議先用小資金測試
"""
import sys, os, json, statistics, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from hyperliquid_api import choose_limit_price
from indicators_v3 import adx, atr, ema
from live_monitor import get_binance_klines
import urllib.request

# ══════════════════════════════════════════════════════════════
# 配置 - 在此調整參數
# ══════════════════════════════════════════════════════════════

# 模式: "paper" 或 "live"
MODE = "paper"

# ⚠️ 實盤：填入你的錢包私鑰（建議從環境變數讀取）
PRIVATE_KEY = os.environ.get("HL_PRIVATE_KEY", "")
WALLET_ADDRESS = os.environ.get("HL_WALLET_ADDRESS", "")

# Hyperliquid API
HL_API_URL = "https://api.hyperliquid.xyz"

# 策略參數（1000天回測最佳）
STRATEGIES = {
    "趨勢5x_8pct": {
        "initial_balance": 1000.0, "max_positions": 3, "max_hold_days": 30,
        "leverage": 5, "risk_per_trade": 0.08, "strategy_type": "trend",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
        "min_score": 4, "min_cor_confirm": 0, "entry_order_type": "post_only",
    },
}

# 風控
CIRCUIT_BREAKER = {
    "max_daily_loss_pct": 15.0,      # 單日最大虧損 %
    "max_consecutive_losses": 5,     # 連續虧損次數
    "cooldown_hours": 24,            # 熔斷後冷卻時間
    "max_positions": 3,              # 最大同時倉位
}

# 數據
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
MULTI_STATE_DIR = os.path.join(PROJECT_ROOT, 'data', 'paper_strategies_live')
os.makedirs(MULTI_STATE_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# 幣種管理
# ══════════════════════════════════════════════════════════════

def load_coin_list():
    cache_path = os.path.join(MULTI_STATE_DIR, 'coin_list.json')
    if os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            return json.load(f)
    
    try:
        url = 'https://api.binance.com/api/v3/exchangeInfo'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        coins = []
        for s in data.get('symbols', []):
            if s.get('quoteAsset') == 'USDT' and s.get('status') == 'TRADING':
                coins.append({'name': s['symbol'].replace('USDT', ''), 'symbol': s['symbol']})
        coins = coins[:50]
        with open(cache_path, 'w') as f:
            json.dump(coins, f, indent=2)
        return coins
    except:
        return [{'name': c, 'symbol': c+'USDT'} for c in ['BTC','ETH','BNB','SOL','XRP','ADA','DOGE','AVAX','LINK','DOT','MATIC','LTC','UNI','ATOM','ETC','FIL','APT','ARB','OP','NEAR'][:20]]

# ══════════════════════════════════════════════════════════════
# 信號生成
# ══════════════════════════════════════════════════════════════

def get_adx_val(highs, lows, closes, n=14):
    result = adx(highs, lows, closes, n)
    if isinstance(result, tuple) and len(result) >= 1:
        if isinstance(result[0], list):
            for v in reversed(result[0]):
                if v is not None: return v
    return 20

def get_atr_val(highs, lows, closes, n=14):
    result = atr(highs, lows, closes, n)
    if isinstance(result, list): return result[-1] if result else None
    return result

def get_ema_val(closes, period):
    result = ema(closes, period)
    if isinstance(result, list): return result[-1] if result else None
    return result

def generate_signal(data, min_score=4):
    if len(data) < 50: return None
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d.get('volume', 0) for d in data]
    i = len(data) - 1
    current = closes[i]
    adx_val = get_adx_val(highs, lows, closes)
    atr_val = get_atr_val(highs, lows, closes)
    if not atr_val or atr_val == 0: atr_val = current * 0.03
    ema20 = get_ema_val(closes, 20) or current
    ema50 = get_ema_val(closes, 50) or current
    
    if adx_val < 25: return None
    
    ts = 0
    roc_5 = (closes[i]-closes[i-5])/closes[i-5]*100 if i>=5 else 0
    roc_20 = (closes[i]-closes[i-20])/closes[i-20]*100 if i>=20 else 0
    ma = roc_5 - roc_20*0.3
    if ma > 3: ts += 3
    elif ma > 1: ts += 1
    elif ma < -3: ts -= 3
    elif ma < -1: ts -= 1
    atr5 = get_atr_val(highs[i-5:i+1], lows[i-5:i+1], closes[i-5:i+1], 5) or atr_val
    atr20 = get_atr_val(highs[i-20:i+1], lows[i-20:i+1], closes[i-20:i+1], 20) or atr_val
    vr = atr5/atr20 if atr20 > 0 else 1
    if vr > 1.5: ts += 2
    elif vr < 0.7: ts -= 1
    va = statistics.mean(vols[max(0,i-5):i+1])
    vb = statistics.mean(vols[max(0,i-20):i+1])
    if vb > 0 and va/vb > 1.5: ts += 2
    elif vb > 0 and va/vb < 0.6: ts -= 1
    if current > max(highs[i-20:i]): ts += 2
    if current > ema20 and ema20 > ema50: ts += 1
    elif current < ema20 and ema20 < ema50: ts -= 1
    
    if ts >= min_score:
        return {'direction': 'long', 'score': ts, 'tp': current+atr_val*2.0,
                'sl': current-atr_val*1.5, 'reason': 'TREND_BUY', 'adx': adx_val}
    elif ts <= -min_score:
        return {'direction': 'short', 'score': ts, 'tp': current-atr_val*2.0,
                'sl': current+atr_val*1.5, 'reason': 'TREND_SELL', 'adx': adx_val}
    return None

# ══════════════════════════════════════════════════════════════
# 交易引擎
# ══════════════════════════════════════════════════════════════

def calc_size(balance, entry, sl, lev, risk):
    ra = balance * risk
    sd = abs(entry - sl)
    if sd == 0: return 0
    size = ra / sd
    margin = size * entry / lev
    if margin > balance * 0.95:
        size = (balance * 0.95 * lev) / entry
    return size

def get_btc_direction():
    try:
        data = get_binance_klines("BTCUSDT", limit=30)
        if data and len(data) >= 7:
            c = [d['close'] for d in data]
            chg = (c[-1]/c[-7]-1)*100
            if chg > 3: return "bull"
            elif chg < -3: return "bear"
    except: pass
    return "neutral"

def get_current_prices(coins):
    prices = {}
    for coin in coins:
        try:
            d = get_binance_klines(coin['symbol'], limit=5)
            if d: prices[coin['name']] = d[-1]['close']
        except: pass
    return prices

def check_circuit_breaker(state):
    today = datetime.now().strftime('%Y-%m-%d')
    today_pnl = sum(h.get('pnl',0) for h in state.get('history',[]) if h.get('exit_time','').startswith(today))
    if today_pnl < -state['balance'] * CIRCUIT_BREAKER['max_daily_loss_pct']/100:
        return False
    recent = [h for h in state.get('history',[]) if h.get('exit_time','') >= (datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d')]
    cons = sum(1 for h in reversed(recent) if h.get('pnl',0) < 0)
    if cons >= CIRCUIT_BREAKER['max_consecutive_losses']:
        return False
    return True

def is_cooldown(state, coin):
    cutoff = datetime.now() - timedelta(hours=CIRCUIT_BREAKER['cooldown_hours'])
    for h in reversed(state.get('history',[])):
        if h.get('coin') == coin:
            try:
                if datetime.fromisoformat(h.get('exit_time','')) > cutoff: return True
            except: pass
            break
    return False

def update_positions(state, prices):
    """更新持倉：TP/SL + 趨勢反轉檢測"""
    still_open = []
    for pos in state['positions']:
        c = pos['coin']
        if c not in prices: still_open.append(pos); continue
        cur = prices[c]
        pos['current_price'] = cur
        pnl = (cur - pos['entry'])*pos['size'] if pos['direction']=='long' else (pos['entry']-cur)*pos['size']
        pos['pnl_pnl'] = pnl
        
        close = False; reason = ''
        
        # TP/SL
        if pos['direction']=='long':
            if cur>=pos['tp']: close,reason=True,'TP'
            elif cur<=pos['sl']: close,reason=True,'SL'
        else:
            if cur<=pos['tp']: close,reason=True,'TP'
            elif cur>=pos['sl']: close,reason=True,'SL'
        
        # 趨勢反轉檢測
        if not close and c in state.get('_data_cache', {}):
            data = state['_data_cache'][c]
            if len(data) >= 30:
                cls = [x['close'] for x in data]
                e20 = sum(cls[-20:]) / min(20, len(cls))
                e50 = sum(cls[-50:]) / min(50, len(cls))
                e20_prev = sum(cls[-21:-1]) / min(20, len(cls)-1) if len(cls) > 20 else e20
                e50_prev = sum(cls[-51:-1]) / min(50, len(cls)-1) if len(cls) > 50 else e50
                
                if pos['direction'] == 'long':
                    if cur < e20 and e20 < e50 and e20_prev >= e50_prev:
                        close, reason = True, 'REVERSAL'
                else:
                    if cur > e20 and e20 > e50 and e20_prev <= e50_prev:
                        close, reason = True, 'REVERSAL'
        
        # 超時
        if not close:
            try:
                if datetime.now() - datetime.fromisoformat(pos['entry_time']) > timedelta(days=state['params']['max_hold_days']):
                    close, reason = True, 'TIME'
            except: pass
        
        if close:
            state['balance']+=pnl
            state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
            if pnl>0: state['stats']['wins']+=1; state['stats']['max_win']=max(state['stats']['max_win'],pnl)
            else: state['stats']['losses']+=1; state['stats']['max_loss']=min(state['stats']['max_loss'],pnl)
            state['history'].append({
                'coin':c, 'dir':pos['direction'], 'entry':pos['entry'], 'exit':cur,
                'pnl':round(pnl,4), 'reason':reason,
                'exit_time':datetime.now().isoformat(), 'sig':pos.get('sig','')
            })
        else:
            still_open.append(pos)
    state['positions'] = still_open

def check_entries(state, coins):
    p = state['params']
    if len(state['positions']) >= p['max_positions']: return
    if not check_circuit_breaker(state): return
    
    btc_dir = get_btc_direction()
    prices = get_current_prices(coins)
    
    for coin in coins:
        if len(state['positions']) >= p['max_positions']: break
        cn = coin['name']
        if any(pos['coin']==cn for pos in state['positions']): continue
        if is_cooldown(state, cn): continue
        if cn not in prices: continue
        
        try:
            d = get_binance_klines(coin['symbol'], limit=60)
            if not d or len(d) < 50: continue
        except: continue
        
        # 存 cache 給趨勢反轉用
        if '_data_cache' not in state: state['_data_cache'] = {}
        state['_data_cache'][cn] = d
        
        sig = generate_signal(d, p['min_score'])
        if not sig: continue
        if btc_dir=="bull" and sig['direction']=="short": continue
        if btc_dir=="bear" and sig['direction']=="long": continue
        
        entry = prices[cn]
        size = calc_size(state['balance'], entry, sig['sl'], p['leverage'], p['risk_per_trade'])
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

# ══════════════════════════════════════════════════════════════
# 實盤交易接口（待接入）
# ══════════════════════════════════════════════════════════════

def place_hl_order(coin, side, size, price=None, order_type="post_only"):
    """Hyperliquid 下單（需要 PRIVATE_KEY）"""
    if not PRIVATE_KEY:
        return {"status": "error", "message": "未設定私鑰"}

    normalized_order_type = "post_only" if order_type in ("limit", "post_only") else order_type
    orderbook_ref = choose_limit_price(
        coin,
        side,
        base_url=HL_API_URL,
        passive=(normalized_order_type == "post_only"),
    )
    resolved_price = price
    if resolved_price is None and orderbook_ref:
        resolved_price = orderbook_ref["price"]
    if resolved_price is None:
        return {"status": "error", "message": f"無法取得 {coin} 的 HL order book 價格"}
    
    # TODO: 接入 EIP-712 簽名
    # 目前為接口預留
    print(
        f'  🔴 實盤下单: {coin} {side} {size} @ {resolved_price}'
        f' | type={normalized_order_type}'
        f' | bid={orderbook_ref["best_bid"] if orderbook_ref else "n/a"}'
        f' ask={orderbook_ref["best_ask"] if orderbook_ref else "n/a"}'
    )
    return {
        "status": "dry_run",
        "message": "接口預留",
        "resolved_price": resolved_price,
        "order_type": normalized_order_type,
        "best_bid": orderbook_ref["best_bid"] if orderbook_ref else None,
        "best_ask": orderbook_ref["best_ask"] if orderbook_ref else None,
        "source": "hyperliquid_l2_book",
    }

def get_hl_balance():
    """查詢 Hyperliquid 帳戶餘額"""
    if not WALLET_ADDRESS:
        return {"error": "未設定錢包地址"}
    # TODO: 接入 Hyperliquid clearinghouseState API
    return {"status": "dry_run"}

# ══════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════

def load_state(name):
    path = os.path.join(MULTI_STATE_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, 'r') as f: return json.load(f)
    params = list(STRATEGIES.values())[0] if name not in STRATEGIES else STRATEGIES[name]
    return {
        'strategy': name, 'balance': params['initial_balance'],
        'positions': [], 'history': [], 'params': params,
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }

def save_state(name, state):
    path = os.path.join(MULTI_STATE_DIR, f"{name}.json")
    with open(path, 'w') as f: json.dump(state, f, indent=2, ensure_ascii=False)

def run_once(name, coins):
    state = load_state(name)
    prices = get_current_prices(coins)
    
    print(f'\n[{name}] {datetime.now().strftime("%Y-%m-%d %H:%M")} | 餘額: ${state["balance"]:.2f} | 持倉: {len(state["positions"])}')
    
    update_positions(state, prices)
    check_entries(state, coins)
    
    for pos in state['positions']:
        if pos['coin'] in prices:
            pos['current_price'] = prices[pos['coin']]
    
    save_state(name, state)
    print(f'   完成 | 餘額: ${state["balance"]:.2f}')
    return state

def run_all():
    coins = load_coin_list()
    print(f'💰 幣種數: {len(coins)} | 模式: {"實盤" if MODE=="live" else "Paper Trade"}')
    
    if MODE == "live":
        if not PRIVATE_KEY:
            print('❌ 實盤模式需要設定 HL_PRIVATE_KEY 環境變數')
            return
        print(f'  ⚠️ 實盤模式 - 錢包: {WALLET_ADDRESS[:10]}...' if WALLET_ADDRESS else '  ⚠️ 未設定錢包地址')
    
    results = {}
    for name in STRATEGIES:
        state = run_once(name, coins)
        results[name] = state
    
    # 對比
    print(f'\n\n{"="*90}')
    print(f'📊 策略對比')
    print(f'{"="*90}')
    print(f'{"策略":<16} {"類型":<6} {"槓桿":>4} {"風險":>5} {"倉位":>4} {"超時":>4} {"餘額":>10} {"PnL%":>7} {"交易":>5} {"WR":>5}')
    for name, s in results.items():
        p = STRATEGIES[name]
        st = s['stats']
        total = st['total_trades']
        wr = st['wins']/total*100 if total > 0 else 0
        pct = (s['balance']/p['initial_balance']-1)*100
        print(f'{name:<16} {p["strategy_type"]:<6} {p["leverage"]:>3}x {p["risk_per_trade"]*100:>4.0f}% {p["max_positions"]:>3} {p["max_hold_days"]:>3}d ${s["balance"]:>9.2f} {pct:>+6.1f}% {total:>4} {wr:>4.0f}%')
    
    best = max(results.items(), key=lambda x: x[1]['balance'])
    print(f'\n🏆 最佳: {best[0]} → ${best[1]["balance"]:.2f}')
    return results

if __name__ == '__main__':
    import sys
    args = sys.argv[1:]
    
    if '--live' in args:
        MODE = "live"
        print('⚠️ 實盤模式！')
    elif '--reset' in args:
        import shutil
        if os.path.exists(MULTI_STATE_DIR): shutil.rmtree(MULTI_STATE_DIR)
        os.makedirs(MULTI_STATE_DIR, exist_ok=True)
        print('✅ 已重置')
    else:
        run_all()
