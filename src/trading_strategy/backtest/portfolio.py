from trading_strategy.core.state import build_default_state

from .data import get_coin_series
from .engine import BacktestEngine, close_position_at_bar
from .reporting import build_coin_results, build_portfolio_summary
from .strategies import is_signal_blocked_by_btc_filter, resolve_strategy
from .types import BacktestConfig, BacktestResult


class PortfolioBacktester:
    def __init__(self, *, config: BacktestConfig, strategy=None):
        self.config = config
        self.strategy = strategy or resolve_strategy(config.strategy)
        self.engine = BacktestEngine(config=config, strategy=self._wrap_strategy())

    def _wrap_strategy(self):
        config = self.config
        strategy = self.strategy

        class FilteringStrategy:
            name = getattr(strategy, "name", config.strategy)

            def generate_signal(self, context):
                signal = strategy.generate_signal(context)
                if signal is None:
                    return None
                if config.btc_filter_enabled and is_signal_blocked_by_btc_filter(
                    context.coin,
                    signal,
                    context.btc_window,
                ):
                    return None
                return signal

        return FilteringStrategy()

    def run(self, data_map) -> BacktestResult:
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

        max_len = max((len(series) for series in normalized.values()), default=0)
        equity_curve = [self.config.initial_capital]
        peak_balance = self.config.initial_capital

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
