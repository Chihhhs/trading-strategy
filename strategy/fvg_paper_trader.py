#!/usr/bin/env python3
"""
fvg_paper_trader.py - FVG + 趨勢雙策略模擬倉
整合 dual_strategy.py 的 FVG 均值回歸 + 趨勢追蹤邏輯
多組參數對比，每組獨立 state

策略類型：
  FVG均值回歸：ADX < 25 時，找 FVG + Fibonacci 38.2%/50%/61.8% 回撤入場
  趨勢追蹤：ADX >= 25 時，動量+波動率+成交量確認趨勢

參數組合（6組）：
  A: FVG保守    — 只跑 FVG 策略, 3x, 3%, 2倉位, 7天
  B: FVG積極    — 只跑 FVG 策略, 3x, 5%, 3倉位, 14天
  C: 趨勢保守    — 只跑趨勢策略, 3x, 3%, 2倉位, 14天
  D: 趨勢積極    — 只跑趨勢策略, 5x, 5%, 3倉位, 30天
  E: 雙策略保守 — FVG+趨勢, 3x, 3%, 2倉位, 7天
  F: 雙策略積極 — FVG+趨勢, 3x, 5%, 3倉位, 14天
"""
import sys, os, json, time, math, statistics
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from live_monitor import WATCHLIST, get_binance_klines
from indicators_v3 import adx, atr, ema, rsi

# ══════════════════════════════════════════════════════════════
# FVG + 趨勢信號生成
# ══════════════════════════════════════════════════════════════

def find_fvg(closes, highs, lows, i, lookback=5):
    """找最近 lookback 根 K 線內的 FVG"""
    fvgs = []
    for j in range(max(i-lookback, 2), i+1):
        k1, k3 = {'high': highs[j-2], 'low': lows[j-2]}, {'high': highs[j], 'low': lows[j]}
        if k1['high'] < k3['low']:
            fvgs.append(('bull', k1['high'], k3['low']))
        if k1['low'] > k3['high']:
            fvgs.append(('bear', k3['high'], k1['low']))
    return fvgs

def price_in_fvg(price, fvgs):
    """檢查價格是否在任何 FVG 範圍內"""
    for direction, low, high in fvgs:
        if low <= price <= high:
            return direction
    return None

def fib_position(price, high_50, low_50):
    """計算價格在 Fibonacci 回撤中的位置 (0-100)"""
    r = high_50 - low_50
    if r == 0: return 50
    return (high_50 - price) / r * 100

def get_adx_val(highs, lows, closes, n=14):
    result = adx(highs, lows, closes, n)
    if isinstance(result, tuple) and len(result) >= 1:
        adx_list = result[0]
        if isinstance(adx_list, list) and adx_list:
            for v in reversed(adx_list):
                if v is not None: return v
    return 20

