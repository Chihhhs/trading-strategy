"""Repeatable robustness checks for frozen trend candidates."""

from dataclasses import replace

from .portfolio import PortfolioBacktester


def _exit_diagnostics(trades):
    rows = {}
    for reason in sorted({trade.get("exit_reason") for trade in trades if trade.get("exit_reason")}):
        subset = [trade for trade in trades if trade.get("exit_reason") == reason]
        mfe_r_values = [float(item["mfe_r"]) for item in subset if item.get("mfe_r") is not None]
        mae_r_values = [float(item["mae_r"]) for item in subset if item.get("mae_r") is not None]
        rows[reason] = {
            "trades": len(subset),
            "avg_pnl_pct": round(sum(float(item.get("pnl_pct") or 0.0) for item in subset) / len(subset), 3),
            "avg_hold_bars": round(sum(float(item.get("hold_bars") or 0.0) for item in subset) / len(subset), 2),
            "avg_mfe_pct": round(sum(float(item.get("mfe_pct") or 0.0) for item in subset) / len(subset), 3),
            "avg_mae_pct": round(sum(float(item.get("mae_pct") or 0.0) for item in subset) / len(subset), 3),
            "avg_mfe_r": round(sum(mfe_r_values) / len(mfe_r_values), 3) if mfe_r_values else None,
            "avg_mae_r": round(sum(mae_r_values) / len(mae_r_values), 3) if mae_r_values else None,
        }
    return rows


def _price_return_correlations(data_map, coins):
    returns = {}
    for coin in coins:
        closes = [float(bar.get("close") or 0.0) for bar in (data_map or {}).get(coin, [])]
        returns[coin] = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes)) if closes[index - 1]]
    rows = []
    for index, left in enumerate(coins):
        for right in coins[index + 1 :]:
            paired = list(zip(returns.get(left, []), returns.get(right, [])))
            if len(paired) < 2:
                value = None
            else:
                left_values, right_values = zip(*paired)
                left_mean = sum(left_values) / len(left_values)
                right_mean = sum(right_values) / len(right_values)
                numerator = sum((a - left_mean) * (b - right_mean) for a, b in paired)
                left_scale = sum((a - left_mean) ** 2 for a in left_values) ** 0.5
                right_scale = sum((b - right_mean) ** 2 for b in right_values) ** 0.5
                value = round(numerator / (left_scale * right_scale), 3) if left_scale and right_scale else None
            rows.append({"left": left, "right": right, "correlation": value})
    return rows


def run_trend_evaluation(
    data_map,
    *,
    baseline_config,
    candidate_config,
    derivatives_data_map=None,
    baseline_strategy=None,
    candidate_strategy=None,
    windows=(120, 180, 240),
    universes=(("BTC",), ("BTC", "ETH", "BNB"), ("BTC", "ETH", "BNB", "XRP", "DOGE", "ADA", "LINK", "LTC")),
    min_trades=5,
):
    comparisons = []
    for window in windows:
        for universe in universes:
            coins = tuple(coin for coin in universe if coin in (data_map or {}))
            if not coins:
                continue
            baseline = PortfolioBacktester(
                config=replace(baseline_config, coins=coins, max_days=window),
                strategy=baseline_strategy,
                derivatives_data_map=derivatives_data_map,
            ).run(data_map)
            candidate = PortfolioBacktester(
                config=replace(candidate_config, coins=coins, max_days=window),
                strategy=candidate_strategy,
                derivatives_data_map=derivatives_data_map,
            ).run(data_map)
            baseline_summary = baseline.portfolio
            candidate_summary = candidate.portfolio
            comparisons.append(
                {
                    "coins": coins,
                    "window": window,
                    "baseline": baseline_summary,
                    "candidate": candidate_summary,
                    "net_pnl_delta_pct": round(float(candidate_summary.get("total_pnl_pct") or 0.0) - float(baseline_summary.get("total_pnl_pct") or 0.0), 2),
                    "drawdown_delta_pct": round(float(candidate_summary.get("max_drawdown") or 0.0) - float(baseline_summary.get("max_drawdown") or 0.0), 2),
                    "score_delta": round(float(candidate_summary.get("score") or 0.0) - float(baseline_summary.get("score") or 0.0), 2),
                    "coin_contributions": [item.__dict__ for item in candidate.coin_results],
                    "price_return_correlations": _price_return_correlations(data_map, coins),
                    "exit_diagnostics": _exit_diagnostics(candidate.trades),
                }
            )
    eligible = [
        row
        for row in comparisons
        if int(row["baseline"].get("trades") or 0) >= min_trades
        and int(row["candidate"].get("trades") or 0) >= min_trades
    ]
    non_worse = sum(1 for row in eligible if row["net_pnl_delta_pct"] >= 0 and row["drawdown_delta_pct"] <= 0)
    return {
        "comparisons": comparisons,
        "summary": {
            "comparisons": len(comparisons),
            "min_trades_per_comparison": min_trades,
            "eligible_comparisons": len(eligible),
            "insufficient_trade_comparisons": len(comparisons) - len(eligible),
            "non_worse_comparisons": non_worse,
            "passes_majority_gate": len(eligible) >= 3 and non_worse >= (len(eligible) + 1) // 2,
        },
    }


def format_trend_evaluation_lines(report):
    lines = ["Trend robustness evaluation"]
    for row in report.get("comparisons") or []:
        baseline = row["baseline"]
        candidate = row["candidate"]
        lines.append(
            "coins={coins} window={window}: baseline net={base:+.1f}% dd={base_dd:.1f}% | candidate net={candidate:+.1f}% dd={candidate_dd:.1f}% | delta net={delta:+.1f}% dd={dd_delta:+.1f}%".format(
                coins=",".join(row["coins"]), window=row["window"], base=float(baseline.get("total_pnl_pct") or 0.0), base_dd=float(baseline.get("max_drawdown") or 0.0), candidate=float(candidate.get("total_pnl_pct") or 0.0), candidate_dd=float(candidate.get("max_drawdown") or 0.0), delta=row["net_pnl_delta_pct"], dd_delta=row["drawdown_delta_pct"]
            )
        )
        lines.append(f"  candidate exits: {row['exit_diagnostics']}")
    lines.append(f"Gate: {report.get('summary')}")
    return lines
