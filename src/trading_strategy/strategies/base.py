from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class StrategySignal:
    direction: str
    tp: float | None
    sl: float | None
    score: int | float
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyContext:
    coin: str
    window: list[dict[str, Any]]
    current_bar: dict[str, Any] | None = None
    btc_window: list[dict[str, Any]] | None = None
    balance: float = 0.0
    open_positions: tuple[dict[str, Any], ...] = ()
    config: Any = None
    mode: str = "paper"
    price: float | None = None
    diagnostics: dict[str, Any] | None = None


class Strategy(Protocol):
    name: str

    def generate_signal(self, context: StrategyContext):
        ...

    def build_exit_policy(self, *, signal=None, position=None):
        ...

    def initialize_position(self, position, signal, context: StrategyContext):
        ...

    def should_block_for_btc(self, coin, signal, btc_window):
        ...

    def evaluate_open_position(self, position, context: StrategyContext):
        ...

    def resolve_stop_target(self, position, context: StrategyContext):
        ...


class BaseStrategy:
    name = ""

    def build_exit_policy(self, *, signal=None, position=None):
        return {
            "name": "fixed_tpsl",
            "requires_tp": True,
            "requires_sl": True,
            "protection_event_prefix": "tpsl",
        }

    def initialize_position(self, position, signal, context: StrategyContext):
        return position

    def should_block_for_btc(self, coin, signal, btc_window):
        return False

    def evaluate_open_position(self, position, context: StrategyContext):
        return {}

    def resolve_stop_target(self, position, context: StrategyContext):
        return None


def signal_value(signal, key, default=None):
    if isinstance(signal, dict):
        return signal.get(key, default)
    return getattr(signal, key, default)
