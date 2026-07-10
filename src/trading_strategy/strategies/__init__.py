"""Strategy registry and shared interfaces."""

from .base import BaseStrategy, Strategy, StrategyContext, StrategySignal
from .intraday_momentum import IntradayMomentumStrategy
from .trend import (
    TrendStrategy,
    build_exit_policy,
    generate_trend_signal,
    get_btc_direction_from_klines,
    get_trend_structure_context,
    is_signal_blocked_by_btc_filter,
)


_STRATEGIES = {
    "intraday_momentum": IntradayMomentumStrategy(),
    "trend": TrendStrategy(),
}


def available_strategy_names():
    return tuple(sorted(_STRATEGIES))


def get_strategy(name="trend"):
    strategy_name = str(name or "trend").strip().lower() or "trend"
    if strategy_name not in _STRATEGIES:
        available = ", ".join(sorted(_STRATEGIES))
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {available}")
    return _STRATEGIES[strategy_name]


def resolve_strategy(name="trend"):
    return get_strategy(name)


__all__ = [
    "BaseStrategy",
    "IntradayMomentumStrategy",
    "Strategy",
    "StrategyContext",
    "StrategySignal",
    "TrendStrategy",
    "available_strategy_names",
    "build_exit_policy",
    "generate_trend_signal",
    "get_btc_direction_from_klines",
    "get_strategy",
    "get_trend_structure_context",
    "is_signal_blocked_by_btc_filter",
    "resolve_strategy",
]
