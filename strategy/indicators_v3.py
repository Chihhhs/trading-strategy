
"""
indicators_v3.py - 專業級技術指標函式庫
位置: ~/.hermes/scripts/trading_lib/
更新：加入費波那契回撤、OBV
"""
import math

# ══════════════════════════════════════════════════════════════
# 基礎指標
# ══════════════════════════════════════════════════════════════

def sma(data, n):
    if len(data) < n: return [None] * len(data)
    result = [None] * (n - 1)
    for i in range(n - 1, len(data)):
        result.append(sum(data[i-n+1:i+1]) / n)
    return result

def ema(data, n):
    if len(data) < n: return [None] * len(data)
    k = 2 / (n + 1)
    result = [None] * (n - 1)
    val = sum(data[:n]) / n
    result.append(val)
    for i in range(n, len(data)):
        val = data[i] * k + val * (1 - k)
        result.append(val)
    return result

def rsi(data, n=14):
    if len(data) < n + 1: return [None] * len(data)
    result = [None] * n
    gains, losses = [], []
    for i in range(1, len(data)):
        diff = data[i] - data[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    if len(gains) < n: return [None] * len(data)
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    if avg_loss == 0: result.append(100)
    else:
        rs = avg_gain / avg_loss
        result.append(100 - 100 / (1 + rs))
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n-1) + gains[i]) / n
        avg_loss = (avg_loss * (n-1) + losses[i]) / n
        if avg_loss == 0: result.append(100)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
    while len(result) < len(data): result.append(result[-1] if result else None)
    return result

def obv(closes, vols):
    """
    計算 OBV（On-Balance Volume 能量潮）
    返回: obv 列表（與 closes 等長）
    
    邏輯：
    - 收盤上漲 → 加上成交量
    - 收盤下跌 → 減去成交量
    - 收盤持平 → 不變
    """
    if len(closes) < 2 or len(vols) < 2:
        return [0] * len(closes)
    
    result = [vols[0]]  # 第一個值用當日成交量
    for i in range(1, len(closes)):
        if i >= len(vols):
            result.append(result[-1])
        elif closes[i] > closes[i-1]:
            result.append(result[-1] + vols[i])
        elif closes[i] < closes[i-1]:
            result.append(result[-1] - vols[i])
        else:
            result.append(result[-1])
    return result

def obv_score(obv_vals, closes, vols, lookback=20):
    """
    OBV 評分（改進版）
    返回: -10 到 +10 的分數
    
    邏輯：
    - OBV 上升 + 價格上升 + 成交量增加 = 健康上漲（+10）
    - OBV 下降 + 價格下降 + 成交量增加 = 健康下跌（-10）
    - OBV 上升 + 價格上升 + 成交量減少 = 上漲無力（+3）
    - OBV 下降 + 價格下降 + 成交量減少 = 下跌無力（-3）
    - OBV 上升 + 價格下降 = 可能見底（+5）
    - OBV 下降 + 價格上升 = 可能見頂（-5）
    """
    if len(obv_vals) < lookback or len(closes) < lookback or len(vols) < lookback:
        return 0
    
    # OBV 趨勢
    obv_sma_short = sum(obv_vals[-5:]) / 5
    obv_sma_long = sum(obv_vals[-lookback:]) / lookback
    obv_rising = obv_sma_short > obv_sma_long * 1.02
    obv_falling = obv_sma_short < obv_sma_long * 0.98
    
    # 價格趨勢
    price_rising = closes[-1] > closes[-5]
    price_falling = closes[-1] < closes[-5]
    
    # 成交量趨勢
    vol_sma_short = sum(vols[-5:]) / 5
    vol_sma_long = sum(vols[-lookback:]) / lookback
    vol_increasing = vol_sma_short > vol_sma_long * 1.1
    vol_decreasing = vol_sma_short < vol_sma_long * 0.9
    
    if obv_rising and price_rising:
        if vol_increasing:
            return 10  # 量價配合，健康上漲
        elif vol_decreasing:
            return 3  # 上漲但縮量，無力
        else:
            return 7  # 上漲，成交量正常
    elif obv_falling and price_falling:
        if vol_increasing:
            return -10  # 量價配合，健康下跌
        elif vol_decreasing:
            return -3  # 下跌但縮量，無力
        else:
            return -7  # 下跌，成交量正常
    elif obv_rising and price_falling:
        return 5  # OBV 上升但價格下跌，可能見底
    elif obv_falling and price_rising:
        return -5  # OBV 下降但價格上升，可能見頂
    else:
        return 0  # 中性

