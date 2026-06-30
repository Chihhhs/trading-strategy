#!/usr/bin/env python3
"""
fvg_backtest_60d.py - 用 60 天歷史數據跑 FVG + 趨勢回測
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

from fvg_paper_trader import STRATEGIES, generate_fvg_signal, calc_position_size
# 覆蓋：FVG 和雙策略用更高風險
STRATEGIES["A_FVG保守"]["risk_per_trade"] = 0.08
STRATEGIES["A_FVG保守"]["max_daily_loss_pct"] = 15.0
STRATEGIES["B_FVG積極"]["risk_per_trade"] = 0.10
STRATEGIES["B_FVG積極"]["leverage"] = 5
STRATEGIES["B_FVG積極"]["max_daily_loss_pct"] = 15.0
STRATEGIES["C_趨勢保守"]["risk_per_trade"] = 0.05
STRATEGIES["D_趨勢積極"]["risk_per_trade"] = 0.08
STRATEGIES["E_雙策略保守"]["risk_per_trade"] = 0.08
STRATEGIES["E_雙策略保守"]["max_daily_loss_pct"] = 15.0
STRATEGIES["F_雙策略積極"]["risk_per_trade"] = 0.10
STRATEGIES["F_雙策略積極"]["leverage"] = 5
STRATEGIES["F_雙策略積極"]["max_daily_loss_pct"] = 15.0
from live_monitor import WATCHLIST, get_binance_klines

print('📊 收集 60 天數據...')
all_coin_data = {}
for coin in WATCHLIST:
    try:
        data = get_binance_klines(coin['symbol'], limit=60)
        if data and len(data) >= 50:
            all_coin_data[coin['name']] = data
            print(f'  ✅ {coin["name"]}: {len(data)} 天')
    except:
        pass

min_days = min(len(d) for d in all_coin_data.values()) if all_coin_data else 0
print(f'回測天數: {min_days} 天 ({min_days} 個幣種)')

results = {}
for strat_name, params in STRATEGIES.items():
    state = {
        'balance': params['initial_balance'],
        'positions': [], 'history': [],
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }
    
    for day_idx in range(50, min_days):
        # 當天價格
        prices = {}
        for cn, d in all_coin_data.items():
            if day_idx < len(d):
                prices[cn] = d[day_idx]['close']
        
        # 更新持倉
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
            if pos['direction'] == 'long':
                if cur >= pos['tp']: close, reason = True, 'TP'
                elif cur <= pos['sl']: close, reason = True, 'SL'
            else:
                if cur <= pos['tp']: close, reason = True, 'TP'
                elif cur >= pos['sl']: close, reason = True, 'SL'
            if not close and day_idx - pos.get('entry_day', 0) > params['max_hold_days']:
                close, reason = True, 'TIME'
            
            if close:
                state['balance'] += pnl
                state['stats']['total_trades'] += 1
                state['stats']['total_pnl'] += pnl
                if pnl > 0: state['stats']['wins'] += 1; state['stats']['max_win'] = max(state['stats']['max_win'], pnl)
                else: state['stats']['losses'] += 1; state['stats']['max_loss'] = min(state['stats']['max_loss'], pnl)
                state['history'].append({'coin': c, 'dir': pos['direction'], 'entry': pos['entry'], 'exit': cur, 'pnl': round(pnl,4), 'reason': reason, 'days': day_idx-pos.get('entry_day',0), 'sig': pos.get('sig','')})
            else:
                still_open.append(pos)
        state['positions'] = still_open
        
        # 每 3 天掃描
        if day_idx % 3 == 0 and len(state['positions']) < params['max_positions']:
            for coin in WATCHLIST:
                if len(state['positions']) >= params['max_positions']: break
                cn = coin['name']
                if any(p['coin'] == cn for p in state['positions']): continue
                if cn not in all_coin_data or day_idx >= len(all_coin_data[cn]): continue
                sub = all_coin_data[cn][:day_idx+1]
                if len(sub) < 50: continue
                sig = generate_fvg_signal(sub, params['strategy_type'])
                if not sig: continue
                entry = prices.get(cn)
                if not entry: continue
                size = calc_position_size(state['balance'], entry, sig['sl'], params['leverage'], params['risk_per_trade'])
                if size <= 0: continue
                state['positions'].append({'coin': cn, 'direction': sig['direction'], 'entry': entry, 'tp': sig['tp'], 'sl': sig['sl'], 'size': round(size,6), 'current_price': entry, 'entry_day': day_idx, 'sig': sig.get('reason','')})
    
    # 平倉
    for pos in state['positions']:
        c = pos['coin']
        if c in all_coin_data and all_coin_data[c]:
            fp = all_coin_data[c][min_days-1]['close']
            pnl = (fp - pos['entry']) * pos['size'] if pos['direction'] == 'long' else (pos['entry'] - fp) * pos['size']
            state['balance'] += pnl
            state['stats']['total_trades'] += 1
            state['stats']['total_pnl'] += pnl
            if pnl > 0: state['stats']['wins'] += 1
            else: state['stats']['losses'] += 1
            state['history'].append({'coin': c, 'dir': pos['direction'], 'entry': pos['entry'], 'exit': fp, 'pnl': round(pnl,4), 'reason': 'END', 'days': min_days-pos.get('entry_day',0), 'sig': pos.get('sig','')})
    
    results[strat_name] = state

# 輸出
print(f'\n{"="*90}')
print(f'📊 60 天回測結果')
print(f'{"="*90}')
print(f'{"策略":<16} {"類型":<6} {"槓桿":>4} {"風險":>5} {"倉位":>4} {"超時":>4} {"餘額":>10} {"PnL%":>8} {"交易":>5} {"WR":>5} {"Avg":>9}')
for name, s in results.items():
    p = STRATEGIES[name]
    st = s['stats']
    total = st['total_trades']
    wr = st['wins']/total*100 if total > 0 else 0
    avg = st['total_pnl']/total if total > 0 else 0
    pct = (s['balance']/p['initial_balance']-1)*100
    print(f'{name:<16} {p["strategy_type"]:<6} {p["leverage"]:>3}x {p["risk_per_trade"]*100:>4.0f}% {p["max_positions"]:>3} {p["max_hold_days"]:>3}d ${s["balance"]:>9.2f} {pct:>+7.1f}% {total:>4} {wr:>4.0f}% ${avg:>+8.2f}')

best = max(results.items(), key=lambda x: x[1]['balance'])
print(f'\n🏆 最佳: {best[0]} → ${best[1]["balance"]:.2f} ({(best[1]["balance"]/1000-1)*100:+.1f}%)')

# 計算最大回撤
for name, s in results.items():
    if s['history']:
        peak = 1000
        max_dd = 0
        cum = 0
        for h in sorted(s['history'], key=lambda x: x.get('entry',0)):
            cum += h['pnl']
            peak = max(peak, 1000 + cum)
            dd = (peak - (1000 + cum)) / peak * 100
            max_dd = max(max_dd, dd)
        print(f'  {name}: 最大回撤 {max_dd:.1f}%')

# 交易原因分佈
print(f'\n📋 交易原因分佈:')
for name, s in results.items():
    reasons = {}
    for h in s['history']:
        r = h.get('reason', '?')
        reasons[r] = reasons.get(r, 0) + 1
    if reasons:
        print(f'  {name}: {reasons}')
