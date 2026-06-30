#!/usr/bin/env python3
"""
dual_strategy.py - 雙策略交易框架
策略 A: FVG + Fibonacci 均值回歸（震盪市場 ADX < 25）
策略 B: 趨勢追蹤（趨勢市場 ADX >= 25）

根據市場狀態自動切換，避免趨勢行情用震盪策略、震盪行情用趨勢策略。

用法:
  from dual_strategy import DualStrategy
  ds = DualStrategy(leverage=3, risk_pct=0.03)
  result = ds.analyze_and_backtest(data, coin_name)
"""
import sys, os, statistics, math
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import atr, adx, ema, rsi as _rsi

# ══════════════════════════════════════════════════════════════
# 策略參數
# ══════════════════════════════════════════════════════════════

# 策略 A: FVG + Fibonacci（震盪）
FVG_PARAMS = {
    'fib_382': (33, 43),     # 38.2% 回撤範圍
    'fib_50': (47, 53),      # 50% 回撤範圍
    'fib_618': (58, 65),     # 61.8% 回撤範圍
    'score_bull_fvg': 3,     # 支撐 FVG 加分
    'score_bear_fvg': -3,    # 阻力 FVG 加分
    'score_fib382': 3,       # 38.2% 位置加分
    'score_fib50': 2,        # 50% 位置加分
    'score_fib618': 1,       # 61.8% 位置加分
    'score_near_high': -3,   # 接近高點扣分
    'score_near_low': -2,    # 接近低點扣分
    'vol_boost': 1.15,       # 放量加成
    'vol_penalty': 0.85,     # 縮量懲罰
    'tp_rr_ratio': 1.5,      # TP = 1.5x risk
    'max_hold_days': 14,     # 最大持倉天數
    'min_score': 5,          # 最低開倉分數（避免假信號）
    'adx_threshold': 25,     # ADX 低於此值才用此策略
}

# 策略 B: 趨勢追蹤
TREND_PARAMS = {
    'adx_threshold': 25,     # ADX 高於此值才用此策略
    'ema_tp_mult': 2.0,      # 趨勢 TP = 2x ATR
    'ema_sl_mult': 1.5,      # 趨勢 SL = 1.5x ATR
    'trailing_sl_mult': 2.0, # 追蹤止損 = 2x ATR from high/low
    'min_pnl_for_trail': 5,  # 盈利 > 5% 才啟動追蹤止損
    'max_hold_days': 30,     # 趨勢持倉更久
    'score_threshold': 25,   # scoring_v6 分數門檻
}

# 熔斷
CIRCUIT_BREAKER = {
    'max_daily_loss': 0.05,     # 單日最大虧損 5%
    'max_consecutive_losses': 5,  # 連續虧損 5 次暫停
    'cooldown_days': 3,        # 暫停天數
    'max_positions': 3,         # 同時最多 3 個倉位
}


# ══════════════════════════════════════════════════════════════
# 技術工具
# ══════════════════════════════════════════════════════════════

def calc_rsi(closes, n=14):
    if len(closes) < n + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[-n:]) / n
    avg_l = sum(losses[-n:]) / n
    if avg_l == 0: return 100
    return 100 - 100 / (1 + avg_g / avg_l)


def get_adx_val(highs, lows, closes, n=14):
    """保留 ADX 向後相容，但內部不再作為主要判斷"""
    result = adx(highs, lows, closes, n)
    if isinstance(result, tuple) and len(result) >= 1:
        adx_list = result[0]
        if isinstance(adx_list, list) and adx_list:
            for v in reversed(adx_list):
                if v is not None: return v
    return 20


# ══════════════════════════════════════════════════════════════
# 新型趨勢檢測（替代 ADX/DMI）
# ══════════════════════════════════════════════════════════════

