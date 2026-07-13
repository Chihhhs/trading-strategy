from .base import BaseStrategy, StrategyContext, StrategySignal, signal_value
from .trend import get_atr_value, get_btc_direction_from_klines, get_ema_value


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


def _mean(values):
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else 0.0


class IntradayMomentumStrategy(BaseStrategy):
    name = "intraday_momentum"

    def generate_signal(self, context: StrategyContext):
        window = list(context.window or [])
        lookback = int(_config_value(context.config, "intraday_breakout_lookback", 12) or 12)
        fast_period = int(_config_value(context.config, "intraday_fast_ema", 8) or 8)
        slow_period = int(_config_value(context.config, "intraday_slow_ema", 21) or 21)
        min_score = float(_config_value(context.config, "min_score", 4) or 4)
        min_bars = max(lookback + 2, slow_period + 2, 30)
        if len(window) < min_bars:
            return None

        closes = [float(bar["close"]) for bar in window]
        highs = [float(bar["high"]) for bar in window]
        lows = [float(bar["low"]) for bar in window]
        volumes = [float(bar.get("volume", 0.0) or 0.0) for bar in window]
        current = closes[-1]
        previous_close = closes[-2]
        previous_high = max(highs[-lookback - 1 : -1])
        previous_low = min(lows[-lookback - 1 : -1])
        atr_value = get_atr_value(highs, lows, closes, default=current * 0.01)
        if not atr_value or atr_value <= 0:
            atr_value = current * 0.01

        fast_ema = get_ema_value(closes, fast_period, current)
        slow_ema = get_ema_value(closes, slow_period, current)
        momentum_pct = ((current / previous_close) - 1.0) * 100 if previous_close else 0.0
        range_pct = (atr_value / current) * 100 if current else 0.0
        recent_volume = _mean(volumes[-5:])
        base_volume = _mean(volumes[-lookback - 1 : -1])
        volume_ratio = recent_volume / base_volume if base_volume > 0 else 1.0

        score = 0.0
        if current > previous_high:
            score += 2.0
        elif current < previous_low:
            score -= 2.0

        if fast_ema > slow_ema:
            score += 1.0
        elif fast_ema < slow_ema:
            score -= 1.0

        momentum_threshold = float(_config_value(context.config, "intraday_momentum_threshold_pct", 0.2) or 0.2)
        if momentum_pct >= momentum_threshold:
            score += 1.0
        elif momentum_pct <= -momentum_threshold:
            score -= 1.0

        volume_threshold = float(_config_value(context.config, "intraday_volume_ratio", 1.2) or 1.2)
        if volume_ratio >= volume_threshold:
            score += 1.0 if score > 0 else -1.0 if score < 0 else 0.0

        tp_mult = float(_config_value(context.config, "tp_mult", 1.2) or 1.2)
        sl_mult = float(_config_value(context.config, "sl_mult", 0.8) or 0.8)
        raw = {
            "atr": atr_value,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "previous_high": previous_high,
            "previous_low": previous_low,
            "momentum_pct": momentum_pct,
            "range_pct": range_pct,
            "volume_ratio": volume_ratio,
            "lookback": lookback,
        }
        if score >= min_score:
            return StrategySignal(
                "long",
                tp=current + atr_value * tp_mult,
                sl=current - atr_value * sl_mult,
                score=score,
                reason="INTRADAY_MOMENTUM_BUY",
                raw=raw,
            )
        if score <= -min_score:
            return StrategySignal(
                "short",
                tp=current - atr_value * tp_mult,
                sl=current + atr_value * sl_mult,
                score=score,
                reason="INTRADAY_MOMENTUM_SELL",
                raw=raw,
            )
        return None

    def initialize_position(self, position, signal, context: StrategyContext):
        raw = dict(signal_value(signal, "raw", {}) or {})
        position["strategy_name"] = self.name
        position["entry_atr"] = raw.get("atr")
        position["entry_breakout_level"] = (
            raw.get("previous_high")
            if signal_value(signal, "direction") == "long"
            else raw.get("previous_low")
        )
        position["entry_klines_len"] = position.get("entry_klines_len") or len(context.window or [])
        position["bars_since_entry"] = position.get("bars_since_entry", 0)
        return position

    def should_block_for_btc(self, coin, signal, btc_window):
        if coin == "BTC" or not btc_window:
            return False
        btc_dir = get_btc_direction_from_klines(btc_window)
        direction = signal_value(signal, "direction")
        if btc_dir == "bull" and direction == "short":
            return True
        if btc_dir == "bear" and direction == "long":
            return True
        return False

    def evaluate_open_position(self, position, context: StrategyContext):
        window = list(context.window or [])
        if position.get("entry_klines_len") and window and position.get("bars_since_entry") is None:
            position["bars_since_entry"] = max(
                len(window) - int(position.get("entry_klines_len") or 0),
                0,
            )
        max_hold_bars = int(_config_value(context.config, "intraday_max_hold_bars", 24) or 24)
        if max_hold_bars > 0 and int(position.get("bars_since_entry") or 0) >= max_hold_bars:
            return {
                "exit_reason": "TIME",
                "bars_since_entry": position.get("bars_since_entry"),
            }
        return {
            "exit_reason": None,
            "bars_since_entry": position.get("bars_since_entry"),
        }


__all__ = ["IntradayMomentumStrategy"]