def atr(highs, lows, closes, n=14):
    if len(closes) < 1: return []
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sma(trs, n)


def adx(highs, lows, closes, n=14):
    """
    計算 ADX（Average Directional Index）
    返回: (adx_vals, plus_di_vals, minus_di_vals) — 全部與 closes 等長
    
    ADX > 25 = 強趨勢
    ADX < 20 = 無趨勢/盤整
    +DI > -DI = 多頭主導
    -DI > +DI = 空頭主導
    """
    length = len(closes)
    if length < n + 1:
        return [None]*length, [None]*length, [None]*length
    
    # 計算 +DM, -DM, TR（從 index 1 開始）
    plus_dm = [0.0] * length
    minus_dm = [0.0] * length
    tr = [0.0] * length
    tr[0] = highs[0] - lows[0]
    
    for i in range(1, length):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
    
    # Wilder 平滑：前 n 期 sum，之後用遞推
    def wilder_smooth(vals, n):
        result = [None] * length
        # 前 n 期（index 0..n-1）設為 None
        s = sum(vals[1:n+1])  # index 1 到 n
        result[n] = s
        for i in range(n+1, length):
            result[i] = result[i-1] - result[i-1]/n + vals[i]
        return result
    
    smooth_tr = wilder_smooth(tr, n)
    smooth_pdm = wilder_smooth(plus_dm, n)
    smooth_mdm = wilder_smooth(minus_dm, n)
    
    # 計算 +DI, -DI, DX
    plus_di_vals = [None] * length
    minus_di_vals = [None] * length
    dx_vals = [None] * length
    
    for i in range(n, length):
        if smooth_tr[i] is None or smooth_tr[i] == 0:
            continue
        pdi = smooth_pdm[i] / smooth_tr[i] * 100 if smooth_pdm[i] is not None else None
        mdi = smooth_mdm[i] / smooth_tr[i] * 100 if smooth_mdm[i] is not None else None
        plus_di_vals[i] = pdi
        minus_di_vals[i] = mdi
        if pdi is not None and mdi is not None and (pdi + mdi) > 0:
            dx_vals[i] = abs(pdi - mdi) / (pdi + mdi) * 100
    
    # 計算 ADX = DX 的 n 期 Wilder 平滑
    adx_vals = [None] * length
    # 找第一個有效 DX
    first_dx = None
    for i in range(n, length):
        if dx_vals[i] is not None:
            first_dx = i
            break
    
    if first_dx is None:
        return adx_vals, plus_di_vals, minus_di_vals
    
    # ADX 起始點 = first_dx + n - 1（需要 n 個 DX 值）
    adx_start = first_dx + n - 1
    if adx_start >= length:
        return adx_vals, plus_di_vals, minus_di_vals
    
    # 前 n 個 DX 平均作為第一個 ADX
    dx_window = []
    for i in range(first_dx, min(first_dx + n, length)):
        if dx_vals[i] is not None:
            dx_window.append(dx_vals[i])
    
    if len(dx_window) < n:
        return adx_vals, plus_di_vals, minus_di_vals
    
    adx_vals[adx_start] = sum(dx_window) / n
    
    # 之後用 Wilder 平滑
    for i in range(adx_start + 1, length):
        if dx_vals[i] is not None:
            adx_vals[i] = (adx_vals[i-1] * (n-1) + dx_vals[i]) / n
    
    return adx_vals, plus_di_vals, minus_di_vals

def macd(data, fast=12, slow=26, signal=9):
    ema_fast = ema(data, fast)
    ema_slow = ema(data, slow)
    macd_line = [None if ema_fast[i] is None or ema_slow[i] is None else ema_fast[i] - ema_slow[i] for i in range(len(data))]
    valid = [v for v in macd_line if v is not None]
    sig = ema(valid, signal)
    signal_line, si = [], 0
    for v in macd_line:
        if v is None: signal_line.append(None)
        elif si < len(sig): signal_line.append(sig[si]); si += 1
        else: signal_line.append(None)
    histogram = [None if macd_line[i] is None or signal_line[i] is None else macd_line[i] - signal_line[i] for i in range(len(data))]
    return macd_line, signal_line, histogram

def bollinger(data, n=20, mult=2):
    sma_vals = sma(data, n)
    upper, lower = [], []
    for i in range(len(data)):
        if sma_vals[i] is None: upper.append(None); lower.append(None)
        else:
            window = data[i-n+1:i+1]
            mean = sma_vals[i]
            std = (sum((x-mean)**2 for x in window)/n)**0.5
            upper.append(mean + mult*std)
            lower.append(mean - mult*std)
    return sma_vals, upper, lower

