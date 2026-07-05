from trading_strategy.core.signals import generate_fvg_signal, get_btc_direction_from_klines

from .types import BacktestStrategy, StrategyContext, StrategySignal


class CoreSignalStrategy:
    def __init__(self, strategy_type="both"):
        self.name = strategy_type
        self.strategy_type = strategy_type

    def generate_signal(self, context: StrategyContext) -> StrategySignal | None:
        signal = generate_fvg_signal(context.window, strategy_type=self.strategy_type)
        if signal is None:
            return None
        return StrategySignal(
            direction=signal["direction"],
            tp=float(signal["tp"]),
            sl=float(signal["sl"]),
            score=signal["score"],
            reason=signal.get("reason", ""),
            raw=dict(signal),
        )


def resolve_strategy(strategy_type="both") -> BacktestStrategy:
    return CoreSignalStrategy(strategy_type=strategy_type)


def is_signal_blocked_by_btc_filter(coin, signal: StrategySignal, btc_window):
    if coin == "BTC" or not btc_window:
        return False
    btc_dir = get_btc_direction_from_klines(btc_window)
    if btc_dir == "bull" and signal.direction == "short":
        return True
    if btc_dir == "bear" and signal.direction == "long":
        return True
    return False