def detect_trend_early(closes, highs, lows, vols, i):
    """
    早期趨勢檢測器（不依賴滯後 EMA/ADX）
    
    返回: ('strong_up', score) / ('up', score) / ('neutral', score) / ('down', score) / ('strong_down', score)
    
    核心信號：
    1. 動量加速（5天 vs 20天 ROC 差）→ 權重 3
    2. 波動率收縮→擴張（5天/20天 ATR 比）→ 權重 2
    3. 成交量突增（5天/20天 量比）→ 權重 2
    4. 價格突破 20 天高點 → 權重 2
    """
    if i < 30: return 'neutral', 0
    
    # 1. 價格動量加速
    roc_5 = (closes[i] - closes[i-5]) / closes[i-5] * 100 if i >= 5 else 0
    roc_20 = (closes[i] - closes[i-20]) / closes[i-20] * 100 if i >= 20 else 0
    momentum_accel = roc_5 - (roc_20 * 0.3)
    
    # 2. 波動率收縮→擴張
    atr_5 = atr(highs[i-5:i+1], lows[i-5:i+1], closes[i-5:i+1], 5)
    atr_20 = atr(highs[i-20:i+1], lows[i-20:i+1], closes[i-20:i+1], 20)
    if isinstance(atr_5, list): atr_5 = atr_5[-1] if atr_5 else closes[i] * 0.03
    if isinstance(atr_20, list): atr_20 = atr_20[-1] if atr_20 else closes[i] * 0.03
    if atr_20 == 0: vol_ratio = 1.0
    else: vol_ratio = atr_5 / atr_20
    
    # 3. 成交量突增
    vol_avg = statistics.mean(vols[max(0, i-5):i+1])
    vol_base = statistics.mean(vols[max(0, i-20):i+1])
    vol_conf = vol_avg / vol_base if vol_base > 0 else 1.0
    
    # 4. 價格突破 20 天高點
    high_20_prev = max(highs[i-20:i])  # 不含當前這根
    price_break = 1 if closes[i] > high_20_prev else 0
    
    # 5. 綜合評分
    score = 0
    
    # 動量加速
    if momentum_accel > 3: score += 3
    elif momentum_accel > 1: score += 1
    elif momentum_accel < -3: score -= 3
    elif momentum_accel < -1: score -= 1
    
    # 波動率擴張
    if vol_ratio > 1.5: score += 2
    elif vol_ratio < 0.7: score -= 1
    
    # 成交量確認
    if vol_conf > 1.5: score += 2
    elif vol_conf < 0.6: score -= 1
    
    # 價格突破
    score += price_break * 2
    
    # 判定（更嚴格的閾值，避免過度切換）
    if score >= 6: return 'strong_up', score
    elif score >= 4: return 'up', score
    elif score <= -6: return 'strong_down', score
    elif score <= -4: return 'down', score
    else: return 'neutral', score


def get_ema_val(closes, period):
    result = ema(closes, period)
    if isinstance(result, list) and result: return result[-1]
    return result if result else closes[-1]


def find_fvg(data, i, lookback=5):
    """
    找最近 lookback 根 K 線內的 FVG
    返回: ('bull', low, high) 或 ('bear', low, high) 或 None
    """
    fvgs = []
    for j in range(max(i-lookback, 2), i+1):
        k1, k3 = data[j-2], data[j]
        # 看多 FVG: k1.high < k3.low
        if k1['high'] < k3['low']:
            fvgs.append(('bull', k1['high'], k3['low']))
        # 看空 FVG: k1.low > k3.high
        if k1['low'] > k3['high']:
            fvgs.append(('bear', k3['high'], k1['low']))
    return fvgs


def price_in_fvg(current_price, fvgs):
    """檢查價格是否在任何 FVG 範圍內"""
    for direction, low, high in fvgs:
        if low <= current_price <= high:
            return direction
    return None


def fib_position(price, high, low):
    """計算價格在 Fibonacci 回撤中的位置 (0-100)"""
    r = high - low
    if r == 0: return 50
    return (high - price) / r * 100


# ══════════════════════════════════════════════════════════════
# 策略 A: FVG + Fibonacci 均值回歸
# ══════════════════════════════════════════════════════════════

