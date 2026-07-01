#!/usr/bin/env python3
"""
fvg_enhanced_backtest.py - 改善版本回測
對比原策略 vs 加入 Daily Risk Limit + EMA200 Filter + Break-even Stop
用 1000 天數據 + Walk Forward 驗證
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
# 指標
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
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
           for i in range(1, len(highs))]
    if len(trs) < period: return sum(trs)/len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period-1) + tr) / period
    return atr

def calc_adx(highs, lows, closes, period=14):
    if len(highs) < period+1: return 20
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(highs)):
        up, down = highs[i]-highs[i-1], lows[i-1]-lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        trs.append(max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])))
    if len(plus_dm) < period: return 20
    atr = sum(trs[:period]) / period if trs else 1
    if atr == 0: return 20
    plus_di = sum(plus_dm[-period:]) / (period*atr) * 100
    minus_di = sum(minus_dm[-period:]) / (period*atr) * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di+minus_di) > 0 else 0
    return dx

# ══════════════════════════════════════════════════════════════
# 信號生成
# ══════════════════════════════════════════════════════════════

def generate_signal(klines, min_score=4, use_ema200_filter=False):
    if not klines or len(klines) < 50: return None
    closes = [d['close'] for d in klines]
    highs = [d['high'] for d in klines]
    lows = [d['low'] for d in klines]
    vols = [d.get('volume', 0) for d in klines]
    i = len(klines) - 1
    current = closes[i]
    
    adx_val = calc_adx(highs, lows, closes)
    atr_val = calc_atr(highs, lows, closes)
    if not atr_val or atr_val == 0: atr_val = current * 0.03
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else None
    
    if adx_val < 25: return None
    
    ts = 0
    if i >= 20:
        roc_5 = (closes[i]-closes[i-5])/closes[i-5]*100
        roc_20 = (closes[i]-closes[i-20])/closes[i-20]*100
        ma = roc_5 - roc_20*0.3
        if ma > 3: ts += 3
        elif ma > 1: ts += 1
        elif ma < -3: ts -= 3
        elif ma < -1: ts -= 1
    
    if i >= 20:
        atr5 = calc_atr(highs[-5:], lows[-5:], closes[-5:])
        vr = atr5/atr_val if atr_val > 0 else 1
        if vr > 1.5: ts += 2
        elif vr < 0.7: ts -= 1
    
    if i >= 20:
        va = statistics.mean(vols[max(0,i-5):i+1])
        vb = statistics.mean(vols[max(0,i-20):i+1])
        if vb > 0:
            vr = va/vb
            if vr > 1.5: ts += 2
            elif vr < 0.6: ts -= 1
    
    if i >= 20 and current > max(highs[i-20:i]): ts += 2
    if current > ema20 and ema20 > ema50: ts += 1
    elif current < ema20 and ema20 < ema50: ts -= 1
    
    if ts < min_score and ts > -min_score: return None
    
    # EMA200 Filter
    if use_ema200_filter and ema200:
        if ts > 0 and current < ema200: return None  # 價格在 EMA200 下方不做多
        if ts < 0 and current > ema200: return None  # 價格在 EMA200 上方不做空
    
    direction = 'long' if ts > 0 else 'short'
    sl_dist = atr_val * 1.5
    tp_dist = atr_val * 2.0
    
    if direction == 'long':
        return {'direction': 'long', 'score': ts, 'tp': current+tp_dist,
                'sl': current-sl_dist, 'reason': 'TREND_BUY', 'adx': adx_val}
    else:
        return {'direction': 'short', 'score': ts, 'tp': current-tp_dist,
                'sl': current+sl_dist, 'reason': 'TREND_SELL', 'adx': adx_val}

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
# 回測引擎
# ══════════════════════════════════════════════════════════════

def run_backtest(name, lev, risk, use_ema200=False, use_daily_limit=False,
                 use_breakeven=False, use_dynamic_sizing=False,
                 start_day=50, end_day=None):
    """完整回測，可選擇不同保護機制"""
    if end_day is None: end_day = min_days
    
    state = {
        'balance': 1000.0, 'positions': [], 'history': [],
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }
    
    daily_pnl = 0.0
    today = ''
    
    for day_idx in range(start_day, end_day):
        # 每日虧損重置
        current_day = f"day_{day_idx}"
        if current_day != today:
            today = current_day
            if use_daily_limit and daily_pnl < -state['balance'] * 0.05:
                pass  # 跳過今天
            daily_pnl = 0.0
        
        prices = {cn: d[day_idx]['close'] for cn, d in all_data.items() if day_idx < len(d)}
        if not prices: continue
        
        # 更新持倉
        still_open = []
        for pos in state['positions']:
            c = pos['coin']
            if c not in prices: still_open.append(pos); continue
            cur = prices[c]
            pos['current_price'] = cur
            pnl = (cur - pos['entry']) * pos['size'] if pos['direction'] == 'long' else (pos['entry'] - cur) * pos['size']
            pos['pnl_pnl'] = pnl
            
            close = False; reason = ''
            
            # TP/SL
            if pos['direction'] == 'long':
                if cur >= pos['tp']: close, reason = True, 'TP'
                elif cur <= pos['sl']: close, reason = True, 'SL'
            else:
                if cur <= pos['tp']: close, reason = True, 'TP'
                elif cur >= pos['sl']: close, reason = True, 'SL'
            
            # Break-even Stop
            if not close and use_breakeven and pnl > 0:
                entry = pos['entry']
                risk_amt = abs(entry - pos['sl'])
                if pos['direction']=='long' and cur >= entry + risk_amt:
                    new_sl = entry * 1.005  # break-even + fee
                    if new_sl > pos['sl']: pos['sl'] = new_sl
                    if cur <= pos['sl']: close,reason=True,'BREAKEVEN'
                elif pos['direction']=='short' and cur <= entry - risk_amt:
                    new_sl = entry * 0.995
                    if new_sl < pos['sl']: pos['sl'] = new_sl
                    if cur >= pos['sl']: close,reason=True,'BREAKEVEN'
            
            # 趨勢反轉
            if not close and c in all_data:
                d = all_data[c]
                if day_idx < len(d):
                    sub = d[:day_idx+1]
                    if len(sub) >= 30:
                        cls = [x['close'] for x in sub]
                        e20 = calc_ema(cls, 20)
                        e50 = calc_ema(cls, 50)
                        e20_prev = calc_ema(cls[:-1], 20) if len(cls)>20 else e20
                        e50_prev = calc_ema(cls[:-1], 50) if len(cls)>50 else e50
                        if pos['direction']=='long' and cur<e20 and e20<e50 and e20_prev>=e50_prev:
                            close,reason=True,'REVERSAL'
                        elif pos['direction']=='short' and cur>e20 and e20>e50 and e20_prev<=e50_prev:
                            close,reason=True,'REVERSAL'
            
            # 超時
            if not close and day_idx-pos.get('entry_day',0) > (14 if lev==3 else 30):
                close,reason=True,'TIME'
            
            if close:
                state['balance']+=pnl; daily_pnl+=pnl
                state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
                if pnl>0: state['stats']['wins']+=1; state['stats']['max_win']=max(state['stats']['max_win'],pnl)
                else: state['stats']['losses']+=1; state['stats']['max_loss']=min(state['stats']['max_loss'],pnl)
                state['history'].append({'coin':c,'dir':pos['direction'],'pnl':round(pnl,4),'reason':reason})
            else: still_open.append(pos)
        state['positions']=still_open
        
        # 每日虧損上限
        if use_daily_limit and daily_pnl < -state['balance'] * 0.05:
            continue  # 停止當天交易
        
        # 每 3 天掃描
        if day_idx%3==0 and len(state['positions'])<(2 if lev==3 else 3):
            btc_dir = get_btc_direction(day_idx)
            for cn, d in all_data.items():
                if len(state['positions'])>=(2 if lev==3 else 3): break
                if any(p['coin']==cn for p in state['positions']): continue
                if day_idx>=len(d): continue
                sub = d[:day_idx+1]
                if len(sub)<50: continue
                
                sig = generate_signal(sub, 4, use_ema200)
                if not sig: continue
                if btc_dir=="bull" and sig['direction']=="short": continue
                if btc_dir=="bear" and sig['direction']=="long": continue
                
                entry = prices.get(cn)
                if not entry: continue
                
                # Dynamic Position Size
                actual_risk = risk
                if use_dynamic_sizing:
                    atr_val = calc_atr([x['high'] for x in sub[-14:]], [x['low'] for x in sub[-14:]], [x['close'] for x in sub[-14:]])
                    atr_pct = atr_val / entry * 100
                    if atr_pct > 5: actual_risk = 0.05
                    elif atr_pct < 2: actual_risk = 0.10
                
                size = calc_size(state['balance'], entry, sig['sl'], lev, actual_risk)
                if size<=0: continue
                
                state['positions'].append({'coin':cn,'direction':sig['direction'],
                    'entry':entry,'tp':sig['tp'],'sl':sig['sl'],'size':round(size,6),
                    'current_price':entry,'entry_day':day_idx,'sig':sig.get('reason','')})
    
    # 平倉
    for pos in state['positions']:
        c=pos['coin']
        if c in all_data:
            fp=all_data[c][end_day-1]['close']
            pnl=(fp-pos['entry'])*pos['size'] if pos['direction']=='long' else (pos['entry']-fp)*pos['size']
            state['balance']+=pnl
            state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
            if pnl>0: state['stats']['wins']+=1
            else: state['stats']['losses']+=1
            state['history'].append({'coin':c,'dir':pos['direction'],'pnl':round(pnl,4),'reason':'END'})
    
    return state

def calc_max_drawdown(state):
    peak = 1000.0
    max_dd = 0.0
    cum = 0.0
    for h in state['history']:
        cum += h['pnl']
        peak = max(peak, 1000+cum)
        dd = (peak - (1000+cum)) / peak * 100
        max_dd = max(max_dd, dd)
    return max_dd

def calc_profit_factor(state):
    wins = sum(h['pnl'] for h in state['history'] if h['pnl'] > 0)
    losses = abs(sum(h['pnl'] for h in state['history'] if h['pnl'] < 0))
    return wins / losses if losses > 0 else float('inf')

def calc_sharpe(state):
    if not state['history']: return 0
    rets = [h['pnl']/1000*100 for h in state['history']]
    if len(rets) < 2: return 0
    avg = statistics.mean(rets)
    std = statistics.stdev(rets)
    return avg / std * (252**0.5) if std > 0 else 0

# ══════════════════════════════════════════════════════════════
# 跑 8 組對比
# ══════════════════════════════════════════════════════════════

print(f'\n{"="*110}')
print(f'🔬 改善版本對比（1000天，50幣種）')
print(f'{"="*110}')

configs = [
    # 基準
    ("原策略 5x 8%", 5, 0.08, False, False, False, False),
    # 單個改善
    ("+ EMA200 Filter", 5, 0.08, True, False, False, False),
    ("+ Daily Risk Limit", 5, 0.08, False, True, False, False),
    ("+ Break-even Stop", 5, 0.08, False, False, True, False),
    ("+ Dynamic Sizing", 5, 0.08, False, False, False, True),
    # 組合
    ("+ EMA200 + Daily Limit", 5, 0.08, True, True, False, False),
    ("+ 全保護", 5, 0.08, True, True, True, True),
    # 保守組合
    ("3x + 全保護", 3, 0.08, True, True, True, True),
]

results = []
for name, lev, risk, ema200, daily_limit, breakeven, dynamic in configs:
    state = run_backtest(name, lev, risk, ema200, daily_limit, breakeven, dynamic)
    st = state['stats']
    total = st['total_trades']
    wr = st['wins']/total*100 if total > 0 else 0
    pct = (state['balance']/1000-1)*100
    pf = calc_profit_factor(state)
    mdd = calc_max_drawdown(state)
    sharpe = calc_sharpe(state)
    avg = st['total_pnl']/total if total > 0 else 0
    results.append((name, state, total, wr, pct, pf, mdd, sharpe, avg))

# 輸出
print(f'\n{"策略":<25} {"交易":>5} {"WR":>5} {"PnL%":>8} {"PF":>6} {"MaxDD":>7} {"Sharpe":>7} {"Avg":>9}')
print(f'{"─"*25} {"─"*5} {"─"*5} {"─"*8} {"─"*6} {"─"*7} {"─"*7} {"─"*9}')

for name, s, total, wr, pct, pf, mdd, sharpe, avg in sorted(results, key=lambda x: -x[4]):
    print(f'{name:<25} {total:>4} {wr:>4.0f}% {pct:>+7.1f}% {pf:>5.2f} {mdd:>5.1f}% {sharpe:>6.2f} ${avg:>+8.2f}')

# 最佳
best = max(results, key=lambda x: x[4])
print(f'\n🏆 最高報酬: {best[0]} → PnL {best[4]:+.1f}%')
best_pf = max(results, key=lambda x: x[5])
print(f'🏆 最高損益比: {best_pf[0]} → PF {best_pf[5]:.2f}')
best_mdd = min(results, key=lambda x: x[6])
print(f'🏆 最小回撤: {best_mdd[0]} → MDD {best_mdd[6]:.1f}%')
best_sharpe = max(results, key=lambda x: x[7])
print(f'🏆 最高 Sharpe: {best_sharpe[0]} → {best_sharpe[7]:.2f}')

# 改善對比
print(f'\n📊 改善效果（vs 原策略）:')
base = [x for x in results if x[0] == '原策略 5x 8%'][0]
for name, s, total, wr, pct, pf, mdd, sharpe, avg in results[1:]:
    pct_diff = pct - base[4]
    mdd_diff = mdd - base[6]
    pf_diff = pf - base[5]
    sh_diff = sharpe - base[7]
    print(f'  {name:<25}: PnL {pct_diff:+7.1f}% | MDD {mdd_diff:+5.1f}% | PF {pf_diff:+.2f} | Sharpe {sh_diff:+.2f}')
