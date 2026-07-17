"""Cost-aware portfolio evaluator for the clean-room strength strategy."""

from dataclasses import dataclass


def _timestamp(bar):
    value = bar.get("ts", bar.get("time", bar.get("open_time", bar.get("t"))))
    return value


@dataclass(frozen=True)
class CrossSectionalBacktestResult:
    trades: int
    net_pnl_pct: float
    gross_pnl_pct: float
    max_drawdown_pct: float
    turnover: float
    coin_contributions: dict[str, float]
    rebalance_count: int


class CrossSectionalStrengthBacktester:
    def __init__(self, *, initial_capital, fee_bps, slippage_bps, parameters):
        self.initial_capital = float(initial_capital)
        self.cost_rate = (float(fee_bps) + float(slippage_bps)) / 10000.0
        self.lookback = int(parameters.lookback_days)
        self.rebalance_days = int(parameters.rebalance_days)
        self.top_n = int(parameters.top_n)
        self.min_momentum = float(parameters.min_momentum_pct) / 100.0
        self.min_positive_fraction = float(parameters.min_positive_fraction)
        if self.lookback < 2 or self.rebalance_days < 1 or self.top_n < 1:
            raise ValueError("cross-sectional parameters must be positive")
        if not 0.0 <= self.min_positive_fraction <= 1.0:
            raise ValueError("min_positive_fraction must be between zero and one")

    def run(self, data_map, *, coins, max_days=None):
        series = {}
        for coin in coins:
            bars = list(data_map.get(coin, []))
            if max_days is not None:
                bars = bars[-int(max_days) :]
            points = {_timestamp(bar): float(bar["close"]) for bar in bars if _timestamp(bar) is not None}
            if points:
                series[coin] = points
        if not series:
            return CrossSectionalBacktestResult(0, 0.0, 0.0, 0.0, 0.0, {}, 0)
        timestamps = sorted(set.intersection(*(set(points) for points in series.values())))
        if len(timestamps) <= self.lookback + 1:
            return CrossSectionalBacktestResult(0, 0.0, 0.0, 0.0, 0.0, 0.0, {}, 0)

        weights = {}
        net_equity = self.initial_capital
        gross_equity = self.initial_capital
        peak = net_equity
        max_drawdown = 0.0
        turnover = 0.0
        trades = 0
        rebalances = 0
        contributions = {coin: 0.0 for coin in series}

        for index in range(self.lookback, len(timestamps)):
            current_time = timestamps[index]
            previous_time = timestamps[index - 1]
            daily_returns = {
                coin: series[coin][current_time] / series[coin][previous_time] - 1.0
                for coin in series
            }
            portfolio_return = sum(weights.get(coin, 0.0) * value for coin, value in daily_returns.items())
            gross_equity *= 1.0 + portfolio_return
            net_equity *= 1.0 + portfolio_return
            for coin, value in daily_returns.items():
                contributions[coin] += weights.get(coin, 0.0) * value * 100.0

            if (index - self.lookback) % self.rebalance_days == 0:
                signal_time = timestamps[index]
                lookback_time = timestamps[index - self.lookback]
                ranked = sorted(
                    (
                        (series[coin][signal_time] / series[coin][lookback_time] - 1.0, coin)
                        for coin in series
                    ),
                    reverse=True,
                )
                positive_fraction = sum(momentum > 0.0 for momentum, _coin in ranked) / len(ranked)
                selected = (
                    [coin for momentum, coin in ranked if momentum > self.min_momentum][: self.top_n]
                    if positive_fraction >= self.min_positive_fraction
                    else []
                )
                target = {coin: 1.0 / len(selected) for coin in selected} if selected else {}
                changed = set(weights) | set(target)
                rebalance_turnover = sum(abs(target.get(coin, 0.0) - weights.get(coin, 0.0)) for coin in changed)
                trades += sum(1 for coin in changed if abs(target.get(coin, 0.0) - weights.get(coin, 0.0)) > 1e-12)
                turnover += rebalance_turnover
                net_equity *= max(1.0 - rebalance_turnover * self.cost_rate, 0.0)
                weights = target
                rebalances += 1

            peak = max(peak, net_equity)
            drawdown = (peak - net_equity) / peak * 100.0 if peak else 0.0
            max_drawdown = max(max_drawdown, drawdown)

        return CrossSectionalBacktestResult(
            trades=trades,
            net_pnl_pct=(net_equity / self.initial_capital - 1.0) * 100.0,
            gross_pnl_pct=(gross_equity / self.initial_capital - 1.0) * 100.0,
            max_drawdown_pct=max_drawdown,
            turnover=turnover,
            coin_contributions={coin: value for coin, value in contributions.items() if value},
            rebalance_count=rebalances,
        )
