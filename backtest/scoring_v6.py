#!/usr/bin/env python3
"""
scoring_v6.py - 專業級評分系統 v6
位置: ~/.hermes/scripts/trading_lib/

改進重點（根據模型評估報告）：
1. 市況分類器：自動識別上漲/下跌/盤整，不同市況用不同因子權重
2. 信號確認機制：需要連續 N 次同方向信號才確認，避免信號跳動
3. 上漲趨勢因子：專屬多頭因子，解決 BUY 信號命中率 0% 的問題
4. 做空優化：独立做空評分系統

新增因子（上漲專用）:
- ema_alignment: 均線多頭排列分數
- breakout_score: 突破 N 天高點
- volume_momentum: 上漲日 vs 下跌日成交量比
- rsi_health: RSI 是否保持在健康區間 (40-70)
- obv_trend: OBV 趨勢強度
- pullbacK_shallow: 費波那契回撤深度
"""

import sys, os, math
sys.path.insert(0, os.path.dirname(__file__))
from indicators_v3 import *


# ══════════════════════════════════════════════════════════════
# 上漲趨勢因子（新增）
# ══════════════════════════════════════════════════════════════

def ema_alignment_score(closes, fast=10, mid=20, slow=50):
    """
    均線多頭排列分數
    
    邏輯：
    - EMA10 > EMA20 > EMA50 = 完美多頭排列（+15）
    - EMA10 > EMA20 但 EMA20 < EMA50 = 潛在反轉（+5）
    - EMA10 < EMA20 = 空頭（-10）
    """
    if len(closes) < slow:
        return 0, "數據不足"
    
    ema10 = ema(closes, fast)
    ema20 = ema(closes, mid)
    ema50 = ema(closes, slow)
    
    if not ema10 or not ema20 or not ema50:
        return 0, "EMA 計算失敗"
    
    v10 = ema10[-1]
    v20 = ema20[-1]
    v50 = ema50[-1]
    
    if v10 is None or v20 is None or v50 is None:
        return 0, "EMA 無效"
    
    # 完美多頭排列
    if v10 > v20 * 1.01 and v20 > v50 * 1.01:
        strength = min(15, (v10 / v50 - 1) * 100)
        return round(strength, 1), f"多頭排列(EMA10={v10:.2f}>EMA20={v20:.2f}>EMA50={v50:.2f})"
    
    # 潛在反轉（短期均線已上穿，但中期還沒）
    elif v10 > v20 * 1.01 and v20 <= v50:
        return 5, f"潛在反轉(EMA10>EMA20 但 EMA20<EMA50)"
    
    # 空頭排列
    elif v10 < v20 * 0.99 and v20 < v50 * 0.99:
        strength = max(-15, -(v50 / v10 - 1) * 100)
        return round(strength, 1), f"空頭排列(EMA10={v10:.2f}<EMA20={v20:.2f}<EMA50={v50:.2f})"
    
    # 混合
    else:
        return 0, f"混合(EMA10={v10:.2f}, EMA20={v20:.2f}, EMA50={v50:.2f})"


def breakout_score(closes, highs, lookback=20):
    """
    突破分數：價格是否突破 N 天高點
    
    邏輯：
    - 突破 20 天高點（+15）
    - 突破 10 天高點（+10）
    - 接近高點（<3%）=+5
    - 跌破 20 天低點（-15）
    """
    if len(closes) < lookback:
        return 0, "數據不足"
    
    current = closes[-1]
    high_20 = max(highs[-20:])
    high_10 = max(highs[-10:])
    low_20 = min(closes[-20:])
    
    # 突破 20 天高點
    if current >= high_20 * 0.998:
        return 15, f"突破 20 天高點(${high_20:.2f})"
    
    # 突破 10 天高點
    if current >= high_10 * 0.998:
        return 10, f"突破 10 天高點(${high_10:.2f})"
    
    # 接近 20 天高點
    dist_to_high = (high_20 - current) / current * 100
    if dist_to_high < 3:
        return 5, f"接近 20 天高點(距離 {dist_to_high:.1f}%)"
    
    # 跌破 20 天低點
    if current <= low_20 * 1.002:
        return -15, f"跌破 20 天低點(${low_20:.2f})"
    
    # 中間位置
    if high_20 > low_20:
        position = (current - low_20) / (high_20 - low_20) * 100
        if position > 70:
            return 3, f"偏強(位置 {position:.0f}%)"
        elif position < 30:
            return -3, f"偏弱(位置 {position:.0f}%)"
    
    return 0, f"中性(位置 {position:.0f}%)"


def volume_momentum_score(closes, vols, lookback=10):
    """
    量價動量分數：上漲日 vs 下跌日的成交量比
    
    邏輯：
    - 上漲日成交量和 > 下跌日成交量和 * 1.5 = 量價齊漲（+10）
    - 上漲日成交量和 > 下跌日成交量和 = 偏多（+5）
    - 下跌日成交量和 > 上漲日成交量和 * 1.5 = 量價背離（-10）
    """
    if len(closes) < lookback + 1 or len(vols) < lookback + 1:
        return 0, "數據不足"
    
    up_vol = 0  # 上漲日成交量和
    down_vol = 0  # 下跌日成交量和
    
    for i in range(-lookback, 0):
        if closes[i] > closes[i-1]:
            up_vol += vols[i]
        elif closes[i] < closes[i-1]:
            down_vol += vols[i]
    
    if down_vol == 0:
        ratio = float('inf') if up_vol > 0 else 1
    else:
        ratio = up_vol / down_vol
    
    if ratio > 1.5:
        return 10, f"量價齊漲(上漲量/下跌量={ratio:.1f})"
    elif ratio > 1:
        return 5, f"偏多(上漲量/下跌量={ratio:.1f})"
    elif ratio < 0.67:
        return -10, f"量價背離(上漲量/下跌量={ratio:.1f})"
    elif ratio < 1:
        return -5, f"偏空(上漲量/下跌量={ratio:.1f})"
    else:
        return 0, f"中性(上漲量/下跌量={ratio:.1f})"