def strategy_a_fvg_fib(data, start_day=50):
    """
    震盪市場策略：FVG + Fibonacci 均值回歸
    只在 ADX < 25 時使用
    """
    params = FVG_PARAMS
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d.get('vol', d.get('volume', 0)) for d in data]
    
    trades = []
    position = None
    
    for i in range(start_day, len(data)):
        current = closes[i]
        high_50 = max(highs[i-50:i])
        low_50 = min(lows[i-50:i])
        fib_range = high_50 - low_50
        if fib_range == 0: continue
        
        adx_val = get_adx_val(highs[:i+1], lows[:i+1], closes[:i+1])
        
        # 趨勢市場不用此策略
        if adx_val >= params['adx_threshold']:
            if position:  # 如果有倉位，繼續持有到出場
                pass
            else:
                continue
        
        fib_pos = fib_position(current, high_50, low_50)
        
        # FVG 檢測
        fvgs = find_fvg(data, i)
        fvg_direction = price_in_fvg(current, fvgs)
        
        # 成交量
        avg_vol = statistics.mean(vols[max(0,i-20):i])
        vol_50 = statistics.mean(vols[max(0,i-50):i])
        vol_ratio = avg_vol / vol_50 if vol_50 > 0 else 1
        
        # 評分
        score = 0
        lo, hi = params['fib_382']
        if lo <= fib_pos <= hi: score += params['score_fib382']
        lo, hi = params['fib_50']
        if lo <= fib_pos <= hi: score += params['score_fib50']
        lo, hi = params['fib_618']
        if lo <= fib_pos <= hi: score += params['score_fib618']
        if fib_pos < 15: score += params['score_near_high']
        if fib_pos > 85: score += params['score_near_low']
        
        if fvg_direction == 'bull': score += params['score_bull_fvg']
        elif fvg_direction == 'bear': score += params['score_bear_fvg']
        
        if vol_ratio > 1.3: score = int(score * params['vol_boost'])
        elif vol_ratio < 0.7: score = int(score * params['vol_penalty'])
        
        # 信號判定
        signal = "NEUTRAL"
        if score >= params['min_score']: signal = "BUY"
        elif score <= -params['min_score']: signal = "SELL"
        
        # 持倉管理
        if position:
            days_held = i - position['entry_idx']
            side = position['side']
            
            if side == 'long':
                pnl = (current - position['entry']) / position['entry'] * 100 * 3  # 3x
            else:
                pnl = (position['entry'] - current) / position['entry'] * 100 * 3
            
            exit_reason = None
            if side == 'long':
                if current < position['sl']: exit_reason = 'SL'
                elif current >= position['tp']: exit_reason = 'TP'
                elif signal == 'SELL' and days_held >= 2: exit_reason = 'REV'
            else:
                if current > position['sl']: exit_reason = 'SL'
                elif current <= position['tp']: exit_reason = 'TP'
                elif signal == 'BUY' and days_held >= 2: exit_reason = 'REV'
            
            if days_held >= params['max_hold_days'] and not exit_reason:
                exit_reason = 'TIME'
            
            if exit_reason:
                trades.append({'pnl': pnl, 'days': days_held, 'reason': exit_reason, 'side': side})
                position = None
        
        # 開倉
        if position is None and signal in ['BUY', 'SELL']:
            atr_val = atr(highs[max(0,i-50):i+1], lows[max(0,i-50):i+1], closes[max(0,i-50):i+1], 14)
            if atr_val is None: atr_val = current * 0.03
            
            if signal == 'BUY':
                sl = low_50
                tp = current + (current - low_50) * params['tp_rr_ratio']
                position = {'side':'long','entry':current,'sl':sl,'tp':tp,'entry_idx':i}
            else:
                sl = high_50
                tp = current - (high_50 - current) * params['tp_rr_ratio']
                position = {'side':'short','entry':current,'sl':sl,'tp':tp,'entry_idx':i}
    
    return trades


# ══════════════════════════════════════════════════════════════
# 策略 B: 趨勢追蹤
# ══════════════════════════════════════════════════════════════

