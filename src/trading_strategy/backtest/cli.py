import argparse
from dataclasses import replace
import json

from trading_strategy.strategies import available_strategy_names

from .alpha import (
    DEFAULT_ALPHA_SET,
    DEFAULT_FORWARD_BARS,
    format_alpha_report_lines,
    parse_csv_tuple,
    run_alpha_report,
)
from .carry import (
    DEFAULT_CARRY_SET,
    DEFAULT_TREND_FORWARD_DAYS,
    CarryConfig,
    format_carry_report_lines,
    format_funding_trend_report_lines,
    run_carry_report,
    run_funding_trend_report,
)
from .data import DATA_PATH, DEFAULT_COINS, load_historical_data
from .derivatives import load_derivatives_data
from .evaluation import format_trend_evaluation_lines, run_trend_evaluation
from .microstructure import (
    build_microstructure_guard_outcome_report,
    format_microstructure_guard_outcome_lines,
    normalize_l2_snapshots,
)
from .optimizer import run_parameter_sweep
from .portfolio import PortfolioBacktester
from .research import format_research_report_lines, run_research_report
from .reporting import format_comparison_lines, format_optimization_lines, format_result_lines
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
    parser.add_argument("--derivatives-data-path", default="")
    parser.add_argument("--initial-capital", type=float, default=1000.0)
    parser.add_argument("--leverage", type=float, default=3.0)
    parser.add_argument("--risk-pct", type=float, default=0.05)
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--show-trades", action="store_true")
    parser.add_argument("--compare-strategies", default="")
    parser.add_argument("--research-report", action="store_true")
    parser.add_argument("--trend-evaluation-report", action="store_true")
    parser.add_argument("--evaluation-windows", default="120,180,240")
    parser.add_argument("--evaluation-min-trades", type=int, default=5)
    parser.add_argument("--microstructure-report", action="store_true")
    parser.add_argument("--microstructure-data-path", default="")
    parser.add_argument("--microstructure-forward-steps", default="1,3")
    parser.add_argument("--microstructure-max-spread-bps", type=float, default=8.0)
    parser.add_argument("--microstructure-min-top-depth-usd", type=float, default=1000.0)
    parser.add_argument("--microstructure-max-opposing-imbalance", type=float, default=0.65)
    parser.add_argument("--alpha-report", action="store_true")
    parser.add_argument("--alpha-set", default=",".join(DEFAULT_ALPHA_SET))
    parser.add_argument("--forward-bars", default=",".join(str(value) for value in DEFAULT_FORWARD_BARS))
    parser.add_argument("--bucket-count", type=int, default=10)
    parser.add_argument("--random-baseline-runs", type=int, default=200)
    parser.add_argument("--carry-report", action="store_true")
    parser.add_argument("--carry-set", default=",".join(DEFAULT_CARRY_SET))
    parser.add_argument("--funding-entry-abs", type=float, default=0.00008)
    parser.add_argument("--funding-exit-abs", type=float, default=0.00002)
    parser.add_argument("--basis-entry-abs-pct", type=float, default=0.04)
    parser.add_argument("--basis-exit-abs-pct", type=float, default=0.01)
    parser.add_argument("--carry-max-hold-days", type=int, default=14)
    parser.add_argument("--funding-periods-per-day", type=int, default=3)
    parser.add_argument("--funding-trend-report", action="store_true")
    parser.add_argument("--trend-forward-days", default=",".join(str(value) for value in DEFAULT_TREND_FORWARD_DAYS))
    parser.add_argument("--trend-price-lookback-days", type=int, default=3)
    parser.add_argument("--trend-funding-z-lookback", type=int, default=30)
    parser.add_argument("--trend-funding-z-threshold", type=float, default=0.75)
    parser.add_argument("--trend-basis-abs-threshold-pct", type=float, default=0.03)
    parser.add_argument("--disable-btc-filter", action="store_true")
    parser.add_argument("--enable-atr-trailing", action="store_true")
    parser.add_argument("--enable-adaptive-atr-trail", action="store_true")
    parser.add_argument("--adaptive-atr-strong-adx", type=float, default=35.0)
    parser.add_argument("--adaptive-atr-strong-mult", type=float, default=3.0)
    parser.add_argument("--adaptive-atr-weak-mult", type=float, default=1.5)
    parser.add_argument("--enable-failure-exit", action="store_true")
    parser.add_argument("--failure-exit-bars", type=int, default=3)
    parser.add_argument("--enable-intrabar-exit", action="store_true")
    parser.add_argument("--intrabar-fill-policy", choices=("stop_first", "target_first"), default="stop_first")
    parser.add_argument("--max-hold-bars", type=int, default=None)
    parser.add_argument("--disable-trend-entry-filter", action="store_true")
    parser.add_argument("--enable-derivatives-filter", action="store_true")
    parser.add_argument("--enable-oi-entry-filter", action="store_true")
    parser.add_argument("--oi-entry-lookback", type=int, default=5)
    parser.add_argument("--oi-entry-min-change-pct", type=float, default=0.0)
    parser.add_argument("--oi-entry-min-price-move-pct", type=float, default=0.1)
    parser.add_argument("--disable-oi-entry-block-late-crowded", action="store_true")
    parser.add_argument("--oi-entry-funding-extreme-abs", type=float, default=0.0005)
    parser.add_argument("--enable-trend-position-control", action="store_true")
    parser.add_argument("--enable-trend-alpha-entry", action="store_true")
    parser.add_argument("--trend-alpha-mode", choices=("filter", "score", "combined"), default="combined")
    parser.add_argument("--trend-alpha-score-boost", type=float, default=1.0)
    parser.add_argument("--trend-alpha-require-confirmation", action="store_true")
    parser.add_argument("--trend-alpha-block-crowded-entry", action="store_true", default=True)
    parser.add_argument("--enable-derivatives-crowding-exit", action="store_true")
    parser.add_argument("--derivatives-crowding-action", choices=("exit", "reduce"), default="exit")
    parser.add_argument("--derivatives-crowding-reduce-fraction", type=float, default=0.75)
    parser.add_argument("--derivatives-crowding-funding-z-lookback", type=int, default=30)
    parser.add_argument("--derivatives-crowding-funding-z-threshold", type=float, default=0.75)
    parser.add_argument("--derivatives-crowding-basis-abs-threshold-pct", type=float, default=0.03)
    parser.add_argument("--disable-price-position-filter", action="store_true")
    parser.add_argument("--disable-dead-cat-filter", action="store_true")
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--strategy-grid", default="trend")
    parser.add_argument("--leverage-grid", default="2,3,5")
    parser.add_argument("--risk-grid", default="0.03,0.05,0.08,0.10")
    parser.add_argument("--btc-filter-grid", default="on,off")
    return parser


