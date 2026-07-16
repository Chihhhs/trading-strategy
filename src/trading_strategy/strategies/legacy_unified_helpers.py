"""Legacy unified backtest helpers reconstructed from the knowledge base."""

from __future__ import annotations

from statistics import mean

from trading_strategy.indicators import adx, atr, ema, rsi


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _config_value(config, key, default=None):
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


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


def _increment_counter(diagnostics, key, amount=1):
    if diagnostics is None:
        return
    diagnostics[key] = int(diagnostics.get(key) or 0) + amount


def get_ema_value(closes, period, default=None):
    return _last_numeric(ema(closes, period), default)


def get_rsi_value(closes, period=14, default=50):
    return _last_numeric(rsi(closes, period), default)


def get_atr_value(highs, lows, closes, n=14, default=None):
    return _last_numeric(atr(highs, lows, closes, n), default)


def get_adx_value(highs, lows, closes, n=14, default=20):
    result = adx(highs, lows, closes, n)
    if isinstance(result, tuple) and result:
        return _last_numeric(result[0], default)
    return _last_numeric(result, default)


def get_btc_direction_from_klines(klines, lookback_days=7, threshold_pct=3):
    if not klines or len(klines) < lookback_days:
        return "neutral"
    closes = [float(bar["close"]) for bar in klines]
    change_pct = (closes[-1] / closes[-lookback_days] - 1.0) * 100 if closes[-lookback_days] else 0.0
    if change_pct > threshold_pct:
        return "bull"
    if change_pct < -threshold_pct:
        return "bear"
    return "neutral"


def analyze_market_regime(klines, *, regime_mode="auto"):
    window = list(klines or [])
    if len(window) < 60:
        return None

    closes = [float(bar["close"]) for bar in window]
    highs = [float(bar["high"]) for bar in window]
    lows = [float(bar["low"]) for bar in window]
    current = closes[-1]
    ema20 = get_ema_value(closes, 20, current)
    ema50 = get_ema_value(closes, 50, current)
    adx_val = get_adx_value(highs, lows, closes, default=20)
    atr_val = get_atr_value(highs, lows, closes, default=current * 0.03)
    if not atr_val or atr_val <= 0:
        atr_val = current * 0.03

    roc20 = (current / closes[-20] - 1.0) * 100 if closes[-20] else 0.0
    roc60 = (current / closes[-60] - 1.0) * 100 if closes[-60] else 0.0
    high_20_prev = max(highs[-21:-1])
    low_20_prev = min(lows[-21:-1])
    high_60_prev = max(highs[-61:-1])
    low_60_prev = min(lows[-61:-1])
    price_position_60 = (
        (current - low_60_prev) / (high_60_prev - low_60_prev)
        if high_60_prev > low_60_prev
        else 0.5
    )
    bounce_from_low_pct = (current / low_60_prev - 1.0) * 100 if low_60_prev else 0.0
    recent_volume = mean(float(bar.get("volume", 0.0) or 0.0) for bar in window[-5:])
    base_volume = mean(float(bar.get("volume", 0.0) or 0.0) for bar in window[-20:])
    volume_ratio = recent_volume / base_volume if base_volume > 0 else 1.0

    long_score = 0
    short_score = 0
    if current > ema20 > ema50:
        long_score += 2
    if current < ema20 < ema50:
        short_score += 2
    if roc60 > 15:
        long_score += 2
    elif roc60 < -15:
        short_score += 2
    if roc20 > 3:
        long_score += 1
    elif roc20 < -3:
        short_score += 1
    if adx_val >= 25:
        long_score += 1
        short_score += 1
    if volume_ratio > 1.1:
        if current >= ema20:
            long_score += 1
        if current <= ema20:
            short_score += 1

    if regime_mode in ("long_term", "short_term"):
        selected = regime_mode
    elif abs(roc60) >= 15 or adx_val >= 28:
        selected = "long_term"
    else:
        selected = "short_term"

    return {
        "regime": selected,
        "current": current,
        "ema20": ema20,
        "ema50": ema50,
        "adx": adx_val,
        "atr": atr_val,
        "roc20": roc20,
        "roc60": roc60,
        "high_20_prev": high_20_prev,
        "low_20_prev": low_20_prev,
        "price_position_60": price_position_60,
        "bounce_from_low_pct": bounce_from_low_pct,
        "volume_ratio": volume_ratio,
        "long_score": long_score,
        "short_score": short_score,
        "rsi": get_rsi_value(closes, 14, 50),
    }