def generate_fvg_signal(data, strategy_type="both"):
    """
    生成 FVG + 趨勢信號
    
    參數:
    - data: K線數據 list of dicts (open, high, low, close, volume)
    - strategy_type: "fvg" / "trend" / "both"
    
    返回: signal dict 或 None
    """
    if len(data) < 50:
        return None
    
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d.get('volume', d.get('vol', 0)) for d in data]
    
    i = len(data) - 1
    current = closes[i]
    
    adx_val = get_adx_val(highs, lows, closes)
    atr_val = atr(highs, lows, closes, 14)
    if isinstance(atr_val, list):
        atr_val = atr_val[-1] if atr_val else current * 0.03
    elif isinstance(atr_val, (list, tuple)):
        atr_val = atr_val[-1] if len(atr_val) > 0 else current * 0.03
    if atr_val is None or atr_val == 0: atr_val = current * 0.03
    
    high_50 = max(highs[max(0,i-50):i+1])
    low_50 = min(lows[max(0,i-50):i+1])
    ema20 = ema(closes, 20)
    if isinstance(ema20, list): ema20 = ema20[-1] if ema20 else current
    ema50 = ema(closes, 50)
    if isinstance(ema50, list): ema50 = ema50[-1] if ema50 else current
    
    signal = None
    score = 0
    
    # ── FVG 均值回歸（ADX < 25 時使用）──
    if strategy_type in ("fvg", "both") and adx_val < 25:
        fvgs = find_fvg(closes, highs, lows, i)
        fvg_dir = price_in_fvg(current, fvgs)
        fib_pos = fib_position(current, high_50, low_50)
        
        # Fibonacci 位置評分
        if 33 <= fib_pos <= 43: score += 3   # 38.2%
        if 47 <= fib_pos <= 53: score += 2   # 50%
        if 58 <= fib_pos <= 65: score += 1   # 61.8%
        if fib_pos < 15: score -= 3          # 接近高點不入场
        if fib_pos > 85: score -= 2          # 接近低點不入場
        
        # FVG 確認
        if fvg_dir == 'bull': score += 3
        elif fvg_dir == 'bear': score -= 3
        
        # 成交量確認
        if len(vols) >= 20:
            vol_avg = statistics.mean(vols[max(0,i-5):i+1])
            vol_20 = statistics.mean(vols[max(0,i-20):i+1])
            vol_ratio = vol_avg / vol_20 if vol_20 > 0 else 1
            if vol_ratio > 1.3: score = int(score * 1.15)
            elif vol_ratio < 0.7: score = int(score * 0.85)
        
        if score >= 4:
            # FVG 做多：SL = 50天低點, TP = 1.5x risk
            sl = low_50
            tp = current + (current - low_50) * 1.5
            signal = {'direction': 'long', 'score': score, 'tp': tp, 'sl': sl, 
                      'reason': 'FVG_BUY', 'adx': adx_val, 'fib_pos': fib_pos}
        elif score <= -4:
            sl = high_50
            tp = current - (high_50 - current) * 1.5
            signal = {'direction': 'short', 'score': score, 'tp': tp, 'sl': sl,
                      'reason': 'FVG_SELL', 'adx': adx_val, 'fib_pos': fib_pos}
    
    # ── 趨勢追蹤（ADX >= 25 時使用）──
    if strategy_type in ("trend", "both") and adx_val >= 25:
        trend_score = 0
        
        # 動量加速
        roc_5 = (closes[i] - closes[i-5]) / closes[i-5] * 100 if i >= 5 else 0
        roc_20 = (closes[i] - closes[i-20]) / closes[i-20] * 100 if i >= 20 else 0
        momentum_accel = roc_5 - (roc_20 * 0.3)
        if momentum_accel > 3: trend_score += 3
        elif momentum_accel > 1: trend_score += 1
        elif momentum_accel < -3: trend_score -= 3
        elif momentum_accel < -1: trend_score -= 1
        
        # 波動率擴張
        atr_5 = atr(highs[i-5:i+1], lows[i-5:i+1], closes[i-5:i+1], 5)
        atr_20 = atr(highs[i-20:i+1], lows[i-20:i+1], closes[i-20:i+1], 20)
        if isinstance(atr_5, list): atr_5 = atr_5[-1] if atr_5 else current * 0.03
        if isinstance(atr_20, list): atr_20 = atr_20[-1] if atr_20 else current * 0.03
        vol_ratio = atr_5 / atr_20 if atr_20 > 0 else 1.0
        if vol_ratio > 1.5: trend_score += 2
        elif vol_ratio < 0.7: trend_score -= 1
        
        # 成交量
        vol_avg = statistics.mean(vols[max(0,i-5):i+1])
        vol_base = statistics.mean(vols[max(0,i-20):i+1])
        vol_conf = vol_avg / vol_base if vol_base > 0 else 1.0
        if vol_conf > 1.5: trend_score += 2
        elif vol_conf < 0.6: trend_score -= 1
        
        # 價格突破
        high_20_prev = max(highs[i-20:i])
        if current > high_20_prev: trend_score += 2
        
        # EMA 趨勢確認
        if current > ema20 and ema20 > ema50: trend_score += 1
        elif current < ema20 and ema20 < ema50: trend_score -= 1
        
        if trend_score >= 4:
            sl = current - atr_val * 1.5
            tp = current + atr_val * 2.0
            signal = {'direction': 'long', 'score': trend_score, 'tp': tp, 'sl': sl,
                      'reason': 'TREND_BUY', 'adx': adx_val}
        elif trend_score <= -4:
            sl = current + atr_val * 1.5
            tp = current - atr_val * 2.0
            signal = {'direction': 'short', 'score': trend_score, 'tp': tp, 'sl': sl,
                      'reason': 'TREND_SELL', 'adx': adx_val}
    
    return signal

