#!/usr/bin/env python3
"""
fvg_multi_coin.py - 50 幣種 + FVG/趨勢 + 相關性確認
Paper trade 即時模擬，支援多組參數對比
"""
import sys, os, json, statistics
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import adx, atr, ema
from live_monitor import get_binance_klines
import urllib.request

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

MULTI_STATE_DIR = os.path.expanduser('~/.hermes/trading-knowledge/paper_strategies_v2')
os.makedirs(MULTI_STATE_DIR, exist_ok=True)

# 6 組策略
STRATEGIES = {
    "趨勢5x_8pct": {
        "initial_balance": 1000.0, "max_positions": 3, "max_hold_days": 30,
        "leverage": 5, "risk_per_trade": 0.08, "strategy_type": "trend",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
        "min_score": 4, "min_cor_confirm": 0,
    },
    "趨勢5x_10pct": {
        "initial_balance": 1000.0, "max_positions": 3, "max_hold_days": 30,
        "leverage": 5, "risk_per_trade": 0.10, "strategy_type": "trend",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
        "min_score": 4, "min_cor_confirm": 0,
    },
    "趨勢3x_8pct": {
        "initial_balance": 1000.0, "max_positions": 2, "max_hold_days": 14,
        "leverage": 3, "risk_per_trade": 0.08, "strategy_type": "trend",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
        "min_score": 4, "min_cor_confirm": 0,
    },
    "趨勢3x_10pct": {
        "initial_balance": 1000.0, "max_positions": 2, "max_hold_days": 14,
        "leverage": 3, "risk_per_trade": 0.10, "strategy_type": "trend",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
        "min_score": 4, "min_cor_confirm": 0,
    },
}

# ══════════════════════════════════════════════════════════════
# 幣種管理
# ══════════════════════════════════════════════════════════════

def load_coin_list():
    """載入 Binance USDT 幣種"""
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
        
        # 只保留前 50 個
        coins = coins[:50]
        
        with open(cache_path, 'w') as f:
            json.dump(coins, f, indent=2)
        
        return coins
    except Exception as e:
        print(f'  ⚠️ 載入幣種失敗: {e}，使用備用列表')
        return [{'name': c, 'symbol': c+'USDT'} for c in ['BTC','ETH','BNB','SOL','XRP','ADA','DOGE','AVAX','LINK','DOT','MATIC','LTC','UNI','ATOM','ETC','FIL','APT','ARB','OP','NEAR','FTM','AAVE','MKR','INJ','SUI','SEI','TIA','JUP','WLD','PEPE','SHIB','BCH','ICP','ALGO','FTM','HBAR','VET','MANA','SAND','AXS','THETA','KAVA','RUNE'][:50]]

# ══════════════════════════════════════════════════════════════
# 信號生成（FVG + 趨勢）
# ══════════════════════════════════════════════════════════════

def find_fvg(closes, highs, lows, i, lookback=5):
    fvgs = []
    for j in range(max(i-lookback, 2), i+1):
        k1_h, k1_l = highs[j-2], lows[j-2]
        k3_h, k3_l = highs[j], lows[j]
        if k1_h < k3_l:
            fvgs.append(('bull', k1_h, k3_l))
        if k1_l > k3_h:
            fvgs.append(('bear', k3_h, k1_l))
    return fvgs

def price_in_fvg(price, fvgs):
    for d, lo, hi in fvgs:
        if lo <= price <= hi: return d
    return None

def fib_position(price, h50, l50):
    r = h50 - l50
    if r == 0: return 50
    return (h50 - price) / r * 100

def get_adx_val(highs, lows, closes, n=14):
    result = adx(highs, lows, closes, n)
    if isinstance(result, tuple) and len(result) >= 1:
        if isinstance(result[0], list):
            for v in reversed(result[0]):
                if v is not None: return v
    return 20

def get_atr_val(highs, lows, closes, n=14):
    result = atr(highs, lows, closes, n)
    if isinstance(result, list):
        return result[-1] if result else None
    return result

def get_ema_val(closes, period):
    result = ema(closes, period)
    if isinstance(result, list):
        return result[-1] if result else None
    return result

