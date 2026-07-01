#!/usr/bin/env python3
"""
fvg_backtest_1000d.py - 1000天回測 + TP/SL 參數優化
測試不同 TP/SL 倍數對報酬的影響
"""
import sys, os, json, statistics
sys.path.insert(0, os.path.dirname(__file__))

from fvg_multi_coin import calc_size
from datetime import datetime

# ══════════════════════════════════════════════════════════════
# TP/SL 參數組合
# ══════════════════════════════════════════════════════════════

TP_SL_VARIANTS = {
    "保守_1.5x/1.0x": {"tp_mult": 1.5, "sl_mult": 1.0},
    "積極_3.0x/2.0x": {"tp_mult": 3.0, "sl_mult": 2.0},
}

# 策略類型
STRATEGY_TYPES = {
    "趨勢3x": {"initial_balance": 1000.0, "leverage": 3, "risk_per_trade": 0.05, "strategy_type": "trend", "max_positions": 2, "max_hold_days": 14},
    "趨勢5x": {"initial_balance": 1000.0, "leverage": 5, "risk_per_trade": 0.08, "strategy_type": "trend", "max_positions": 3, "max_hold_days": 30},
    "雙策略3x": {"initial_balance": 1000.0, "leverage": 3, "risk_per_trade": 0.08, "strategy_type": "both", "max_positions": 2, "max_hold_days": 7},
    "雙策略5x": {"initial_balance": 1000.0, "leverage": 5, "risk_per_trade": 0.10, "strategy_type": "both", "max_positions": 3, "max_hold_days": 14},
}

# 優先使用本地快取數據
import os as _os
_local_data_path = _os.path.join(_os.path.dirname(__file__), '..', 'data', '1000d_50coins.json')
if _os.path.exists(_local_data_path):
    print(f'📂 載入本地數據: {_local_data_path}')
    with open(_local_data_path) as _f:
        _raw = json.load(_f)
    # 轉換格式: {coin: [{ts, open, high, low, close, volume}, ...]}
    all_data = {}
    for _coin, _records in _raw.items():
        all_data[_coin] = _records
    min_days = min(len(d) for d in all_data.values())
    print(f'  載入 {len(all_data)} 幣種，回測 {min_days} 天')
else:
    print('📊 收集 50 幣種 1000 天數據...')
    coins = load_coin_list()
    all_data = {}
    for i, coin in enumerate(coins):
        try:
            d = get_binance_klines(coin['symbol'], limit=1000)
            if d and len(d) >= 50:
                all_data[coin['name']] = d
        except: pass
    min_days = min(len(d) for d in all_data.values())
    print(f'  收集 {len(all_data)} 幣種，回測 {min_days} 天')

# ══════════════════════════════════════════════════════════════
# 生成含自訂 TP/SL 的信號
# ══════════════════════════════════════════════════════════════

