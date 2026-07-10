from .portfolio import PortfolioBacktester
from .reporting import calc_score
from .types import BacktestConfig


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
    max_positions=None,
    atr_trailing_modes=(False,),
    fee_bps=0.0,
    slippage_bps=0.0,
):
    results = []
    for strategy in strategies:
        for leverage in leverages:
            for risk_pct in risk_pcts:
                for btc_filter_enabled in btc_filter_modes:
                    for atr_trailing_enabled in atr_trailing_modes:
                        config = BacktestConfig(
                            coins=coins,
                            strategy=strategy,
                            max_days=max_days,
                            initial_capital=initial_capital,
                            max_positions=max_positions,
                            leverage=leverage,
                            risk_pct=risk_pct,
                            btc_filter_enabled=btc_filter_enabled,
                            atr_trailing_enabled=atr_trailing_enabled,
                            intrabar_exit_enabled=(strategy == "legacy_unified"),
                            price_position_filter_enabled=(strategy == "legacy_unified"),
                            dead_cat_filter_enabled=(strategy == "legacy_unified"),
                            fee_bps=fee_bps,
                            slippage_bps=slippage_bps,
                        )
                        result = PortfolioBacktester(config=config).run(data_map)
                        summary = result.portfolio
                        results.append(
                            {
                                "strategy": strategy,
                                "leverage": leverage,
                                "risk_pct": risk_pct,
                                "btc_filter_enabled": btc_filter_enabled,
                                "atr_trailing_enabled": atr_trailing_enabled,
                                "trades": summary["trades"],
                                "win_rate": summary["win_rate"],
                                "avg_hold_bars": summary.get("avg_hold_bars", 0.0),
                                "total_pnl_pct": summary["total_pnl_pct"],
                                "gross_pnl_pct": summary.get("gross_pnl_pct", summary["total_pnl_pct"]),
                                "total_cost_pct": summary.get("total_cost_pct", 0.0),
                                "max_drawdown": summary["max_drawdown"],
                                "atr_trail_exits": (summary.get("exit_reason_counts") or {}).get("ATR_TRAIL", 0),
                                "score": calc_score(summary),
                            }
                        )
    results.sort(key=lambda item: (item["score"], item["total_pnl_pct"]), reverse=True)
    return results
