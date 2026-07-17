"""Small fixed-unit ledger for isolated portfolio paper execution."""

from dataclasses import asdict, dataclass, field


@dataclass
class PaperPortfolio:
    cash: float
    positions: dict[str, float]
    prices: dict[str, float]
    equity: float
    last_time: int
    fees_paid: float = 0.0
    funding_pnl: float = 0.0
    price_pnl: float = 0.0
    turnover_notional: float = 0.0
    coin_pnl: dict[str, float] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def open_portfolio(*, timestamp, prices, target_weights, equity=1000.0, one_way_cost_bps=6.5):
    if equity <= 0 or any(price <= 0 for price in prices.values()):
        raise ValueError("paper portfolio requires positive equity and prices")
    positions = {coin: target_weights.get(coin, 0.0) * equity / price for coin, price in prices.items()}
    turnover = sum(abs(quantity * prices[coin]) for coin, quantity in positions.items())
    fee = turnover * one_way_cost_bps / 10_000.0
    cash = equity - sum(positions[coin] * prices[coin] for coin in positions) - fee
    return PaperPortfolio(
        cash=cash,
        positions=positions,
        prices=dict(prices),
        equity=equity - fee,
        last_time=int(timestamp),
        fees_paid=fee,
        turnover_notional=turnover,
        coin_pnl={coin: 0.0 for coin in positions},
    )


def mark_portfolio(state, *, timestamp, prices, funding_rates=None):
    if int(timestamp) <= state.last_time:
        raise ValueError("paper portfolio timestamps must increase")
    if set(prices) != set(state.positions) or any(price <= 0 for price in prices.values()):
        raise ValueError("paper portfolio prices must cover every position")
    rates = funding_rates or {}
    price_changes = {
        coin: state.positions[coin] * (prices[coin] - state.prices[coin])
        for coin in state.positions
    }
    state.price_pnl += sum(price_changes.values())
    funding_by_coin = {
        coin: -state.positions[coin] * prices[coin] * float(rates.get(coin, 0.0))
        for coin in state.positions
    }
    funding_pnl = sum(funding_by_coin.values())
    for coin in state.positions:
        state.coin_pnl[coin] += price_changes[coin] + funding_by_coin[coin]
    state.cash += funding_pnl
    state.funding_pnl += funding_pnl
    state.prices = dict(prices)
    state.equity = state.cash + sum(state.positions[coin] * prices[coin] for coin in state.positions)
    state.last_time = int(timestamp)
    return state


def rebalance_portfolio(state, *, target_weights, one_way_cost_bps=6.5):
    target_positions = {
        coin: target_weights.get(coin, 0.0) * state.equity / state.prices[coin]
        for coin in state.positions
    }
    turnover = sum(
        abs(target_positions[coin] - state.positions[coin]) * state.prices[coin]
        for coin in state.positions
    )
    fee = turnover * one_way_cost_bps / 10_000.0
    state.cash = state.equity - sum(
        target_positions[coin] * state.prices[coin]
        for coin in state.positions
    ) - fee
    state.positions = target_positions
    state.equity -= fee
    state.fees_paid += fee
    state.turnover_notional += turnover
    return state


__all__ = ["PaperPortfolio", "mark_portfolio", "open_portfolio", "rebalance_portfolio"]
