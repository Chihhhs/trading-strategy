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
    parameters = getattr(config, "strategy_parameters", None) or {}
    if key in parameters:
        return parameters[key]
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


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _std(values):
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def _pct_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def _price_position(current, highs, lows, lookback):
    if lookback <= 1 or len(highs) < lookback + 1 or len(lows) < lookback + 1:
        return 0.5, None, None
    high_prev = max(highs[-lookback - 1 : -1])
    low_prev = min(lows[-lookback - 1 : -1])
    if high_prev <= low_prev:
        return 0.5, high_prev, low_prev
    return (current - low_prev) / (high_prev - low_prev), high_prev, low_prev


def get_derivatives_crowding_context(window, config):
    if not window:
        return None
    funding_lookback = int(_config_value(config, "derivatives_crowding_funding_z_lookback", 30) or 30)
    price_lookback = 3
    if len(window) <= max(funding_lookback, price_lookback):
        return None
    current_bar = window[-1]
    funding = _safe_float(current_bar.get("funding_rate"), default=None)
    basis = _safe_float(current_bar.get("basis_pct"), default=None)
    if funding is None or basis is None:
        return None
    funding_window = [
        _safe_float(bar.get("funding_rate"), default=None)
        for bar in window[-funding_lookback - 1 : -1]
    ]
    funding_mean = _mean(funding_window)
    funding_std = _std(funding_window)
    if funding_mean is None or not funding_std:
        return None
    funding_z = (funding - funding_mean) / funding_std
    threshold = float(_config_value(config, "derivatives_crowding_funding_z_threshold", 0.75))
    basis_threshold = float(_config_value(config, "derivatives_crowding_basis_abs_threshold_pct", 0.03))
    if abs(funding_z) < threshold or abs(basis) < basis_threshold:
        return {
            "label": "neutral",
            "direction": None,
            "funding_z": funding_z,
            "funding_rate": funding,
            "basis_pct": basis,
        }

    current = _safe_float(current_bar.get("close"), default=None)
    previous = _safe_float(window[-price_lookback - 1].get("close"), default=None)
    price_return = _pct_change(current, previous)
    direction = None
    label = "neutral"
    if funding_z > 0 and price_return is not None and price_return <= 0:
        direction = "short"
        label = "short_trend_support"
    elif funding_z < 0 and price_return is not None and price_return >= 0:
        direction = "long"
        label = "long_trend_support"
    elif funding_z > 0:
        direction = "short"
        label = "crowded_long_risk"
    elif funding_z < 0:
        direction = "long"
        label = "crowded_short_risk"

    if direction == "short" and basis < -basis_threshold:
        label = "short_basis_crowded"
    elif direction == "long" and basis > basis_threshold:
        label = "long_basis_crowded"
    elif direction == "short" and basis > basis_threshold:
        label = "short_basis_support"
    elif direction == "long" and basis < -basis_threshold:
        label = "long_basis_support"

    return {
        "label": label,
        "direction": direction,
        "funding_z": funding_z,
        "funding_rate": funding,
        "basis_pct": basis,
        "price_return": price_return,
    }


def evaluate_derivatives_crowding_exit(position, window, config, diagnostics=None):
    if not bool(_config_value(config, "derivatives_crowding_exit_enabled", False)):
        return {"triggered": False}
    context = get_derivatives_crowding_context(window, config)
    if not context or not context.get("direction"):
        return {"triggered": False, "context": context}
    direction = str(position.get("direction") or "").lower()
    label = context.get("label")
    should_exit = (
        (direction == "long" and label == "short_basis_crowded")
        or (direction == "short" and label == "long_basis_crowded")
    )
    action = str(_config_value(config, "derivatives_crowding_action", "exit") or "exit").lower()
    if action not in ("exit", "reduce"):
        action = "exit"
    reduction_key = f"{label}:{direction}"
    already_reduced = reduction_key in set(position.get("derivatives_crowding_reductions") or [])
    should_reduce = should_exit and action == "reduce" and not already_reduced
    if should_exit and action == "exit":
        _increment_counter(diagnostics, "derivatives_crowding_exit_signals")
        if direction == "long":
            _increment_counter(diagnostics, "derivatives_crowding_exit_long_signals")
        else:
            _increment_counter(diagnostics, "derivatives_crowding_exit_short_signals")
    if should_reduce:
        _increment_counter(diagnostics, "derivatives_crowding_reduce_signals")
        if direction == "long":
            _increment_counter(diagnostics, "derivatives_crowding_reduce_long_signals")
        else:
            _increment_counter(diagnostics, "derivatives_crowding_reduce_short_signals")
    return {
        "triggered": should_exit and action == "exit",
        "action": "reduce" if should_reduce else ("exit" if should_exit and action == "exit" else None),
        "reduce_fraction": float(_config_value(config, "derivatives_crowding_reduce_fraction", 0.5) or 0.5),
        "reduction_key": reduction_key,
        "context": context,
    }


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
    candidate = generate_raw_trend_candidate(
        klines,
        min_score=min_score,
        tp_mult=tp_mult,
        sl_mult=sl_mult,
        adx_threshold=adx_threshold,
        price_position_lookback=price_position_lookback,
    )
    if candidate is None:
        return None
    if entry_filter_enabled:
        eligibility = evaluate_trend_entry_eligibility(
            candidate["direction"],
            candidate,
            rsi_min_long=rsi_min_long,
            rsi_max_long=rsi_max_long,
            rsi_min_short=rsi_min_short,
            rsi_max_short=rsi_max_short,
            max_atr_pct=max_atr_pct,
            long_max_price_position=long_max_price_position,
            short_min_price_position=short_min_price_position,
            max_roc_60_long=max_roc_60_long,
            min_roc_60_short=min_roc_60_short,
        )
        if not eligibility["allowed"]:
            _increment_counter(diagnostics, eligibility["reasons"][0])
            return None
    return candidate


