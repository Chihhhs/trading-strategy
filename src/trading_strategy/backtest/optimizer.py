from .portfolio import PortfolioBacktester
from .types import BacktestConfig


def _calc_score(summary, *, drawdown_weight=0.5):
    return round(float(summary["total_pnl_pct"]) - float(summary["max_drawdown"]) * drawdown_weight, 2)


def run_parameter_sweep(
    data_map,
    *,
    coins,
    max_days,
    initial_capital,
    strategies,
    leverages,
    risk_pcts,
    btc_filter_modes,
):
    results = []
    for strategy in strategies:
        for leverage in leverages:
            for risk_pct in risk_pcts:
                for btc_filter_enabled in btc_filter_modes:
                    config = BacktestConfig(
                        coins=coins,
                        strategy=strategy,
                        max_days=max_days,
                        initial_capital=initial_capital,
                        leverage=leverage,
                        risk_pct=risk_pct,
                        btc_filter_enabled=btc_filter_enabled,
                    )
                    result = PortfolioBacktester(config=config).run(data_map)
                    summary = result.portfolio
                    results.append(
                        {
                            "strategy": strategy,
                            "leverage": leverage,
                            "risk_pct": risk_pct,
                            "btc_filter_enabled": btc_filter_enabled,
                            "trades": summary["trades"],
                            "win_rate": summary["win_rate"],
                            "total_pnl_pct": summary["total_pnl_pct"],
                            "max_drawdown": summary["max_drawdown"],
                            "score": _calc_score(summary),
                        }
                    )
    results.sort(key=lambda item: (item["score"], item["total_pnl_pct"]), reverse=True)
    return results