def generate_signal_with_tpsl(data, strategy_type, tp_mult, sl_mult):
    """生成信號，使用自訂 TP/SL 倍數"""
    if len(data) < 50: return None
    
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d.get('volume', 0) for d in data]
    
    i = len(data) - 1
    current = closes[i]
    
    # ADX
    from indicators_v3 import adx, atr, ema
    adx_val = adx(highs, lows, closes, 14)
    if isinstance(adx_val, tuple) and len(adx_val) >= 1:
        if isinstance(adx_val[0], list):
            for v in reversed(adx_val[0]):
                if v is not None: adx_val = v; break
        else:
            adx_val = 20
    if not isinstance(adx_val, (int, float)): adx_val = 20
    
    atr_val = atr(highs, lows, closes, 14)
    if isinstance(atr_val, list): atr_val = atr_val[-1] if atr_val else current * 0.03
    if not atr_val or atr_val == 0: atr_val = current * 0.03
    
    high_50 = max(highs[max(0,i-50):i+1])
    low_50 = min(lows[max(0,i-50):i+1])
    ema20 = ema(closes, 20)
    if isinstance(ema20, list): ema20 = ema20[-1] if ema20 else current
    ema50 = ema(closes, 50)
    if isinstance(ema50, list): ema50 = ema50[-1] if ema50 else current
    
    signal = None
    
    # FVG 均值回歸
    if strategy_type in ("fvg", "both") and adx_val < 25:
        # 簡化 FVG 檢測
        fvgs = []
        for j in range(max(i-5, 2), i+1):
            k1_h, k1_l = highs[j-2], lows[j-2]
            k3_h, k3_l = highs[j], lows[j]
            if k1_h < k3_l: fvgs.append(('bull', k1_h, k3_l))
            if k1_l > k3_h: fvgs.append(('bear', k3_h, k1_l))
        
        fvg_dir = None
        for d, lo, hi in fvgs:
            if lo <= current <= hi: fvg_dir = d; break
        
        fib_pos = (high_50 - current) / (high_50 - low_50) * 100 if high_50 != low_50 else 50
        score = 0
        if 33 <= fib_pos <= 43: score += 3
        if 47 <= fib_pos <= 53: score += 2
        if 58 <= fib_pos <= 65: score += 1
        if fib_pos < 15: score -= 3
        if fib_pos > 85: score -= 2
        if fvg_dir == 'bull': score += 3
        elif fvg_dir == 'bear': score -= 3
        
        if len(vols) >= 20:
            va = statistics.mean(vols[max(0,i-5):i+1])
            vb = statistics.mean(vols[max(0,i-20):i+1])
            if vb > 0:
                vr = va/vb
                if vr > 1.3: score = int(score*1.15)
                elif vr < 0.7: score = int(score*0.85)
        
        if score >= 3:
            risk = current - low_50
            sl = low_50
            tp = current + risk * tp_mult
            signal = {'direction': 'long', 'score': score, 'tp': tp, 'sl': sl, 'reason': 'FVG_BUY', 'adx': adx_val}
        elif score <= -3:
            risk = high_50 - current
            sl = high_50
            tp = current - risk * tp_mult
            signal = {'direction': 'short', 'score': score, 'tp': tp, 'sl': sl, 'reason': 'FVG_SELL', 'adx': adx_val}
    
    # 趨勢追蹤
    if strategy_type in ("trend", "both") and adx_val >= 25:
        ts = 0
        roc_5 = (closes[i]-closes[i-5])/closes[i-5]*100 if i>=5 else 0
        roc_20 = (closes[i]-closes[i-20])/closes[i-20]*100 if i>=20 else 0
        ma = roc_5 - roc_20*0.3
        if ma > 3: ts += 3
        elif ma > 1: ts += 1
        elif ma < -3: ts -= 3
        elif ma < -1: ts -= 1
        
        atr5 = atr(highs[i-5:i+1], lows[i-5:i+1], closes[i-5:i+1], 5)
        atr20 = atr(highs[i-20:i+1], lows[i-20:i+1], closes[i-20:i+1], 20)
        if isinstance(atr5, list): atr5 = atr5[-1] if atr5 else atr_val
        if isinstance(atr20, list): atr20 = atr20[-1] if atr20 else atr_val
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
            sl = current - atr_val * sl_mult
            tp = current + atr_val * tp_mult
            signal = {'direction': 'long', 'score': ts, 'tp': tp, 'sl': sl, 'reason': 'TREND_BUY', 'adx': adx_val}
        elif ts <= -3:
            sl = current + atr_val * sl_mult
            tp = current - atr_val * tp_mult
            signal = {'direction': 'short', 'score': ts, 'tp': tp, 'sl': sl, 'reason': 'TREND_SELL', 'adx': adx_val}
    
    return signal

# ══════════════════════════════════════════════════════════════
# 回測引擎
# ══════════════════════════════════════════════════════════════

def run_backtest(name, params, tp_mult, sl_mult):
    state = {
        'balance': params['initial_balance'],
        'positions': [], 'history': [],
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }
    
    for day_idx in range(50, min_days):
        prices = {cn: d[day_idx]['close'] for cn, d in all_data.items() if day_idx < len(d)}
        
        # 更新持倉
        still_open = []
        for pos in state['positions']:
            c = pos['coin']
            if c not in prices: still_open.append(pos); continue
            cur = prices[c]
            pnl = (cur - pos['entry'])*pos['size'] if pos['direction']=='long' else (pos['entry']-cur)*pos['size']
            pos['pnl_pnl'] = pnl
            close = False; reason = ''
            if pos['direction']=='long':
                if cur>=pos['tp']: close,reason=True,'TP'
                elif cur<=pos['sl']: close,reason=True,'SL'
            else:
                if cur<=pos['tp']: close,reason=True,'TP'
                elif cur>=pos['sl']: close,reason=True,'SL'
            if not close and day_idx-pos.get('entry_day',0)>params['max_hold_days']:
                close,reason=True,'TIME'
            if close:
                state['balance']+=pnl; state['stats']['total_trades']+=1; state['stats']['total_pnl']+=pnl
                if pnl>0: state['stats']['wins']+=1; state['stats']['max_win']=max(state['stats']['max_win'],pnl)
                else: state['stats']['losses']+=1; state['stats']['max_loss']=min(state['stats']['max_loss'],pnl)
                state['history'].append({'coin':c,'dir':pos['direction'],'pnl':round(pnl,4),'reason':reason,'days':day_idx-pos.get('entry_day',0),'sig':pos.get('sig','')})
            else: still_open.append(pos)
        state['positions']=still_open
        
        # 每 3 天掃描
        if day_idx%3==0 and len(state['positions'])<params['max_positions']:
            # BTC direction from local data (offline backtest)
            if 'BTC' in all_data and day_idx >= 7:
                btc_d = all_data['BTC']
                btc_chg = (btc_d[day_idx]['close'] / btc_d[day_idx-7]['close'] - 1) * 100
                if btc_chg > 3: btc_dir = 'bull'
                elif btc_chg < -3: btc_dir = 'bear'
                else: btc_dir = 'neutral'
            else:
                btc_dir = 'neutral'
            for cn in all_data:
                if len(state['positions'])>=params['max_positions']: break
                if any(p['coin']==cn for p in state['positions']): continue
                if cn not in all_data or day_idx>=len(all_data[cn]): continue
                sub = all_data[cn][:day_idx+1]
                if len(sub)<50: continue
                sig = generate_signal_with_tpsl(sub, params['strategy_type'], tp_mult, sl_mult)
                if not sig: continue
                if btc_dir=="bull" and sig['direction']=="short": continue
                if btc_dir=="bear" and sig['direction']=="long": continue
                entry = prices.get(cn)
                if not entry: continue
                size = calc_size(state['balance'], entry, sig['sl'], params['leverage'], params['risk_per_trade'])
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
# 主程式：跑 4 策略 × 4 TP/SL = 16 組
# ══════════════════════════════════════════════════════════════