# ══════════════════════════════════════════════════════════════
# 6 組策略定義
# ══════════════════════════════════════════════════════════════

STRATEGIES = {
    "A_FVG保守": {
        "initial_balance": 1000.0, "max_positions": 2, "max_hold_days": 7,
        "leverage": 3, "risk_per_trade": 0.08, "strategy_type": "fvg",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
    },
    "B_FVG積極": {
        "initial_balance": 1000.0, "max_positions": 3, "max_hold_days": 14,
        "leverage": 5, "risk_per_trade": 0.10, "strategy_type": "fvg",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
    },
    "C_趨勢保守": {
        "initial_balance": 1000.0, "max_positions": 2, "max_hold_days": 14,
        "leverage": 3, "risk_per_trade": 0.05, "strategy_type": "trend",
        "max_daily_loss_pct": 10.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
    },
    "D_趨勢積極": {
        "initial_balance": 1000.0, "max_positions": 3, "max_hold_days": 30,
        "leverage": 5, "risk_per_trade": 0.08, "strategy_type": "trend",
        "max_daily_loss_pct": 10.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
    },
    "E_雙策略保守": {
        "initial_balance": 1000.0, "max_positions": 2, "max_hold_days": 7,
        "leverage": 3, "risk_per_trade": 0.08, "strategy_type": "both",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
    },
    "F_雙策略積極": {
        "initial_balance": 1000.0, "max_positions": 3, "max_hold_days": 14,
        "leverage": 5, "risk_per_trade": 0.10, "strategy_type": "both",
        "max_daily_loss_pct": 15.0, "max_consecutive_losses": 5, "cooldown_hours": 24,
    },
}

# ══════════════════════════════════════════════════════════════
# State 管理
# ══════════════════════════════════════════════════════════════

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
MULTI_STATE_DIR = os.path.join(PROJECT_ROOT, 'data', 'paper_strategies')
os.makedirs(MULTI_STATE_DIR, exist_ok=True)

