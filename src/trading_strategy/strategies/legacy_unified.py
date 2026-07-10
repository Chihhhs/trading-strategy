from trading_strategy.core.legacy_unified import generate_legacy_signal, get_btc_direction_from_klines
from trading_strategy.positions.trend import compute_atr_trailing_result, resolve_trend_stop_target

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


class LegacyUnifiedStrategy(BaseStrategy):
    name = "legacy_unified"

    def generate_signal(self, context: StrategyContext):
        raw_signal = generate_legacy_signal(context.window, config=context.config, diagnostics=context.diagnostics)
        if raw_signal is None:
            return None
        return StrategySignal(
            direction=raw_signal["direction"],
            tp=_safe_float(raw_signal.get("tp")),
            sl=_safe_float(raw_signal.get("sl")),
            score=_safe_float(raw_signal.get("score"), 0.0),
            reason=raw_signal.get("reason", ""),
            raw=dict(raw_signal.get("raw", {})),
        )

    def build_exit_policy(self, *, signal=None, position=None):
        return {
            "name": "legacy_fixed_tpsl",
            "requires_tp": True,
            "requires_sl": True,
            "protection_event_prefix": "legacy_tpsl",
        }

    def initialize_position(self, position, signal, context: StrategyContext):
        raw = dict(signal_value(signal, "raw", {}) or {})
        entry = _safe_float(position.get("entry"))
        sl = _safe_float(position.get("sl"))
        position["exit_policy"] = self.build_exit_policy(signal=signal, position=position)
        position["initial_risk"] = abs(entry - sl) if entry is not None and sl is not None else None
        position["entry_atr"] = raw.get("atr")
        position["sl_stage"] = position.get("sl_stage", 0)
        position["best_price"] = position.get("best_price", entry)
        position["entry_klines_len"] = position.get("entry_klines_len") or len(context.window or [])
        position["bars_since_entry"] = position.get("bars_since_entry", 0)
        position["entry_breakout_level"] = raw.get("breakout_level")
        position["entry_ema20"] = raw.get("ema20")
        position["entry_ema50"] = raw.get("ema50")
        position["entry_regime"] = raw.get("regime")
        position["max_hold_bars"] = int(raw.get("max_hold_bars") or _config_value(context.config, "max_hold_bars", 0) or 0)
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

    def resolve_stop_target(self, position, context: StrategyContext):
        return resolve_trend_stop_target(
            position,
            current_atr=_safe_float(position.get("entry_atr")),
            atr_trailing_enabled=_config_value(context.config, "atr_trailing_enabled", False),
            atr_activation_r=_config_value(context.config, "atr_activation_r", 1.5),
            atr_trailing_mult=_config_value(context.config, "atr_trailing_mult", 2.0),
        )

    def evaluate_open_position(self, position, context: StrategyContext):
        if position.get("current_price") is None and context.price is not None:
            position["current_price"] = context.price
        window = list(context.window or [])
        if position.get("entry_klines_len") and window:
            position["bars_since_entry"] = max(len(window) - int(position.get("entry_klines_len") or 0), 0)

        max_hold_bars = int(position.get("max_hold_bars") or _config_value(context.config, "max_hold_bars", 0) or 0)
        if max_hold_bars > 0 and int(position.get("bars_since_entry") or 0) >= max_hold_bars:
            return {"exit_reason": "TIME", "bars_since_entry": position.get("bars_since_entry")}

        atr_result = compute_atr_trailing_result(
            position,
            current_atr=_safe_float(position.get("entry_atr")),
            enabled=_config_value(context.config, "atr_trailing_enabled", False),
            atr_activation_r=_config_value(context.config, "atr_activation_r", 1.5),
            atr_trailing_mult=_config_value(context.config, "atr_trailing_mult", 2.0),
        )
        if atr_result.get("triggered"):
            return {"exit_reason": "ATR_TRAIL", "bars_since_entry": position.get("bars_since_entry")}

        if _config_value(context.config, "failure_exit_enabled", False) and int(position.get("bars_since_entry") or 0) <= int(
            _config_value(context.config, "failure_exit_bars", 3) or 3
        ):
            current_price = _safe_float(position.get("current_price"))
            breakout_level = _safe_float(position.get("entry_breakout_level"))
            ema20 = _safe_float(position.get("entry_ema20"))
            if current_price is not None and breakout_level is not None and ema20 is not None:
                if position.get("direction") == "long" and current_price < breakout_level and current_price < ema20:
                    return {"exit_reason": "FAILURE", "bars_since_entry": position.get("bars_since_entry")}
                if position.get("direction") == "short" and current_price > breakout_level and current_price > ema20:
                    return {"exit_reason": "FAILURE", "bars_since_entry": position.get("bars_since_entry")}
        return {"exit_reason": None, "bars_since_entry": position.get("bars_since_entry")}


__all__ = ["LegacyUnifiedStrategy"]
