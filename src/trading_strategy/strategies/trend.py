import statistics

from trading_strategy.indicators import adx, atr, ema, rsi
from trading_strategy.positions.trend import (
    compute_atr_trailing_result,
    evaluate_trend_failure_exit,
    resolve_trend_stop_target,
)

from .base import BaseStrategy, StrategyContext, StrategySignal, signal_value


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _config_value(config, key, default=None):
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _normalize_reason(value):
    return str(value or "").strip().upper()


def _is_trend_reason(reason):
    return _normalize_reason(reason).startswith("TREND_")


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


def get_rsi_value(closes, period=14, default=50):
    result = rsi(closes, period)
    return _last_numeric(result, default)


def _increment_counter(diagnostics, key, amount=1):
    if diagnostics is None:
        return
    diagnostics[key] = int(diagnostics.get(key) or 0) + amount


def _price_position(current, highs, lows, lookback):
    if lookback <= 1 or len(highs) < lookback + 1 or len(lows) < lookback + 1:
        return 0.5, None, None
    high_prev = max(highs[-lookback - 1 : -1])
    low_prev = min(lows[-lookback - 1 : -1])
    if high_prev <= low_prev:
        return 0.5, high_prev, low_prev
    return (current - low_prev) / (high_prev - low_prev), high_prev, low_prev


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


def get_trend_structure_context(klines):
    if not klines:
        return None
    closes = [d["close"] for d in klines]
    highs = [d["high"] for d in klines]
    lows = [d["low"] for d in klines]
    index = len(klines) - 1
    current = closes[index]
    ema20 = get_ema_value(closes, 20, current)
    ema50 = get_ema_value(closes, 50, current)
    context = {
        "current": current,
        "ema20": ema20,
        "ema50": ema50,
        "high_20_prev": None,
        "low_20_prev": None,
    }
    if index >= 20:
        context["high_20_prev"] = max(highs[index - 20 : index])
        context["low_20_prev"] = min(lows[index - 20 : index])
    return context


