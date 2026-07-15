"""Strategy registry and shared interfaces."""

from .base import BaseStrategy, Strategy, StrategyContext, StrategySignal
from .definitions import (
    IntradayMomentumParameters,
    LegacyUnifiedParameters,
    StrategyDefinition,
    TrendParameters,
)
from .intraday_momentum import IntradayMomentumStrategy
from .legacy_unified import LegacyUnifiedStrategy
from .trend import (
    TrendStrategy,
    build_exit_policy,
    evaluate_trend_entry_eligibility,
    generate_raw_trend_candidate,
    generate_trend_signal,
    get_btc_direction_from_klines,
    get_trend_structure_context,
    is_signal_blocked_by_btc_filter,
)


_STRATEGY_DEFINITIONS = {
    "intraday_momentum": StrategyDefinition(
        name="intraday_momentum",
        factory=IntradayMomentumStrategy,
        parameter_type=IntradayMomentumParameters,
        capabilities=frozenset({"fixed_tpsl", "short_horizon"}),
        default_timeframe="15m",
        min_bars=50,
        context_bars=90,
    ),
    "legacy_unified": StrategyDefinition(
        name="legacy_unified",
        factory=LegacyUnifiedStrategy,
        parameter_type=LegacyUnifiedParameters,
        capabilities=frozenset({"fixed_tpsl", "intrabar_exit", "btc_filter"}),
        default_timeframe="1d",
        min_bars=50,
        context_bars=None,
    ),
    "trend": StrategyDefinition(
        name="trend",
        factory=TrendStrategy,
        parameter_type=TrendParameters,
        capabilities=frozenset({"btc_filter", "dynamic_stop", "position_adjustment", "sl_only"}),
        default_timeframe="1d",
        min_bars=50,
        context_bars=None,
    ),
}

_STRATEGIES = {
    name: definition.factory()
    for name, definition in _STRATEGY_DEFINITIONS.items()
}


def available_strategy_names():
    return tuple(sorted(_STRATEGIES))


def get_strategy(name="trend"):
    strategy_name = str(name or "trend").strip().lower() or "trend"
    if strategy_name not in _STRATEGIES:
        available = ", ".join(sorted(_STRATEGIES))
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {available}")
    return _STRATEGIES[strategy_name]


def get_strategy_definition(name="trend"):
    strategy_name = str(name or "trend").strip().lower() or "trend"
    if strategy_name not in _STRATEGY_DEFINITIONS:
        available = ", ".join(sorted(_STRATEGY_DEFINITIONS))
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {available}")
    return _STRATEGY_DEFINITIONS[strategy_name]


def resolve_strategy(name="trend"):
    return get_strategy(name)


__all__ = [
    "BaseStrategy",
    "IntradayMomentumStrategy",
    "LegacyUnifiedStrategy",
    "Strategy",
    "StrategyContext",
    "StrategyDefinition",
    "StrategySignal",
    "TrendStrategy",
    "available_strategy_names",
    "build_exit_policy",
    "evaluate_trend_entry_eligibility",
    "generate_raw_trend_candidate",
    "generate_trend_signal",
    "get_btc_direction_from_klines",
    "get_strategy",
    "get_strategy_definition",
    "get_trend_structure_context",
    "is_signal_blocked_by_btc_filter",
    "resolve_strategy",
]