def strategy_b_trend(data, start_day=50):
    """
    趨勢市場策略：EMA 排列 + 動態止損
    只在 ADX >= 25 時使用
    """
    params = TREND_PARAMS
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d['vol'] for d in data]
    atr_vals = atr(highs, lows, closes, 14)
    
    trades = []
    position = None
    
    for i in range(start_day, len(data)):
        current = closes[i]
        atr_val = atr_vals[i-1] if i-1 < len(atr_vals) and atr_vals[i-1] else current * 0.03
        
        adx_val = get_adx_val(highs[:i+1], lows[:i+1], closes[:i+1])
        e20 = get_ema_val(closes[:i+1], 20)
        e50 = get_ema_val(closes[:i+1], 50)
        rsi_val = calc_rsi(closes[:i+1])
        
        # 震盪市場不用此策略
        if adx_val < params['adx_threshold']:
            if position:  # 繼續持有
                pass
            else:
                continue
        
        # 趨勢判定
        if e20 > e50 * 1.02 and rsi_val > 50:
            trend = 'bullish'
        elif e20 < e50 * 0.98 and rsi_val < 50:
            trend = 'bearish'
        else:
            trend = 'mixed'
        
        # 持倉管理
        if position:
            days_held = i - position['entry_idx']
            side = position['side']
            
            if side == 'long':
                pnl = (current - position['entry']) / position['entry'] * 100 * 3
                # 更新最高價
                position['highest'] = max(position.get('highest', position['entry']), current)
                # 追蹤止損
                trail_sl = position['highest'] - params['trailing_sl_mult'] * atr_val
                
                exit_reason = None
                if current < position['sl']:
                    exit_reason = 'SL'
                elif current < trail_sl and pnl > params['min_pnl_for_trail']:
                    exit_reason = 'TRAIL'
                elif trend == 'bearish' and days_held > 3:
                    exit_reason = 'REV'
                if days_held >= params['max_hold_days'] and not exit_reason:
                    exit_reason = 'TIME'
                if exit_reason:
                    trades.append({'pnl': pnl, 'days': days_held, 'reason': exit_reason, 'side': side})
                    position = None
            else:  # short
                pnl = (position['entry'] - current) / position['entry'] * 100 * 3
                position['lowest'] = min(position.get('lowest', position['entry']), current)
                trail_sl = position['lowest'] + params['trailing_sl_mult'] * atr_val
                
                exit_reason = None
                if current > position['sl']:
                    exit_reason = 'SL'
                elif current > trail_sl and pnl > params['min_pnl_for_trail']:
                    exit_reason = 'TRAIL'
                elif trend == 'bullish' and days_held > 3:
                    exit_reason = 'REV'
                if days_held >= params['max_hold_days'] and not exit_reason:
                    exit_reason = 'TIME'
                if exit_reason:
                    trades.append({'pnl': pnl, 'days': days_held, 'reason': exit_reason, 'side': side})
                    position = None
        
        # 開倉
        if position is None:
            if trend == 'bullish' and rsi_val <= 70:
                sl = current - params['ema_sl_mult'] * atr_val
                tp = current + params['ema_tp_mult'] * atr_val
                position = {'side':'long','entry':current,'sl':sl,'tp':tp,'entry_idx':i,'highest':current}
            elif trend == 'bearish' and rsi_val >= 30:
                sl = current + params['ema_sl_mult'] * atr_val
                tp = current - params['ema_tp_mult'] * atr_val
                position = {'side':'short','entry':current,'sl':sl,'tp':tp,'entry_idx':i,'lowest':current}
    
    return trades


# ══════════════════════════════════════════════════════════════
# 雙策略整合引擎
# ══════════════════════════════════════════════════════════════