def is_price_position_blocked(direction, regime, *, enabled=True):
    if not enabled or not regime:
        return False
    position = float(regime.get("price_position_60", 0.5) or 0.5)
    if direction == "long":
        return position > 0.75
    if direction == "short":
        return position < 0.25
    return False


def is_dead_cat_bounce(direction, regime, *, enabled=True, bounce_threshold_pct=15):
    if not enabled or not regime or direction != "long":
        return False
    ema20 = _safe_float(regime.get("ema20"))
    ema50 = _safe_float(regime.get("ema50"))
    bounce = float(regime.get("bounce_from_low_pct", 0.0) or 0.0)
    return ema20 is not None and ema50 is not None and ema20 < ema50 and bounce > float(bounce_threshold_pct)


def _direction_pullback_ok(direction, regime):
    current = float(regime["current"])
    ema20 = float(regime["ema20"])
    atr_val = float(regime["atr"])
    position = float(regime.get("price_position_60", 0.5) or 0.5)
    if direction == "long":
        return current <= ema20 + atr_val * 0.35 and position <= 0.68
    return current >= ema20 - atr_val * 0.35 and position >= 0.32


def generate_legacy_signal(klines, *, config=None, diagnostics=None):
    regime = analyze_market_regime(
        klines,
        regime_mode=_config_value(config, "regime_mode", "auto"),
    )
    if regime is None:
        return None

    current = float(regime["current"])
    atr_val = float(regime["atr"])
    regime_name = regime["regime"]
    long_min_score = float(_config_value(config, "long_term_min_score", 4) or 4)
    short_min_score = float(_config_value(config, "short_term_min_score", 5) or 5)
    tp_mult = float(_config_value(config, "tp_mult", 3.0 if regime_name == "long_term" else 1.5) or 1.5)
    sl_mult = float(_config_value(config, "sl_mult", 2.0 if regime_name == "long_term" else 1.5) or 1.5)
    max_hold_bars = int(_config_value(config, "max_hold_bars", 90 if regime_name == "long_term" else 14) or 0)

    direction = None
    score = 0.0
    if regime["long_score"] >= long_min_score and regime["long_score"] >= regime["short_score"] + 1:
        direction = "long"
        score = float(regime["long_score"])
    elif regime["short_score"] >= short_min_score and regime["short_score"] >= regime["long_score"] + 1:
        direction = "short"
        score = float(regime["short_score"])
    else:
        return None

    if is_price_position_blocked(
        direction,
        regime,
        enabled=bool(_config_value(config, "price_position_filter_enabled", True)),
    ):
        _increment_counter(diagnostics, "price_position_filtered_signals")
        return None

    if is_dead_cat_bounce(
        direction,
        regime,
        enabled=bool(_config_value(config, "dead_cat_filter_enabled", True)),
        bounce_threshold_pct=float(_config_value(config, "dead_cat_bounce_pct", 15.0) or 15.0),
    ):
        _increment_counter(diagnostics, "dead_cat_filtered_signals")
        return None

    if not _direction_pullback_ok(direction, regime):
        _increment_counter(diagnostics, "pullback_filtered_signals")
        return None

    raw = {
        "regime": regime_name,
        "atr": atr_val,
        "ema20": regime["ema20"],
        "ema50": regime["ema50"],
        "roc20": regime["roc20"],
        "roc60": regime["roc60"],
        "adx": regime["adx"],
        "rsi": regime["rsi"],
        "price_position_60": regime["price_position_60"],
        "bounce_from_low_pct": regime["bounce_from_low_pct"],
        "max_hold_bars": max_hold_bars,
        "breakout_level": regime["high_20_prev"] if direction == "long" else regime["low_20_prev"],
    }
    if direction == "long":
        return {
            "direction": "long",
            "score": score,
            "tp": current + atr_val * tp_mult,
            "sl": current - atr_val * sl_mult,
            "reason": f"LEGACY_{regime_name.upper()}_BUY",
            "raw": raw,
        }
    return {
        "direction": "short",
        "score": -score,
        "tp": current - atr_val * tp_mult,
        "sl": current + atr_val * sl_mult,
        "reason": f"LEGACY_{regime_name.upper()}_SELL",
        "raw": raw,
    }


__all__ = [
    "analyze_market_regime",
    "generate_legacy_signal",
    "get_btc_direction_from_klines",
    "is_dead_cat_bounce",
    "is_price_position_blocked",
]