def support_resistance(highs, lows, period=20):
    return sorted(highs[-period:], reverse=True)[:3], sorted(lows[-period:])[:3]

def trend_direction(closes, period=20):
    """長期趨勢：價格 vs EMA20"""
    if len(closes) < period: return 'NEUTRAL'
    ema_val = ema(closes, period)
    if ema_val[-1] is None: return 'NEUTRAL'
    if closes[-1] > ema_val[-1] * 1.02: return 'BULLISH'
    if closes[-1] < ema_val[-1] * 0.98: return 'BEARISH'
    return 'NEUTRAL'


def short_term_trend(closes, fast=10, slow=20):
    """
    短期趨勢：EMA10 vs EMA20 交叉
    比單一 EMA20 快 5-10 天反應反轉
    
    返回: 'BULLISH' / 'BEARISH' / 'NEUTRAL'
    信號:
    - EMA10 上穿 EMA20 = 短期多頭（黃金交叉）
    - EMA10 下穿 EMA20 = 短期空頭（死亡交叉）
    - EMA10 在 EMA20 附近 = 盤整
    """
    if len(closes) < slow: return 'NEUTRAL'
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    if ema_fast[-1] is None or ema_slow[-1] is None: return 'NEUTRAL'
    
    # 當前關係
    curr_above = ema_fast[-1] > ema_slow[-1]
    # 5 天前的關係（判斷是否剛交叉）
    if len(ema_fast) >= 5 and ema_fast[-5] is not None and ema_slow[-5] is not None:
        prev_above = ema_fast[-5] > ema_slow[-5]
    else:
        prev_above = curr_above
    
    # 交叉偵測
    if curr_above and not prev_above:
        return 'BULLISH'  # 黃金交叉
    elif not curr_above and prev_above:
        return 'BEARISH'  # 死亡交叉
    elif curr_above:
        return 'BULLISH'  # 維持多頭
    elif not curr_above:
        return 'BEARISH'  # 維持空頭
    return 'NEUTRAL'


def trend_alignment(closes):
    """
    綜合趨勢判斷：長期 + 短期
    返回: (long_trend, short_trend, alignment)
    alignment: 'ALIGNED' / 'CONFLICTING' / 'NEUTRAL'
    """
    long_trend = trend_direction(closes)
    short_trend = short_term_trend(closes)
    
    if long_trend == short_trend:
        alignment = 'ALIGNED'
    elif long_trend == 'NEUTRAL' or short_trend == 'NEUTRAL':
        alignment = 'NEUTRAL'
    else:
        alignment = 'CONFLICTING'
    
    return long_trend, short_trend, alignment

def candle_pattern(opens, highs, lows, closes):
    if len(closes) < 3: return []
    patterns = []
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    body = abs(c - o)
    upper_shadow = h - max(c, o)
    lower_shadow = min(c, o) - l
    total_range = h - l
    if total_range == 0: return patterns
    if body / total_range < 0.1: patterns.append("DOJI")
    if lower_shadow > body * 2 and upper_shadow < body * 0.5: patterns.append("HAMMER")
    if upper_shadow > body * 2 and lower_shadow < body * 0.5: patterns.append("SHOOTING_STAR")
    if len(closes) >= 2:
        po, pc = opens[-2], closes[-2]
        if pc < po and c > o and o <= pc and c >= po: patterns.append("BULLISH_ENGULFING")
        elif pc > po and c < o and o >= pc and c <= po: patterns.append("BEARISH_ENGULFING")
    if len(closes) >= 3:
        if all(closes[-i] > opens[-i] for i in range(1, 4)): patterns.append("THREE_SOLDIERS")
        elif all(closes[-i] < opens[-i] for i in range(1, 4)): patterns.append("THREE_CROWS")
    return patterns

def trend_strength_score(closes, highs, lows):
    if len(closes) < 20: return 50
    ema20_val = ema(closes, 20)
    if ema20_val[-1] is None: return 50
    score = 50
    if closes[-1] > ema20_val[-1]: score += 15
    else: score -= 15
    up_count = sum(1 for i in range(-10, 0) if closes[i] > closes[i-1])
    if up_count >= 7: score += 15
    elif up_count <= 3: score -= 15
    recent_high = max(highs[-10:])
    recent_low = min(lows[-10:])
    if recent_high > recent_low:
        pullback = (recent_high - closes[-1]) / (recent_high - recent_low)
        if 0.3 < pullback < 0.6: score += 10
        elif pullback > 0.8: score -= 10
    return max(0, min(100, score))

# ══════════════════════════════════════════════════════════════
# 專業指標
# ══════════════════════════════════════════════════════════════