def generate_trend_signal(
    klines,
    *,
    min_score=4,
    tp_mult=1.5,
    sl_mult=1.0,
    adx_threshold=25,
    entry_filter_enabled=True,
    rsi_min_long=45,
    rsi_max_long=70,
    rsi_min_short=30,
    rsi_max_short=55,
    max_atr_pct=8,
    price_position_lookback=60,
    long_max_price_position=0.75,
    short_min_price_position=0.25,
    max_roc_60_long=120,
    min_roc_60_short=-120,
    diagnostics=None,
):
    if not klines or len(klines) < 50:
        return None

    closes = [d["close"] for d in klines]
    highs = [d["high"] for d in klines]
    lows = [d["low"] for d in klines]
    vols = [d.get("volume", 0) for d in klines]
    index = len(klines) - 1
    structure = get_trend_structure_context(klines)
    current = structure["current"]

    adx_val = get_adx_value(highs, lows, closes, default=20)
    atr_val = get_atr_value(highs, lows, closes, default=current * 0.03)
    if not atr_val or atr_val == 0:
        atr_val = current * 0.03
    atr_pct = (atr_val / current * 100) if current else 0.0
    rsi_val = get_rsi_value(closes, 14, 50)
    position_60, high_60_prev, low_60_prev = _price_position(
        current,
        highs,
        lows,
        int(price_position_lookback or 60),
    )
    roc_60 = (current / closes[index - 60] - 1.0) * 100 if index >= 60 and closes[index - 60] else 0.0

    ema20 = structure["ema20"]
    ema50 = structure["ema50"]

    if adx_val < adx_threshold:
        return None

    score = 0
    if index >= 20:
        roc_5 = (closes[index] - closes[index - 5]) / closes[index - 5] * 100
        roc_20 = (closes[index] - closes[index - 20]) / closes[index - 20] * 100
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

        vol_avg = statistics.mean(vols[max(0, index - 5) : index + 1])
        vol_base = statistics.mean(vols[max(0, index - 20) : index + 1])
        if vol_base > 0:
            volume_ratio = vol_avg / vol_base
            if volume_ratio > 1.5:
                score += 2
            elif volume_ratio < 0.6:
                score -= 1

        high_20_prev = structure["high_20_prev"]
        low_20_prev = structure["low_20_prev"]
        if current > high_20_prev:
            score += 2
        elif current < low_20_prev:
            score -= 2

    if current > ema20 and ema20 > ema50:
        score += 1
    elif current < ema20 and ema20 < ema50:
        score -= 1

    raw_context = {
        "adx": adx_val,
        "atr": atr_val,
        "atr_pct": atr_pct,
        "rsi": rsi_val,
        "ema20": ema20,
        "ema50": ema50,
        "high_20_prev": structure["high_20_prev"],
        "low_20_prev": structure["low_20_prev"],
        "high_60_prev": high_60_prev,
        "low_60_prev": low_60_prev,
        "price_position_60": position_60,
        "roc60": roc_60,
    }

    if score >= min_score:
        if entry_filter_enabled:
            if not (float(rsi_min_long) <= rsi_val <= float(rsi_max_long)):
                _increment_counter(diagnostics, "trend_rsi_filtered_signals")
                return None
            if atr_pct > float(max_atr_pct):
                _increment_counter(diagnostics, "trend_atr_filtered_signals")
                return None
            if position_60 > float(long_max_price_position):
                _increment_counter(diagnostics, "trend_price_position_filtered_signals")
                return None
            if roc_60 > float(max_roc_60_long):
                _increment_counter(diagnostics, "trend_overextension_filtered_signals")
                return None
        return {
            "direction": "long",
            "score": score,
            "tp": current + atr_val * tp_mult,
            "sl": current - atr_val * sl_mult,
            "reason": "TREND_BUY",
            **raw_context,
            "breakout_level": structure["high_20_prev"],
        }
    if score <= -min_score:
        if entry_filter_enabled:
            if not (float(rsi_min_short) <= rsi_val <= float(rsi_max_short)):
                _increment_counter(diagnostics, "trend_rsi_filtered_signals")
                return None
            if atr_pct > float(max_atr_pct):
                _increment_counter(diagnostics, "trend_atr_filtered_signals")
                return None
            if position_60 < float(short_min_price_position):
                _increment_counter(diagnostics, "trend_price_position_filtered_signals")
                return None
            if roc_60 < float(min_roc_60_short):
                _increment_counter(diagnostics, "trend_overextension_filtered_signals")
                return None
        return {
            "direction": "short",
            "score": score,
            "tp": current - atr_val * tp_mult,
            "sl": current + atr_val * sl_mult,
            "reason": "TREND_SELL",
            **raw_context,
            "breakout_level": structure["low_20_prev"],
        }
    return None


def build_exit_policy(*, signal=None, position=None):
    if isinstance(position, dict) and isinstance(position.get("exit_policy"), dict):
        return dict(position["exit_policy"])

    reason = ""
    if signal is not None:
        reason = signal_value(signal, "reason", "")
    elif isinstance(position, dict):
        reason = position.get("sig") or position.get("signal_reason") or ""

    if _is_trend_reason(reason):
        return {
            "name": "trend_sl_only",
            "requires_tp": False,
            "requires_sl": True,
            "protection_event_prefix": "sl",
        }

    return {
        "name": "fixed_tpsl",
        "requires_tp": True,
        "requires_sl": True,
        "protection_event_prefix": "tpsl",
    }


def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    ema_value = sum(closes[:period]) / period
    weight = 2 / (period + 1)
    for close in closes[period:]:
        ema_value = close * weight + ema_value * (1 - weight)
    return ema_value


def calc_atr(highs, lows, closes, period=14):
    true_ranges = [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(highs))
    ]
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0
    atr_value = sum(true_ranges[:period]) / period
    for true_range in true_ranges[period:]:
        atr_value = (atr_value * (period - 1) + true_range) / period
    return atr_value