def load_state(name):
    path = os.path.join(MULTI_STATE_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    params = STRATEGIES[name]
    return {
        'strategy': name, 'balance': params['initial_balance'],
        'positions': [], 'history': [], 'params': params,
        'stats': {'total_trades': 0, 'wins': 0, 'losses': 0,
                  'total_pnl': 0.0, 'max_win': 0.0, 'max_loss': 0.0},
    }

def save_state(name, state):
    path = os.path.join(MULTI_STATE_DIR, f"{name}.json")
    with open(path, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# ══════════════════════════════════════════════════════════════
# 交易引擎
# ══════════════════════════════════════════════════════════════

def get_current_prices():
    prices = {}
    for coin in WATCHLIST:
        try:
            data = get_binance_klines(coin['symbol'], limit=5)
            if data and len(data) > 0:
                prices[coin['name']] = data[-1]['close']
        except:
            continue
    return prices

def calc_position_size(balance, entry, sl, leverage, risk_per_trade):
    risk_amount = balance * risk_per_trade
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
    params = state['params']
    history = state.get('history', [])
    today = datetime.now().strftime('%Y-%m-%d')
    today_pnl = sum(h.get('pnl', 0) for h in history if h.get('exit_time', '').startswith(today))
    if today_pnl < -state['balance'] * params['max_daily_loss_pct'] / 100:
        return False, f'單日虧損 ${today_pnl:.2f} 超過上限'
    recent = [h for h in history if h.get('exit_time', '') >= (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')]
    consecutive = sum(1 for h in reversed(recent) if h.get('pnl', 0) < 0)
    if consecutive >= params['max_consecutive_losses']:
        return False, f'連續 {consecutive} 次虧損'
    return True, ''

def is_in_cooldown(state, coin_name):
    cutoff = datetime.now() - timedelta(hours=state['params']['cooldown_hours'])
    for h in reversed(state.get('history', [])):
        if h.get('coin') == coin_name:
            try:
                if datetime.fromisoformat(h.get('exit_time', '')) > cutoff:
                    return True
            except:
                pass
            break
    return False

def update_positions(state, prices):
    params = state['params']
    still_open = []
    for pos in state['positions']:
        coin = pos['coin']
        if coin not in prices:
            still_open.append(pos)
            continue
        current = prices[coin]
        pos['current_price'] = current
        
        if pos['direction'] == 'long':
            pnl = (current - pos['entry']) * pos['size']
        else:
            pnl = (pos['entry'] - current) * pos['size']
        pos['pnl_pnl'] = pnl
        pos['pnl_pct'] = pnl / state['balance'] * 100 * params['leverage']
        
        should_close = False
        reason = ''
        
        # TP/SL
        if pos['direction'] == 'long':
            if current >= pos['tp']:
                should_close, reason = True, 'TP 觸發'
            elif current <= pos['sl']:
                should_close, reason = True, 'SL 觸發'
        else:
            if current <= pos['tp']:
                should_close, reason = True, 'TP 觸發'
            elif current >= pos['sl']:
                should_close, reason = True, 'SL 觸發'
        
        # 超時
        if not should_close:
            try:
                entry_time = datetime.fromisoformat(pos['entry_time'])
                if datetime.now() - entry_time > timedelta(days=params['max_hold_days']):
                    should_close, reason = True, f'持倉超時 {params["max_hold_days"]}天'
            except:
                pass
        
        if should_close:
            close_pos(state, pos, current, reason)
        else:
            still_open.append(pos)
    
    state['positions'] = still_open

def close_pos(state, pos, close_price, reason):
    if pos['direction'] == 'long':
        pnl = (close_price - pos['entry']) * pos['size']
    else:
        pnl = (pos['entry'] - close_price) * pos['size']
    
    state['balance'] += pnl
    state['stats']['total_trades'] += 1
    state['stats']['total_pnl'] += pnl
    if pnl > 0:
        state['stats']['wins'] += 1
        state['stats']['max_win'] = max(state['stats']['max_win'], pnl)
    else:
        state['stats']['losses'] += 1
        state['stats']['max_loss'] = min(state['stats']['max_loss'], pnl)
    
    state['history'].append({
        'coin': pos['coin'], 'direction': pos['direction'],
        'entry': pos['entry'], 'exit': close_price, 'size': pos['size'],
        'pnl': round(pnl, 4), 'reason': reason,
        'entry_time': pos['entry_time'],
        'exit_time': datetime.now().isoformat(),
        'signal_reason': pos.get('signal_reason', ''),
    })

def check_new_entries(state):
    params = state['params']
    if len(state['positions']) >= params['max_positions']:
        return
    
    circuit_ok, _ = check_circuit_breaker(state)
    if not circuit_ok:
        return
    
    prices = get_current_prices()
    strategy_type = params['strategy_type']
    
    for coin in WATCHLIST:
        if len(state['positions']) >= params['max_positions']:
            break
        
        if any(p['coin'] == coin['name'] for p in state['positions']):
            continue
        
        if is_in_cooldown(state, coin['name']):
            continue
        
        try:
            data = get_binance_klines(coin['symbol'], limit=60)
            if not data or len(data) < 50:
                continue
            
            sig = generate_fvg_signal(data, strategy_type)
            if sig is None:
                continue
            
            direction = sig['direction']
            entry = prices.get(coin['name'])
            if entry is None:
                continue
            
            tp = sig['tp']
            sl = sig['sl']
            
            size = calc_position_size(state['balance'], entry, sl, params['leverage'], params['risk_per_trade'])
            if size <= 0:
                continue
            
            pos = {
                'coin': coin['name'], 'direction': direction,
                'entry': entry, 'tp': tp, 'sl': sl,
                'size': round(size, 6), 'current_price': entry,
                'pnl_pnl': 0, 'pnl_pct': 0,
                'entry_time': datetime.now().isoformat(),
                'signal_reason': sig.get('reason', ''),
            }
            state['positions'].append(pos)
            print(f"  ✅ 建倉: {coin['name']} {direction} @ ${entry:,.2f} | {sig.get('reason','')} | score={sig['score']}")
        
        except Exception as e:
            print(f"  ⚠️ {coin['name']} 失敗: {e}")

def run_once(name):
    state = load_state(name)
    prices = get_current_prices()
    
    print(f'\n[{name}] {datetime.now().strftime("%Y-%m-%d %H:%M")} | 餘額: ${state["balance"]:.2f} | 持倉: {len(state["positions"])}')
    
    update_positions(state, prices)
    check_new_entries(state)
    
    for pos in state['positions']:
        if pos['coin'] in prices:
            pos['current_price'] = prices[pos['coin']]
    
    save_state(name, state)
    print(f'   完成 | 餘額: ${state["balance"]:.2f}')
    return state

def run_all():
    print(f'{"=" * 70}')
    print(f'🔬 FVG + 趨勢 多策略對比 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'{"=" * 70}')
    
    results = {}
    for name in STRATEGIES:
        state = run_once(name)
        results[name] = state
    
    # 對比摘要
    print(f'\n\n{"=" * 80}')
    print('📊 策略對比摘要')
    print(f'{"=" * 80}')
    print(f'{"策略":<16} {"類型":<5} {"槓桿":>4} {"風險":>5} {"倉位":>4} {"超時":>4} {"餘額":>10} {"PnL%":>7} {"交易":>5} {"WR":>5}')
    print(f'{"─" * 16} {"─" * 5} {"─" * 4} {"─" * 5} {"─" * 4} {"─" * 4} {"─" * 10} {"─" * 7} {"─" * 5} {"─" * 5}')
    
    for name, state in results.items():
        p = state['params']
        s = state['stats']
        total = s['total_trades']
        wr = s['wins'] / total * 100 if total > 0 else 0
        pct = (state['balance'] / p['initial_balance'] - 1) * 100
        stype = p['strategy_type']
        print(f'{name:<16} {stype:<5} {p["leverage"]:>3}x {p["risk_per_trade"]*100:>4.0f}% {p["max_positions"]:>3} {p["max_hold_days"]:>3}d ${state["balance"]:>9.2f} {pct:>+6.1f}% {total:>4} {wr:>4.0f}%')
    
    best = max(results.items(), key=lambda x: x[1]['balance'])
    print(f'\n🏆 最佳: {best[0]} → ${best[1]["balance"]:.2f} ({(best[1]["balance"]/best[1]["params"]["initial_balance"]-1)*100:+.1f}%)')
    
    return results

if __name__ == '__main__':
    args = sys.argv[1:]
    if '--reset' in args:
        import shutil
        if os.path.exists(MULTI_STATE_DIR):
            shutil.rmtree(MULTI_STATE_DIR)
        os.makedirs(MULTI_STATE_DIR, exist_ok=True)
        print('✅ 已重置所有策略')
    else:
        run_all()