def volume_profile(highs, lows, closes, vols, num_bins=20):
    if len(closes) < 20: return None
    price_min = min(lows)
    price_max = max(highs)
    bin_size = (price_max - price_min) / num_bins
    if bin_size == 0: return None
    volume_by_price = {}
    for i in range(len(closes)):
        low = lows[i]
        high = highs[i]
        vol = vols[i]
        low_bin = int((low - price_min) / bin_size)
        high_bin = int((high - price_min) / bin_size)
        for b in range(low_bin, min(high_bin + 1, num_bins)):
            price_level = price_min + b * bin_size
            volume_by_price[price_level] = volume_by_price.get(price_level, 0) + vol / (high_bin - low_bin + 1)
    if not volume_by_price: return None
    poc = max(volume_by_price, key=volume_by_price.get)
    total_volume = sum(volume_by_price.values())
    target_volume = total_volume * 0.7
    volume_sorted = sorted(volume_by_price.items(), key=lambda x: x[1], reverse=True)
    accumulated = 0
    va_prices = []
    for price, vol in volume_sorted:
        accumulated += vol
        va_prices.append(price)
        if accumulated >= target_volume: break
    va_high = max(va_prices)
    va_low = min(va_prices)
    avg_volume = total_volume / len(volume_by_price)
    hvn = sorted([p for p, v in volume_by_price.items() if v > avg_volume * 1.5])[:5]
    lvn = sorted([p for p, v in volume_by_price.items() if v < avg_volume * 0.5])[:5]
    return {"poc": poc, "va_high": va_high, "va_low": va_low, "hvn": hvn, "lvn": lvn}