def rsi_health_score(rsi_val):
    """
    RSI 健康度分數
    
    邏輯：
    - RSI 50-70 = 健康上漲（+8）
    - RSI 40-50 = 偏弱但可接受（+3）
    - RSI > 70 = 過熱（-5）
    - RSI < 40 = 過冷（-8）
    - RSI < 30 = 超賣（可能反轉，但當前趨勢中不操作）
    """
    if rsi_val is None:
        return 0, "RSI 無效"
    
    if 50 <= rsi_val <= 70:
        return 8, f"RSI健康({rsi_val:.1f})"
    elif 40 <= rsi_val < 50:
        return 3, f"RSI偏弱({rsi_val:.1f})"
    elif rsi_val > 80:
        return -8, f"RSI嚴重過熱({rsi_val:.1f})"
    elif rsi_val > 70:
        return -5, f"RSI過熱({rsi_val:.1f})"
    elif rsi_val < 30:
        return -3, f"RSI超賣({rsi_val:.1f})"
    else:
        return -5, f"RSI偏弱({rsi_val:.1f})"


def obv_trend_score(obv_vals, lookback=20):
    """
    OBV 趨勢分數
    
    邏輯：
    - OBV 上升且創 N 天新高（+10）
    - OBV 上升（+5）
    - OBV 下降且創 N 天新低（-10）
    """
    if not obv_vals or len(obv_vals) < lookback:
        return 0, "OBV 數據不足"
    
    recent = obv_vals[-lookback:]
    if any(v is None for v in recent):
        return 0, "OBV 含 None"
    
    # OBV 趨勢
    obv_sma_short = sum(recent[-5:]) / 5
    obv_sma_long = sum(recent) / lookback
    
    obv_rising = obv_sma_short > obv_sma_long * 1.02
    obv_falling = obv_sma_short < obv_sma_long * 0.98
    
    # 是否創 N 天新高
    obv_high = max(recent)
    obv_low = min(recent)
    current = obv_vals[-1]
    
    if obv_rising and current >= obv_high * 0.99:
        return 10, f"OBV創{lookback}天新高"
    elif obv_rising:
        return 5, f"OBV上升"
    elif obv_falling and current <= obv_low * 1.01:
        return -10, f"OBV創{lookback}天新低"
    elif obv_falling:
        return -5, f"OBV下降"
    else:
        return 0, f"OBV盤整"


def pullback_depth_score(closes, highs, lows, lookback=30):
    """
    回撤深度分數：在上漲趨勢中，回撤越淺越好
    
    邏輯：
    - 回撤 < 23.6% = 極淺，趨勢強勁（+10）
    - 回撤 23.6-38.2% = 正常回撤（+5）
    - 回撤 38.2-50% = 中度回撤（+2）
    - 回撤 > 50% = 深回撤，可能反轉（-5）
    """
    if len(closes) < lookback:
        return 0, "數據不足"
    
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    current = closes[-1]
    
    if recent_high <= recent_low:
        return 0, "無波動"
    
    # 計算回撤深度
    retracement = (recent_high - current) / (recent_high - recent_low) * 100
    
    if retracement < 23.6:
        return 10, f"極淺回撤({retracement:.1f}%)"
    elif retracement < 38.2:
        return 5, f"正常回撤({retracement:.1f}%)"
    elif retracement < 50:
        return 2, f"中度回撤({retracement:.1f}%)"
    else:
        return -5, f"深回撤({retracement:.1f}%)"


# ══════════════════════════════════════════════════════════════
# 市況分類器
# ══════════════════════════════════════════════════════════════

