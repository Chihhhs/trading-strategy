import argparse

from trading_strategy.strategies import available_strategy_names

from .data import DATA_PATH, DEFAULT_COINS, load_historical_data
from .optimizer import run_parameter_sweep
from .portfolio import PortfolioBacktester
from .reporting import format_optimization_lines, format_result_lines
from .types import BacktestConfig


def _parse_csv_values(raw_value, cast):
    return [cast(item.strip()) for item in str(raw_value).split(",") if item.strip()]


def _parse_btc_filter_grid(raw_value):
    values = []
    for item in str(raw_value).split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value in ("on", "true", "1"):
            values.append(True)
        elif value in ("off", "false", "0"):
            values.append(False)
    return values or [True]


def build_parser():
    parser = argparse.ArgumentParser()
    strategy_names = available_strategy_names()
    parser.add_argument("--coins", default=",".join(DEFAULT_COINS))
    parser.add_argument("--strategy", choices=strategy_names, default="trend")
    parser.add_argument("--max-days", type=int, default=240)
    parser.add_argument("--data-path", default=DATA_PATH)
    parser.add_argument("--initial-capital", type=float, default=1000.0)
    parser.add_argument("--leverage", type=float, default=3.0)
    parser.add_argument("--risk-pct", type=float, default=0.05)
    parser.add_argument("--show-trades", action="store_true")
    parser.add_argument("--disable-btc-filter", action="store_true")
    parser.add_argument("--enable-atr-trailing", action="store_true")
    parser.add_argument("--enable-failure-exit", action="store_true")
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--strategy-grid", default="trend")
    parser.add_argument("--leverage-grid", default="2,3,5")
    parser.add_argument("--risk-grid", default="0.03,0.05,0.08,0.10")
    parser.add_argument("--btc-filter-grid", default="on,off")
    return parser


def build_config(args):
    coins = tuple(coin.strip().upper() for coin in args.coins.split(",") if coin.strip())
    return BacktestConfig(
        coins=coins,
        strategy=args.strategy,
        max_days=args.max_days,
        initial_capital=args.initial_capital,
        leverage=args.leverage,
        risk_pct=args.risk_pct,
        btc_filter_enabled=not args.disable_btc_filter,
        atr_trailing_enabled=args.enable_atr_trailing,
        failure_exit_enabled=args.enable_failure_exit,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    data_map = load_historical_data(args.data_path)
    if args.optimize:
        rows = run_parameter_sweep(
            data_map,
            coins=tuple(coin.strip().upper() for coin in args.coins.split(",") if coin.strip()),
            max_days=args.max_days,
            initial_capital=args.initial_capital,
            strategies=_parse_csv_values(args.strategy_grid, str),
            leverages=_parse_csv_values(args.leverage_grid, float),
            risk_pcts=_parse_csv_values(args.risk_grid, float),
            btc_filter_modes=_parse_btc_filter_grid(args.btc_filter_grid),
            atr_trailing_modes=(False, True),
        )
        for line in format_optimization_lines(rows, top_n=args.top):
            print(line)
        return rows
    config = build_config(args)
    result = PortfolioBacktester(config=config).run(data_map)
    for line in format_result_lines(result, show_trades=args.show_trades):
        print(line)
    return result