class DualStrategy:
    """
    雙策略引擎：根據市場狀態自動切換
    
    邏輯（v2: 用早期趨勢檢測替代 ADX）:
    1. 用動量+波動率+成交量+價格突破 計算趨勢分數
    2. score >= 3 → 趨勢市場 → 用策略 B (趨勢追蹤)
    3. score <= -3 → 反趨勢 → 用策略 B (做空)
    4. -3 < score < 3 → 震盪 → 用策略 A (FVG + Fib 均值回歸)
    """
    
    def __init__(self, leverage=3, risk_pct=0.03):
        self.leverage = leverage
        self.risk_pct = risk_pct
        self.circuit_breaker = {
            'consecutive_losses': 0,
            'cooldown_until': 0,
            'daily_pnl': 0,
        }
    
    def detect_regime(self, highs, lows, closes, vols, i):
        """
        檢測市場狀態（新版，不用 ADX）
        返回: 'trending_up', 'trending_down', 'ranging'
        """
        regime, score = detect_trend_early(closes, highs, lows, vols, i)
        
        if regime in ('strong_up', 'up'):
            return 'trending_up', score
        elif regime in ('strong_down', 'down'):
            return 'trending_down', score
        else:
            return 'ranging', score
    
    def run_backtest(self, data, coin_name, start_day=50):
        """
        雙策略回測
        """
        closes = [d['close'] for d in data]
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        vols = [d.get('vol', d.get('volume', 0)) for d in data]
        atr_vals = atr(highs, lows, closes, 14)
        
        trades = []
        position = None
        regime_log = {'ranging_buys': 0, 'trend_buys': 0, 'transition_skips': 0}
        
        for i in range(start_day, len(data)):
            current = closes[i]
            atr_val = atr_vals[i-1] if i-1 < len(atr_vals) and atr_vals[i-1] else current * 0.03
            
            # 市場狀態檢測（新版：用早期趨勢檢測）
            regime, trend_score = self.detect_regime(highs, lows, closes, vols, i)
            
            # 熔斷檢查
            if i < self.circuit_breaker['cooldown_until']:
                continue
            
            # 持倉管理（通用）
            if position:
                days_held = i - position['entry_idx']
                side = position['side']
                
                if side == 'long':
                    pnl = (current - position['entry']) / position['entry'] * 100 * self.leverage
                else:
                    pnl = (position['entry'] - current) / position['entry'] * 100 * self.leverage
                
                exit_reason = None
                
                # 更新最高/最低價（用於追蹤止損）
                if side == 'long':
                    position['highest'] = max(position.get('highest', position['entry']), current)
                else:
                    position['lowest'] = min(position.get('lowest', position['entry']), current)
                
                strategy_type = position.get('strategy', 'unknown')
                
                # ── 策略 A (FVG): 固定 TP/SL + 信號反轉 ──
                if strategy_type == 'fvg':
                    if side == 'long' and current < position['sl']:
                        exit_reason = 'SL'
                    elif side == 'short' and current > position['sl']:
                        exit_reason = 'SL'
                    elif side == 'long' and current >= position['tp']:
                        exit_reason = 'TP'
                    elif side == 'short' and current <= position['tp']:
                        exit_reason = 'TP'
                    # 信號反轉
                    elif days_held >= 2:
                        e20 = get_ema_val(closes[:i+1], 20)
                        e50 = get_ema_val(closes[:i+1], 50)
                        if side == 'long' and e20 < e50:
                            exit_reason = 'REV'
                        elif side == 'short' and e20 > e50:
                            exit_reason = 'REV'
                    # 時間止損
                    if not exit_reason and days_held >= FVG_PARAMS['max_hold_days']:
                        exit_reason = 'TIME'
                
                # ── 策略 B (Trend): 追蹤止損 + 趨勢追蹤 ──
                elif strategy_type == 'trend':
                    # 階段1: 固定 SL（保護本金）
                    if side == 'long' and current < position['sl']:
                        exit_reason = 'SL'
                    elif side == 'short' and current > position['sl']:
                        exit_reason = 'SL'
                    
                    # 階段2: 追蹤止損（盈利後鎖定利潤）
                    if not exit_reason and pnl > 3:
                        trail_mult = 2.0  # 2x ATR 追蹤
                        if side == 'long':
                            trail_sl = position['highest'] - trail_mult * atr_val
                            if current < trail_sl:
                                exit_reason = 'TRAIL'
                        else:
                            trail_sl = position['lowest'] + trail_mult * atr_val
                            if current > trail_sl:
                                exit_reason = 'TRAIL'
                    
                    # 階段3: 盈利 > 10% 後收緊追蹤止損
                    if not exit_reason and pnl > 10:
                        trail_mult = 1.5  # 1.5x ATR 收緊
                        if side == 'long':
                            trail_sl = position['highest'] - trail_mult * atr_val
                            if current < trail_sl:
                                exit_reason = 'TRAIL_TIGHT'
                        else:
                            trail_sl = position['lowest'] + trail_mult * atr_val
                            if current > trail_sl:
                                exit_reason = 'TRAIL_TIGHT'
                    
                    # 階段4: 趨勢反轉（EMA 穿越 + 動量轉負）
                    if not exit_reason and days_held >= 5:
                        e20 = get_ema_val(closes[:i+1], 20)
                        e50 = get_ema_val(closes[:i+1], 50)
                        rsi_now = calc_rsi(closes[:i+1])
                        
                        if side == 'long':
                            # EMA 空頭排列 + RSI < 45 → 趨勢結束
                            if e20 < e50 and rsi_now < 45:
                                exit_reason = 'TREND_END'
                            # ADX 轉弱（趨勢衰竭）
                            _, trend_score = self.detect_regime(highs, lows, closes, vols, i)
                            if trend_score < -2:
                                exit_reason = 'TREND_WEAK'
                        else:
                            if e20 > e50 and rsi_now > 55:
                                exit_reason = 'TREND_END'
                            _, trend_score = self.detect_regime(highs, lows, closes, vols, i)
                            if trend_score > 2:
                                exit_reason = 'TREND_WEAK'
                    
                    # 時間止損（趨勢策略可以持有更久）
                    if not exit_reason and days_held >= TREND_PARAMS['max_hold_days']:
                        exit_reason = 'TIME'
                
                if exit_reason:
                    trades.append({
                        'pnl': pnl, 'days': days_held, 'reason': exit_reason,
                        'side': side, 'strategy': position.get('strategy', 'unknown')
                    })
                    # 熔斷更新
                    if pnl < 0:
                        self.circuit_breaker['consecutive_losses'] += 1
                        if self.circuit_breaker['consecutive_losses'] >= CIRCUIT_BREAKER['max_consecutive_losses']:
                            self.circuit_breaker['cooldown_until'] = i + CIRCUIT_BREAKER['cooldown_days']
                            self.circuit_breaker['consecutive_losses'] = 0
                    else:
                        self.circuit_breaker['consecutive_losses'] = 0
                    position = None
            
            # 開倉邏輯
            if position is None:
                # 根據市場狀態選擇策略
                if regime == 'ranging':
                    # 用策略 A: FVG + Fib（震盪市場）
                    new_trades = self._try_fvg_entry(data, i)
                    if new_trades:
                        regime_log['ranging_buys'] += 1
                        position = new_trades
                elif regime == 'trending_up':
                    # 用策略 B: 趨勢追蹤（做多）
                    new_trades = self._try_trend_entry(data, i, direction='long')
                    if new_trades:
                        regime_log['trend_buys'] += 1
                        position = new_trades
                elif regime == 'trending_down':
                    # 用策略 B: 趨勢追蹤（做空）
                    new_trades = self._try_trend_entry(data, i, direction='short')
                    if new_trades:
                        regime_log['trend_buys'] += 1
                        position = new_trades
        
        return trades, regime_log
    
    def _try_fvg_entry(self, data, i, strict=False):
        """嘗試 FVG + Fib 入場"""
        closes = [d['close'] for d in data]
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        vols = [d.get('vol', d.get('volume', 0)) for d in data]
        
        current = closes[i]
        high_50 = max(highs[i-50:i])
        low_50 = min(lows[i-50:i])
        fib_range = high_50 - low_50
        if fib_range == 0: return None
        
        fib_pos = fib_position(current, high_50, low_50)
        fvgs = find_fvg(data, i)
        fvg_direction = price_in_fvg(current, fvgs)
        
        avg_vol = statistics.mean(vols[max(0,i-20):i])
        vol_50 = statistics.mean(vols[max(0,i-50):i])
        vol_ratio = avg_vol / vol_50 if vol_50 > 0 else 1
        
        score = 0
        lo, hi = FVG_PARAMS['fib_382']
        if lo <= fib_pos <= hi: score += FVG_PARAMS['score_fib382']
        lo, hi = FVG_PARAMS['fib_50']
        if lo <= fib_pos <= hi: score += FVG_PARAMS['score_fib50']
        lo, hi = FVG_PARAMS['fib_618']
        if lo <= fib_pos <= hi: score += FVG_PARAMS['score_fib618']
        if fib_pos < 15: score += FVG_PARAMS['score_near_high']
        if fib_pos > 85: score += FVG_PARAMS['score_near_low']
        
        if fvg_direction == 'bull': score += FVG_PARAMS['score_bull_fvg']
        elif fvg_direction == 'bear': score += FVG_PARAMS['score_bear_fvg']
        
        if vol_ratio > 1.3: score = int(score * FVG_PARAMS['vol_boost'])
        elif vol_ratio < 0.7: score = int(score * FVG_PARAMS['vol_penalty'])
        
        min_score = FVG_PARAMS['min_score'] + 2 if strict else FVG_PARAMS['min_score']
        
        if score >= min_score:
            sl = low_50
            tp = current + (current - low_50) * FVG_PARAMS['tp_rr_ratio']
            return {'strategy':'fvg','side':'long','entry':current,'sl':sl,'tp':tp,'entry_idx':i}
        elif score <= -min_score:
            sl = high_50
            tp = current - (high_50 - current) * FVG_PARAMS['tp_rr_ratio']
            return {'strategy':'fvg','side':'short','entry':current,'sl':sl,'tp':tp,'entry_idx':i}
        return None
    
    def _try_trend_entry(self, data, i, direction=None):
        """
        嘗試趨勢追蹤入場
        direction: 'long' / 'short' / None（自動偵測）
        """
        closes = [d['close'] for d in data]
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        
        current = closes[i]
        e20 = get_ema_val(closes[:i+1], 20)
        e50 = get_ema_val(closes[:i+1], 50)
        rsi_val = calc_rsi(closes[:i+1])
        atr_result = atr(highs[:i+1], lows[:i+1], closes[:i+1], 14)
        if atr_result is None: atr_val = current * 0.03
        elif isinstance(atr_result, list):
            atr_val = atr_result[-1] if atr_result else current * 0.03
        elif isinstance(atr_result, tuple):
            atr_val = atr_result[-1] if atr_result else current * 0.03
        else:
            atr_val = atr_result
        
        # 做多：EMA 多頭排列 + RSI 健康
        can_long = e20 > e50 * 1.02 and rsi_val > 50 and rsi_val <= 70
        # 做空：EMA 空頭排列 + RSI 健康
        can_short = e20 < e50 * 0.98 and rsi_val < 50 and rsi_val >= 30
        
        if direction == 'long' and can_long:
            sl = current - TREND_PARAMS['ema_sl_mult'] * atr_val
            tp = current + TREND_PARAMS['ema_tp_mult'] * atr_val
            return {'strategy':'trend','side':'long','entry':current,'sl':sl,'tp':tp,'entry_idx':i,'highest':current}
        elif direction == 'short' and can_short:
            sl = current + TREND_PARAMS['ema_sl_mult'] * atr_val
            tp = current - TREND_PARAMS['ema_tp_mult'] * atr_val
            return {'strategy':'trend','side':'short','entry':current,'sl':sl,'tp':tp,'entry_idx':i,'lowest':current}
        elif direction is None:
            # 自動偵測（舊邏輯）
            if can_long:
                sl = current - TREND_PARAMS['ema_sl_mult'] * atr_val
                tp = current + TREND_PARAMS['ema_tp_mult'] * atr_val
                return {'strategy':'trend','side':'long','entry':current,'sl':sl,'tp':tp,'entry_idx':i,'highest':current}
            elif can_short:
                sl = current + TREND_PARAMS['ema_sl_mult'] * atr_val
                tp = current - TREND_PARAMS['ema_tp_mult'] * atr_val
                return {'strategy':'trend','side':'short','entry':current,'sl':sl,'tp':tp,'entry_idx':i,'lowest':current}
        return None