def check_trend_reversal(pos, klines):
    if not klines or len(klines) < 30:
        return False
    closes = [d["close"] for d in klines]
    ema20 = calc_ema(closes, 20)
    ema50 = calc_ema(closes, 50)
    ema20_prev = calc_ema(closes[:-1], 20)
    ema50_prev = calc_ema(closes[:-1], 50) if len(closes) > 50 else ema50
    current = closes[-1]
    if pos["direction"] == "long":
        return current < ema20 and ema20 < ema50 and ema20_prev >= ema50_prev
    return current > ema20 and ema20 > ema50 and ema20_prev <= ema50_prev


class TrendStrategy(BaseStrategy):
    name = "trend"

    def generate_signal(self, context: StrategyContext):
        min_score = _config_value(context.config, "min_score", 4)
        tp_mult = _config_value(context.config, "tp_mult", 1.5)
        sl_mult = _config_value(context.config, "sl_mult", 1.0)
        raw_signal = generate_trend_signal(
            context.window,
            min_score=min_score,
            tp_mult=tp_mult,
            sl_mult=sl_mult,
            entry_filter_enabled=bool(_config_value(context.config, "trend_entry_filter_enabled", True)),
            rsi_min_long=_config_value(context.config, "trend_rsi_min_long", 45.0),
            rsi_max_long=_config_value(context.config, "trend_rsi_max_long", 70.0),
            rsi_min_short=_config_value(context.config, "trend_rsi_min_short", 30.0),
            rsi_max_short=_config_value(context.config, "trend_rsi_max_short", 55.0),
            max_atr_pct=_config_value(context.config, "trend_max_atr_pct", 8.0),
            price_position_lookback=_config_value(context.config, "trend_price_position_lookback", 60),
            long_max_price_position=_config_value(context.config, "trend_long_max_price_position", 0.75),
            short_min_price_position=_config_value(context.config, "trend_short_min_price_position", 0.25),
            max_roc_60_long=_config_value(context.config, "trend_max_roc_60_long", 120.0),
            min_roc_60_short=_config_value(context.config, "trend_min_roc_60_short", -120.0),
            diagnostics=context.diagnostics,
        )
        if raw_signal is None:
            return None
        return StrategySignal(
            direction=raw_signal["direction"],
            tp=_safe_float(raw_signal.get("tp"), default=None),
            sl=_safe_float(raw_signal.get("sl"), default=None),
            score=raw_signal["score"],
            reason=raw_signal.get("reason", ""),
            raw=dict(raw_signal),
        )

    def build_exit_policy(self, *, signal=None, position=None):
        return build_exit_policy(signal=signal, position=position)

    def initialize_position(self, position, signal, context: StrategyContext):
        raw = dict(signal_value(signal, "raw", {}) or {})
        exit_policy = position.get("exit_policy") or self.build_exit_policy(signal=signal, position=position)
        entry = _safe_float(position.get("entry"), default=None)
        sl = _safe_float(position.get("sl"), default=None)
        position["exit_policy"] = exit_policy
        if not exit_policy.get("requires_tp"):
            position["tp"] = None
        position["initial_risk"] = abs(entry - sl) if entry is not None and sl is not None else None
        if exit_policy.get("name") == "trend_sl_only":
            position["entry_atr"] = raw.get("atr")
            position["sl_stage"] = position.get("sl_stage", 0)
            position["best_price"] = position.get("best_price", entry)
            position["entry_klines_len"] = position.get("entry_klines_len") or len(context.window or [])
            position["bars_since_entry"] = position.get("bars_since_entry", 0)
            position["entry_breakout_level"] = raw.get("breakout_level")
            position["entry_ema20"] = raw.get("ema20")
            position["entry_ema50"] = raw.get("ema50")
        return position

    def should_block_for_btc(self, coin, signal, btc_window):
        if coin == "BTC" or not btc_window:
            return False
        btc_dir = get_btc_direction_from_klines(btc_window)
        signal_direction = signal_value(signal, "direction")
        if btc_dir == "bull" and signal_direction == "short":
            return True
        if btc_dir == "bear" and signal_direction == "long":
            return True
        return False

    def evaluate_open_position(self, position, context: StrategyContext):
        window = context.window or []
        if position.get("current_price") is None and context.price is not None:
            position["current_price"] = context.price
        if position.get("entry_klines_len") and window:
            position["bars_since_entry"] = max(
                len(window) - int(position.get("entry_klines_len") or 0),
                0,
            )
        atr_result = self.check_atr_trailing_exit(position, window, context.config)
        reversal_detected = check_trend_reversal(position, window) if window else False
        failure_exit = self.check_failure_exit(position, window, context.config)
        exit_reason = None
        if reversal_detected:
            exit_reason = "REVERSAL"
        elif atr_result.get("triggered"):
            exit_reason = "ATR_TRAIL"
        elif failure_exit.get("triggered"):
            exit_reason = "FAILURE"
        return {
            "exit_reason": exit_reason,
            "atr_trail_result": atr_result,
            "reversal_detected": reversal_detected,
            "failure_exit": failure_exit,
            "bars_since_entry": position.get("bars_since_entry"),
        }

    def resolve_stop_target(self, position, context: StrategyContext):
        current_atr = None
        if context.window and len(context.window) >= 2:
            current_atr = calc_atr(
                [bar["high"] for bar in context.window],
                [bar["low"] for bar in context.window],
                [bar["close"] for bar in context.window],
            )
        return resolve_trend_stop_target(
            position,
            current_atr=current_atr,
            atr_trailing_enabled=_config_value(context.config, "atr_trailing_enabled", False),
            atr_activation_r=_config_value(context.config, "atr_activation_r", 1.5),
            atr_trailing_mult=_config_value(context.config, "atr_trailing_mult", 2.0),
        )

    def check_atr_trailing_exit(self, position, window, config):
        current_atr = None
        if window and len(window) >= 2:
            current_atr = calc_atr(
                [bar["high"] for bar in window],
                [bar["low"] for bar in window],
                [bar["close"] for bar in window],
            )
        return compute_atr_trailing_result(
            position,
            current_atr=current_atr,
            enabled=_config_value(config, "atr_trailing_enabled", False),
            atr_activation_r=_config_value(config, "atr_activation_r", 1.5),
            atr_trailing_mult=_config_value(config, "atr_trailing_mult", 2.0),
        )

    def check_failure_exit(self, position, window, config):
        if not window:
            return {
                "triggered": False,
                "bars_since_entry": 0,
                "entry_breakout_level": None,
                "current_ema20": None,
            }
        structure = get_trend_structure_context(window)
        current_price = _safe_float(position.get("current_price"), default=None)
        return evaluate_trend_failure_exit(
            position,
            bars_since_entry=position.get("bars_since_entry", 0),
            current_price=current_price,
            current_ema20=(structure or {}).get("ema20"),
            enabled=_config_value(config, "failure_exit_enabled", False),
            failure_exit_bars=_config_value(config, "failure_exit_bars", 3),
            failure_exit_mode=_config_value(config, "failure_exit_mode", "breakout_failure"),
        )


__all__ = [
    "TrendStrategy",
    "build_exit_policy",
    "calc_atr",
    "calc_ema",
    "check_trend_reversal",
    "generate_trend_signal",
    "get_adx_value",
    "get_atr_value",
    "get_btc_direction_from_klines",
    "get_ema_value",
    "get_rsi_value",
    "get_trend_structure_context",
    "is_signal_blocked_by_btc_filter",
]


def is_signal_blocked_by_btc_filter(coin, signal, btc_window):
    return TrendStrategy().should_block_for_btc(coin, signal, btc_window)