def anchored_vwap(highs, lows, closes, vols, anchor_idx=0):
    if len(closes) < 2 or anchor_idx >= len(closes): return None
    cum_pv = 0
    cum_v = 0
    result = [None] * len(closes)
    for i in range(anchor_idx, len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        cum_pv += tp * vols[i]
        cum_v += vols[i]
        result[i] = cum_pv / cum_v if cum_v > 0 else None
    return result

def liquidity_sweep(highs, lows, closes, lookback=20):
    if len(closes) < lookback: return 0
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    current = closes[-1]
    if highs[-1] > recent_high * 0.998 and current < highs[-1] * 0.995: return -1
    if lows[-1] < recent_low * 1.002 and current > lows[-1] * 1.005: return 1
    return 0

def order_flow_delta(closes, highs, lows, vols, lookback=10):
    if len(closes) < 2: return 0
    total_delta = 0
    for i in range(-min(lookback, len(closes)), 0):
        h, l, c, v = highs[i], lows[i], closes[i], vols[i]
        if h == l: continue
        position = (c - l) / (h - l)
        delta = (position - 0.5) * 2 * v
        total_delta += delta
    return total_delta

def order_flow_imbalance(closes, highs, lows, lookback=10):
    if len(closes) < lookback: return 0
    bullish = bearish = 0
    for i in range(-min(lookback, len(closes)), 0):
        h, l, c = highs[i], lows[i], closes[i]
        if h == l: continue
        position = (c - l) / (h - l)
        if position > 0.6: bullish += 1
        elif position < 0.4: bearish += 1
    if bullish > bearish * 1.5: return 1
    if bearish > bullish * 1.5: return -1
    return 0

def calculate_tp_sl(entry, atr_val, direction, risk_pct=0.02, rr_ratio=2.0):
    sl_distance = entry * risk_pct
    tp_distance = sl_distance * rr_ratio
    if direction == "long":
        return round(entry + tp_distance, 8), round(entry - sl_distance, 8)
    else:
        return round(entry - tp_distance, 8), round(entry + sl_distance, 8)


# ══════════════════════════════════════════════════════════════
# 費波那契回撤
# ══════════════════════════════════════════════════════════════

def fibonacci_retracement(high, low):
    """計算費波那契回撤位"""
    diff = high - low
    return {
        23.6: round(high - diff * 0.236, 8),
        38.2: round(high - diff * 0.382, 8),
        50.0: round(high - diff * 0.500, 8),
        61.8: round(high - diff * 0.618, 8),
        78.6: round(high - diff * 0.786, 8),
    }


def fibonacci_position_score(current, highs, lows, lookback=30):
    """
    判斷價格在費波那契回撤位的位置
    返回: (score, nearest_level, description)
    
    邏輯：
    - 上升趨勢中，價格在 38.2%/50% 回撤位附近 = 最佳入場（+15）
    - 上升趨勢中，價格突破前高（>23.6% 位）= 延續信號（+8）
    - 下降趨勢中，價格在 38.2%/50% 反彈位附近 = 最佳做空（-15）
    - 下降趨勢中，價格跌破前低（<61.8% 位）= 延續信號（-8）
    """
    if len(highs) < lookback or len(lows) < lookback:
        return 0, None, "數據不足"
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    if recent_high <= recent_low:
        return 0, None, "無波動"
    fibs = fibonacci_retracement(recent_high, recent_low)
    
    # 判斷趨勢
    mid = lookback // 2
    early_high = max(highs[-lookback:][:mid])
    late_high = max(highs[-lookback:][mid:])
    early_low = min(lows[-lookback:][:mid])
    late_low = min(lows[-lookback:][mid:])
    is_uptrend = late_high > early_high and late_low > early_low
    is_downtrend = late_high < early_high and late_low < early_low
    
    # 找最近的 fib 位
    nearest_level = None
    nearest_dist = float('inf')
    for level, price in fibs.items():
        dist = abs(current - price) / current * 100
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_level = level
    
    # 价格在 fib 范围之外的情况
    if nearest_dist > 2:
        fib_236 = fibs[23.6]  # 最深回撤位（最靠近起點）
        fib_786 = fibs[78.6]  # 最浅回撤位（最靠近高点）
        
        if is_uptrend:
            if current > fib_236:
                # 价格突破所有 fib 位（在前高之上）= 趨勢延續
                return 12, 0, f"上升趨勢，價格突破前高（當前 ${current:.2f} > 23.6%回撤 ${fib_236:.2f}）"
            elif current < fib_786:
                # 深回撤到 78.6% 以下 = 可能反轉
                return -5, 78.6, f"上升趨勢，但深回撤到 78.6% 以下"
        elif is_downtrend:
            if current < fib_236:
                # 价格跌破所有 fib 位（在前低之下）= 趨勢延續
                return -12, 0, f"下降趨勢，價格跌破前低（當前 ${current:.2f} < 23.6%反彈 ${fib_236:.2f}）"
            elif current > fib_786:
                # 深反彈到 78.6% 以上 = 可能反轉
                return 5, 78.6, f"下降趨勢，但深反彈到 78.6% 以上"
    
    # 价格在 fib 范围之内
    if is_uptrend:
        if nearest_level in [38.2, 50.0] and nearest_dist <= 3:
            return 15, nearest_level, f"上升趨勢，回撤到 {nearest_level}%（距離 {nearest_dist:.1f}%）"
        elif nearest_level == 61.8 and nearest_dist <= 3:
            return 8, nearest_level, f"上升趨勢，深回撤到 61.8%（距離 {nearest_dist:.1f}%）"
        elif nearest_level == 23.6 and nearest_dist <= 3:
            return 10, nearest_level, f"上升趨勢，价格在 23.6% 附近（延續信號）"
        else:
            return 0, nearest_level, f"上升趨勢，在 {nearest_level}% 附近（距離 {nearest_dist:.1f}%）"
    elif is_downtrend:
        if nearest_level in [38.2, 50.0] and nearest_dist <= 3:
            return -15, nearest_level, f"下降趨勢，反彈到 {nearest_level}%"
        elif nearest_level == 61.8 and nearest_dist <= 3:
            return -8, nearest_level, f"下降趨勢，深反彈到 61.8%"
        elif nearest_level == 23.6 and nearest_dist <= 3:
            return -10, nearest_level, f"下降趨勢，价格在 23.6% 附近（延續信號）"
        else:
            return 0, nearest_level, f"下降趨勢，在 {nearest_level}% 附近"
    else:
        if nearest_dist <= 2:
            return 3, nearest_level, f"盤整，價格在 {nearest_level}% 附近"
        else:
            return 0, nearest_level, f"盤整，距離 {nearest_level}% 較遠"


def get_fib_entry_zones(highs, lows, current, lookback=30):
    """返回建議的入場區域"""
    if len(highs) < lookback or len(lows) < lookback:
        return []
    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    fibs = fibonacci_retracement(recent_high, recent_low)
    zones = []
    for level, price in fibs.items():
        dist = abs(current - price) / current * 100
        if level in [38.2, 50.0]:
            zones.append({"level": level, "price": price, "type": "long",
                          "priority": "high" if dist <= 5 else "medium", "dist_pct": round(dist, 2)})
        elif level == 61.8:
            zones.append({"level": level, "price": price, "type": "long",
                          "priority": "medium" if dist <= 5 else "low", "dist_pct": round(dist, 2)})
    return sorted(zones, key=lambda x: x["dist_pct"])