def build_config(args):
    coins = tuple(coin.strip().upper() for coin in args.coins.split(",") if coin.strip())
    intrabar_exit_enabled = args.enable_intrabar_exit or args.strategy == "legacy_unified"
    price_position_filter_enabled = args.strategy == "legacy_unified" and not args.disable_price_position_filter
    dead_cat_filter_enabled = args.strategy == "legacy_unified" and not args.disable_dead_cat_filter
    return BacktestConfig(
        coins=coins,
        strategy=args.strategy,
        max_days=args.max_days,
        initial_capital=args.initial_capital,
        leverage=args.leverage,
        risk_pct=args.risk_pct,
        max_positions=args.max_positions,
        btc_filter_enabled=not args.disable_btc_filter,
        atr_trailing_enabled=args.enable_atr_trailing,
        adaptive_atr_trailing_enabled=args.enable_adaptive_atr_trail,
        adaptive_atr_strong_adx=args.adaptive_atr_strong_adx,
        adaptive_atr_strong_mult=args.adaptive_atr_strong_mult,
        adaptive_atr_weak_mult=args.adaptive_atr_weak_mult,
        failure_exit_enabled=args.enable_failure_exit,
        failure_exit_bars=args.failure_exit_bars,
        max_hold_bars=args.max_hold_bars,
        intrabar_exit_enabled=intrabar_exit_enabled,
        intrabar_fill_policy=args.intrabar_fill_policy,
        price_position_filter_enabled=price_position_filter_enabled,
        dead_cat_filter_enabled=dead_cat_filter_enabled,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        trend_entry_filter_enabled=not args.disable_trend_entry_filter,
        derivatives_filter_enabled=args.enable_derivatives_filter,
        oi_entry_filter_enabled=args.enable_oi_entry_filter,
        oi_entry_filter_lookback=args.oi_entry_lookback,
        oi_entry_filter_min_change_pct=args.oi_entry_min_change_pct,
        oi_entry_filter_min_price_move_pct=args.oi_entry_min_price_move_pct,
        oi_entry_filter_block_late_crowded=not args.disable_oi_entry_block_late_crowded,
        oi_entry_filter_funding_extreme_abs=args.oi_entry_funding_extreme_abs,
        derivatives_crowding_exit_enabled=args.enable_derivatives_crowding_exit or args.enable_trend_position_control,
        derivatives_crowding_action="reduce" if args.enable_trend_position_control else args.derivatives_crowding_action,
        derivatives_crowding_reduce_fraction=args.derivatives_crowding_reduce_fraction,
        derivatives_crowding_funding_z_lookback=args.derivatives_crowding_funding_z_lookback,
        derivatives_crowding_funding_z_threshold=args.derivatives_crowding_funding_z_threshold,
        derivatives_crowding_basis_abs_threshold_pct=args.derivatives_crowding_basis_abs_threshold_pct,
        trend_alpha_entry_enabled=args.enable_trend_alpha_entry,
        trend_alpha_mode=args.trend_alpha_mode,
        trend_alpha_score_boost=args.trend_alpha_score_boost,
        trend_alpha_require_confirmation=args.trend_alpha_require_confirmation,
        trend_alpha_block_crowded_entry=args.trend_alpha_block_crowded_entry,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.microstructure_report:
        if not args.microstructure_data_path:
            parser.error("--microstructure-data-path is required with --microstructure-report")
        with open(args.microstructure_data_path, "r", encoding="utf-8") as handle:
            snapshots = normalize_l2_snapshots(json.load(handle))
        report = build_microstructure_guard_outcome_report(
            snapshots,
            max_spread_bps=args.microstructure_max_spread_bps,
            min_top_depth_usd=args.microstructure_min_top_depth_usd,
            max_opposing_imbalance=args.microstructure_max_opposing_imbalance,
            forward_steps=tuple(_parse_csv_values(args.microstructure_forward_steps, int)),
        )
        for line in format_microstructure_guard_outcome_lines(report):
            print(line)
        return report
    coins = tuple(coin.strip().upper() for coin in args.coins.split(",") if coin.strip())
    derivatives_data_map = load_derivatives_data(args.derivatives_data_path)
    if args.carry_report:
        report = run_carry_report(
            derivatives_data_map,
            config=CarryConfig(
                coins=coins,
                max_days=args.max_days,
                carry_set=parse_csv_tuple(args.carry_set, str),
                funding_entry_abs=args.funding_entry_abs,
                funding_exit_abs=args.funding_exit_abs,
                basis_entry_abs_pct=args.basis_entry_abs_pct,
                basis_exit_abs_pct=args.basis_exit_abs_pct,
                max_hold_days=args.carry_max_hold_days,
                fee_bps=args.fee_bps,
                slippage_bps=args.slippage_bps,
                funding_periods_per_day=args.funding_periods_per_day,
            ),
        )
        for line in format_carry_report_lines(report):
            print(line)
        return report
    data_map = load_historical_data(args.data_path)
    if args.trend_evaluation_report:
        candidate_config = build_config(args)
        baseline_config = replace(candidate_config, adaptive_atr_trailing_enabled=False)
        requested_coins = set(candidate_config.coins)
        universes = []
        for universe in (("BTC",), ("BTC", "ETH", "BNB"), ("BTC", "ETH", "BNB", "XRP", "DOGE", "ADA", "LINK", "LTC")):
            filtered = tuple(coin for coin in universe if coin in requested_coins)
            if filtered and filtered not in universes:
                universes.append(filtered)
        report = run_trend_evaluation(
            data_map,
            derivatives_data_map=derivatives_data_map,
            baseline_config=baseline_config,
            candidate_config=candidate_config,
            windows=tuple(_parse_csv_values(args.evaluation_windows, int)),
            universes=tuple(universes),
            min_trades=max(int(args.evaluation_min_trades), 1),
        )
        for line in format_trend_evaluation_lines(report):
            print(line)
        return report
    if args.funding_trend_report:
        report = run_funding_trend_report(
            data_map,
            derivatives_data_map,
            config=CarryConfig(
                coins=coins,
                max_days=args.max_days,
                trend_forward_days=parse_csv_tuple(args.trend_forward_days, int),
                trend_price_lookback_days=args.trend_price_lookback_days,
                trend_funding_z_lookback=args.trend_funding_z_lookback,
                trend_funding_z_threshold=args.trend_funding_z_threshold,
                trend_basis_abs_threshold_pct=args.trend_basis_abs_threshold_pct,
            ),
        )
        for line in format_funding_trend_report_lines(report):
            print(line)
        return report
    if args.alpha_report:
        report = run_alpha_report(
            data_map,
            derivatives_data_map=derivatives_data_map,
            coins=coins,
            max_days=args.max_days,
            alpha_set=parse_csv_tuple(args.alpha_set, str),
            forward_bars=parse_csv_tuple(args.forward_bars, int),
            bucket_count=args.bucket_count,
            random_baseline_runs=args.random_baseline_runs,
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
        )
        for line in format_alpha_report_lines(report):
            print(line)
        return report
    if args.research_report:
        report = run_research_report(
            data_map,
            derivatives_data_map=derivatives_data_map,
            coins=coins,
            max_days=args.max_days,
            initial_capital=args.initial_capital,
            fee_bps=args.fee_bps or 4.5,
            slippage_bps=args.slippage_bps,
        )
        for line in format_research_report_lines(report):
            print(line)
        return report
    if args.optimize:
        rows = run_parameter_sweep(
            data_map,
            coins=coins,
            max_days=args.max_days,
            initial_capital=args.initial_capital,
            max_positions=args.max_positions,
            strategies=_parse_csv_values(args.strategy_grid, str),
            leverages=_parse_csv_values(args.leverage_grid, float),
            risk_pcts=_parse_csv_values(args.risk_grid, float),
            btc_filter_modes=_parse_btc_filter_grid(args.btc_filter_grid),
            atr_trailing_modes=(False, True),
            fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
        )
        for line in format_optimization_lines(rows, top_n=args.top):
            print(line)
        return rows
    compare_strategies = tuple(item.strip() for item in str(args.compare_strategies or "").split(",") if item.strip())
    if compare_strategies:
        results = {}
        for strategy_name in compare_strategies:
            args.strategy = strategy_name
            config = build_config(args)
            results[strategy_name] = PortfolioBacktester(config=config, derivatives_data_map=derivatives_data_map).run(data_map)
        for line in format_comparison_lines(results):
            print(line)
        return results
    config = build_config(args)
    result = PortfolioBacktester(config=config, derivatives_data_map=derivatives_data_map).run(data_map)
    for line in format_result_lines(result, show_trades=args.show_trades):
        print(line)
    return result
