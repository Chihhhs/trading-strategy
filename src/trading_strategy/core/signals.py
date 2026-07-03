import statistics

from trading_strategy.indicators import adx, atr, ema


def _last_numeric(value, default=None):
    if isinstance(value, list):
        for item in reversed(value):
            if item is not None:
                return item
        return default
    if isinstance(value, tuple):
        for item in value:
            resolved = _last_numeric(item, None)
            if resolved is not None:
                return resolved
        return default
    return default if value is None else value


def get_adx_value(highs, lows, closes, n=14, default=20):
    result = adx(highs, lows, closes, n)
    if isinstance(result, tuple) and result:
        return _last_numeric(result[0], default)
    return _last_numeric(result, default)


def get_atr_value(highs, lows, closes, n=14, default=None):
    result = atr(highs, lows, closes, n)
    return _last_numeric(result, default)


def get_ema_value(closes, period, default=None):
    result = ema(closes, period)
    return _last_numeric(result, default)


def get_btc_direction_from_klines(klines, lookback_days=7, threshold_pct=3):
    if not klines or len(klines) < lookback_days:
        return "neutral"

    closes = [d["close"] for d in klines]
    change_pct = (closes[-1] / closes[-lookback_days] - 1) * 100
    if change_pct > threshold_pct:
        return "bull"
    if change_pct < -threshold_pct:
        return "bear"
    return "neutral"


def generate_trend_signal(
    klines,
    *,
    min_score=4,
    tp_mult=1.5,
    sl_mult=1.0,
    adx_threshold=25,
):
    if not klines or len(klines) < 50:
        return None

    closes = [d["close"] for d in klines]
    highs = [d["high"] for d in klines]
    lows = [d["low"] for d in klines]
    vols = [d.get("volume", 0) for d in klines]
    i = len(klines) - 1
    current = closes[i]

    adx_val = get_adx_value(highs, lows, closes, default=20)
    atr_val = get_atr_value(highs, lows, closes, default=current * 0.03)
    if not atr_val or atr_val == 0:
        atr_val = current * 0.03

    ema20 = get_ema_value(closes, 20, current)
    ema50 = get_ema_value(closes, 50, current)

    if adx_val < adx_threshold:
        return None

    score = 0
    if i >= 20:
        roc_5 = (closes[i] - closes[i - 5]) / closes[i - 5] * 100
        roc_20 = (closes[i] - closes[i - 20]) / closes[i - 20] * 100
        momentum_accel = roc_5 - roc_20 * 0.3
        if momentum_accel > 3:
            score += 3
        elif momentum_accel > 1:
            score += 1
        elif momentum_accel < -3:
            score -= 3
        elif momentum_accel < -1:
            score -= 1

        atr5 = get_atr_value(highs[-5:], lows[-5:], closes[-5:], n=5, default=atr_val)
        vol_ratio = atr5 / atr_val if atr_val > 0 else 1
        if vol_ratio > 1.5:
            score += 2
        elif vol_ratio < 0.7:
            score -= 1

        vol_avg = statistics.mean(vols[max(0, i - 5) : i + 1])
        vol_base = statistics.mean(vols[max(0, i - 20) : i + 1])
        if vol_base > 0:
            v_ratio = vol_avg / vol_base
            if v_ratio > 1.5:
                score += 2
            elif v_ratio < 0.6:
                score -= 1

        high_20_prev = max(highs[i - 20 : i])
        low_20_prev = min(lows[i - 20 : i])
        if current > high_20_prev:
            score += 2
        elif current < low_20_prev:
            score -= 2

    if current > ema20 and ema20 > ema50:
        score += 1
    elif current < ema20 and ema20 < ema50:
        score -= 1

    if score >= min_score:
        return {
            "direction": "long",
            "score": score,
            "tp": current + atr_val * tp_mult,
            "sl": current - atr_val * sl_mult,
            "reason": "TREND_BUY",
            "adx": adx_val,
        }
    if score <= -min_score:
        return {
            "direction": "short",
            "score": score,
            "tp": current - atr_val * tp_mult,
            "sl": current + atr_val * sl_mult,
            "reason": "TREND_SELL",
            "adx": adx_val,
        }
    return None


def find_fvg(closes, highs, lows, i, lookback=5):
    fvgs = []
    for j in range(max(i - lookback, 2), i + 1):
        k1 = {"high": highs[j - 2], "low": lows[j - 2]}
        k3 = {"high": highs[j], "low": lows[j]}
        if k1["high"] < k3["low"]:
            fvgs.append(("bull", k1["high"], k3["low"]))
        if k1["low"] > k3["high"]:
            fvgs.append(("bear", k3["high"], k1["low"]))
    return fvgs


def price_in_fvg(price, fvgs):
    for direction, low, high in fvgs:
        if low <= price <= high:
            return direction
    return None


def fib_position(price, high_50, low_50):
    trading_range = high_50 - low_50
    if trading_range == 0:
        return 50
    return (high_50 - price) / trading_range * 100


def generate_fvg_signal(klines, strategy_type="both", min_score=4):
    if not klines or len(klines) < 50:
        return None

    closes = [d["close"] for d in klines]
    highs = [d["high"] for d in klines]
    lows = [d["low"] for d in klines]
    vols = [d.get("volume", d.get("vol", 0)) for d in klines]
    i = len(klines) - 1
    current = closes[i]

    adx_val = get_adx_value(highs, lows, closes, default=20)
    atr_val = get_atr_value(highs, lows, closes, default=current * 0.03)
    if not atr_val or atr_val == 0:
        atr_val = current * 0.03

    high_50 = max(highs[max(0, i - 50) : i + 1])
    low_50 = min(lows[max(0, i - 50) : i + 1])

    if strategy_type in ("fvg", "both") and adx_val < 25:
        score = 0
        fvg_dir = price_in_fvg(current, find_fvg(closes, highs, lows, i))
        fib_pos = fib_position(current, high_50, low_50)
        if 33 <= fib_pos <= 43:
            score += 3
        if 47 <= fib_pos <= 53:
            score += 2
        if 58 <= fib_pos <= 65:
            score += 1
        if fib_pos < 15:
            score -= 3
        if fib_pos > 85:
            score -= 2

        if fvg_dir == "bull":
            score += 3
        elif fvg_dir == "bear":
            score -= 3

        if len(vols) >= 20:
            vol_avg = statistics.mean(vols[max(0, i - 5) : i + 1])
            vol_base = statistics.mean(vols[max(0, i - 20) : i + 1])
            vol_ratio = vol_avg / vol_base if vol_base > 0 else 1
            if vol_ratio > 1.3:
                score = int(score * 1.15)
            elif vol_ratio < 0.7:
                score = int(score * 0.85)

        if score >= min_score:
            return {
                "direction": "long",
                "score": score,
                "tp": current + (current - low_50) * 1.5,
                "sl": low_50,
                "reason": "FVG_BUY",
                "adx": adx_val,
                "fib_pos": fib_pos,
            }
        if score <= -min_score:
            return {
                "direction": "short",
                "score": score,
                "tp": current - (high_50 - current) * 1.5,
                "sl": high_50,
                "reason": "FVG_SELL",
                "adx": adx_val,
                "fib_pos": fib_pos,
            }

    if strategy_type in ("trend", "both") and adx_val >= 25:
        return generate_trend_signal(
            klines,
            min_score=min_score,
            tp_mult=2.0,
            sl_mult=1.5,
            adx_threshold=25,
        )

    return None