def classify_market(closes, highs, lows, volumes=None):
    """
    市況分類器：自動識別當前市場狀態
    
    返回: {
        'regime': 'trending_up' | 'trending_down' | 'ranging' | 'volatile' | 'dead_cat_bounce',
        'strength': 0-100,
        'confidence': 0-100,
    }
    """
    n = len(closes)
    if n < 20:
        return {'regime': 'ranging', 'strength': 0, 'confidence': 0}
    
    current = closes[-1]
    
    # SMA 趨勢（根據數據長度自適應）
    sma_short_period = min(7, n // 3)
    sma_mid_period = min(20, n // 2)
    sma_long_period = min(50, n - 1)
    
    sma_short = sma(closes, sma_short_period)
    sma_mid = sma(closes, sma_mid_period)
    sma_long = sma(closes, sma_long_period)
    
    sma_short_val = sma_short[-1] if sma_short and sma_short[-1] is not None else current
    sma_mid_val = sma_mid[-1] if sma_mid and sma_mid[-1] is not None else current
    sma_long_val = sma_long[-1] if sma_long and sma_long[-1] is not None else current
    
    sma_bullish = sma_short_val > sma_mid_val * 1.01 and sma_mid_val > sma_long_val * 1.005
    sma_bearish = sma_short_val < sma_mid_val * 0.99 and sma_mid_val < sma_long_val * 0.995
    sma_mixed = not sma_bullish and not sma_bearish
    
    # ADX
    adx_vals, plus_di_vals, minus_di_vals = adx(highs, lows, closes, 14)
    adx_val = adx_vals[-1] if adx_vals and adx_vals[-1] is not None else 15
    plus_di = plus_di_vals[-1] if plus_di_vals and plus_di_vals[-1] is not None else 25
    minus_di = minus_di_vals[-1] if minus_di_vals and minus_di_vals[-1] is not None else 25
    
    adx_strong = adx_val > 25
    adx_weak = adx_val < 20
    
    # 價格位置
    lookback = min(180, n)
    high_180 = max(highs[-lookback:])
    low_180 = min(lows[-lookback:])
    if high_180 > low_180:
        price_position = (current - low_180) / (high_180 - low_180) * 100
    else:
        price_position = 50
    
    # 波動率
    atr_vals = atr(highs, lows, closes, 14)
    atr_valid = [v for v in atr_vals[-20:] if v is not None] if atr_vals else []
    atr_current = atr_valid[-1] if atr_valid else current * 0.03
    atr_avg = sum(atr_valid) / len(atr_valid) if atr_valid else atr_current
    atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1
    is_volatile = atr_ratio > 1.5
    
    # 趨勢持續性
    direction_changes = 0
    for i in range(-20, 0):
        if i > -n and closes[i] > closes[i-1]:
            direction_changes += 1
        elif i > -n:
            direction_changes -= 1
    direction_consistency = abs(direction_changes) / 20 * 100
    
    # 計算 20 天價格範圍（用於盤整判斷）
    high_20d = max(highs[-20:])
    low_20d = min(lows[-20:])
    range_20d_pct = (high_20d - low_20d) / current * 100 if current > 0 else 0
    is_tight_range = range_20d_pct < 10  # 20 天範圍 < 10% 才是真正的盤整
    
    # 市況判斷（優先順序：趨勢 > 死貓反彈 > 高波動 > 盤整）
    
    # 上漲趨勢：ADX 強 + SMA 多頭 + 價格在高位
    if adx_strong and sma_bullish and price_position > 55 and plus_di > minus_di:
        regime = 'trending_up'
        strength = min(100, adx_val * 2 + direction_consistency * 0.3)
        confidence = 80
    
    # 下跌趨勢：ADX 強 + SMA 空頭 + 價格在低位
    elif adx_strong and sma_bearish and price_position < 45 and minus_di > plus_di:
        regime = 'trending_down'
        strength = min(100, adx_val * 2 + direction_consistency * 0.3)
        confidence = 80
    
    # 死貓反彈：SMA 空頭 + 價格極低 + 弱趨勢
    elif sma_bearish and price_position < 25 and adx_weak:
        regime = 'dead_cat_bounce'
        strength = 50
        confidence = 55
    
    # 高波動：ATR 極高 + 弱趨勢
    elif is_volatile and adx_weak:
        regime = 'volatile'
        strength = min(100, atr_ratio * 40)
        confidence = 60
    
    # 盤整：價格範圍窄 + 弱趨勢（必須同時滿足）
    elif is_tight_range and adx_weak:
        regime = 'ranging'
        strength = max(0, 50 - adx_val)
        confidence = 60
    
    # 寬幅波動（不是盤整也不是趨勢）
    elif not is_tight_range and adx_weak:
        regime = 'volatile'
        strength = min(80, range_20d_pct * 2)
        confidence = 50
    
    # 輕度趨勢（ADX 中等）
    elif sma_bullish and plus_di > minus_di:
        regime = 'trending_up'
        strength = min(70, adx_val * 1.5)
        confidence = 60
    elif sma_bearish and minus_di > plus_di:
        regime = 'trending_down'
        strength = min(70, adx_val * 1.5)
        confidence = 60
    
    # 預設：盤整
    else:
        regime = 'ranging'
        strength = max(0, 40 - adx_val)
        confidence = 40
    
    return {
        'regime': regime,
        'strength': round(strength, 1),
        'confidence': confidence,
    }


# ══════════════════════════════════════════════════════════════
# 市況自適應因子權重
# ══════════════════════════════════════════════════════════════

# 基礎因子權重
BASE_WEIGHTS = {
    # 趨勢類
    'trend': 1.0, 'structure': 1.2, 'fib_score': 0.8,
    # 動量類
    'rsi': 0.7, 'macd': 0.8, 'divergence': 0.9,
    # 成交量類
    'volume': 0.6, 'obv': 0.7,
    # 價格位置類
    'sr': 0.6, 'candle': 0.5,
    # 風險類
    'adx_penalty': 0.8, 'vol_state': 0.4,
    # 外部類
    'fear_greed': 0.7, 'funding': 0.5, 'macro_score': 0.8,
}

# 上漲專用因子權重
BULL_WEIGHTS = {
    # 趨勢類（提高）
    'trend': 1.5, 'structure': 1.5, 'fib_score': 1.0,
    # 動量類（提高）
    'rsi': 1.0, 'macd': 1.2, 'divergence': 0.8,
    # 成交量類（提高）
    'volume': 1.0, 'obv': 1.0,
    # 價格位置類
    'sr': 0.8, 'candle': 0.7,
    # 風險類（降低）
    'adx_penalty': 0.3, 'vol_state': 0.3,
    # 外部類
    'fear_greed': 0.5, 'funding': 0.3, 'macro_score': 0.6,
    # 新增上漲因子
    'ema_alignment': 1.5, 'breakout': 1.2, 'volume_momentum': 1.0,
    'rsi_health': 0.8, 'obv_trend': 0.8, 'pullback_depth': 1.0,
}

# 下跌專用因子權重
BEAR_WEIGHTS = {
    'trend': 1.5, 'structure': 1.5, 'fib_score': 0.8,
    'rsi': 0.8, 'macd': 1.2, 'divergence': 1.0,
    'volume': 0.8, 'obv': 0.8,
    'sr': 0.6, 'candle': 0.7,
    'adx_penalty': 0.5, 'vol_state': 0.3,
    'fear_greed': 0.8, 'funding': 0.5, 'macro_score': 0.8,
    # 上漲因子在下跌市場中權重降低
    'ema_alignment': 0.5, 'breakout': 0.3, 'volume_momentum': 0.5,
    'rsi_health': 0.3, 'obv_trend': 0.5, 'pullback_depth': 0.3,
}

# 盤整權重
# 盤整中：趨勢類降低，成交量類提高（確認突破需要量）
# 關鍵：盤整中只做「成交量確認的突破」
RANGING_WEIGHTS = {
    'trend': 0.5, 'structure': 0.5, 'fib_score': 1.2,
    'rsi': 1.2, 'macd': 0.6, 'divergence': 1.0,
    'volume': 1.5, 'obv': 1.5,  # 成交量類權重提高（確認突破）
    'sr': 1.2, 'candle': 0.8,
    'adx_penalty': 1.0, 'vol_state': 0.8,
    'fear_greed': 0.8, 'funding': 0.5, 'macro_score': 0.5,
    # 上漲因子在盤整中：突破和量價因子提高
    'ema_alignment': 0.5, 'breakout': 1.5, 'volume_momentum': 1.5,
    'rsi_health': 0.5, 'obv_trend': 1.0, 'pullback_depth': 0.8,
}

# 死貓反彈權重
DCB_WEIGHTS = {
    'trend': 2.0, 'structure': 2.0, 'fib_score': 0.5,
    'rsi': 0.3, 'macd': 0.5, 'divergence': 0.3,
    'volume': 0.5, 'obv': 0.5,
    'sr': 0.3, 'candle': 0.3,
    'adx_penalty': 0.3, 'vol_state': 0.3,
    'fear_greed': 0.3, 'funding': 0.3, 'macro_score': 0.5,
    'ema_alignment': 0.2, 'breakout': 0.1, 'volume_momentum': 0.2,
    'rsi_health': 0.1, 'obv_trend': 0.2, 'pullback_depth': 0.1,
}

# 高波動權重
VOLATILE_WEIGHTS = {
    'trend': 0.3, 'structure': 0.3, 'fib_score': 0.5,
    'rsi': 0.8, 'macd': 0.5, 'divergence': 0.8,
    'volume': 1.0, 'obv': 1.0,
    'sr': 0.8, 'candle': 0.5,
    'adx_penalty': 1.5, 'vol_state': 1.5,
    'fear_greed': 1.0, 'funding': 0.8, 'macro_score': 0.8,
    'ema_alignment': 0.2, 'breakout': 0.3, 'volume_momentum': 0.5,
    'rsi_health': 0.5, 'obv_trend': 0.5, 'pullback_depth': 0.3,
}

REGIME_WEIGHTS = {
    'trending_up': BULL_WEIGHTS,
    'trending_down': BEAR_WEIGHTS,
    'ranging': RANGING_WEIGHTS,
    'dead_cat_bounce': DCB_WEIGHTS,
    'volatile': VOLATILE_WEIGHTS,
}


# ══════════════════════════════════════════════════════════════
# 信號歷史與確認機制（波段版）
# ══════════════════════════════════════════════════════════════

class SignalHistory:
    def __init__(self, max_history=60):
        self.history = {}
        self.max_history = max_history
    
    def record(self, coin, signal, score, confidence, regime):
        if coin not in self.history:
            self.history[coin] = []
        self.history[coin].append({
            'signal': signal, 'score': score, 'confidence': confidence,
            'regime': regime, 'time': len(self.history[coin]),
        })
        if len(self.history[coin]) > self.max_history:
            self.history[coin] = self.history[coin][-self.max_history:]
    
    def get_confirmed_signal(self, coin, current_signal, current_score,
                              min_consecutive=2, lookback=20, adx_val=15, regime='ranging'):
        """
        波段版信號確認（v2 - 趨勢自適應）：
        
        核心邏輯：
        - 只確認 BUY/SELL 信號，NEUTRAL 直接通過
        - 強趨勢（ADX>25）：只需 1 次信號就確認
        - 正常趨勢（ADX 15-25）：連續 min_consecutive(2) 次同方向
        - 盤整/弱趨勢（ADX<15）：連續 3 次或 stability > 70%
        
        注意：歷史記錄中只計算非 NEUTRAL 信號的連續性
        """
        # NEUTRAL 信號不需要確認，直接通過
        if current_signal == 'NEUTRAL':
            return {'confirmed': True, 'signal': 'NEUTRAL', 'consecutive': 0, 
                    'stability': 0, 'adx_adaptive': False, 'effective_min': 0}
        
        if coin not in self.history or len(self.history[coin]) < 1:
            return {'confirmed': False, 'signal': current_signal, 'consecutive': 0, 
                    'stability': 0, 'adx_adaptive': False, 'effective_min': min_consecutive}
        
        # 根據趨勢強度調整確認門檻
        if adx_val > 25:
            effective_min = 1
            stability_threshold = 50
            adx_adaptive = True
        elif adx_val >= 15:
            effective_min = min_consecutive
            stability_threshold = 60
            adx_adaptive = False
        else:
            effective_min = 3
            stability_threshold = 70
            adx_adaptive = False
        
        recent = self.history[coin][-lookback:]
        
        # 判斷當前方向
        if current_score > 3:
            direction = 'long'
        elif current_score < -3:
            direction = 'short'
        else:
            # 分數太弱，不確認
            return {'confirmed': False, 'signal': current_signal, 'consecutive': 0,
                    'stability': 0, 'adx_adaptive': False, 'effective_min': effective_min}
        
        # 計算連續次數（只計算非 NEUTRAL 信號）
        consecutive = 0
        for h in reversed(recent):
            h_sig = h['signal']
            h_score = h['score']
            # 跳過 NEUTRAL 信號
            if h_sig == 'NEUTRAL':
                continue
            if direction == 'long' and h_score > 3:
                consecutive += 1
            elif direction == 'short' and h_score < -3:
                consecutive += 1
            else:
                break
        
        # 計算 stability（只計算非 NEUTRAL 信號）
        non_neutral = [h for h in recent if h['signal'] != 'NEUTRAL']
        if non_neutral:
            same_direction = sum(1 for h in non_neutral 
                                if (direction == 'long' and h['score'] > 3) or 
                                   (direction == 'short' and h['score'] < -3))
            stability = same_direction / len(non_neutral) * 100
        else:
            stability = 0
        
        # 確認條件（趨勢自適應）
        confirmed = (consecutive >= effective_min) or (stability > stability_threshold and consecutive >= 2)
        
        return {
            'confirmed': confirmed,
            'signal': current_signal if confirmed else 'NEUTRAL',
            'consecutive': consecutive,
            'stability': round(stability, 1),
            'adx_adaptive': adx_adaptive,
            'effective_min': effective_min,
        }


_signal_history = SignalHistory()


_signal_history = SignalHistory()


# ══════════════════════════════════════════════════════════════
# 過濾器（保留）
# ══════════════════════════════════════════════════════════════

def market_structure(highs, lows, closes, lookback=30):
    if len(highs) < lookback or len(closes) < lookback:
        return "NEUTRAL", 0
    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]
    mid = lookback // 2
    early_high = max(recent_highs[:mid])
    late_high = max(recent_highs[mid:])
    early_low = min(recent_lows[:mid])
    late_low = min(recent_lows[mid:])
    hh = late_high > early_high
    hl = late_low > early_low
    lh = late_high < early_high
    ll = late_low < early_low
    if hh and hl:
        strength = min(100, (late_high / early_high - 1) * 1000 + (late_low / early_low - 1) * 1000)
        return "BULLISH", round(strength, 1)
    elif lh and ll:
        strength = min(100, (early_high / late_high - 1) * 1000 + (early_low / late_low - 1) * 1000)
        return "BEARISH", round(strength, 1)
    else:
        return "NEUTRAL", 0


def is_dead_cat_bounce(current, highs, lows, closes):
    if len(closes) < 50:
        return False, "數據不足"
    sma20_vals = sma(closes, 20)
    sma50_vals = sma(closes, 50)
    if not sma20_vals or not sma50_vals:
        return False, "SMA 無效"
    sma20 = sma20_vals[-1]
    sma50 = sma50_vals[-1]
    if sma20 is None or sma50 is None:
        return False, "SMA 無效"
    if sma20 >= sma50:
        return False, "非空頭排列"
    high_180 = max(highs[-180:]) if len(highs) >= 180 else max(highs)
    low_180 = min(lows[-180:]) if len(lows) >= 180 else min(lows)
    if high_180 <= low_180:
        return False, "無波動"
    price_pct = (current - low_180) / (high_180 - low_180) * 100
    if price_pct > 20:
        return False, f"價格位置 {price_pct:.1f}%"
    recent_low = min(lows[-30:])
    if recent_low <= 0:
        return False, "最低價為 0"
    bounce_pct = (current / recent_low - 1) * 100
    if bounce_pct < 5 or bounce_pct > 40:
        return False, f"反彈 {bounce_pct:.1f}%"
    drop_pct = (1 - current / high_180) * 100
    if drop_pct < 30:
        return False, f"跌幅 {drop_pct:.1f}%"
    return True, f"死貓反彈(位置{price_pct:.0f}%,反彈{bounce_pct:.0f}%,跌幅{drop_pct:.0f}%)"


def adx_filter(adx_val, plus_di, minus_di):
    if adx_val is None or plus_di is None or minus_di is None:
        return 'none', 'neutral', 0
    if adx_val >= 30:
        trend, penalty = 'strong', 0
    elif adx_val >= 20:
        trend, penalty = 'moderate', -3
    else:
        trend, penalty = 'weak', -8
    if plus_di > minus_di:
        direction = 'bullish'
    elif minus_di > plus_di:
        direction = 'bearish'
    else:
        direction = 'neutral'
    return trend, direction, penalty


# ══════════════════════════════════════════════════════════════
# 主評分函數 v6
# ══════════════════════════════════════════════════════════════

def composite_score_v6(closes, highs, lows, vols, opens=None,
                       fear_greed=None, funding_rate=None,
                       btc_7d_change=None, macro_score=None,
                       coin_name=None, existing_positions=None,
                       decay_halflife=30,
                       use_confirmation=True, min_consecutive=2):
    """
    v6 評分系統 — 市況分類 + 上漲趨勢因子 + 信號確認
    """
    if len(closes) < 30:
        return {"score": 0, "signal": "N/A", "confidence": 0, "details": {}}
    if opens is None:
        opens = [closes[0]] + closes[:-1]
    
    d = {}
    current = closes[-1]
    
    # ── 步驟 1: 市況分類 ──
    market_regime = classify_market(closes, highs, lows, vols)
    regime = market_regime['regime']
    regime_weights = REGIME_WEIGHTS.get(regime, BASE_WEIGHTS)
    d['market_regime'] = regime
    d['regime_strength'] = market_regime['strength']
    d['regime_confidence'] = market_regime['confidence']
    
    # ── 步驟 2: 計算所有因子 ──
    
    # 趨勢類
    trend = trend_direction(closes)
    d["trend"] = 12 if trend == "BULLISH" else -12 if trend == "BEARISH" else 0
    
    struct, struct_strength = market_structure(highs, lows, closes)
    d["structure"] = 15 if struct == "BULLISH" else -15 if struct == "BEARISH" else 0
    
    fib_score, fib_level, fib_desc = fibonacci_position_score(current, highs, lows)
    d["fib_score"] = fib_score
    
    # 動量類
    rsi_v = rsi(closes, 14)
    rsi_val = rsi_v[-1] if rsi_v and rsi_v[-1] is not None else 50
    d["rsi"] = 8 if rsi_val < 30 else 2 if rsi_val < 45 else -8 if rsi_val > 70 else -2 if rsi_val > 55 else 0
    
    _, _, hist = macd(closes)
    d["macd"] = 0
    if hist and len(hist) >= 2 and hist[-1] is not None and hist[-2] is not None:
        if hist[-1] > 0 and hist[-1] > hist[-2]: d["macd"] = 8
        elif hist[-1] < 0 and hist[-1] < hist[-2]: d["macd"] = -8
        elif hist[-1] > 0: d["macd"] = 2
        elif hist[-1] < 0: d["macd"] = -2
    
    d["divergence"] = 0
    if rsi_v and len(rsi_v) >= 20:
        rsi_recent = [v for v in rsi_v[-10:] if v is not None]
        rsi_earlier = [v for v in rsi_v[-20:-10] if v is not None]
        if rsi_recent and rsi_earlier:
            if max(highs[-10:]) > max(highs[-20:-10]) and max(rsi_recent) < max(rsi_earlier):
                d["divergence"] = -8
            if min(lows[-10:]) < min(lows[-20:-10]) and min(rsi_recent) > min(rsi_earlier):
                d["divergence"] = 8
    
    # 成交量類
    avg_vol = sum(vols[-20:]) / 20
    d["volume"] = 0
    if len(closes) >= 2:
        pu, vu = closes[-1] > closes[-2], vols[-1] > avg_vol
        d["volume"] = 6 if pu and vu else 2 if pu and not vu else -6 if not pu and vu else -2
    
    obv_vals = obv(closes, vols)
    d["obv"] = obv_score(obv_vals, closes, vols)
    
    # 價格位置類
    res, sup = support_resistance(highs, lows)
    d["sr"] = 0
    if sup[0] > 0 and res[0] > 0:
        ds = (current - sup[0]) / current * 100
        dr = (res[0] - current) / current * 100
        d["sr"] = 8 if ds < 3 else 4 if ds < 5 else -8 if dr < 3 else -4 if dr < 5 else 0
    
    patterns = candle_pattern(opens, highs, lows, closes)
    d["candle"] = (sum(4 for p in patterns if p in ["HAMMER","BULLISH_ENGULFING","THREE_SOLDIERS"]) 
                   - sum(4 for p in patterns if p in ["SHOOTING_STAR","BEARISH_ENGULFING","THREE_CROWS"]) 
                   + sum(2 for p in patterns if p == "DOJI"))
    
    # 風險類
    adx_vals, plus_di_vals, minus_di_vals = adx(highs, lows, closes, 14)
    adx_val = adx_vals[-1] if adx_vals else None
    plus_di = plus_di_vals[-1] if plus_di_vals else None
    minus_di = minus_di_vals[-1] if minus_di_vals else None
    adx_trend, adx_direction, adx_penalty = adx_filter(adx_val, plus_di, minus_di)
    d["adx_penalty"] = adx_penalty
    
    atr_v = atr(highs, lows, closes, 14)
    d["vol_state"] = 0
    if atr_v:
        atr_valid = [v for v in atr_v[-20:] if v is not None]
        if atr_valid and atr_v[-1] is not None:
            ac = atr_v[-1]
            aa = sum(atr_valid) / len(atr_valid)
            d["vol_state"] = -4 if ac > aa * 1.5 else 4 if ac < aa * 0.5 else 0
    
    # 外部類
    d["fear_greed"] = 0
    if fear_greed is not None:
        d["fear_greed"] = 6 if fear_greed < 20 else 3 if fear_greed < 40 else -6 if fear_greed > 80 else -3 if fear_greed > 60 else 0
    
    d["funding"] = 0
    if funding_rate is not None:
        d["funding"] = -4 if funding_rate > 0.1 else -2 if funding_rate > 0.05 else 4 if funding_rate < -0.1 else 2 if funding_rate < -0.05 else 0
    
    if macro_score is not None:
        d["macro_score"] = macro_score
    
    # 死貓反彈檢測
    is_dcb, dcb_reason = is_dead_cat_bounce(current, highs, lows, closes)
    d["is_dead_cat_bounce"] = is_dcb
    d["dcb_reason"] = dcb_reason
    
    # ── 新增：上漲趨勢因子 ──
    ema_score, ema_desc = ema_alignment_score(closes)
    d["ema_alignment"] = ema_score
    
    bo_score, bo_desc = breakout_score(closes, highs)
    d["breakout"] = bo_score
    
    vm_score, vm_desc = volume_momentum_score(closes, vols)
    d["volume_momentum"] = vm_score
    
    rh_score, rh_desc = rsi_health_score(rsi_val)
    d["rsi_health"] = rh_score
    
    ot_score, ot_desc = obv_trend_score(obv_vals)
    d["obv_trend"] = ot_score
    
    pb_score, pb_desc = pullback_depth_score(closes, highs, lows)
    d["pullback_depth"] = pb_score
    
    # ── 步驟 3: 綜合評分（使用市況自適應權重）──
    _meta_keys = {"is_dead_cat_bounce", "dcb_reason", "structure_type", "fib_level", "fib_desc",
                  "adx_trend", "adx_direction", "ema20", "market_regime", "regime_strength", "regime_confidence"}
    _score_keys = [k for k in d if k not in _meta_keys and isinstance(d[k], (int, float))]
    
    total = sum(d[k] * regime_weights.get(k, 1.0) for k in _score_keys)
    max_possible = sum(abs(regime_weights.get(k, 1.0)) * 15 for k in _score_keys)
    total = max(-100, min(100, total / max_possible * 100)) if max_possible > 0 else 0
    
    # ── 步驟 4: 信號生成（波段版 - 高門檻 + 趨勢自適應）──
    # 
    # 波段交易核心原則：
    # 1. 高門檻：避免頻繁交易，只捕捉明確的波段機會
    # 2. 趨勢順勢：強趨勢中降低門檻（趨勢明確），盤整中提高門檻（避免假突破）
    # 3. 信號確認：盤整中需要連續確認，趨勢中不需要
    #
    # 基礎門檻（波段交易用較高門檻）
    _base_threshold = 12  # 從 3 提高到 12，減少頻繁交易
    
    # 波動率調整
    _atr_val = atr_v[-1] if (atr_v and len(atr_v) > 0 and atr_v[-1] is not None) else current * 0.03
    _atr_ratio = _atr_val / current if current > 0 else 0.03
    
    if _atr_ratio > 0.05:  # 高波動，略降門檻（但還是高）
        _fee_threshold = max(8, _base_threshold - 4)
    elif _atr_ratio < 0.02:  # 低波動，提高門檻
        _fee_threshold = min(20, _base_threshold + 4)
    else:
        _fee_threshold = _base_threshold
    
    # 趨勢強度調整
    _adx_val = adx_val if adx_val is not None else 15
    if _adx_val > 30:  # 強趨勢，降低門檻（趨勢明確時不猶豫）
        _fee_threshold = max(6, _fee_threshold - 6)
    elif _adx_val > 25:
        _fee_threshold = max(8, _fee_threshold - 4)
    elif _adx_val < 15:  # 弱趨勢/盤整，提高門檻（避免假突破）
        _fee_threshold = min(20, _fee_threshold + 6)
    
    _structure_bullish = struct == "BULLISH"
    _structure_bearish = struct == "BEARISH"
    _structure_neutral = struct == "NEUTRAL"
    _trend_bullish = trend == "BULLISH"
    _trend_bearish = trend == "BEARISH"
    
    _is_bullish_aligned = (_structure_bullish and _trend_bullish) or (_structure_neutral and _trend_bullish)
    _is_bearish_aligned = (_structure_bearish and _trend_bearish) or (_structure_neutral and _trend_bearish)
    _is_contrarian = (_structure_bullish and _trend_bearish) or (_structure_bearish and _trend_bullish)
    
    # 做空增強
    _rsi_overbought = rsi_val > 70
    _rsi_oversold = rsi_val < 30
    _funding_high = funding_rate is not None and funding_rate > 0.08
    _funding_low = funding_rate is not None and funding_rate < -0.08
    _bearish_boost = (_rsi_overbought or _funding_high) and total < 0
    _bullish_boost = (_rsi_oversold or _funding_low) and total > 0
    
    # 強趨勢過濾
    _strong_trend_filter = False
    if regime == 'trending_up' and _adx_val > 25 and _is_bullish_aligned:
        _strong_trend_filter = True
    elif regime == 'trending_down' and _adx_val > 25 and _is_bearish_aligned:
        _strong_trend_filter = True
    
    # ── 信號強度分級（統一使用動態門檻）──
    _strong_threshold = int(_fee_threshold * 1.5)
    
    if regime == 'dead_cat_bounce':
        if total <= -_fee_threshold:
            sig = "STRONG_SELL" if total <= -_strong_threshold else "SELL"
        else:
            sig = "NEUTRAL"
        d["filter_reason"] = "死貓反彈市況"
    
    elif regime == 'trending_up':
        if _strong_trend_filter:
            if total >= _fee_threshold:
                sig = "STRONG_BUY" if total >= _strong_threshold else "BUY"
            else:
                sig = "NEUTRAL"
            d["filter_reason"] = "強上漲趨勢，只做多"
        else:
            if _is_bullish_aligned and total >= _fee_threshold:
                sig = "STRONG_BUY" if total >= _strong_threshold else "BUY"
            elif _is_bearish_aligned and total <= -_fee_threshold:
                sig = "STRONG_SELL" if total <= -_strong_threshold else "SELL"
            else:
                sig = "NEUTRAL"
    
    elif regime == 'trending_down':
        if _is_contrarian:
            sig = "NEUTRAL"
            d["filter_reason"] = "結構與趨勢矛盾"
        elif _strong_trend_filter:
            if total <= -_fee_threshold:
                sig = "STRONG_SELL" if total <= -_strong_threshold else "SELL"
            else:
                sig = "NEUTRAL"
            d["filter_reason"] = "強下跌趨勢，只做空"
        else:
            if _is_bearish_aligned and total <= -_fee_threshold:
                sig = "STRONG_SELL" if total <= -_strong_threshold else "SELL"
            elif _is_bullish_aligned and total >= _fee_threshold:
                sig = "STRONG_BUY" if total >= _strong_threshold else "BUY"
            else:
                sig = "NEUTRAL"
    
    elif regime == 'volatile':
        # 高波動：只接受強信號（1.5x 門檻）
        if _is_bullish_aligned and total >= _strong_threshold:
            sig = "STRONG_BUY"
        elif _is_bearish_aligned and total <= -_strong_threshold:
            sig = "STRONG_SELL"
        else:
            sig = "NEUTRAL"
        d["filter_reason"] = "高波動市況，只接受強信號"
    
    elif regime == 'ranging':
        # 盤整：需要成交量確認 + 高門檻
        vol_confirmed = d.get('volume_momentum', 0) > 0 or d.get('obv_trend', 0) > 0
        if abs(total) < _fee_threshold:
            sig = "NEUTRAL"
            d["filter_reason"] = f"盤整市況，信號太弱({total:.1f})"
        elif not vol_confirmed:
            sig = "NEUTRAL"
            d["filter_reason"] = "盤整市況，成交量未確認"
        elif _is_bullish_aligned and total >= _fee_threshold:
            sig = "STRONG_BUY" if total >= _strong_threshold else "BUY"
        elif _is_bearish_aligned and total <= -_fee_threshold:
            sig = "STRONG_SELL" if total <= -_strong_threshold else "SELL"
        else:
            sig = "NEUTRAL"
            d["filter_reason"] = "盤整市況，無明確突破"
    
    else:
        sig = "NEUTRAL"
        d["filter_reason"] = f"未知市況({regime})"
    
    # ── 步驟 5: 信號確認機制（趨勢自適應版）──        d["filter_reason"] = f"未知市況({regime})"
    
    # ── 步驟 5: 信號確認機制（趨勢自適應版）──
    if use_confirmation and coin_name:
        _signal_history.record(coin_name, sig, total, 0, regime)
        _adx_for_confirmation = adx_val if adx_val is not None else 15
        confirmation = _signal_history.get_confirmed_signal(
            coin_name, sig, total,
            min_consecutive=min_consecutive,
            lookback=20,
            adx_val=_adx_for_confirmation,
            regime=regime
        )
        d['signal_confirmed'] = confirmation['confirmed']
        d['signal_consecutive'] = confirmation['consecutive']
        d['signal_stability'] = confirmation['stability']
        d['signal_adx_adaptive'] = confirmation['adx_adaptive']
        
        if not confirmation['confirmed'] and sig != 'NEUTRAL':
            sig = 'NEUTRAL'
            d['filter_reason'] = f"信號未確認（連續 {confirmation['consecutive']}/{confirmation['effective_min']} 次, 穩定度 {confirmation['stability']}%）"
    
    # ── 步驟 6: 信心度計算 ──
    pos_weight = sum(regime_weights.get(k, 1.0) for k in _score_keys if d[k] > 0)
    neg_weight = sum(regime_weights.get(k, 1.0) for k in _score_keys if d[k] < 0)
    total_weight = sum(regime_weights.get(k, 1.0) for k in _score_keys)
    
    if total_weight > 0:
        agreement = abs(pos_weight - neg_weight) / total_weight
        conf = min(95, max(20, int(agreement * 100)))
    else:
        conf = 50
    
    # 市況加成
    if regime in ('trending_up', 'trending_down') and market_regime['strength'] > 60:
        conf = min(95, int(conf * 1.2))
    
    if d.get('signal_confirmed'):
        conf = min(95, int(conf * 1.15))
    
    return {
        "score": round(total, 1),
        "signal": sig,
        "confidence": conf,
        "details": d,
        "patterns": patterns,
        "rsi": rsi_val,
        "trend": trend,
        "market_structure": struct,
        "fib_level": fib_level,
        "fib_desc": fib_desc,
        "adx": adx_val,
        "adx_trend": adx_trend,
        "adx_direction": adx_direction,
        "is_dead_cat_bounce": is_dcb,
        "dcb_reason": dcb_reason,
        "macro_score": macro_score,
        "market_regime": regime,
        "regime_strength": market_regime['strength'],
        "decay_halflife": decay_halflife,
    }


def get_signal_summary(result):
    """信號摘要"""
    s = []
    d = result.get("details", {})
    
    regime = d.get('market_regime', 'unknown')
    regime_names = {
        'trending_up': '📈上漲趨勢',
        'trending_down': '📉下跌趨勢',
        'ranging': '↔️盤整',
        'volatile': '⚡高波動',
        'dead_cat_bounce': '⚠️死貓反彈',
    }
    s.append(regime_names.get(regime, regime))
    
    if d.get("trend", 0) > 0: s.append("多頭趨勢")
    elif d.get("trend", 0) < 0: s.append("空頭趨勢")
    
    if d.get("macd", 0) > 0: s.append("MACD多頭")
    elif d.get("macd", 0) < 0: s.append("MACD空頭")
    
    if d.get("divergence", 0) > 0: s.append("底背離")
    elif d.get("divergence", 0) < 0: s.append("頂背離")
    
    if d.get("obv", 0) > 0: s.append("OBV流入")
    elif d.get("obv", 0) < 0: s.append("OBV流出")
    
    if d.get("structure", 0) > 0: s.append("多頭結構")
    elif d.get("structure", 0) < 0: s.append("空頭結構")
    
    if d.get("adx_trend") == "strong": s.append("ADX強趨勢")
    elif d.get("adx_trend") == "weak": s.append("ADX弱趨勢")
    
    if d.get("is_dead_cat_bounce"): s.append("⚠️死貓反彈")
    
    if d.get("signal_confirmed"): s.append("✅信號確認")
    
    # 上漲因子摘要
    if d.get("ema_alignment", 0) > 5: s.append("均線多頭排列")
    elif d.get("ema_alignment", 0) < -5: s.append("均線空頭排列")
    
    if d.get("breakout", 0) > 5: s.append("突破信號")
    
    return s


# ══════════════════════════════════════════════════════════════
# 向後相容
# ══════════════════════════════════════════════════════════════

def composite_score_v5(*args, **kwargs):
    kwargs.pop('exchange_netflow', None)
    kwargs.pop('dxy', None)
    kwargs.pop('btc_d', None)
    return composite_score_v6(*args, **kwargs)

def composite_score_v4(*args, **kwargs):
    kwargs.pop('exchange_netflow', None)
    kwargs.pop('dxy', None)
    kwargs.pop('btc_d', None)
    return composite_score_v6(*args, **kwargs)


if __name__ == "__main__":
    from backtester_v3 import get_binance_klines
    from macro_data import MacroData, macro_score
    
    print("Testing scoring_v6 with bull market factors...")
    
    macro = MacroData()
    mdata = macro.get_all()
    ms, _ = macro_score(mdata)
    
    for coin in ["BTC", "ETH", "SOL", "DOGE"]:
        data = get_binance_klines(coin + "USDT", limit=180)
        if data:
            closes = [d['close'] for d in data]
            highs = [d['high'] for d in data]
            lows = [d['low'] for d in data]
            vols = [d['volume'] for d in data]
            opens = [d['open'] for d in data]
            
            r = composite_score_v6(closes, highs, lows, vols, opens,
                                   fear_greed=mdata['fear_greed']['value'],
                                   macro_score=ms,
                                   coin_name=coin,
                                   use_confirmation=False)
            
            print(f"\n{coin}: {r['signal']} (score={r['score']}, conf={r['confidence']}%)")
            print(f"  市況: {r.get('market_regime')} (強度: {r.get('regime_strength')})")
            print(f"  因子: {', '.join(get_signal_summary(r)[:8])}")
            
            # 顯示上漲因子
            d = r['details']
            bull_factors = []
            for k in ['ema_alignment', 'breakout', 'volume_momentum', 'rsi_health', 'obv_trend', 'pullback_depth']:
                v = d.get(k, 0)
                if v != 0:
                    bull_factors.append(f"{k}={v:+.1f}")
            if bull_factors:
                print(f"  上漲因子: {', '.join(bull_factors)}")
    
    print("\nDone.")