def evaluate_trend_entry_eligibility(
    direction,
    features,
    *,
    rsi_min_long=45,
    rsi_max_long=70,
    rsi_min_short=30,
    rsi_max_short=55,
    max_atr_pct=8,
    long_max_price_position=0.75,
    short_min_price_position=0.25,
    max_roc_60_long=120,
    min_roc_60_short=-120,
):
    """Evaluate Trend entry filters without mutating diagnostics or strategy state."""
    rsi_value = float(features.get("rsi", 50.0))
    atr_pct = float(features.get("atr_pct", 0.0))
    price_position = float(features.get("price_position_60", 0.5))
    roc_60 = float(features.get("roc60", 0.0))
    reasons = []
    if direction == "long":
        if not float(rsi_min_long) <= rsi_value <= float(rsi_max_long):
            reasons.append("trend_rsi_filtered_signals")
        if atr_pct > float(max_atr_pct):
            reasons.append("trend_atr_filtered_signals")
        if price_position > float(long_max_price_position):
            reasons.append("trend_price_position_filtered_signals")
        if roc_60 > float(max_roc_60_long):
            reasons.append("trend_overextension_filtered_signals")
    elif direction == "short":
        if not float(rsi_min_short) <= rsi_value <= float(rsi_max_short):
            reasons.append("trend_rsi_filtered_signals")
        if atr_pct > float(max_atr_pct):
            reasons.append("trend_atr_filtered_signals")
        if price_position < float(short_min_price_position):
            reasons.append("trend_price_position_filtered_signals")
        if roc_60 < float(min_roc_60_short):
            reasons.append("trend_overextension_filtered_signals")
    else:
        reasons.append("trend_unknown_direction_filtered_signals")
    return {"allowed": not reasons, "reasons": tuple(reasons)}


def generate_raw_trend_candidate(
    klines,
    *,
    min_score=4,
    tp_mult=1.5,
    sl_mult=1.0,
    adx_threshold=25,
    price_position_lookback=60,
):
    """Return a structurally valid Trend candidate before entry eligibility filters."""
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
    volume_ratio = None
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
        "ema_slope": ((ema20 - calc_ema(closes[:-5], 20)) / current * 100.0) if index >= 24 and current else 0.0,
        "volume_ratio": volume_ratio,
    }

    if score >= min_score:
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
            position["entry_adx"] = raw.get("adx")
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
        paper_bar_age_is_authoritative = context.mode == "paper" and position.get("last_evaluated_bar") is not None
        if position.get("entry_klines_len") and window and context.mode != "backtest" and not paper_bar_age_is_authoritative:
            position["bars_since_entry"] = max(
                len(window) - int(position.get("entry_klines_len") or 0),
                0,
            )
        atr_result = self.check_atr_trailing_exit(position, window, context.config)
        reversal_detected = check_trend_reversal(position, window) if window else False
        failure_exit = self.check_failure_exit(position, window, context.config)
        crowding_exit = evaluate_derivatives_crowding_exit(
            position,
            window,
            context.config,
            diagnostics=context.diagnostics,
        )
        exit_reason = None
        if reversal_detected:
            exit_reason = "REVERSAL"
        elif atr_result.get("triggered"):
            exit_reason = "ATR_TRAIL"
        elif failure_exit.get("triggered"):
            exit_reason = "FAILURE"
        elif crowding_exit.get("triggered"):
            exit_reason = "DERIVATIVES_CROWDING"
        return {
            "exit_reason": exit_reason,
            "atr_trail_result": atr_result,
            "reversal_detected": reversal_detected,
            "failure_exit": failure_exit,
            "derivatives_crowding_exit": crowding_exit,
            "position_adjustment": {
                "action": "reduce",
                "fraction": crowding_exit.get("reduce_fraction"),
                "reason": "DERIVATIVES_CROWDING_REDUCE",
                "reduction_key": crowding_exit.get("reduction_key"),
            }
            if crowding_exit.get("action") == "reduce"
            else None,
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
            atr_trailing_mult=self._effective_atr_trailing_mult(position, context.config),
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
            atr_trailing_mult=self._effective_atr_trailing_mult(position, config),
        )

    def _effective_atr_trailing_mult(self, position, config):
        default = float(_config_value(config, "atr_trailing_mult", 2.0) or 2.0)
        if not bool(_config_value(config, "adaptive_atr_trailing_enabled", False)):
            return default
        entry_adx = _safe_float((position or {}).get("entry_adx"), default=None)
        strong_adx = float(_config_value(config, "adaptive_atr_strong_adx", 35.0) or 35.0)
        if entry_adx is not None and entry_adx >= strong_adx:
            return float(_config_value(config, "adaptive_atr_strong_mult", 3.0) or 3.0)
        return float(_config_value(config, "adaptive_atr_weak_mult", 1.5) or 1.5)

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
    "get_derivatives_crowding_context",
    "get_ema_value",
    "get_rsi_value",
    "get_trend_structure_context",
    "is_signal_blocked_by_btc_filter",
    "evaluate_derivatives_crowding_exit",
]


def is_signal_blocked_by_btc_filter(coin, signal, btc_window):
    return TrendStrategy().should_block_for_btc(coin, signal, btc_window)
