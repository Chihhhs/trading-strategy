"""Deterministic, causal market-context classification for trend research."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from trading_strategy.indicators import adx, atr, bollinger, ema


class MarketRegime(str, Enum):
    STRONG_TREND = "strong_trend"
    WEAK_TREND = "weak_trend"
    RANGE = "range"
    COMPRESSION = "compression"
    BREAKOUT = "breakout"
    EXHAUSTION = "exhaustion"
    REVERSAL = "reversal"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MarketContext:
    regime: MarketRegime
    direction: str | None
    confidence: float
    reasons: tuple[str, ...] = ()
    features: dict[str, Any] = field(default_factory=dict)
    breakout_confirmed: bool = False

    def to_dict(self):
        payload = asdict(self)
        payload["regime"] = self.regime.value
        return payload


@dataclass
class _TransitionState:
    regime: MarketRegime = MarketRegime.UNKNOWN
    direction: str | None = None
    pending_regime: MarketRegime | None = None
    pending_direction: str | None = None
    pending_bars: int = 0
    bar_key: Any = None
    context: MarketContext | None = None


def _config_value(config, key, default):
    if isinstance(config, dict):
        return config.get(key, default)
    parameters = getattr(config, "strategy_parameters", None) or {}
    if key in parameters:
        return parameters[key]
    return getattr(config, key, default)


def _last_numeric(values, default=None):
    if isinstance(values, tuple):
        values = values[0] if values else []
    if not isinstance(values, list):
        return default
    for value in reversed(values):
        if value is not None:
            return float(value)
    return default


def _safe_mean(values):
    values = [float(value) for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _percentile_rank(value, values):
    values = [float(item) for item in values if item is not None]
    if value is None or not values:
        return None
    return sum(item <= value for item in values) / len(values)


def _bar_key(bar):
    if not isinstance(bar, dict):
        return None
    return bar.get("open_time", bar.get("time", bar.get("timestamp")))


def _btc_direction(btc_window, config):
    lookback = int(_config_value(config, "market_context_btc_lookback", 7))
    threshold_pct = float(_config_value(config, "market_context_btc_threshold_pct", 3.0))
    if not btc_window or len(btc_window) <= lookback:
        return "unavailable"
    current = float(btc_window[-1]["close"])
    previous = float(btc_window[-lookback - 1]["close"])
    if not previous:
        return "unavailable"
    change_pct = (current / previous - 1.0) * 100.0
    if change_pct >= threshold_pct:
        return "bull"
    if change_pct <= -threshold_pct:
        return "bear"
    return "neutral"


def _direction_from_ema(ema_fast, ema_slow, slope, minimum_slope):
    if ema_fast is None or ema_slow is None or slope is None:
        return None
    if ema_fast > ema_slow and slope >= minimum_slope:
        return "long"
    if ema_fast < ema_slow and slope <= -minimum_slope:
        return "short"
    return None


def _momentum_is_decaying(closes, direction, bars):
    if direction not in ("long", "short") or len(closes) < 5 + bars:
        return False
    sign = 1.0 if direction == "long" else -1.0
    momentum = []
    for index in range(len(closes) - bars, len(closes)):
        previous = closes[index - 5]
        if not previous:
            return False
        momentum.append(sign * (closes[index] / previous - 1.0))
    return all(later < earlier for earlier, later in zip(momentum, momentum[1:]))


def _bb_widths(closes, period):
    middle, upper, lower = bollinger(closes, n=period)
    widths = []
    for mid, top, bottom in zip(middle, upper, lower):
        if mid in (None, 0) or top is None or bottom is None:
            widths.append(None)
        else:
            widths.append((top - bottom) / mid)
    return widths


def classify_market_context(window, previous: _TransitionState, config, btc_window=None) -> MarketContext:
    """Classify a bar using only the supplied completed window and prior state."""
    fast_period = int(_config_value(config, "market_context_ema_fast", 20))
    slow_period = int(_config_value(config, "market_context_ema_slow", 50))
    slope_bars = int(_config_value(config, "market_context_slope_bars", 5))
    adx_period = int(_config_value(config, "market_context_adx_period", 14))
    atr_short_period = int(_config_value(config, "market_context_atr_short_period", 5))
    atr_long_period = int(_config_value(config, "market_context_atr_long_period", 14))
    bb_period = int(_config_value(config, "market_context_bb_period", 20))
    bb_rank_lookback = int(_config_value(config, "market_context_bb_rank_lookback", 40))
    donchian_lookback = int(_config_value(config, "market_context_donchian_lookback", 20))
    min_bars = max(slow_period + slope_bars, bb_period + bb_rank_lookback, donchian_lookback + 1, adx_period * 2)
    if not window or len(window) < min_bars:
        return MarketContext(MarketRegime.UNKNOWN, None, 0.0, ("insufficient_warmup",))

    closes = [float(bar["close"]) for bar in window]
    highs = [float(bar.get("high", bar["close"])) for bar in window]
    lows = [float(bar.get("low", bar["close"])) for bar in window]
    volumes = [bar.get("volume") for bar in window]
    ema_fast_values = ema(closes, fast_period)
    ema_slow_values = ema(closes, slow_period)
    atr_short_values = atr(highs, lows, closes, atr_short_period)
    atr_long_values = atr(highs, lows, closes, atr_long_period)
    adx_values = adx(highs, lows, closes, adx_period)[0]
    ema_fast = _last_numeric(ema_fast_values)
    ema_slow = _last_numeric(ema_slow_values)
    atr_short = _last_numeric(atr_short_values)
    atr_long = _last_numeric(atr_long_values)
    adx_current = _last_numeric(adx_values)
    adx_previous = _last_numeric(adx_values[:-int(_config_value(config, "momentum_decay_adx_lookback", 5))])
    if None in (ema_fast, ema_slow, atr_short, atr_long, adx_current) or not atr_long:
        return MarketContext(MarketRegime.UNKNOWN, None, 0.0, ("indicator_warmup",))

    previous_fast = ema_fast_values[-slope_bars - 1]
    slope = None if previous_fast is None else (ema_fast - float(previous_fast)) / (atr_long * slope_bars)
    direction = _direction_from_ema(
        ema_fast,
        ema_slow,
        slope,
        float(_config_value(config, "market_context_ema_slope_min", 0.05)),
    )
    widths = _bb_widths(closes, bb_period)
    bb_width = _last_numeric(widths)
    bb_percentile = _percentile_rank(bb_width, widths[-bb_rank_lookback:])
    atr_contraction = atr_short / atr_long if atr_long else None
    current = closes[-1]
    high_previous = max(highs[-donchian_lookback - 1 : -1])
    low_previous = min(lows[-donchian_lookback - 1 : -1])
    price_break_direction = "long" if current > high_previous else "short" if current < low_previous else None
    breakout_distance = (
        abs(current - (high_previous if price_break_direction == "long" else low_previous)) / atr_long
        if price_break_direction else 0.0
    )
    volume_base = _safe_mean(volumes[-donchian_lookback - 1 : -1])
    volume_ratio = (float(volumes[-1]) / volume_base) if volume_base and volumes[-1] is not None else None
    breakout_checks = (
        bool(price_break_direction),
        breakout_distance >= float(_config_value(config, "market_context_breakout_atr_multiple", 0.5)),
        volume_ratio is not None and volume_ratio >= float(_config_value(config, "market_context_breakout_volume_ratio", 1.2)),
    )
    breakout_score = sum(breakout_checks)
    breakout_confirmed = breakout_score >= int(_config_value(config, "market_context_breakout_min_confirmations", 2))
    features = {
        "adx": adx_current,
        "adx_previous": adx_previous,
        "ema_slope_atr": slope,
        "atr_contraction": atr_contraction,
        "bb_width_percentile": bb_percentile,
        "breakout_score": breakout_score,
        "breakout_distance_atr": breakout_distance,
        "volume_ratio": volume_ratio,
        "btc_direction": _btc_direction(btc_window, config),
    }

    if breakout_confirmed:
        return MarketContext(MarketRegime.BREAKOUT, price_break_direction, breakout_score / 3.0, ("confirmed_donchian_breakout",), features, True)
    compression = (
        bb_percentile is not None
        and bb_percentile <= float(_config_value(config, "market_context_compression_percentile", 0.2))
        and atr_contraction is not None
        and atr_contraction <= float(_config_value(config, "market_context_atr_contraction_threshold", 0.8))
    )
    if compression:
        return MarketContext(MarketRegime.COMPRESSION, direction, 0.75, ("bb_width_and_atr_contracting",), features)
    if (
        previous.direction
        and direction
        and previous.direction != direction
        and adx_current >= float(_config_value(config, "market_context_adx_weak", 20.0))
    ):
        return MarketContext(MarketRegime.REVERSAL, direction, 0.7, ("ema_direction_reversal",), features)
    if (
        previous.regime in (MarketRegime.STRONG_TREND, MarketRegime.WEAK_TREND)
        and direction == previous.direction
        and adx_current >= float(_config_value(config, "market_context_adx_weak", 20.0))
        and adx_previous is not None
        and adx_current < adx_previous
        and _momentum_is_decaying(closes, direction, int(_config_value(config, "momentum_decay_bars", 3)))
    ):
        return MarketContext(MarketRegime.EXHAUSTION, direction, 0.7, ("momentum_decay_with_falling_adx",), features)
    if direction and adx_current >= float(_config_value(config, "market_context_adx_strong", 30.0)):
        return MarketContext(MarketRegime.STRONG_TREND, direction, min(adx_current / 50.0, 1.0), ("ema_alignment_and_strong_adx",), features)
    if direction and adx_current >= float(_config_value(config, "market_context_adx_weak", 20.0)):
        return MarketContext(MarketRegime.WEAK_TREND, direction, min(adx_current / 40.0, 1.0), ("ema_alignment_and_weak_adx",), features)
    if (
        adx_current <= float(_config_value(config, "market_context_adx_range", 18.0))
        and low_previous <= current <= high_previous
    ):
        return MarketContext(MarketRegime.RANGE, None, 0.7, ("low_adx_inside_donchian",), features)
    return MarketContext(MarketRegime.UNKNOWN, direction, 0.25, ("no_confirmed_regime",), features)


class MarketContextDetector:
    """Maintains causal, per-coin regime-transition state for a backtest run."""

    def __init__(self, config):
        self.config = config
        self._states: dict[str, _TransitionState] = {}

    def observe(self, coin, window, btc_window=None):
        state = self._states.setdefault(coin, _TransitionState())
        key = _bar_key(window[-1]) if window else None
        if key is not None and state.bar_key == key and state.context is not None:
            return state.context
        raw = classify_market_context(window, state, self.config, btc_window)
        confirmation_bars = max(int(_config_value(self.config, "market_context_transition_confirmation_bars", 2)), 1)
        if raw.regime == MarketRegime.BREAKOUT and raw.breakout_confirmed:
            state.regime = raw.regime
            state.direction = raw.direction
            state.pending_regime = None
            state.pending_direction = None
            state.pending_bars = 0
            context = raw
        elif raw.regime == state.regime and raw.direction == state.direction:
            state.pending_regime = None
            state.pending_direction = None
            state.pending_bars = 0
            context = raw
        elif raw.regime == state.pending_regime and raw.direction == state.pending_direction:
            state.pending_bars += 1
            if state.pending_bars >= confirmation_bars:
                state.regime = raw.regime
                state.direction = raw.direction
                state.pending_regime = None
                state.pending_direction = None
                state.pending_bars = 0
                context = raw
            else:
                context = state.context or raw
        else:
            state.pending_regime = raw.regime
            state.pending_direction = raw.direction
            state.pending_bars = 1
            context = raw if state.context is None else state.context
        state.bar_key = key
        state.context = context
        return context


def entry_decision(signal_direction, context: MarketContext):
    """Return a deterministic entry allow/block decision for a trend signal."""
    allowed_regimes = {MarketRegime.STRONG_TREND, MarketRegime.WEAK_TREND, MarketRegime.BREAKOUT, MarketRegime.REVERSAL}
    direction_matches = context.direction == signal_direction
    allowed = context.regime in allowed_regimes and direction_matches
    if context.regime == MarketRegime.BREAKOUT:
        allowed = allowed and context.breakout_confirmed
    reason = "market_context_allowed" if allowed else f"market_context_blocked:{context.regime.value}"
    return {"allowed": allowed, "reason": reason}
