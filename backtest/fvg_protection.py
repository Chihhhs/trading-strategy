#!/usr/bin/env python3
"""
fvg_protection.py - 測試移動止損 + 趨勢反轉檢測效果
用 1000 天數據回測，對比有/無保護的差異
"""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import adx, atr, ema

# 載入數據
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_PATH = os.path.join(PROJECT_ROOT, 'data', 'historical_prices', '1000d_50coins.json')
with open(DATA_PATH, 'r') as f:
    all_data = json.load(f)

coins = list(all_data.keys())
min_days = min(len(d) for d in all_data.values())
print(f'📊 載入 {len(coins)} 幣種，{min_days} 天')

# ══════════════════════════════════════════════════════════════
# 信號生成
# ══════════════════════════════════════════════════════════════

def find_fvg(closes, highs, lows, i, lookback=5):
    fvgs = []
    for j in range(max(i-lookback, 2), i+1):
        if highs[j-2] < lows[j]: fvgs.append(('bull', highs[j-2], lows[j]))
        if lows[j-2] > highs[j]: fvgs.append(('bear', highs[j], lows[j-2]))
    return fvgs

def price_in_fvg(price, fvgs):
    for d, lo, hi in fvgs:
        if lo <= price <= hi: return d
    return None

def fib_position(price, h50, l50):
    r = h50 - l50
    return (h50 - price) / r * 100 if r != 0 else 50

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

def generate_signal(data, strategy_type, min_score=4):
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
        if ts >= min_score:
            signal = {'direction': 'long', 'score': ts, 'tp': current+atr_val*2.0,
                      'sl': current-atr_val*1.5, 'reason': 'TREND_BUY', 'adx': adx_val}
        elif ts <= -min_score:
            signal = {'direction': 'short', 'score': ts, 'tp': current-atr_val*2.0,
                      'sl': current+atr_val*1.5, 'reason': 'TREND_SELL', 'adx': adx_val}
    
    return signal

def calc_size(balance, entry, sl, lev, risk):
    ra = balance * risk
    sd = abs(entry - sl)
    if sd == 0: return 0
    size = ra / sd
    margin = size * entry / lev
    if margin > balance * 0.95:
        size = (balance * 0.95 * lev) / entry
    return size

def get_btc_direction(day_idx):
    if 'BTC' not in all_data: return "neutral"
    d = all_data['BTC']
    if day_idx < 7: return "neutral"
    chg = (d[day_idx]['close']/d[day_idx-7]['close']-1)*100
    if chg > 3: return "bull"
    elif chg < -3: return "bear"
    return "neutral"

# ══════════════════════════════════════════════════════════════
# 回測
# ══════════════════════════════════════════════════════════════

def run_backtest(name, lev, risk, use_trailing=True, use_reversal=True):
    state = {
        'balance': 1000.0, 'positions': [], 'history': [],
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }
    
    for day_idx in range(50, min_days):
        prices = {cn: d[day_idx]['close'] for cn, d in all_data.items() if day_idx < len(d)}
        if not prices: continue
        
        # 更新持倉
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
            
            # 2. 移動止損
            if not close and use_trailing and pnl > 0:
                entry = pos['entry']
                if pos['direction'] == 'long':
                    pnl_pct = (cur - entry) / entry * 100 * lev
                    if pnl_pct > 5:
                        trailing_sl = cur - (cur - entry) * 0.5
                        trailing_sl = max(trailing_sl, entry * 1.02)
                        if trailing_sl > pos['sl']:
                            pos['sl'] = trailing_sl
                        if cur <= pos['sl']:
                            close, reason = True, 'TRAIL'
                else:
                    pnl_pct = (entry - cur) / entry * 100 * lev
                    if pnl_pct > 5:
                        trailing_sl = cur + (entry - cur) * 0.5
                        trailing_sl = min(trailing_sl, entry * 0.98)
                        if trailing_sl < pos['sl']:
                            pos['sl'] = trailing_sl
                        if cur >= pos['sl']:
                            close, reason = True, 'TRAIL'
            
            # 3. 趨勢反轉檢測
            if not close and use_reversal and c in all_data:
                d = all_data[c]
                if day_idx < len(d):
                    sub = d[:day_idx+1]
                    if len(sub) >= 30:
                        cls = [x['close'] for x in sub]
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
            
            # 4. 超時
            if not close and day_idx - pos.get('entry_day', 0) > (14 if lev == 3 else 30):
                close, reason = True, 'TIME'
            
            if close:
                state['balance']+=pnl
                state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
                if pnl>0: state['stats']['wins']+=1; state['stats']['max_win']=max(state['stats']['max_win'],pnl)
                else: state['stats']['losses']+=1; state['stats']['max_loss']=min(state['stats']['max_loss'],pnl)
                state['history'].append({'coin':c,'dir':pos['direction'],'pnl':round(pnl,4),'reason':reason,'days':day_idx-pos.get('entry_day',0),'sig':pos.get('sig','')})
            else: still_open.append(pos)
        state['positions']=still_open
        
        # 每 3 天掃描
        if day_idx%3==0 and len(state['positions'])<(2 if lev==3 else 3):
            btc_dir = get_btc_direction(day_idx)
            for cn, d in all_data.items():
                if len(state['positions'])>=(2 if lev==3 else 3): break
                if any(p['coin']==cn for p in state['positions']): continue
                if day_idx>=len(d): continue
                sub = d[:day_idx+1]
                if len(sub)<50: continue
                sig = generate_signal(sub, "trend", 4)
                if not sig: continue
                if btc_dir=="bull" and sig['direction']=="short": continue
                if btc_dir=="bear" and sig['direction']=="long": continue
                entry = prices.get(cn)
                if not entry: continue
                size = calc_size(state['balance'], entry, sig['sl'], lev, risk)
                if size<=0: continue
                state['positions'].append({'coin':cn,'direction':sig['direction'],'entry':entry,'tp':sig['tp'],'sl':sig['sl'],'size':round(size,6),'current_price':entry,'entry_day':day_idx,'sig':sig.get('reason','')})
    
    # 平倉
    for pos in state['positions']:
        c=pos['coin']
        if c in all_data:
            fp=all_data[c][min_days-1]['close']
            pnl=(fp-pos['entry'])*pos['size'] if pos['direction']=='long' else (pos['entry']-fp)*pos['size']
            state['balance']+=pnl; state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
            if pnl>0: state['stats']['wins']+=1
            else: state['stats']['losses']+=1
            state['history'].append({'coin':c,'dir':pos['direction'],'pnl':round(pnl,4),'reason':'END','days':min_days-pos.get('entry_day',0),'sig':pos.get('sig','')})
    
    return state