print(f'\n{"="*100}')
print(f'🔬 1000 天回測：4 策略 × 4 TP/SL = 16 組對比')
print(f'{"="*100}')

all_results = {}
for strat_name, params in STRATEGY_TYPES.items():
    for tpsl_name, tpsl in TP_SL_VARIANTS.items():
        run_name = f"{strat_name}_{tpsl_name}"
        state = run_backtest(run_name, params, tpsl['tp_mult'], tpsl['sl_mult'])
        all_results[run_name] = state

# 輸出
print(f'\n{"策略":<14} {"TP/SL":<16} {"槓桿":>4} {"風險":>5} {"交易":>5} {"WR":>5} {"餘額":>10} {"PnL%":>7} {"Avg":>9} {"最大盈":>9} {"最大虧":>9}')
print(f'{"─"*14} {"─"*16} {"─"*4} {"─"*5} {"─"*5} {"─"*5} {"─"*10} {"─"*7} {"─"*9} {"─"*9} {"─"*9}')

for name, s in sorted(all_results.items(), key=lambda x: -x[1]['balance']):
    parts = name.split('_', 1)
    strat = parts[0]
    tpsl = '_'.join(parts[1:]) if len(parts) > 1 else ''
    p = STRATEGY_TYPES.get(strat, {})
    st = s['stats']
    total = st['total_trades']
    wr = st['wins']/total*100 if total > 0 else 0
    avg = st['total_pnl']/total if total > 0 else 0
    pct = (s['balance']/1000-1)*100
    print(f'{strat:<14} {tpsl:<16} {p.get("leverage",0):>3}x {p.get("risk_per_trade",0)*100:>4.0f}% {total:>4} {wr:>4.0f}% ${s["balance"]:>9.2f} {pct:>+6.1f}% ${avg:>+8.2f} ${st["max_win"]:>+8.2f} ${st["max_loss"]:>+8.2f}')

# 最佳
best = max(all_results.items(), key=lambda x: x[1]['balance'])
print(f'\n🏆 最佳: {best[0]} → ${best[1]["balance"]:.2f} ({(best[1]["balance"]/1000-1)*100:+.1f}%)')

# 按 TP/SL 分組看平均
print(f'\n📊 TP/SL 平均表現:')
for tpsl_name in TP_SL_VARIANTS:
    group = {k:v for k,v in all_results.items() if k.endswith(tpsl_name)}
    if group:
        avg_pnl = sum((s['balance']/1000-1)*100 for s in group.values()) / len(group)
        avg_trades = sum(s['stats']['total_trades'] for s in group.values()) / len(group)
        print(f'  {tpsl_name}: 平均 PnL {avg_pnl:+.1f}% | 平均 {avg_trades:.1f} 筆')

# 按策略分組
print(f'\n📊 策略平均表現:')
for strat_name in STRATEGY_TYPES:
    group = {k:v for k,v in all_results.items() if k.startswith(strat_name)}
    if group:
        avg_pnl = sum((s['balance']/1000-1)*100 for s in group.values()) / len(group)
        avg_trades = sum(s['stats']['total_trades'] for s in group.values()) / len(group)
        print(f'  {strat_name}: 平均 PnL {avg_pnl:+.1f}% | 平均 {avg_trades:.1f} 筆')
