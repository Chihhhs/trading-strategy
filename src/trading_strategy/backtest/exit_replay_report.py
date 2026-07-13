from .portfolio import PortfolioBacktester


def _avg(trades, key):
    values = [float(item[key]) for item in trades if item.get(key) is not None]
    return round(sum(values) / len(values), 3) if values else None


def _summary(result):
    portfolio = result.portfolio
    return {
        "trades": portfolio["trades"],
        "net_pnl_pct": portfolio["total_pnl_pct"],
        "gross_pnl_pct": portfolio["gross_pnl_pct"],
        "cost_pct": portfolio["total_cost_pct"],
        "max_drawdown": portfolio["max_drawdown"],
        "exit_reasons": portfolio["exit_reason_counts"],
        "avg_mfe_r": _avg(result.trades, "mfe_r"),
        "avg_mae_r": _avg(result.trades, "mae_r"),
        "avg_best_close_r": _avg(result.trades, "best_close_r"),
    }


def run_trend_exit_replay_report(data_map, hourly_data_map, *, config, derivatives_data_map=None):
    baseline = PortfolioBacktester(
        config=config,
        derivatives_data_map=derivatives_data_map,
    ).run(data_map)
    replay = PortfolioBacktester(
        config=config,
        derivatives_data_map=derivatives_data_map,
        exit_replay_data_map=hourly_data_map,
    ).run(data_map)
    diagnostics = replay.portfolio.get("diagnostics") or {}
    expected = int(diagnostics.get("exit_replay_expected_hours") or 0)
    available = int(diagnostics.get("exit_replay_available_hours") or 0)
    missing = int(diagnostics.get("exit_replay_missing_hours") or 0)
    return {
        "baseline": _summary(baseline),
        "replay": _summary(replay),
        "delta": {
            "net_pnl_pct": round(replay.portfolio["total_pnl_pct"] - baseline.portfolio["total_pnl_pct"], 2),
            "max_drawdown": round(replay.portfolio["max_drawdown"] - baseline.portfolio["max_drawdown"], 2),
        },
        "coverage": {
            "expected_hours": expected,
            "available_hours": available,
            "missing_hours": missing,
            "eligible": expected > 0 and missing == 0,
            "coverage_pct": round(available / expected * 100, 2) if expected else 0.0,
            "stop_fills": int(diagnostics.get("exit_replay_stop_fills") or 0),
            "gap_fills": int(diagnostics.get("exit_replay_gap_fills") or 0),
        },
        "results": {"baseline": baseline, "replay": replay},
    }


def format_trend_exit_replay_lines(report):
    lines = ["Trend exit replay report (daily signals, 1h exits)"]
    for name in ("baseline", "replay"):
        row = report[name]
        lines.append(
            f"{name}: trades={row['trades']}, net_pnl={row['net_pnl_pct']:+.1f}%, "
            f"gross_pnl={row['gross_pnl_pct']:+.1f}%, cost={row['cost_pct']:.1f}%, "
            f"drawdown={row['max_drawdown']:.1f}%"
        )
        lines.append(
            f"{name} exits={row['exit_reasons']}, avg_mfe_r={row['avg_mfe_r']}, "
            f"avg_mae_r={row['avg_mae_r']}, avg_best_close_r={row['avg_best_close_r']}"
        )
    delta = report["delta"]
    coverage = report["coverage"]
    lines.append(
        f"delta: net_pnl={delta['net_pnl_pct']:+.2f}pp, drawdown={delta['max_drawdown']:+.2f}pp"
    )
    lines.append(
        f"coverage: {coverage['available_hours']}/{coverage['expected_hours']} "
        f"({coverage['coverage_pct']:.2f}%), missing={coverage['missing_hours']}, "
        f"stop_fills={coverage['stop_fills']}, gap_fills={coverage['gap_fills']}"
    )
    if not coverage["eligible"]:
        lines.append("decision: INELIGIBLE because hourly replay coverage is incomplete")
    return lines