# ══════════════════════════════════════════════════════════════
# 跑 4 組對比
# ══════════════════════════════════════════════════════════════

print(f'\n{"="*100}')
print(f'🔬 移動止損 + 趨勢反轉檢測 效果對比（1000天，50幣種）')
print(f'{"="*100}')

configs = [
    ("5x_8pct", 5, 0.08),
    ("5x_10pct", 5, 0.10),
    ("3x_8pct", 3, 0.08),
    ("3x_10pct", 3, 0.10),
]

protection_modes = [
    ("無保護", False, False),
    ("僅移動止損", True, False),
    ("僅趨勢反轉", False, True),
    ("全保護", True, True),
]

results = []
for cfg_name, lev, risk in configs:
    for prot_name, use_trail, use_rev in protection_modes:
        name = f"{cfg_name}_{prot_name}"
        state = run_backtest(name, lev, risk, use_trail, use_rev)
        st = state['stats']
        total = st['total_trades']
        wr = st['wins']/total*100 if total > 0 else 0
        pct = (state['balance']/1000-1)*100
        results.append((name, state, total, wr, pct, st['max_win'], st['max_loss']))

# 輸出
print(f'\n{"策略":<20} {"保護":<12} {"交易":>5} {"WR":>5} {"PnL%":>8} {"最大盈":>9} {"最大虧":>9}')
print(f'{"─"*20} {"─"*12} {"─"*5} {"─"*5} {"─"*8} {"─"*9} {"─"*9}')

for cfg_name, lev, risk in configs:
    print(f'\n  ▼ {cfg_name}')
    for prot_name, use_trail, use_rev in protection_modes:
        name = f"{cfg_name}_{prot_name}"
        for n, s, total, wr, pct, mxw, mxl in results:
            if n == name:
                print(f'  {n:<20} {prot_name:<12} {total:>4} {wr:>4.0f}% {pct:>+7.1f}% ${mxw:>+8.2f} ${mxl:>+8.2f}')

# 最佳
best = max(results, key=lambda x: x[1]['balance'])
print(f'\n🏆 最佳: {best[0]} → ${best[1]["balance"]:.2f} ({(best[1]["balance"]/1000-1)*100:+.1f}%)')

# 保護 vs 無保護對比
print(f'\n📊 保護效果分析:')
for cfg_name, lev, risk in configs:
    none_pnl = [x[4] for x in results if x[0]==f"{cfg_name}_無保護"]
    full_pnl = [x[4] for x in results if x[0]==f"{cfg_name}_全保護"]
    if none_pnl and full_pnl:
        diff = full_pnl[0] - none_pnl[0]
        print(f'  {cfg_name}: 全保護 vs 無保護 = {diff:+.1f}%')
