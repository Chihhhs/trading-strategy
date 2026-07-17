from dataclasses import dataclass, fields
from typing import Any, Callable
import math


@dataclass(frozen=True)
class TrendParameters:
    timeframe: str = "1d"
    min_score: int = 4
    atr_trailing_enabled: bool = False
    atr_activation_r: float = 1.5
    atr_trailing_mult: float = 2.0
    adaptive_atr_trailing_enabled: bool = False
    adaptive_atr_strong_adx: float = 35.0
    adaptive_atr_strong_mult: float = 3.0
    adaptive_atr_weak_mult: float = 1.5
    failure_exit_enabled: bool = False
    failure_exit_bars: int = 3
    failure_exit_mode: str = "breakout_failure"
    max_hold_bars: int | None = None
    trend_entry_filter_enabled: bool = True
    trend_rsi_min_long: float = 45.0
    trend_rsi_max_long: float = 75.0
    trend_rsi_min_short: float = 30.0
    trend_rsi_max_short: float = 55.0
    trend_max_atr_pct: float = 8.0
    trend_price_position_lookback: int = 60
    trend_long_max_price_position: float = 0.85
    trend_short_min_price_position: float = 0.25
    trend_max_roc_60_long: float = 120.0
    trend_min_roc_60_short: float = -120.0
    derivatives_filter_enabled: bool = False
    oi_entry_filter_enabled: bool = False
    oi_entry_filter_lookback: int = 5
    oi_entry_filter_min_change_pct: float = 0.0
    oi_entry_filter_min_price_move_pct: float = 0.1
    oi_entry_filter_block_late_crowded: bool = True
    oi_entry_filter_funding_extreme_abs: float = 0.0005
    derivatives_crowding_exit_enabled: bool = False
    derivatives_crowding_action: str = "exit"
    derivatives_crowding_reduce_fraction: float = 0.75
    derivatives_crowding_funding_z_lookback: int = 30
    derivatives_crowding_funding_z_threshold: float = 0.75
    derivatives_crowding_basis_abs_threshold_pct: float = 0.03
    trend_alpha_entry_enabled: bool = False
    trend_alpha_mode: str = "combined"
    trend_alpha_score_boost: float = 1.0
    trend_alpha_require_confirmation: bool = False
    trend_alpha_block_crowded_entry: bool = True
    market_context_enabled: bool = False
    market_context_ema_fast: int = 20
    market_context_ema_slow: int = 50
    market_context_slope_bars: int = 5
    market_context_ema_slope_min: float = 0.05
    market_context_adx_period: int = 14
    market_context_adx_strong: float = 30.0
    market_context_adx_weak: float = 20.0
    market_context_adx_range: float = 18.0
    market_context_atr_short_period: int = 5
    market_context_atr_long_period: int = 14
    market_context_atr_contraction_threshold: float = 0.8
    market_context_bb_period: int = 20
    market_context_bb_rank_lookback: int = 40
    market_context_compression_percentile: float = 0.2
    market_context_donchian_lookback: int = 20
    market_context_transition_confirmation_bars: int = 2
    market_context_breakout_atr_multiple: float = 0.5
    market_context_breakout_volume_ratio: float = 1.2
    market_context_breakout_min_confirmations: int = 2
    market_context_btc_lookback: int = 7
    market_context_btc_threshold_pct: float = 3.0
    momentum_decay_time_limit_enabled: bool = False
    momentum_decay_bars: int = 3
    momentum_decay_adx_lookback: int = 5
    momentum_decay_grace_bars: int = 3


@dataclass(frozen=True)
class IntradayMomentumParameters:
    timeframe: str = "15m"
    min_score: int = 4
    intraday_breakout_lookback: int = 12
    intraday_fast_ema: int = 8
    intraday_slow_ema: int = 21
    intraday_max_hold_bars: int = 24
    intraday_momentum_threshold_pct: float = 0.2
    intraday_volume_ratio: float = 1.2


@dataclass(frozen=True)
class LegacyUnifiedParameters:
    timeframe: str = "1d"
    min_score: int = 4
    intrabar_exit_enabled: bool = True
    intrabar_fill_policy: str = "stop_first"
    price_position_filter_enabled: bool = True
    dead_cat_filter_enabled: bool = True


@dataclass(frozen=True)
class CrossSectionalStrengthParameters:
    timeframe: str = "1d"
    lookback_days: int = 90
    rebalance_days: int = 7
    top_n: int = 5
    min_momentum_pct: float = 0.0
    min_positive_fraction: float = 0.5


@dataclass(frozen=True)
class CrossSectionalMomentumParameters:
    timeframe: str = "4h"
    lookback_bars: int = 84
    rebalance_bars: int = 6
    top_n: int = 3
    overlap_cohorts: int = 7
    cohort_spacing_bars: int = 6
    rebalance_hour_utc: int = 0


def _validate_parameter_types(name: str, parameter_type: type, values: dict[str, Any]):
    for field in fields(parameter_type):
        if field.name not in values or values[field.name] is None:
            continue
        value = values[field.name]
        default = field.default
        if isinstance(default, bool) and not isinstance(value, bool):
            raise ValueError(f"invalid {name} parameter type: {field.name}")
        if isinstance(default, int) and not isinstance(default, bool) and not isinstance(value, int):
            raise ValueError(f"invalid {name} parameter type: {field.name}")
        if isinstance(default, float) and not isinstance(value, (int, float)):
            raise ValueError(f"invalid {name} parameter type: {field.name}")
        if isinstance(default, (int, float)) and not isinstance(default, bool) and (
            isinstance(value, bool) or not math.isfinite(float(value))
        ):
            raise ValueError(f"invalid {name} parameter type: {field.name}")
        if isinstance(default, str) and not isinstance(value, str):
            raise ValueError(f"invalid {name} parameter type: {field.name}")


@dataclass(frozen=True)
class StrategyDefinition:
    name: str
    factory: Callable[[], Any]
    parameter_type: type
    capabilities: frozenset[str]
    default_timeframe: str
    min_bars: int
    context_bars: int | None = None

    def parse_parameters(self, values=None):
        values = dict(values or {})
        allowed = {field.name for field in fields(self.parameter_type)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"unknown {self.name} parameters: {', '.join(unknown)}")
        _validate_parameter_types(self.name, self.parameter_type, values)
        return self.parameter_type(**values)
