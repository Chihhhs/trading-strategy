from .cli import build_config, build_parser, main
from .data import DATA_PATH, DEFAULT_COINS, get_coin_series, load_historical_data
from .derivatives import load_derivatives_data, normalize_derivatives_data_map
from .optimizer import run_parameter_sweep
from .portfolio import PortfolioBacktester
from .research import format_research_report_lines, run_research_report
from .reporting import format_optimization_lines, format_result_lines
from .strategies import resolve_strategy
from .types import BacktestConfig, BacktestResult, CoinResult, StrategyContext, StrategySignal


def run_backtest_for_coin(coin, data_map, strategy_type="trend", max_days=None):
    config = BacktestConfig(
        coins=(coin,),
        strategy=strategy_type,
        max_days=max_days,
    )
    result = PortfolioBacktester(config=config).run(data_map)
    return result.coin_results[0].__dict__ if result.coin_results else None


__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "CoinResult",
    "DATA_PATH",
    "DEFAULT_COINS",
    "PortfolioBacktester",
    "StrategyContext",
    "StrategySignal",
    "build_config",
    "build_parser",
    "format_optimization_lines",
    "format_research_report_lines",
    "format_result_lines",
    "get_coin_series",
    "load_historical_data",
    "load_derivatives_data",
    "main",
    "normalize_derivatives_data_map",
    "resolve_strategy",
    "run_parameter_sweep",
    "run_backtest_for_coin",
    "run_research_report",
]
