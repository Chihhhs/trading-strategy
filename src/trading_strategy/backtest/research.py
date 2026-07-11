from dataclasses import dataclass

from .portfolio import PortfolioBacktester
from .types import BacktestConfig


@dataclass(frozen=True)
class ResearchCandidate:
    name: str
    track: str
    decision: str
    config: BacktestConfig
    note: str = ""


def _normalize_coins(coins):
    normalized = tuple(str(coin).strip().upper() for coin in coins if str(coin).strip())
    return normalized or ("BTC",)


def _first_available(preferred, coins):
    for coin in preferred:
        if coin in coins:
            return coin
    return coins[0]


def _preferred_portfolio(coins):
    selected = tuple(coin for coin in ("BTC", "BNB", "ETH") if coin in coins)
    if selected:
        return selected
    return coins[: min(len(coins), 3)]


def build_research_candidates(
    *,
    coins,
    max_days,
    initial_capital=1000.0,
    fee_bps=4.5,
    slippage_bps=0.0,
):
    coins = _normalize_coins(coins)
    control_coin = _first_available(("BTC", "BNB", "ETH"), coins)
    portfolio_coins = _preferred_portfolio(coins)
    shared = {
        "max_days": max_days,
        "initial_capital": initial_capital,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
    }
    return [
        ResearchCandidate(
            name="trend_control",
            track="optimize_existing",
            decision="control",
            config=BacktestConfig(
                coins=(control_coin,),
                strategy="trend",
                leverage=2.0,
                risk_pct=0.03,
                btc_filter_enabled=True,
                atr_trailing_enabled=True,
                failure_exit_enabled=True,
                **shared,
            ),
            note="Single-coin trend baseline used to judge every other candidate.",
        ),
        ResearchCandidate(
            name="trend_controlled_portfolio",
            track="optimize_existing",
            decision="candidate",
            config=BacktestConfig(
                coins=portfolio_coins,
                strategy="trend",
                leverage=2.0,
                risk_pct=0.015,
                max_positions=2,
                btc_filter_enabled=True,
                atr_trailing_enabled=True,
                failure_exit_enabled=True,
                **shared,
            ),
            note="Lower per-coin risk plus max positions to test whether a basket improves risk-adjusted results.",
        ),
        ResearchCandidate(
            name="intraday_momentum_probe",
            track="new_strategy",
            decision="research_only",
            config=BacktestConfig(
                coins=(control_coin,),
                strategy="intraday_momentum",
                leverage=2.0,
                risk_pct=0.01,
                max_positions=1,
                btc_filter_enabled=True,
                max_hold_bars=24,
                **shared,
            ),
            note="Wiring probe for shorter-horizon momentum; only meaningful with intraday candle data.",
        ),
    ]


def build_pending_research_tracks():
    return [
        {
            "name": "funding_basis_monitor",
            "track": "new_strategy",
            "decision": "data_pipeline_next",
            "required_data": "perp funding history, mark/index price, and comparable spot or perp basis",
            "note": "Build as reporting first; do not mix into directional trend execution until validated.",
        },
        {
            "name": "order_flow_imbalance",
            "track": "new_strategy",
            "decision": "infrastructure_next",
            "required_data": "replayable L2 book snapshots or websocket order-book deltas",
            "note": "More defensible than indicator scalping, but needs execution and spread simulation.",
        },
    ]


def _row_from_result(candidate, result, control_summary):
    summary = result.portfolio
    control_score = float((control_summary or {}).get("score") or 0.0)
    control_pnl = float((control_summary or {}).get("total_pnl_pct") or 0.0)
    return {
        "name": candidate.name,
        "track": candidate.track,
        "decision": candidate.decision,
        "strategy": result.config.strategy,
        "coins": ",".join(result.config.coins),
        "risk_pct": result.config.risk_pct,
        "max_positions": result.config.max_positions,
        "trades": summary["trades"],
        "win_rate": summary["win_rate"],
        "net_pnl_pct": summary["total_pnl_pct"],
        "gross_pnl_pct": summary.get("gross_pnl_pct", summary["total_pnl_pct"]),
        "cost_pct": summary.get("total_cost_pct", 0.0),
        "max_drawdown": summary["max_drawdown"],
        "avg_hold_bars": summary.get("avg_hold_bars", 0.0),
        "score": summary.get("score", 0.0),
        "score_delta_vs_control": round(float(summary.get("score", 0.0)) - control_score, 2),
        "pnl_delta_vs_control": round(float(summary.get("total_pnl_pct", 0.0)) - control_pnl, 1),
        "exit_reason_counts": summary.get("exit_reason_counts", {}),
        "note": candidate.note,
    }


def run_research_report(
    data_map,
    *,
    coins,
    max_days,
    initial_capital=1000.0,
    fee_bps=4.5,
    slippage_bps=0.0,
):
    candidates = build_research_candidates(
        coins=coins,
        max_days=max_days,
        initial_capital=initial_capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    rows = []
    control_summary = None
    for candidate in candidates:
        result = PortfolioBacktester(config=candidate.config).run(data_map)
        if control_summary is None:
            control_summary = result.portfolio
        rows.append(_row_from_result(candidate, result, control_summary))
    return {
        "runnable": rows,
        "pending": build_pending_research_tracks(),
    }


def format_research_report_lines(report):
    lines = ["Dual-track research report"]
    rows = list(report.get("runnable") or [])
    for track in ("optimize_existing", "new_strategy"):
        lines.append(f"[{track}]")
        track_rows = [row for row in rows if row.get("track") == track]
        if not track_rows:
            lines.append("No runnable candidates.")
            continue
        for row in track_rows:
            lines.append(
                "{name}: decision={decision}, strategy={strategy}, coins={coins}, risk={risk_pct:.3f}, "
                "max_positions={max_positions}, trades={trades}, win_rate={win_rate:.1f}%, "
                "net_pnl={net_pnl_pct:+.1f}%, gross_pnl={gross_pnl_pct:+.1f}%, cost={cost_pct:.1f}%, "
                "drawdown={max_drawdown:.1f}%, score={score:+.2f}, "
                "score_delta={score_delta_vs_control:+.2f}, pnl_delta={pnl_delta_vs_control:+.1f}%".format(
                    **row
                )
            )
            if row.get("exit_reason_counts"):
                lines.append(f"{row['name']} exits: {row['exit_reason_counts']}")
            if row.get("note"):
                lines.append(f"{row['name']} note: {row['note']}")
    pending = list(report.get("pending") or [])
    if pending:
        lines.append("[new_strategy_pending]")
        for item in pending:
            lines.append(
                "{name}: decision={decision}, required_data={required_data}, note={note}".format(
                    **item
                )
            )
    return lines
