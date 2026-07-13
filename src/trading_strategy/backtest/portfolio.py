from trading_strategy.shared.state import build_default_state

from .alpha_overlay import apply_trend_alpha_entry_overlay
from .derivatives import (
    merge_derivatives_into_price_data,
    should_block_signal_for_derivatives,
    should_block_signal_for_oi_entry_filter,
)
from .data import get_coin_series
from .engine import BacktestEngine, close_position_at_bar
from .reporting import build_coin_results, build_portfolio_summary
from .strategies import is_signal_blocked_by_btc_filter, resolve_strategy
from .types import BacktestConfig, BacktestResult


class PortfolioBacktester:
    def __init__(self, *, config: BacktestConfig, strategy=None, derivatives_data_map=None):
        self.config = config
        self.strategy = strategy or resolve_strategy(config.strategy)
        self.derivatives_data_map = derivatives_data_map or {}
        self.engine = BacktestEngine(config=config, strategy=self._wrap_strategy())

    def _wrap_strategy(self):
        config = self.config
        strategy = self.strategy
        fallback_strategy = resolve_strategy(config.strategy)

        class FilteringStrategy:
            name = getattr(strategy, "name", config.strategy)

            def generate_signal(self, context):
                signal = strategy.generate_signal(context)
                if signal is None:
                    return None
                if config.btc_filter_enabled and self.should_block_for_btc(context.coin, signal, context.btc_window):
                    diagnostics = context.diagnostics
                    if diagnostics is not None:
                        diagnostics["btc_filtered_signals"] = int(diagnostics.get("btc_filtered_signals") or 0) + 1
                    return None
                if should_block_signal_for_derivatives(signal, context.window, config, context.diagnostics):
                    return None
                if should_block_signal_for_oi_entry_filter(signal, context.window, config, context.diagnostics):
                    return None
                return apply_trend_alpha_entry_overlay(signal, context, config)

            def build_exit_policy(self, *, signal=None, position=None):
                if hasattr(strategy, "build_exit_policy"):
                    return strategy.build_exit_policy(signal=signal, position=position)
                return fallback_strategy.build_exit_policy(signal=signal, position=position)

            def initialize_position(self, position, signal, context):
                if hasattr(strategy, "initialize_position"):
                    return strategy.initialize_position(position, signal, context)
                explicit_tp = position.get("tp")
                initialized = fallback_strategy.initialize_position(position, signal, context)
                if explicit_tp is not None:
                    initialized["tp"] = explicit_tp
                return initialized

            def should_block_for_btc(self, coin, signal, btc_window):
                if hasattr(strategy, "should_block_for_btc"):
                    return strategy.should_block_for_btc(coin, signal, btc_window)
                if hasattr(fallback_strategy, "should_block_for_btc"):
                    return fallback_strategy.should_block_for_btc(coin, signal, btc_window)
                return is_signal_blocked_by_btc_filter(coin, signal, btc_window)

            def evaluate_open_position(self, position, context):
                if hasattr(strategy, "evaluate_open_position"):
                    return strategy.evaluate_open_position(position, context)
                return fallback_strategy.evaluate_open_position(position, context)

            def resolve_stop_target(self, position, context):
                if hasattr(strategy, "resolve_stop_target"):
                    return strategy.resolve_stop_target(position, context)
                return fallback_strategy.resolve_stop_target(position, context)

        return FilteringStrategy()

    def run(self, data_map) -> BacktestResult:
        merge_diagnostics = {}
        source_data_map = data_map or {}
        data_map = {
            coin: list(source_data_map.get(coin, []))
            for coin in self.config.coins
            if coin in source_data_map
        }
        if "BTC" in source_data_map:
            data_map["BTC"] = list(source_data_map.get("BTC", []))
        data_map = merge_derivatives_into_price_data(data_map, self.derivatives_data_map, merge_diagnostics)
        normalized = {}
        for coin in self.config.coins:
            normalized[coin] = get_coin_series(data_map, coin, max_days=self.config.max_days)
        btc_series = get_coin_series(data_map, "BTC", max_days=self.config.max_days)

        state = build_default_state(
            {"strategy": self.config.strategy},
            initial_balance=self.config.initial_capital,
            strategy_name="backtest",
        )
        state["positions"] = []
        state["history"] = []
        state["initial_balance"] = self.config.initial_capital
        state["_config"] = self.config
        state["_diagnostics"] = {}
        state["_diagnostics"].update(merge_diagnostics)

        max_len = max((len(series) for series in normalized.values()), default=0)
        equity_curve = [self.config.initial_capital]
        peak_balance = self.config.initial_capital
        state["_diagnostics"]["missing_data_coins"] = [coin for coin, series in normalized.items() if not series]

        for index in range(self.config.min_bars, max_len):
            for coin in self.config.coins:
                series = normalized.get(coin, [])
                if len(series) <= index:
                    continue
                window = series[: index + 1]
                current_bar = window[-1]
                btc_window = btc_series[: index + 1] if len(btc_series) > index else btc_series
                self.engine.step(coin, current_bar, window, btc_window, state)
            current_balance = float(state.get("balance") or 0.0)
            equity_curve.append(current_balance)
            peak_balance = max(peak_balance, current_balance)

        open_positions = list(state.get("positions", []))
        for position in open_positions:
            coin = position["coin"]
            series = normalized.get(coin, [])
            if not series:
                continue
            active = next((item for item in state.get("positions", []) if item.get("coin") == coin), None)
            if active is None:
                continue
            state["positions"].remove(active)
            close_position_at_bar(state, active, series[-1], exit_reason="EOD")

        coin_results = build_coin_results(state, self.config.coins)
        portfolio = build_portfolio_summary(state, equity_curve, peak_balance)
        return BacktestResult(
            config=self.config,
            coin_results=coin_results,
            portfolio=portfolio,
            trades=list(state.get("history", [])),
            state=state,
            equity_curve=equity_curve,
        )