def generate_signal(data, strategy_type):
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
    
    high_50 = max(highs[max(0,i-50):i+1])
    low_50 = min(lows[max(0,i-50):i+1])
    ema20 = get_ema_val(closes, 20) or current
    ema50 = get_ema_val(closes, 50) or current
    
    signal = None
    
    # FVG 均值回歸（ADX < 25）
    if strategy_type in ("fvg", "both") and adx_val < 25:
        fvgs = find_fvg(closes, highs, lows, i)
        fvg_dir = price_in_fvg(current, fvgs)
        fib_pos = fib_position(current, high_50, low_50)
        
        score = 0
        if 33 <= fib_pos <= 43: score += 3
        if 47 <= fib_pos <= 53: score += 2
        if 58 <= fib_pos <= 65: score += 1
        if fib_pos < 15: score -= 3
        if fib_pos > 85: score -= 2
        if fvg_dir == 'bull': score += 3
        elif fvg_dir == 'bear': score -= 3
        
        if len(vols) >= 20:
            vol_avg = statistics.mean(vols[max(0,i-5):i+1])
            vol_20 = statistics.mean(vols[max(0,i-20):i+1])
            vr = vol_avg / vol_20 if vol_20 > 0 else 1
            if vr > 1.3: score = int(score * 1.15)
            elif vr < 0.7: score = int(score * 0.85)
        
        if score >= 4:
            signal = {'direction': 'long', 'score': score, 'tp': current + (current-low_50)*1.5,
                      'sl': low_50, 'reason': 'FVG_BUY', 'adx': adx_val}
        elif score <= -4:
            signal = {'direction': 'short', 'score': score, 'tp': current - (high_50-current)*1.5,
                      'sl': high_50, 'reason': 'FVG_SELL', 'adx': adx_val}
    
    # 趨勢追蹤（ADX >= 25）
    if strategy_type in ("trend", "both") and adx_val >= 25:
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
        
        if ts >= 3:
            signal = {'direction': 'long', 'score': ts, 'tp': current+atr_val*2.0,
                      'sl': current-atr_val*1.5, 'reason': 'TREND_BUY', 'adx': adx_val}
        elif ts <= -3:
            signal = {'direction': 'short', 'score': ts, 'tp': current-atr_val*2.0,
                      'sl': current+atr_val*1.5, 'reason': 'TREND_SELL', 'adx': adx_val}
    
    return signal

# ══════════════════════════════════════════════════════════════
# 相關性確認
# ══════════════════════════════════════════════════════════════

def build_corr_pairs(all_data, min_corr=0.7):
    """從歷史數據建立高相關對"""
    coins = list(all_data.keys())
    min_len = 30
    closes = {}
    for c, d in all_data.items():
        closes[c] = [x['close'] for x in d]
    
    pairs = {}
    for i in range(len(coins)):
        for j in range(i+1, len(coins)):
            c1, c2 = coins[i], coins[j]
            d1, d2 = closes[c1], closes[c2]
            n = min(len(d1), len(d2))
            if n < min_len: continue
            d1, d2 = d1[:n], d2[:n]
            m1, m2 = sum(d1)/n, sum(d2)/n
            cov = sum((a-m1)*(b-m2) for a,b in zip(d1,d2))/n
            s1 = (sum((a-m1)**2 for a in d1)/n)**0.5
            s2 = (sum((b-m2)**2 for b in d2)/n)**0.5
            r = cov/(s1*s2) if s1>0 and s2>0 else 0
            if r >= min_corr:
                if c1 not in pairs: pairs[c1] = []
                if c2 not in pairs: pairs[c2] = []
                pairs[c1].append(c2)
                pairs[c2].append(c1)
    
    return pairs

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

def check_correlation(target_coin, target_dir, signal_cache, corr_pairs):
    """檢查是否有高相關幣種同方向信號"""
    if target_coin not in corr_pairs:
        return 0
    count = 0
    for corr_coin in corr_pairs[target_coin]:
        if corr_coin in signal_cache:
            if signal_cache[corr_coin] == target_dir:
                count += 1
    return count

# ══════════════════════════════════════════════════════════════
# 交易引擎
# ══════════════════════════════════════════════════════════════

def load_state(name):
    path = os.path.join(MULTI_STATE_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, 'r') as f: return json.load(f)
    params = STRATEGIES[name]
    return {
        'strategy': name, 'balance': params['initial_balance'],
        'positions': [], 'history': [], 'params': params,
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }

