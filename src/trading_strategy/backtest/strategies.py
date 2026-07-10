from trading_strategy.strategies import (
    get_btc_direction_from_klines,
    resolve_strategy as resolve_registered_strategy,
)

from .types import BacktestStrategy, StrategySignal


def resolve_strategy(strategy_type="trend") -> BacktestStrategy:
    return resolve_registered_strategy(strategy_type)


def is_signal_blocked_by_btc_filter(coin, signal: StrategySignal, btc_window):
    if coin == "BTC" or not btc_window:
        return False
    btc_dir = get_btc_direction_from_klines(btc_window)
    direction = getattr(signal, "direction", None)
    if btc_dir == "bull" and direction == "short":
        return True
    if btc_dir == "bear" and direction == "long":
        return True
    return False
