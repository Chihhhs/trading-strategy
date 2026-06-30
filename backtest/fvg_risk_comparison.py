#!/usr/bin/env python3
"""
fvg_risk_comparison.py - 風險對比：低風險 vs 高風險+趨勢反轉
1000天回測，看最大回撤 vs 損益比
"""
import json, os, sys, statistics
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import adx, atr, ema

DATA_PATH = os.path.expanduser('~/.hermes/trading-knowledge/historical_prices/1000d_50coins.json')
with open(DATA_PATH, 'r') as f:
    all_data = json.load(f)

coins = list(all_data.keys())
min_days = min(len(d) for d in all_data.values())
print(f'📊 載入 {len(coins)} 幣種，{min_days} 天')

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
    
    if adx_val < 25: return None  # 只要趨勢
    
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

def run_backtest(name, lev, risk, use_reversal):
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
            
            # TP/SL
            if pos['direction']=='long':
                if cur>=pos['tp']: close,reason=True,'TP'
                elif cur<=pos['sl']: close,reason=True,'SL'
            else:
                if cur<=pos['tp']: close,reason=True,'TP'
                elif cur>=pos['sl']: close,reason=True,'SL'
            
            # 趨勢反轉檢測
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
            
            # 超時
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
                sig = generate_signal(sub, 4)
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
            state['balance']+=pnl
            state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
            if pnl>0: state['stats']['wins']+=1
            else: state['stats']['losses']+=1
            state['history'].append({'coin':c,'dir':pos['direction'],'pnl':round(pnl,4),'reason':'END','days':min_days-pos.get('entry_day',0),'sig':pos.get('sig','')})
    
    return state

def calc_max_drawdown(state):
    """計算最大回撤"""
    peak = 1000.0
    max_dd = 0.0
    cum = 0.0
    for h in state['history']:
        cum += h['pnl']
        balance = 1000 + cum
        peak = max(peak, balance)
        dd = (peak - balance) / peak * 100
        max_dd = max(max_dd, dd)
    return max_dd

def calc_profit_factor(state):
    """計算損益比"""
    wins = sum(h['pnl'] for h in state['history'] if h['pnl'] > 0)
    losses = abs(sum(h['pnl'] for h in state['history'] if h['pnl'] < 0))
    return wins / losses if losses > 0 else float('inf')

# ══════════════════════════════════════════════════════════════
# 跑 12 組：3 風險等級 × 2 槓桿 × 2 保護
# ══════════════════════════════════════════════════════════════

configs = [
    ("3x_5%", 3, 0.05),
    ("3x_8%", 3, 0.08),
    ("3x_10%", 3, 0.10),
    ("5x_5%", 5, 0.05),
    ("5x_8%", 5, 0.08),
    ("5x_10%", 5, 0.10),
]

print(f'\n{"="*110}')
print(f'🔬 風險對比：最大回撤 vs 損益比（1000天，50幣種）')
print(f'{"="*110}')

results = []
for cfg_name, lev, risk in configs:
    for use_rev in [False, True]:
        name = f"{cfg_name}_{'有反轉' if use_rev else '無保護'}"
        state = run_backtest(name, lev, risk, use_rev)
        st = state['stats']
        total = st['total_trades']
        wr = st['wins']/total*100 if total > 0 else 0
        pct = (state['balance']/1000-1)*100
        pf = calc_profit_factor(state)
        mdd = calc_max_drawdown(state)
        avg = st['total_pnl']/total if total > 0 else 0
        results.append((name, state, total, wr, pct, pf, mdd, avg, st['max_win'], st['max_loss']))

# 輸出
print(f'\n{"策略":<18} {"交易":>5} {"WR":>5} {"PnL%":>8} {"損益比":>7} {"最大回撤":>8} {"Avg":>9} {"最大盈":>9} {"最大虧":>9}')
print(f'{"─"*18} {"─"*5} {"─"*5} {"─"*8} {"─"*7} {"─"*8} {"─"*9} {"─"*9} {"─"*9}')

for name, s, total, wr, pct, pf, mdd, avg, mxw, mxl in sorted(results, key=lambda x: -x[4]):
    print(f'{name:<18} {total:>4} {wr:>4.0f}% {pct:>+7.1f}% {pf:>6.2f} {mdd:>6.1f}% ${avg:>+8.2f} ${mxw:>+8.2f} ${mxl:>+8.2f}')

# 最佳
best = max(results, key=lambda x: x[4])
print(f'\n🏆 最高報酬: {best[0]} → PnL {best[4]:+.1f}%')
best_pf = max(results, key=lambda x: x[5])
print(f'🏆 最高損益比: {best_pf[0]} → PF {best_pf[5]:.2f}')
best_mdd = min(results, key=lambda x: x[6])
print(f'🏆 最小回撤: {best_mdd[0]} → MDD {best_mdd[6]:.1f}%')

# 有/無保護對比
print(f'\n📊 趨勢反轉保護效果:')
for cfg_name, lev, risk in configs:
    none = [x for x in results if x[0]==f"{cfg_name}_無保護"]
    rev = [x for x in results if x[0]==f"{cfg_name}_有反轉"]
    if none and rev:
        pct_diff = rev[0][4] - none[0][4]
        mdd_diff = rev[0][6] - none[0][6]
        pf_diff = rev[0][5] - none[0][5]
        print(f'  {cfg_name}: PnL {pct_diff:+.1f}% | MDD {mdd_diff:+.1f}% | PF {pf_diff:+.2f}')
