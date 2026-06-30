#!/usr/bin/env python3
"""
backtest_v6.py - 完整回測框架 v6
整合所有修復 + 動態出場引擎（DynamicExitCalculator）

改進 vs v5:
1. 動態 TP/SL（波動率自適應）
2. 趨勢追蹤止損（ADX > 25）
3. 結構破壞出場
4. ADX 轉弱出場
5. 最小持倉 3 天
"""
import sys, os, json, time, math
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import atr, adx, ema
from scoring_v6 import composite_score_v6, _signal_history, classify_market
from decision_filter_v2 import filter_signals, get_btc_direction_simple
from dynamic_exit import DynamicExitCalculator

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

WATCHLIST = [
    {'name': 'BTC', 'symbol': 'BTCUSDT'},
    {'name': 'SOL', 'symbol': 'SOLUSDT'},
    {'name': 'BNB', 'symbol': 'BNBUSDT'},
    {'name': 'AVAX', 'symbol': 'AVAXUSDT'},
    {'name': 'XRP', 'symbol': 'XRPUSDT'},
    {'name': 'NEAR', 'symbol': 'NEARUSDT'},
    {'name': 'WLD', 'symbol': 'WLDUSDT'},
    {'name': 'ZEC', 'symbol': 'ZECUSDT'},
]

INITIAL_CAPITAL = 1000.0
LEVERAGE = 3
RISK_PER_TRADE = 0.05
MAX_POSITIONS = 3

# 熔斷
MAX_DAILY_LOSS_PCT = 40.0
MAX_CONSECUTIVE_LOSSES = 10
COOLDOWN_DAYS = 7

# 動態出場引擎
EXIT_CALC = DynamicExitCalculator({
    'atr_period': 14,
    'trailing_mult': 2.0,
    'min_hold_days': 3,
    'max_hold_days': 7,
})

# ══════════════════════════════════════════════════════════════
# 數據獲取
# ══════════════════════════════════════════════════════════════

def get_binance_klines(symbol, interval='1d', limit=1000):
    import urllib.request
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return [{
                'ts': d[0], 'open': float(d[1]), 'high': float(d[2]),
                'low': float(d[3]), 'close': float(d[4]), 'volume': float(d[5]),
            } for d in data]
    except Exception as e:
        return None

# ══════════════════════════════════════════════════════════════
# 回測引擎
# ══════════════════════════════════════════════════════════════