def save_state(name, state):
    path = os.path.join(MULTI_STATE_DIR, f"{name}.json")
    with open(path, 'w') as f: json.dump(state, f, indent=2, ensure_ascii=False)

def calc_size(balance, entry, sl, lev, risk):
    ra = balance * risk
    sd = abs(entry - sl)
    if sd == 0: return 0
    size = ra / sd
    margin = size * entry / lev
    if margin > balance * 0.95:
        size = (balance * 0.95 * lev) / entry
    return size

def check_circuit(state):
    p = state['params']
    today = datetime.now().strftime('%Y-%m-%d')
    today_pnl = sum(h.get('pnl',0) for h in state.get('history',[]) if h.get('exit_time','').startswith(today))
    if today_pnl < -state['balance'] * p['max_daily_loss_pct']/100:
        return False
    recent = [h for h in state.get('history',[]) if h.get('exit_time','') >= (datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d')]
    cons = sum(1 for h in reversed(recent) if h.get('pnl',0) < 0)
    if cons >= p['max_consecutive_losses']:
        return False
    return True

def is_cooldown(state, coin):
    cutoff = datetime.now() - timedelta(hours=state['params']['cooldown_hours'])
    for h in reversed(state.get('history',[])):
        if h.get('coin') == coin:
            try:
                if datetime.fromisoformat(h.get('exit_time','')) > cutoff: return True
            except: pass
            break
    return False

def update_positions(state, prices, day_idx=None):
    """更新持倉：TP/SL + 趨勢反轉檢測（無移動止損，5x太激進）"""
    still_open = []
    for pos in state['positions']:
        c = pos['coin']
        if c not in prices: still_open.append(pos); continue
        cur = prices[c]
        pos['current_price'] = cur
        pnl = (cur - pos['entry'])*pos['size'] if pos['direction']=='long' else (pos['entry']-cur)*pos['size']
        pos['pnl_pnl'] = pnl
        
        close = False; reason = ''
        
        # 1. TP/SL
        if pos['direction']=='long':
            if cur>=pos['tp']: close,reason=True,'TP'
            elif cur<=pos['sl']: close,reason=True,'SL'
        else:
            if cur<=pos['tp']: close,reason=True,'TP'
            elif cur>=pos['sl']: close,reason=True,'SL'
        
        # 2. 趨勢反轉檢測（需要 K 線數據）
        if not close and c in state.get('_data_cache', {}):
            data = state['_data_cache'][c]
            if day_idx and day_idx < len(data):
                sub = data[:day_idx+1]
                if len(sub) >= 30:
                    closes = [d['close'] for d in sub]
                    ema20_now = sum(closes[-20:]) / min(20, len(closes))
                    ema50_now = sum(closes[-50:]) / min(50, len(closes))
                    ema20_prev = sum(closes[-21:-1]) / min(20, len(closes)-1) if len(closes) > 20 else ema20_now
                    ema50_prev = sum(closes[-51:-1]) / min(50, len(closes)-1) if len(closes) > 50 else ema50_now
                    
                    if pos['direction'] == 'long':
                        # 多頭：價格跌破 EMA20 且 EMA20 下穿 EMA50
                        if cur < ema20_now and ema20_now < ema50_now and ema20_prev >= ema50_prev:
                            close, reason = True, 'REVERSAL'
                    else:
                        # 空頭：價格站上 EMA20 且 EMA20 上穿 EMA50
                        if cur > ema20_now and ema20_now > ema50_now and ema20_prev <= ema50_prev:
                            close, reason = True, 'REVERSAL'
        
        # 3. 超時
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
            state['history'].append({'coin':c,'dir':pos['direction'],'entry':pos['entry'],'exit':cur,'pnl':round(pnl,4),'reason':reason,'exit_time':datetime.now().isoformat(),'sig':pos.get('sig','')})
        else:
            still_open.append(pos)
    state['positions'] = still_open

def check_entries(state, coins, corr_pairs):
    p = state['params']
    if len(state['positions']) >= p['max_positions']: return
    if not check_circuit(state): return
    
    btc_dir = get_btc_direction()
    prices = {}
    for coin in coins:
        try:
            d = get_binance_klines(coin['symbol'], limit=60)
            if d and len(d) >= 50:
                prices[coin['name']] = d[-1]['close']
        except: pass
    
    # 先掃描所有幣種，快取信號
    signal_cache = {}
    for coin in coins:
        cn = coin['name']
        try:
            d = get_binance_klines(coin['symbol'], limit=60)
            if d and len(d) >= 50:
                sig = generate_signal(d, p['strategy_type'])
                if sig:
                    signal_cache[cn] = sig['direction']
        except: pass
    
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
        
        # 存到 state cache 給趨勢反轉檢測用
        if '_data_cache' not in state:
            state['_data_cache'] = {}
        state['_data_cache'][cn] = d
        
        sig = generate_signal(d, p['strategy_type'])
        if not sig: continue
        
        # BTC 方向過濾
        if btc_dir == "bull" and sig['direction'] == "short": continue
        if btc_dir == "bear" and sig['direction'] == "long": continue
        
        # 相關性確認（若無相關對則跳過此檢查）
        confirms = 0
        if cn in corr_pairs and corr_pairs[cn]:
            confirms = check_correlation(cn, sig['direction'], signal_cache, corr_pairs)
            if confirms < p.get('min_cor_confirm', 1):
                continue
        
        entry = prices[cn]
        size = calc_size(state['balance'], entry, sig['sl'], p['leverage'], p['risk_per_trade'])
        if size <= 0: continue
        
        state['positions'].append({
            'coin': cn, 'direction': sig['direction'],
            'entry': entry, 'tp': sig['tp'], 'sl': sig['sl'],
            'size': round(size, 6), 'current_price': entry,
            'pnl_pnl': 0, 'entry_time': datetime.now().isoformat(),
            'sig': sig.get('reason', ''),
        })
        print(f'  ✅ 建倉: {cn} {sig["direction"]} @ ${entry:,.2f} | {sig["reason"]} | 確認={confirms}')

def run_once(name, coins, corr_pairs):
    state = load_state(name)
    prices = {}
    for coin in coins:
        try:
            d = get_binance_klines(coin['symbol'], limit=5)
            if d: prices[coin['name']] = d[-1]['close']
        except: pass
    
    print(f'\n[{name}] {datetime.now().strftime("%Y-%m-%d %H:%M")} | 餘額: ${state["balance"]:.2f} | 持倉: {len(state["positions"])}')
    
    update_positions(state, prices)
    check_entries(state, coins, corr_pairs)
    
    for pos in state['positions']:
        if pos['coin'] in prices:
            pos['current_price'] = prices[pos['coin']]
    
    save_state(name, state)
    print(f'   完成 | 餘額: ${state["balance"]:.2f}')
    return state

def run_once_with_idx(name, coins, corr_pairs, day_idx, data_cache):
    """帶 day_idx 和 data_cache 的版本（用於回測）"""
    state = load_state(name)
    state['_data_cache'] = data_cache
    
    prices = {}
    for coin in coins:
        try:
            d = data_cache.get(coin, [])
            if d and day_idx < len(d):
                prices[coin] = d[day_idx]['close']
        except: pass
    
    update_positions(state, prices, day_idx=day_idx)
    
    for pos in state['positions']:
        if pos['coin'] in prices:
            pos['current_price'] = prices[pos['coin']]
    
    return state

def run_all():
    coins = load_coin_list()
    print(f'💰 幣種數: {len(coins)}')
    
    # 建立相關性對（用 BTC 相關性 > 0.7）
    print('📊 建立相關性...')
    all_data = {}
    for coin in coins[:10]:  # 先取 10 個建立
        try:
            d = get_binance_klines(coin['symbol'], limit=60)
            if d and len(d) >= 30:
                all_data[coin['name']] = d
        except: pass
    
    corr_pairs = build_corr_pairs(all_data)
    print(f'  相關對: {sum(len(v) for v in corr_pairs.values())//2} 對')
    
    results = {}
    for name in STRATEGIES:
        state = run_once(name, coins, corr_pairs)
        results[name] = state
    
    # 對比
    print(f'\n\n{"="*90}')
    print('📊 50 幣種 + 相關性過濾 策略對比')
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
    if '--reset' in args:
        import shutil
        if os.path.exists(MULTI_STATE_DIR): shutil.rmtree(MULTI_STATE_DIR)
        os.makedirs(MULTI_STATE_DIR, exist_ok=True)
        print('✅ 已重置')
    else:
        run_all()
