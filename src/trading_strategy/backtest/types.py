from dataclasses import dataclass
from typing import Any, Protocol

from trading_strategy.strategies.base import StrategyContext, StrategySignal

DEFAULT_INITIAL_CAPITAL = 1000.0
DEFAULT_LEVERAGE = 3.0
DEFAULT_RISK_PCT = 0.05


@dataclass(frozen=True)
class BacktestConfig:
    coins: tuple[str, ...]
    strategy: str = "trend"
    strategy_parameters: dict[str, Any] | None = None
    max_days: int | None = 240
    initial_capital: float = DEFAULT_INITIAL_CAPITAL
    leverage: float = DEFAULT_LEVERAGE
    risk_pct: float = DEFAULT_RISK_PCT
    max_positions: int | None = None
    btc_filter_enabled: bool = True
    min_bars: int = 50
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
    intraday_cooldown_bars: int = 0
    intraday_max_range_pct: float | None = None
    intrabar_exit_enabled: bool = False
    intrabar_fill_policy: str = "stop_first"
    price_position_filter_enabled: bool = False
    dead_cat_filter_enabled: bool = False
    regime_mode: str = "auto"
    long_term_min_score: float = 4.0
    short_term_min_score: float = 5.0
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
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
    derivatives_funding_upper: float = 0.0005
    derivatives_funding_lower: float = -0.0005
    derivatives_basis_upper: float = 1.0
    derivatives_basis_lower: float = -1.0
    derivatives_oi_lookback: int = 5
    derivatives_min_oi_change_long: float = -10.0
    derivatives_max_oi_change_short: float = 10.0
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