def run_backtest(coin_config, btc_data, all_coin_data, initial_capital=INITIAL_CAPITAL):
    name = coin_config['name']
    data = all_coin_data.get(name)
    if not data or len(data) < 60:
        return None
    
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d['volume'] for d in data]
    opens = [d['open'] for d in data]
    
    btc_closes = [d['close'] for d in btc_data] if btc_data else []
    btc_highs = [d['high'] for d in btc_data] if btc_data else []
    btc_lows = [d['low'] for d in btc_data] if btc_data else []
    
    capital = initial_capital
    positions = []
    trades = []
    consecutive_losses = 0
    peak_capital = initial_capital
    max_drawdown = 0.0
    stopped = False
    stop_reason = ""
    
    _signal_history.history = {}
    
    start_day = 60
    
    for i in range(start_day, len(closes)):
        current_price = closes[i]
        
        # 更新峰值和回撤
        if capital > peak_capital:
            peak_capital = capital
        if peak_capital > 0:
            dd = (peak_capital - capital) / peak_capital * 100
            if dd > max_drawdown:
                max_drawdown = dd
        
        # 更新現有持倉
        still_open = []
        for pos in positions:
            days_held = i - pos['entry_day']
            close_pos = False
            close_price = current_price
            close_reason = ""
            
            # ── 動態出場檢查（取代固定 TP/SL）──
            # 建立動態出場計算器需要的 highs/lows/closes 切片
            h_slice = highs[:i+1]
            l_slice = lows[:i+1]
            c_slice = closes[:i+1]
            
            # 計算波動率百分位數
            vol_pct, atr_pct, atr_val = EXIT_CALC.get_vol_percentile(h_slice, l_slice, c_slice)
            
            # 用動態出場引擎檢查
            exit_result = EXIT_CALC.check_exit(
                {
                    'side': pos['side'],
                    'entry_price': pos['entry'],
                    'tp_price': pos['tp'],
                    'sl_price': pos['sl'],
                    'strategy': pos.get('exit_strategy', 'fixed'),
                    'days_held': days_held,
                    'highest_price': pos.get('highest_price', pos['entry']),
                    'lowest_price': pos.get('lowest_price', pos['entry']),
                    'adx_at_entry': pos.get('adx_at_entry', 25),
                },
                current_price, h_slice, l_slice, c_slice
            )
            
            if exit_result['should_exit']:
                close_pos = True
                close_reason = exit_result['reason']
                # 對於追蹤止損，用實際出場價
                if '追蹤止損' in close_reason:
                    if pos['side'] == 'long':
                        close_price = pos.get('sl', pos['entry'] - atr_val * 2)
                    else:
                        close_price = pos.get('sl', pos['entry'] + atr_val * 2)
            
            # 信號反轉（只在真正反轉時）
            if not close_pos:
                c_closes = closes[:i+1]
                c_highs = highs[:i+1]
                c_lows = lows[:i+1]
                c_vols = vols[:i+1]
                c_opens = opens[:i+1]
                
                r = composite_score_v6(c_closes, c_highs, c_lows, c_vols, c_opens,
                                       fear_greed=50, funding_rate=0.01,
                                       coin_name=name, use_confirmation=True, min_consecutive=2)
                sig = r['signal']
                
                if pos['side'] == 'long' and sig in ('STRONG_SELL', 'SELL'):
                    close_pos = True
                    close_reason = f'REVERSE_{sig}'
                elif pos['side'] == 'short' and sig in ('STRONG_BUY', 'BUY'):
                    close_pos = True
                    close_reason = f'REVERSE_{sig}'
            
            if close_pos:
                if pos['side'] == 'long':
                    pnl = (close_price - pos['entry']) * pos['size']
                else:
                    pnl = (pos['entry'] - close_price) * pos['size']
                
                pnl_pct = pnl / INITIAL_CAPITAL * 100 * LEVERAGE
                capital += pnl
                
                trades.append({
                    'coin': name,
                    'side': pos['side'],
                    'entry': pos['entry'],
                    'exit': close_price,
                    'pnl': round(pnl, 4),
                    'pnl_pct': round(pnl_pct, 2),
                    'reason': close_reason,
                    'days': days_held,
                    'score': pos.get('score', 0),
                    'strategy': pos.get('exit_strategy', 'fixed'),
                })
                
                if pnl > 0:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
            else:
                # 更新追蹤止損的極值
                if pos['side'] == 'long':
                    pos['highest_price'] = max(pos.get('highest_price', pos['entry']), current_price)
                else:
                    pos['lowest_price'] = min(pos.get('lowest_price', pos['entry']), current_price)
                still_open.append(pos)
        
        positions = still_open
        
        # 熔斷檢查
        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            stopped = True
            stop_reason = f'連續虧損 {consecutive_losses} 次'
            break
        
        if max_drawdown > MAX_DAILY_LOSS_PCT:
            stopped = True
            stop_reason = f'回撤 {max_drawdown:.1f}% 超過 {MAX_DAILY_LOSS_PCT}%'
            break
        
        # 冷卻期檢查
        if positions:
            continue
        
        if len(positions) >= MAX_POSITIONS:
            continue
        
        cooldown_active = False
        for t in reversed(trades):
            if t['coin'] == name and (i - t.get('exit_day', 0)) < COOLDOWN_DAYS:
                cooldown_active = True
                break
        if cooldown_active:
            continue
        
        # 生成信號
        c_closes = closes[:i+1]
        c_highs = highs[:i+1]
        c_lows = lows[:i+1]
        c_vols = vols[:i+1]
        c_opens = opens[:i+1]
        
        r = composite_score_v6(c_closes, c_highs, c_lows, c_vols, c_opens,
                               fear_greed=50, funding_rate=0.01,
                               coin_name=name, use_confirmation=True, min_consecutive=2)
        
        signal = r['signal']
        score = r['score']
        
        if signal not in ('STRONG_BUY', 'STRONG_SELL'):
            continue
        
        # BTC 方向過濾
        if len(btc_closes) > 50:
            btc_dir = get_btc_direction_simple(btc_closes[:i+1], btc_highs[:i+1], btc_lows[:i+1])
        else:
            btc_dir = 'neutral'
        
        side = 'long' if 'BUY' in signal else 'short'
        
        btc_penalty = 0.0
        if btc_dir != 'neutral' and btc_dir != side:
            btc_penalty = 0.2
        
        # 相關性確認
        confirm_count = 0
        for other_name, other_data in all_coin_data.items():
            if other_name == name or len(other_data) <= i:
                continue
            o_closes = [d['close'] for d in other_data[:i+1]]
            o_highs = [d['high'] for d in other_data[:i+1]]
            o_lows = [d['low'] for d in other_data[:i+1]]
            o_vols = [d['volume'] for d in other_data[:i+1]]
            o_opens = [d['open'] for d in other_data[:i+1]]
            
            _signal_history.history = {}
            o_r = composite_score_v6(o_closes, o_highs, o_lows, o_vols, o_opens,
                                     fear_greed=50, funding_rate=0.01,
                                     coin_name=other_name, use_confirmation=True, min_consecutive=2)
            o_sig = o_r['signal']
            o_side = 'long' if 'BUY' in o_sig else ('short' if 'SELL' in o_sig else None)
            if o_side == side:
                confirm_count += 1
        
        confirm_penalty = 0.0
        if confirm_count == 0:
            confirm_penalty = 0.25
        
        # 信心計算
        CONFIRM_WEIGHTS = {0: 0, 1: 0.15, 2: 0.25, 3: 0.3, 4: 0.3, 5: 0.3, 6: 0.25, 7: 0.2}
        
        confidence = 0.2
        confidence += CONFIRM_WEIGHTS.get(confirm_count, 0.2)
        if btc_dir == side:
            confidence += 0.3
        elif btc_dir == 'neutral':
            confidence += 0.05
        else:
            confidence -= btc_penalty
        confidence -= confirm_penalty
        
        adx_result = adx(c_highs, c_lows, c_closes, 14)
        adx_val = 20
        if isinstance(adx_result, tuple) and len(adx_result) >= 1:
            adx_list = adx_result[0]
            if isinstance(adx_list, list) and adx_list:
                for v in reversed(adx_list):
                    if v is not None:
                        adx_val = v
                        break
        if 20 <= adx_val <= 46:
            confidence += 0.1
        
        confidence = max(0.0, min(1.0, confidence))
        
        if confidence < 0.3:
            continue
        
        # ── 動態出場計算 ──
        vol_pct, atr_pct, atr_val = EXIT_CALC.get_vol_percentile(c_highs, c_lows, c_closes)
        regime = classify_market(c_closes, c_highs, c_lows, c_vols)['regime']
        
        exit_plan = EXIT_CALC.calc_exit(
            current_price, atr_val, side, regime, vol_pct,
            c_highs, c_lows, c_closes
        )
        
        sl_price = exit_plan['sl_price']
        tp_price = exit_plan['tp_price']
        exit_strategy = exit_plan['strategy']
        
        # 倉位計算
        risk_amount = capital * RISK_PER_TRADE
        sl_dist = abs(current_price - sl_price)
        if sl_dist <= 0:
            continue
        size = risk_amount / sl_dist
        notional = size * current_price
        margin = notional / LEVERAGE
        max_margin = capital * 0.95
        if margin > max_margin:
            size = (max_margin * LEVERAGE) / current_price
        
        positions.append({
            'side': side,
            'entry': current_price,
            'sl': sl_price,
            'tp': tp_price,
            'size': round(size, 6),
            'entry_day': i,
            'score': score,
            'confidence': round(confidence, 3),
            'exit_strategy': exit_strategy,
            'highest_price': current_price,
            'lowest_price': current_price,
            'adx_at_entry': adx_val,
        })
    
    # 統計
    total_trades = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    total_pnl_pct = (capital / initial_capital - 1) * 100
    
    long_trades = [t for t in trades if t['side'] == 'long']
    short_trades = [t for t in trades if t['side'] == 'short']
    
    trend_trades = [t for t in trades if t.get('strategy') == 'trend_following']
    fixed_trades = [t for t in trades if t.get('strategy') == 'fixed']
    
    return {
        'coin': name,
        'trades': total_trades,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins) / total_trades * 100, 1) if total_trades else 0,
        'total_pnl': round(total_pnl, 4),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'final_capital': round(capital, 4),
        'max_drawdown': round(max_drawdown, 1),
        'avg_pnl': round(total_pnl / total_trades, 4) if total_trades else 0,
        'avg_days': round(sum(t['days'] for t in trades) / total_trades, 1) if total_trades else 0,
        'long_trades': len(long_trades),
        'long_wr': round(len([t for t in long_trades if t['pnl'] > 0]) / len(long_trades) * 100, 1) if long_trades else 0,
        'short_trades': len(short_trades),
        'short_wr': round(len([t for t in short_trades if t['pnl'] > 0]) / len(short_trades) * 100, 1) if short_trades else 0,
        'trend_trades': len(trend_trades),
        'trend_wr': round(len([t for t in trend_trades if t['pnl'] > 0]) / len(trend_trades) * 100, 1) if trend_trades else 0,
        'fixed_trades': len(fixed_trades),
        'fixed_wr': round(len([t for t in fixed_trades if t['pnl'] > 0]) / len(fixed_trades) * 100, 1) if fixed_trades else 0,
        'stopped': stopped,
        'stop_reason': stop_reason,
        'price_change': round((closes[-1] / closes[start_day] - 1) * 100, 1),
    }


