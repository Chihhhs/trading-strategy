from dataclasses import dataclass, field
from typing import Any, Protocol


DEFAULT_INITIAL_CAPITAL = 1000.0
DEFAULT_LEVERAGE = 3.0
DEFAULT_RISK_PCT = 0.05


@dataclass(frozen=True)
class BacktestConfig:
    coins: tuple[str, ...]
    strategy: str = "trend"
    max_days: int | None = 240
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    leverage: float = DEFAULT_LEVERAGE
    risk_pct: float = DEFAULT_RISK_PCT
    btc_filter_enabled: bool = True
    min_bars: int = 50
    atr_trailing_enabled: bool = False
    atr_activation_r: float = 1.5
    atr_trailing_mult: float = 2.0
    failure_exit_enabled: bool = False
    failure_exit_bars: int = 3
    failure_exit_mode: str = "breakout_failure"


@dataclass(frozen=True)
class StrategySignal:
    direction: str
    tp: float
    sl: float
    score: int | float
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyContext:
    coin: str
    window: list[dict[str, Any]]
    current_bar: dict[str, Any]
    btc_window: list[dict[str, Any]] | None
    balance: float
    open_positions: tuple[dict[str, Any], ...]
    config: BacktestConfig


@dataclass(frozen=True)
class CoinResult:
    coin: str
    trades: int
    wins: int
    win_rate: float
    ending_balance: float
    total_pnl: float
    total_pnl_pct: float
    max_drawdown: float


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    coin_results: list[CoinResult]
    portfolio: dict[str, Any]
    trades: list[dict[str, Any]]
    state: dict[str, Any]
    equity_curve: list[float]


class BacktestStrategy(Protocol):
    name: str

    def generate_signal(self, context: StrategyContext) -> StrategySignal | None:
        ...
