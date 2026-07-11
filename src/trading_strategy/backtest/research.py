from dataclasses import dataclass

from .derivatives import build_derivatives_monitor
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
            name="trend_unfiltered_reference",
            track="optimize_existing",
            decision="reference",
            config=BacktestConfig(
                coins=(control_coin,),
                strategy="trend",
                leverage=2.0,
                risk_pct=0.03,
                btc_filter_enabled=True,
                atr_trailing_enabled=True,
                failure_exit_enabled=True,
                trend_entry_filter_enabled=False,
                **shared,
            ),
            note="Previous trend behavior without the reference-based anti-chase entry filters.",
        ),
        ResearchCandidate(
            name="trend_filtered_control",
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
                trend_entry_filter_enabled=True,
                **shared,
            ),
            note="Single-coin trend baseline with RSI, ATR, price-position, and overextension filters.",
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
                trend_entry_filter_enabled=True,
                **shared,
            ),
            note="Lower per-coin risk plus max positions to test whether a basket improves risk-adjusted results.",
        ),
        ResearchCandidate(
            name="trend_derivatives_filtered",
            track="optimize_existing",
            decision="candidate",
            config=BacktestConfig(
                coins=(control_coin,),
                strategy="trend",
                leverage=2.0,
                risk_pct=0.03,
                btc_filter_enabled=True,
                atr_trailing_enabled=True,
                failure_exit_enabled=True,
                trend_entry_filter_enabled=True,
                derivatives_filter_enabled=True,
                **shared,
            ),
            note="Trend signal quality filter using funding, open interest, and basis. It only blocks existing trend signals.",
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
        "diagnostics": summary.get("diagnostics", {}),
        "note": candidate.note,
    }


def _equity_returns(equity_curve):
    returns = []
    for previous, current in zip(equity_curve, equity_curve[1:]):
        previous = float(previous or 0.0)
        current = float(current or 0.0)
        returns.append((current / previous - 1.0) if previous else 0.0)
    return returns


def _correlation(left, right):
    count = min(len(left), len(right))
    if count < 2:
        return None
    x = left[-count:]
    y = right[-count:]
    mean_x = sum(x) / count
    mean_y = sum(y) / count
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    var_x = sum((a - mean_x) ** 2 for a in x)
    var_y = sum((b - mean_y) ** 2 for b in y)
    if var_x <= 0 or var_y <= 0:
        return None
    return round(cov / ((var_x * var_y) ** 0.5), 3)


def _build_portfolio_correlation_report(results_by_name):
    returns_by_name = {
        name: _equity_returns(result.equity_curve)
        for name, result in results_by_name.items()
    }
    names = list(returns_by_name)
    rows = []
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            value = _correlation(returns_by_name[left], returns_by_name[right])
            if value is not None:
                rows.append({"left": left, "right": right, "correlation": value})
    return rows


def run_research_report(
    data_map,
    *,
    derivatives_data_map=None,
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
    results_by_name = {}
    control_summary = None
    for candidate in candidates:
        result = PortfolioBacktester(
            config=candidate.config,
            derivatives_data_map=derivatives_data_map,
        ).run(data_map)
        results_by_name[candidate.name] = result
        if control_summary is None:
            control_summary = result.portfolio
        rows.append(_row_from_result(candidate, result, control_summary))
    monitor_rows = build_derivatives_monitor(
        derivatives_data_map or {},
        coins=coins,
        oi_lookback=BacktestConfig(coins=coins).derivatives_oi_lookback,
    )
    rows.append(
        {
            "name": "funding_basis_monitor",
            "track": "new_strategy",
            "decision": "runnable_monitor",
            "strategy": "monitor",
            "coins": ",".join(coins),
            "risk_pct": 0.0,
            "max_positions": None,
            "trades": 0,
            "win_rate": 0.0,
            "net_pnl_pct": 0.0,
            "gross_pnl_pct": 0.0,
            "cost_pct": 0.0,
            "max_drawdown": 0.0,
            "avg_hold_bars": 0.0,
            "score": 0.0,
            "score_delta_vs_control": 0.0,
            "pnl_delta_vs_control": 0.0,
            "exit_reason_counts": {},
            "diagnostics": {
                "derivatives_monitor": monitor_rows,
                "missing_derivatives_data_coins": [
                    row["coin"] for row in monitor_rows if not row.get("derivative_bars")
                ],
            },
            "note": "Monitor-only funding, open-interest, and basis report. It does not create trades.",
        }
    )
    return {
        "runnable": rows,
        "portfolio_correlations": _build_portfolio_correlation_report(results_by_name),
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
            diagnostics = row.get("diagnostics") or {}
            relevant_diagnostics = {
                key: diagnostics.get(key)
                for key in (
                    "derivatives_funding_filtered_signals",
                    "derivatives_basis_filtered_signals",
                    "derivatives_oi_filtered_signals",
                    "derivatives_missing_context_signals",
                    "missing_derivatives_data_coins",
                )
                if diagnostics.get(key)
            }
            if relevant_diagnostics:
                lines.append(f"{row['name']} diagnostics: {relevant_diagnostics}")
            if row.get("name") == "funding_basis_monitor":
                for item in (diagnostics.get("derivatives_monitor") or [])[:5]:
                    lines.append(
                        "funding_basis_monitor {coin}: bars={bars}, derivative_bars={derivative_bars}, "
                        "latest_funding={latest_funding_rate}, avg_funding={avg_funding_rate}, "
                        "latest_basis={latest_basis_pct}, oi_change={oi_change_pct}".format(**item)
                    )
            if row.get("note"):
                lines.append(f"{row['name']} note: {row['note']}")
    correlations = list(report.get("portfolio_correlations") or [])
    lines.append("[portfolio_correlation]")
    if not correlations:
        lines.append("No non-flat candidate return pairs available.")
    for item in correlations:
        lines.append(
            "{left} vs {right}: return_correlation={correlation:+.3f}".format(**item)
        )
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
