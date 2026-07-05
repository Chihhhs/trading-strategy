import argparse

from .data import DATA_PATH, DEFAULT_COINS, load_historical_data
from .portfolio import PortfolioBacktester
from .reporting import format_result_lines
from .types import BacktestConfig


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", default=",".join(DEFAULT_COINS))
    parser.add_argument("--strategy", choices=("fvg", "trend", "both"), default="both")
    parser.add_argument("--max-days", type=int, default=240)
    parser.add_argument("--data-path", default=DATA_PATH)
    parser.add_argument("--initial-capital", type=float, default=1000.0)
    parser.add_argument("--leverage", type=float, default=3.0)
    parser.add_argument("--risk-pct", type=float, default=0.05)
    parser.add_argument("--show-trades", action="store_true")
    parser.add_argument("--disable-btc-filter", action="store_true")
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
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    config = build_config(args)
    data_map = load_historical_data(args.data_path)
    result = PortfolioBacktester(config=config).run(data_map)
    for line in format_result_lines(result, show_trades=args.show_trades):
        print(line)
    return result
