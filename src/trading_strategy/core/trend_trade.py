"""Compatibility wrapper for trend position helpers."""

from trading_strategy.positions.trend import (
    compute_atr_trailing_result,
    compute_dynamic_sl_target,
    initialize_trend_position_state,
    resolve_trend_stop_target,
)

__all__ = [
    "compute_atr_trailing_result",
    "compute_dynamic_sl_target",
    "initialize_trend_position_state",
    "resolve_trend_stop_target",
]
