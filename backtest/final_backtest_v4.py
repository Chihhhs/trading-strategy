#!/usr/bin/env python3
"""final_backtest_v4.py - 最終回測 v4：只用波動率自適應，無過濾"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from backtester_v3 import get_binance_klines
from scoring_v6 import composite_score_v6, _signal_history, classify_market
from dynamic_exit import DynamicExitCalculator, DynamicExitMonitor
from indicators_v3 import atr

all_coins = [
    ('BTC', 'BTCUSDT'), ('ETH', 'ETHUSDT'), ('SOL', 'SOLUSDT'),
    ('BNB', 'BNBUSDT'), ('AVAX', 'AVAXUSDT'), ('XRP', 'XRPUSDT'),
    ('NEAR', 'NEARUSDT'), ('WLD', 'WLDUSDT'), ('ZEC', 'ZECUSDT'),
]

def get_vol_percentile(highs, lows, closes, lookback=90):
    current = closes[-1]
    atr_vals = atr(highs, lows, closes, 14)
    atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else current * 0.03
    atr_pct = atr_val / current * 100
    historical = []
    for i in range(max(0, len(closes) - lookback), len(closes)):
        if i < 14:
            continue
        a = atr(highs[:i+1], lows[:i+1], closes[:i+1], 14)
        if a and a[-1] is not None:
            historical.append(a[-1] / closes[i] * 100)
    if not historical:
        return 50, atr_pct, atr_val
    below = sum(1 for x in historical if x < atr_pct)
    equal = sum(1 for x in historical if x == atr_pct)
    return (below + 0.5 * equal) / len(historical) * 100, atr_pct, atr_val

def run_backtest(coin_name, symbol):
    data = get_binance_klines(symbol, limit=365)
    if not data or len(data) < 60:
        return None
    
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d['volume'] for d in data]
    opens_arr = [d['open'] for d in data]
    
    _signal_history.history = {}
    monitor = DynamicExitMonitor()
    position = None
    trades = []
    
    for i in range(60, len(closes)):
        c = closes[:i+1]; h = highs[:i+1]; l = lows[:i+1]; v = vols[:i+1]; o = opens_arr[:i+1]
        
        r = composite_score_v6(c, h, l, v, o, fear_greed=50, funding_rate=0.01,
                               coin_name=coin_name, use_confirmation=True, min_consecutive=2)
        
        signal = r['signal']
        current_price = closes[i]
        regime = r['details'].get('market_regime', 'ranging')
        
        atr_vals = atr(h, l, c, 14)
        atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else current_price * 0.03
        vol_pct, _, _ = get_vol_percentile(h, l, c)
        
        # 持倉管理
        if position:
            position['days_held'] = i - position['entry_day']
            exit_result = monitor.calc.check_exit(position, current_price, h, l, c)
            if exit_result['should_exit']:
                trades.append({'type': position['side'], 'pnl': exit_result['pnl_pct'] * 3,
                               'days': position['days_held'], 'reason': exit_result['reason']})
                position = None
                monitor.positions.pop(coin_name, None)
        
        # 開倉（無過濾）
        if position is None and signal != 'NEUTRAL':
            side = 'long' if 'BUY' in signal else 'short'
            exit_plan = monitor.open_position(coin_name, side, current_price, regime, atr_val, vol_pct, h, l, c)
            position = {
                'side': side, 'entry_price': current_price, 'entry_day': i, 'days_held': 0,
                'tp_price': exit_plan['tp_price'], 'sl_price': exit_plan['sl_price'],
                'strategy': exit_plan['strategy'], 'regime': regime,
                'highest_price': current_price, 'lowest_price': current_price,
                'adx_at_entry': r['details'].get('adx', 25),
            }
    
    if not trades:
        return None
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    
    return {
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': len(wins) / len(trades) * 100,
        'total_pnl': round(total_pnl, 2),
        'avg_pnl': round(total_pnl / len(trades), 2),
        'avg_days': round(sum(t['days'] for t in trades) / len(trades), 1),
        'price_change': round((closes[-1] / closes[60] - 1) * 100, 1),
    }

print('=' * 80)
print('最終回測 v4：波動率自適應 TP/SL（無過濾）')
print('=' * 80)
print(f'策略：低波動(1.0x/1.5R) | 正常(1.5x/2R) | 高波動(2.0x/3R) | 趨勢(追蹤止損)')
print('=' * 80)

results = []
for coin_name, symbol in all_coins:
    r = run_backtest(coin_name, symbol)
    if r:
        results.append((coin_name, r))

print(f'\n{"幣種":<6} {"漲幅":>8} | {"次數":>4} {"勝率":>5} {"總PnL":>8} {"平均PnL":>8} {"天數":>4}')
print('─' * 60)

for coin_name, r in results:
    print(f'{coin_name:<6} {r["price_change"]:>7.1f}% | {r["trades"]:>4} {r["win_rate"]:>4.1f}% {r["total_pnl"]:>7.1f}% {r["avg_pnl"]:>7.2f}% {r["avg_days"]:>3.1f}天')

if results:
    n = len(results)
    avg = {k: sum(r[k] for _, r in results) / n for k in ['trades', 'win_rate', 'total_pnl', 'avg_pnl', 'avg_days']}
    print('─' * 60)
    print(f'{"平均":<6} {"":8} | {avg["trades"]:>4.0f} {avg["win_rate"]:>4.1f}% {avg["total_pnl"]:>7.1f}% {avg["avg_pnl"]:>7.2f}% {avg["avg_days"]:>3.1f}天')