# ══════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════

def main():
    print('=' * 75)
    print('🔬 修復後策略回測 v6（動態出場引擎）')
    print(f'   參數: {LEVERAGE}x 槓桿, {RISK_PER_TRADE*100}% 風險')
    print(f'   出場: 波動率自適應 TP/SL + 趨勢追蹤止損(ADX>25)')
    print(f'   熔斷: 回撤>{MAX_DAILY_LOSS_PCT}%, 連續虧損>{MAX_CONSECUTIVE_LOSSES}次')
    print('=' * 75)
    
    print('\n📊 獲取 BTC 數據...')
    btc_data = get_binance_klines('BTCUSDT', limit=1000)
    if not btc_data:
        print('❌ BTC 數據獲取失敗')
        return
    print(f'   BTC: {len(btc_data)} 根 K 線')
    
    print('\n📊 獲取所有幣種數據...')
    all_coin_data = {}
    for coin in WATCHLIST:
        data = get_binance_klines(coin['symbol'], limit=1000)
        if data and len(data) >= 60:
            all_coin_data[coin['name']] = data
            print(f'   ✅ {coin["name"]}: {len(data)} 根')
        else:
            print(f'   ⚠️ {coin["name"]}: 數據不足')
    
    print('\n' + '=' * 75)
    print('📈 回測結果')
    print('=' * 75)
    
    all_results = []
    for coin in WATCHLIST:
        if coin['name'] not in all_coin_data:
            continue
        
        print(f'\n   分析 {coin["name"]}...', end=' ', flush=True)
        result = run_backtest(coin, btc_data, all_coin_data)
        if result:
            all_results.append(result)
            trend_str = f', 趨勢={result["trend_trades"]}筆(WR={result["trend_wr"]}%)' if result['trend_trades'] > 0 else ''
            print(f'{result["trades"]}筆, WR={result["win_rate"]}%, PnL={result["total_pnl_pct"]:+.1f}%{trend_str}')
        else:
            print('數據不足')
    
    # 匯總報告
    print('\n' + '=' * 75)
    print('📊 匯總報告')
    print('=' * 75)
    
    header = f'{"幣種":<5} {"交易":>4} {"勝率":>6} {"做多":>5} {"做空":>5} {"趨勢":>5} {"固定":>5} {"PnL":>8} {"回撤":>6} {"天數":>5} {"價格":>7}'
    print(header)
    print('─' * 75)
    
    total_trades_all = 0
    total_wins_all = 0
    total_pnl_all = 0.0
    
    for r in all_results:
        print(f'{r["coin"]:<5} {r["trades"]:>4} {r["win_rate"]:>5.1f}% {r["long_wr"]:>4.1f}% {r["short_wr"]:>4.1f}% {r["trend_wr"]:>4.1f}% {r["fixed_wr"]:>4.1f}% {r["total_pnl_pct"]:>+7.1f}% {r["max_drawdown"]:>5.1f}% {r["avg_days"]:>4.1f}天 {r["price_change"]:>+6.1f}%')
        total_trades_all += r['trades']
        total_wins_all += r['wins']
        total_pnl_all += r['total_pnl']
    
    print('─' * 75)
    
    overall_wr = total_wins_all / total_trades_all * 100 if total_trades_all else 0
    avg_pnl_all = total_pnl_all / total_trades_all if total_trades_all else 0
    
    print(f'{"合計":<5} {total_trades_all:>4} {overall_wr:>5.1f}% {"":>5} {"":>5} {"":>5} {"":>5} {total_pnl_all:>+7.1f}% {"":>6} {"":>5}')
    
    if all_results:
        best = max(all_results, key=lambda x: x['total_pnl_pct'])
        worst = min(all_results, key=lambda x: x['total_pnl_pct'])
        print(f'\n   🏆 最佳: {best["coin"]} ({best["total_pnl_pct"]:+.1f}%)')
        print(f'   💀 最差: {worst["coin"]} ({worst["total_pnl_pct"]:+.1f}%)')
    
    stopped = [r for r in all_results if r['stopped']]
    if stopped:
        print(f'\n   🔴 熔斷觸發: {len(stopped)} 個')
        for s in stopped:
            print(f'      {s["coin"]}: {s["stop_reason"]}')
    
    # 出場策略統計
    all_trend = sum(r['trend_trades'] for r in all_results)
    all_fixed = sum(r['fixed_trades'] for r in all_results)
    trend_wins = sum(1 for r in all_results for _ in range(r['trend_trades']))
    print(f'\n   📊 出場策略: 趨勢追蹤={all_trend}筆, 固定TP/SL={all_fixed}筆')
    
    print('\n✅ 回測完成')


if __name__ == '__main__':
    main()
