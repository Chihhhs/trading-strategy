from dataclasses import replace

from .portfolio import PortfolioBacktester
from .types import BacktestConfig


def _trade_metrics(result):
    trades = result.trades
    initial = float(result.portfolio.get("starting_balance") or 0.0)
    notional = sum(
        abs(float(t.get("entry") or 0.0) * float(t.get("size") or 0.0))
        + abs(float(t.get("exit") or 0.0) * float(t.get("size") or 0.0))
        for t in trades
    )
    turnover = notional / initial if initial else 0.0
    return {
        "trades": len(trades),
        "turnover": round(turnover, 4),
        "avg_hold_bars": result.portfolio.get("avg_hold_bars", 0.0),
        "gross_pnl_pct": result.portfolio.get("gross_pnl_pct", 0.0),
        "net_pnl_pct": result.portfolio.get("total_pnl_pct", 0.0),
        "fee_slippage_pct": result.portfolio.get("total_cost_pct", 0.0),
        "drawdown_pct": result.portfolio.get("max_drawdown", 0.0),
        "exit_reason_counts": result.portfolio.get("exit_reason_counts", {}),
        "direction_summary": result.portfolio.get("direction_summary", {}),
        "mfe_r_avg": round(
            sum(float(t.get("mfe_r")) for t in trades if t.get("mfe_r") is not None)
            / max(sum(1 for t in trades if t.get("mfe_r") is not None), 1),
            4,
        ),
        "mae_r_avg": round(
            sum(float(t.get("mae_r")) for t in trades if t.get("mae_r") is not None)
            / max(sum(1 for t in trades if t.get("mae_r") is not None), 1),
            4,
        ),
    }


def run_intraday_turnover_report(data_map, *, config: BacktestConfig, min_trades=100):
    baseline_config = replace(config, btc_filter_enabled=False, intraday_cooldown_bars=0)
    candidates = {
        "baseline": baseline_config,
        "cooldown_8": replace(baseline_config, intraday_cooldown_bars=8),
        "btc_filter": replace(baseline_config, btc_filter_enabled=True),
        "cooldown_8_btc_filter": replace(baseline_config, intraday_cooldown_bars=8, btc_filter_enabled=True),
        "atr_2pct": replace(baseline_config, intraday_max_range_pct=2.0),
        "cooldown_8_atr_2pct": replace(baseline_config, intraday_cooldown_bars=8, intraday_max_range_pct=2.0),
    }
    rows = []
    for name, candidate_config in candidates.items():
        result = PortfolioBacktester(config=candidate_config).run(data_map)
        metrics = _trade_metrics(result)
        metrics.update({"candidate": name, "eligible": metrics["trades"] >= int(min_trades or 1)})
        rows.append(metrics)
    baseline = next(row for row in rows if row["candidate"] == "baseline")
    for row in rows:
        row["turnover_delta"] = round(row["turnover"] - baseline["turnover"], 4)
        row["net_pnl_delta"] = round(row["net_pnl_pct"] - baseline["net_pnl_pct"], 4)
        row["passes_cost_gate"] = bool(
            row["eligible"]
            and row["candidate"] != "baseline"
            and row["net_pnl_pct"] >= baseline["net_pnl_pct"]
            and row["drawdown_pct"] <= baseline["drawdown_pct"]
            and row["turnover"] < baseline["turnover"]
        )
    return {
        "report_type": "intraday_turnover",
        "strategy": config.strategy,
        "timeframe": "15m",
        "fee_bps": config.fee_bps,
        "slippage_bps": config.slippage_bps,
        "min_trades": int(min_trades or 1),
        "candidates": rows,
        "promotion_gate": {
            "baseline_candidate": "baseline",
            "passing_candidates": [row["candidate"] for row in rows if row["passes_cost_gate"]],
            "passes": any(row["passes_cost_gate"] for row in rows if row["candidate"] != "baseline"),
        },
    }


def format_intraday_turnover_report(report):
    lines = [
        "Intraday turnover report: strategy={strategy}, timeframe={timeframe}, fee_bps={fee_bps}, slippage_bps={slippage_bps}".format(**report)
    ]
    for row in report.get("candidates", []):
        lines.append(
            "{candidate}: trades={trades}, turnover={turnover:.4f}, hold={avg_hold_bars:.1f}, "
            "gross={gross_pnl_pct:+.1f}%, net={net_pnl_pct:+.1f}%, cost={fee_slippage_pct:.1f}%, "
            "dd={drawdown_pct:.1f}%, eligible={eligible}, passes={passes_cost_gate}".format(**row)
        )
    lines.append(f"Promotion gate: {report.get('promotion_gate')}")
    return lines