# ══════════════════════════════════════════════════════════════
# 回測報告
# ══════════════════════════════════════════════════════════════

def generate_report(trades, coin_name, regime_log=None):
    """生成回測報告"""
    if not trades:
        return f"{coin_name}: 無交易"
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    # 出場原因統計
    reasons = {}
    for t in trades:
        reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
    
    # 策略統計
    fvg_trades = [t for t in trades if t.get('strategy') == 'fvg']
    trend_trades = [t for t in trades if t.get('strategy') == 'trend']
    
    avg_pnl = total_pnl / len(trades)
    avg_win = statistics.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = statistics.mean([t['pnl'] for t in losses]) if losses else 0
    pf = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    
    report = f"""🪙 {coin_name} 回測結果
交易: {len(trades)} 筆 | 勝率: {win_rate:.1f}% | 總PnL: {total_pnl:+.1f}% | 平均: {avg_pnl:+.2f}%
盈虧比: {pf:.2f} | 均贏: {avg_win:+.1f}% | 均輸: {avg_loss:+.1f}%
出場: {', '.join(f'{k}:{v}' for k,v in sorted(reasons.items()))}"""
    
    if fvg_trades:
        fvg_wr = len([t for t in fvg_trades if t['pnl']>0]) / len(fvg_trades) * 100
        fvg_pnl = sum(t['pnl'] for t in fvg_trades)
        report += f"\n  策略A(FVG): {len(fvg_trades)}筆 | WR {fvg_wr:.0f}% | PnL {fvg_pnl:+.1f}%"
    
    if trend_trades:
        trend_wr = len([t for t in trend_trades if t['pnl']>0]) / len(trend_trades) * 100
        trend_pnl = sum(t['pnl'] for t in trend_trades)
        report += f"\n  策略B(Trend): {len(trend_trades)}筆 | WR {trend_wr:.0f}% | PnL {trend_pnl:+.1f}%"
    
    if regime_log:
        report += f"\n  市場: 震盪買入 {regime_log.get('ranging_buys',0)} | 趨勢買入 {regime_log.get('trend_buys',0)} | 過渡觀望 {regime_log.get('transition_skips',0)}"
    
    return report


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    from backtester_v3 import get_binance_klines
    
    print("="*70)
    print("🔄 雙策略回測框架 v1.0")
    print("   策略A: FVG + Fibonacci（震盪 | ADX<22）")
    print("   策略B: 趨勢追蹤（趨勢 | ADX>=28）")
    print("   過渡區: 22-28 嚴格條件")
    print("="*70)
    
    coins = [
        ('BTCUSDT', 'BTC'), ('ETHUSDT', 'ETH'), ('SOLUSDT', 'SOL'),
        ('AVAXUSDT', 'AVAX'), ('WLDUSDT', 'WLD'), ('ZECUSDT', 'ZEC'),
    ]
    
    all_results = []
    
    for sym, name in coins:
        data = get_binance_klines(sym, limit=1000)
        if not data or len(data) < 50:
            print(f"{name}: 數據不足")
            continue
        
        ds = DualStrategy(leverage=3)
        trades, regime_log = ds.run_backtest(data, name)
        
        if trades:
            report = generate_report(trades, name, regime_log)
            print(report)
            all_results.append({'name': name, 'trades': len(trades), 
                               'pnl': sum(t['pnl'] for t in trades),
                               'wr': len([t for t in trades if t['pnl']>0])/len(trades)*100})
        else:
            print(f"{name}: 無交易")
    
    # 總結
    if all_results:
        print("\n" + "="*70)
        print("📊 總結")
        print("="*70)
        print(f"{'幣種':<6}|{'交易':>5}|{'勝率':>7}|{'總PnL':>9}")
        print("-"*40)
        for r in all_results:
            print(f"{r['name']:<6}|{r['trades']:>5}|{r['wr']:>6.1f}%|{r['pnl']:>+8.1f}%")
        avg_pnl = sum(r['pnl'] for r in all_results) / len(all_results)
        avg_wr = sum(r['wr'] for r in all_results) / len(all_results)
        print("-"*40)
        print(f"{'平均':<6}|{'':>5}|{avg_wr:>6.1f}%|{avg_pnl:>+8.1f}%")
