from collections import Counter
from dataclasses import replace
from statistics import median

from .exit_replay import HOUR_MS, normalize_hourly_data
from .portfolio import PortfolioBacktester


DEFAULT_FORWARD_HOURS = (6, 12, 24, 72)
DEFAULT_WINDOWS = (120, 180, 240)
DEFAULT_UNIVERSES = (("BTC",), ("BTC", "ETH", "BNB"))


def classify_stop_sweep_event(event, *, false_sweep_r=0.5):
    if not event.get("eligible") or event.get("fill_type") == "gap":
        return "ineligible"
    if event.get("reclaimed"):
        if float(event.get("max_favorable_r") or 0.0) >= float(false_sweep_r):
            return "false_sweep"
        return "reclaimed_stop"
    if float(event.get("signed_return_r") or 0.0) <= -float(false_sweep_r):
        return "valid_stop"
    return "unclear"


def _avg(trades, key):
    values = [float(item[key]) for item in trades if item.get(key) is not None]
    return round(sum(values) / len(values), 3) if values else None


def _position_lifecycles(trades):
    grouped = {}
    for index, trade in enumerate(trades or []):
        key = trade.get("position_id") or f"legacy:{index}"
        row = grouped.setdefault(
            key,
            {
                "position_id": key,
                "coin": trade.get("coin"),
                "direction": trade.get("direction"),
                "pnl": 0.0,
                "cost": 0.0,
                "partial_reductions": 0,
                "exit_reason": None,
                "mfe_r": None,
                "mae_r": None,
                "best_close_r": None,
                "hold_bars": None,
            },
        )
        row["pnl"] += float(trade.get("pnl") or 0.0)
        row["cost"] += float(trade.get("cost") or 0.0)
        if trade.get("is_partial"):
            row["partial_reductions"] += 1
        else:
            row["exit_reason"] = trade.get("exit_reason")
            for field in ("mfe_r", "mae_r", "best_close_r", "hold_bars"):
                row[field] = trade.get(field)
    return list(grouped.values())


def _group_lifecycles(rows, key):
    result = {}
    for value in sorted({str(row.get(key) or "unknown") for row in rows}):
        subset = [row for row in rows if str(row.get(key) or "unknown") == value]
        result[value] = {
            "positions": len(subset),
            "net_pnl": round(sum(row["pnl"] for row in subset), 2),
            "expectancy": round(sum(row["pnl"] for row in subset) / len(subset), 2),
            "avg_mfe_r": _avg(subset, "mfe_r"),
            "avg_mae_r": _avg(subset, "mae_r"),
            "avg_best_close_r": _avg(subset, "best_close_r"),
            "avg_hold_bars": _avg(subset, "hold_bars"),
        }
    return result


def _winner_concentration(rows, initial_capital):
    ordered = sorted((float(row.get("pnl") or 0.0) for row in rows), reverse=True)
    net = sum(ordered)
    positive = sum(value for value in ordered if value > 0)
    largest = ordered[0] if ordered else 0.0
    return {
        "largest_winner": round(max(largest, 0.0), 2),
        "largest_winner_pct_of_positive_pnl": round(max(largest, 0.0) / positive * 100, 1) if positive else None,
        "largest_trade_pct_of_net_pnl": round(largest / net * 100, 1) if net else None,
        "net_pnl_without_top_1_pct": round(sum(ordered[1:]) / initial_capital * 100, 1) if initial_capital else None,
        "net_pnl_without_top_2_pct": round(sum(ordered[2:]) / initial_capital * 100, 1) if initial_capital else None,
    }


def _summary(result):
    portfolio = result.portfolio
    diagnostics = portfolio.get("diagnostics") or {}
    lifecycles = _position_lifecycles(result.trades)
    trades = len(lifecycles)
    wins = sum(1 for row in lifecycles if row["pnl"] > 0)
    stop_kind_by_position = {
        event.get("position_id"): event.get("stop_kind")
        for event in diagnostics.get("exit_replay_events") or []
        if event.get("position_id")
    }
    for row in lifecycles:
        row["stop_kind"] = stop_kind_by_position.get(row["position_id"], "not_hard_stop")
    return {
        "trades": trades,
        "execution_records": len(result.trades),
        "partial_reductions": sum(1 for trade in result.trades if trade.get("is_partial")),
        "win_rate": round(wins / trades * 100, 1) if trades else 0.0,
        "net_pnl_pct": portfolio["total_pnl_pct"],
        "gross_pnl_pct": portfolio["gross_pnl_pct"],
        "cost_pct": portfolio["total_cost_pct"],
        "max_drawdown": float(portfolio.get("mark_to_market_max_drawdown") or portfolio["max_drawdown"]),
        "closed_balance_drawdown": portfolio.get("closed_balance_max_drawdown", portfolio["max_drawdown"]),
        "mark_to_market": portfolio.get("mark_to_market"),
        "score": portfolio["score"],
        "average_trade_pct": round(float(portfolio["total_pnl_pct"]) / trades, 3) if trades else 0.0,
        "avg_hold_bars": _avg(lifecycles, "hold_bars") or 0.0,
        "exit_reasons": dict(Counter(row.get("exit_reason") or "unknown" for row in lifecycles)),
        "avg_mfe_r": _avg(lifecycles, "mfe_r"),
        "avg_mae_r": _avg(lifecycles, "mae_r"),
        "avg_best_close_r": _avg(lifecycles, "best_close_r"),
        "stop_fills": int(diagnostics.get("exit_replay_stop_fills") or 0),
        "gap_fills": int(diagnostics.get("exit_replay_gap_fills") or 0),
        "confirmed_fills": int(diagnostics.get("exit_replay_confirmed_fills") or 0),
        "breakdown": {
            "coin": _group_lifecycles(lifecycles, "coin"),
            "direction": _group_lifecycles(lifecycles, "direction"),
            "stop_kind": _group_lifecycles(lifecycles, "stop_kind"),
            "exit_reason": _group_lifecycles(lifecycles, "exit_reason"),
        },
        "winner_concentration": _winner_concentration(lifecycles, float(portfolio["starting_balance"])),
    }


def _coverage(result):
    diagnostics = result.portfolio.get("diagnostics") or {}
    expected = int(diagnostics.get("exit_replay_expected_hours") or 0)
    available = int(diagnostics.get("exit_replay_available_hours") or 0)
    missing = int(diagnostics.get("exit_replay_missing_hours") or 0)
    mark_missing = int(diagnostics.get("mark_to_market_missing_points") or 0)
    return {
        "expected_hours": expected,
        "available_hours": available,
        "missing_hours": missing,
        "eligible": expected > 0 and missing == 0 and mark_missing == 0,
        "coverage_pct": round(available / expected * 100, 2) if expected else 0.0,
        "mark_to_market_missing_points": mark_missing,
    }


def _signed_move(direction, current, reference):
    multiplier = -1.0 if direction == "short" else 1.0
    return (float(current) - float(reference)) * multiplier


def analyze_stop_sweep_events(
    events,
    hourly_data_map,
    *,
    forward_hours=DEFAULT_FORWARD_HOURS,
    reclaim_hours=24,
    false_sweep_r=0.5,
):
    hourly = normalize_hourly_data(hourly_data_map)
    indexes = {
        coin: {int(bar["open_time"]): index for index, bar in enumerate(bars)}
        for coin, bars in hourly.items()
    }
    rows = []
    for raw in events or []:
        row = dict(raw)
        coin = str(row.get("coin") or "").upper()
        bars = hourly.get(coin, [])
        event_open_time = row.get("open_time")
        index = indexes.get(coin, {}).get(int(event_open_time)) if event_open_time is not None else None
        risk = float(row.get("initial_risk") or 0.0)
        def has_contiguous_horizon(horizon):
            if index is None or risk <= 0 or index + int(horizon) >= len(bars):
                return False
            return all(
                bars[index + offset]["open_time"] == int(row["open_time"]) + offset * HOUR_MS
                for offset in range(int(horizon) + 1)
            )

        eligible = has_contiguous_horizon(reclaim_hours) and row.get("fill_type") != "gap"
        row["eligible"] = eligible
        row["forward"] = {}
        if index is not None and risk > 0:
            fill_price = float(row["fill_price"])
            stop_price = float(row["stop_price"])
            direction = row.get("direction")
            for horizon in forward_hours:
                horizon_eligible = has_contiguous_horizon(horizon)
                horizon_row = {"eligible": horizon_eligible}
                if horizon_eligible:
                    close = float(bars[index + int(horizon)]["close"])
                    move = _signed_move(direction, close, fill_price)
                    horizon_row.update(
                        {
                            "signed_return_pct": round(move / fill_price * 100, 4),
                            "signed_return_r": round(move / risk, 4),
                            "reclaimed": close > stop_price if direction == "long" else close < stop_price,
                        }
                    )
                row["forward"][int(horizon)] = horizon_row
        if eligible:
            fill_price = float(row["fill_price"])
            stop_price = float(row["stop_price"])
            direction = row.get("direction")
            reclaim_bars = bars[index : index + int(reclaim_hours) + 1]
            closes = [float(bar["close"]) for bar in reclaim_bars]
            moves = [_signed_move(direction, close, fill_price) / risk for close in closes]
            row["reclaimed"] = any(
                close > stop_price if direction == "long" else close < stop_price
                for close in closes
            )
            row["max_favorable_r"] = round(max(moves), 4)
            row["max_adverse_r"] = round(min(moves), 4)
            reclaim_close = float(bars[index + int(reclaim_hours)]["close"])
            row["signed_return_r"] = round(_signed_move(direction, reclaim_close, fill_price) / risk, 4)
        else:
            row.update(
                {
                    "reclaimed": None,
                    "max_favorable_r": None,
                    "max_adverse_r": None,
                    "signed_return_r": None,
                }
            )
        row["classification"] = classify_stop_sweep_event(row, false_sweep_r=false_sweep_r)
        entry = float(row.get("entry") or 0.0)
        entry_atr = float(row.get("entry_atr") or 0.0)
        row["entry_atr_pct"] = entry_atr / entry * 100 if entry and entry_atr else None
        rows.append(row)

    atr_values = [row["entry_atr_pct"] for row in rows if row["eligible"] and row["entry_atr_pct"] is not None]
    atr_median = median(atr_values) if atr_values else None
    for row in rows:
        value = row.get("entry_atr_pct")
        row["volatility_regime"] = "unknown" if value is None or atr_median is None else ("high" if value >= atr_median else "low")
    eligible_rows = [row for row in rows if row["eligible"]]
    forward_summary = {}
    for horizon in forward_hours:
        horizon_rows = [
            row["forward"][int(horizon)]
            for row in rows
            if row.get("forward", {}).get(int(horizon), {}).get("eligible")
        ]
        forward_summary[int(horizon)] = {
            "events": len(horizon_rows),
            "avg_signed_return_pct": round(sum(row["signed_return_pct"] for row in horizon_rows) / len(horizon_rows), 4) if horizon_rows else None,
            "avg_signed_return_r": round(sum(row["signed_return_r"] for row in horizon_rows) / len(horizon_rows), 4) if horizon_rows else None,
            "positive_rate_pct": round(sum(1 for row in horizon_rows if row["signed_return_r"] > 0) / len(horizon_rows) * 100, 1) if horizon_rows else None,
            "reclaim_rate_pct": round(sum(1 for row in horizon_rows if row["reclaimed"]) / len(horizon_rows) * 100, 1) if horizon_rows else None,
        }
    groups = {}
    for key in ("coin", "direction", "stop_source", "volatility_regime"):
        groups[key] = {}
        for value in sorted({str(row.get(key) or "unknown") for row in eligible_rows}):
            subset = [row for row in eligible_rows if str(row.get(key) or "unknown") == value]
            groups[key][value] = {
                "events": len(subset),
                "classifications": dict(Counter(row["classification"] for row in subset)),
                "avg_reclaim_r": round(sum(row["signed_return_r"] for row in subset) / len(subset), 4),
            }
    return {
        "events": rows,
        "events_total": len(rows),
        "events_eligible": len(eligible_rows),
        "classifications": dict(Counter(row["classification"] for row in rows)),
        "forward_summary": forward_summary,
        "groups": groups,
        "entry_atr_pct_median": round(atr_median, 4) if atr_median is not None else None,
    }


def _run_three(data_map, hourly_data_map, derivatives_data_map, config):
    baseline = PortfolioBacktester(config=config, derivatives_data_map=derivatives_data_map).run(data_map)
    strict = PortfolioBacktester(
        config=config,
        derivatives_data_map=derivatives_data_map,
        exit_replay_data_map=hourly_data_map,
        exit_replay_mode="strict",
    ).run(data_map)
    confirmed = PortfolioBacktester(
        config=config,
        derivatives_data_map=derivatives_data_map,
        exit_replay_data_map=hourly_data_map,
        exit_replay_mode="close_confirmed",
    ).run(data_map)
    return baseline, strict, confirmed


def _comparison(data_map, hourly_data_map, derivatives_data_map, config):
    baseline, strict, confirmed = _run_three(data_map, hourly_data_map, derivatives_data_map, config)
    baseline_summary = _summary(baseline)
    strict_summary = _summary(strict)
    confirmed_summary = _summary(confirmed)
    strict_coverage = _coverage(strict)
    confirmed_coverage = _coverage(confirmed)
    trade_ratio = confirmed_summary["trades"] / baseline_summary["trades"] if baseline_summary["trades"] else 0.0
    return {
        "coins": config.coins,
        "window": config.max_days,
        "daily_close_baseline": baseline_summary,
        "strict_1h_stop": strict_summary,
        "confirmed_1h_stop": confirmed_summary,
        "coverage": strict_coverage,
        "strict_coverage": strict_coverage,
        "confirmed_coverage": confirmed_coverage,
        "candidate_trade_ratio": round(trade_ratio, 4),
        "candidate_vs_baseline": {
            "net_pnl_pct": round(confirmed_summary["net_pnl_pct"] - baseline_summary["net_pnl_pct"], 2),
            "max_drawdown": round(confirmed_summary["max_drawdown"] - baseline_summary["max_drawdown"], 2),
        },
        "candidate_vs_strict": {
            "net_pnl_pct": round(confirmed_summary["net_pnl_pct"] - strict_summary["net_pnl_pct"], 2),
            "max_drawdown": round(confirmed_summary["max_drawdown"] - strict_summary["max_drawdown"], 2),
        },
        "results": {"baseline": baseline, "strict": strict, "confirmed": confirmed},
    }


def run_trend_exit_replay_report(
    data_map,
    hourly_data_map,
    *,
    config,
    derivatives_data_map=None,
    forward_hours=DEFAULT_FORWARD_HOURS,
    reclaim_hours=24,
    false_sweep_r=0.5,
    windows=DEFAULT_WINDOWS,
    universes=DEFAULT_UNIVERSES,
    min_trades=5,
    selected_mode="strict",
):
    primary = _comparison(data_map, hourly_data_map, derivatives_data_map, config)
    strict_events = primary["results"]["strict"].portfolio.get("diagnostics", {}).get("exit_replay_events", [])
    stop_sweep = analyze_stop_sweep_events(
        strict_events,
        hourly_data_map,
        forward_hours=forward_hours,
        reclaim_hours=reclaim_hours,
        false_sweep_r=false_sweep_r,
    )
    comparisons = []
    for window in windows:
        for universe in universes:
            coins = tuple(coin for coin in universe if coin in data_map)
            if not coins:
                continue
            comparisons.append(
                _comparison(
                    data_map,
                    hourly_data_map,
                    derivatives_data_map,
                    replace(config, coins=coins, max_days=int(window)),
                )
            )
    eligible = [
        row
        for row in comparisons
        if row["coverage"]["eligible"]
        and row["strict_1h_stop"]["trades"] >= min_trades
    ]
    positive = [row for row in eligible if row["strict_1h_stop"]["net_pnl_pct"] > 0]
    required = next(
        (row for row in comparisons if row["window"] == 240 and row["coins"] == ("BTC", "ETH", "BNB")),
        None,
    )
    required_pass = bool(
        required
        and required in eligible
        and required["strict_1h_stop"]["net_pnl_pct"] > 0
    )
    gate = {
        "comparisons": len(comparisons),
        "eligible_comparisons": len(eligible),
        "positive_comparisons": len(positive),
        "required_240d_multi_positive": required_pass,
        "passes_live_like_baseline_gate": len(eligible) >= 3 and len(positive) >= (len(eligible) + 1) // 2 and required_pass,
    }
    contribution_config = replace(config, coins=("ETH", "BNB"), max_days=240)
    contribution = _comparison(data_map, hourly_data_map, derivatives_data_map, contribution_config)
    return {
        **{key: primary[key] for key in ("daily_close_baseline", "strict_1h_stop", "confirmed_1h_stop", "coverage")},
        "primary": primary,
        "stop_sweep": stop_sweep,
        "comparisons": comparisons,
        "gate": gate,
        "portfolio_contribution": {
            "BTC": next((row["strict_1h_stop"] for row in comparisons if row["coins"] == ("BTC",) and row["window"] == 240), None),
            "ETH_BNB": contribution["strict_1h_stop"],
            "BTC_ETH_BNB": required["strict_1h_stop"] if required else None,
        },
        "selected_mode": selected_mode,
        "selected_replay": primary["strict_1h_stop" if selected_mode == "strict" else "confirmed_1h_stop"],
    }


def format_trend_exit_replay_lines(report):
    lines = ["Trend exit replay report (daily signals, strict vs confirmed 1h exits)"]
    for name in ("daily_close_baseline", "strict_1h_stop", "confirmed_1h_stop"):
        row = report[name]
        lines.append(
            f"{name}: trades={row['trades']}, win_rate={row['win_rate']:.1f}%, "
            f"net_pnl={row['net_pnl_pct']:+.1f}%, gross_pnl={row['gross_pnl_pct']:+.1f}%, "
            f"cost={row['cost_pct']:.1f}%, drawdown={row['max_drawdown']:.1f}%, score={row['score']:+.2f}"
        )
        lines.append(
            f"  fills=stop:{row['stop_fills']} gap:{row['gap_fills']} confirmed:{row['confirmed_fills']} "
            f"positions={row['trades']} records={row['execution_records']} partials={row['partial_reductions']} "
            f"avg_trade={row['average_trade_pct']:+.3f}% avg_hold={row['avg_hold_bars']:.1f} "
            f"mfe_r={row['avg_mfe_r']} mae_r={row['avg_mae_r']} best_close_r={row['avg_best_close_r']}"
        )
        if row.get("mark_to_market"):
            lines.append(
                f"  drawdown=hourly_mtm:{row['max_drawdown']:.2f}% "
                f"daily_mtm:{row['mark_to_market']['daily_max_drawdown_pct']:.2f}% "
                f"closed_balance:{row['closed_balance_drawdown']:.1f}%"
            )
    sweep = report["stop_sweep"]
    selected = report["selected_replay"]
    lines.append(
        f"Selected mode: {report['selected_mode']} net={selected['net_pnl_pct']:+.1f}% "
        f"drawdown={selected['max_drawdown']:.1f}%"
    )
    lines.append(
        f"Stop sweep: eligible={sweep['events_eligible']}/{sweep['events_total']}, "
        f"classes={sweep['classifications']}"
    )
    lines.append(f"  forward={sweep['forward_summary']}")
    lines.append(f"  groups={sweep['groups']}")
    for row in report["comparisons"]:
        strict = row["strict_1h_stop"]
        lines.append(
            f"coins={','.join(row['coins'])} window={row['window']}: "
            f"canonical net={strict['net_pnl_pct']:+.1f}% mtm_dd={strict['max_drawdown']:.1f}% "
            f"closed_dd={strict['closed_balance_drawdown']:.1f}% positions={strict['trades']} "
            f"coverage={row['coverage']['coverage_pct']:.2f}%"
        )
    lines.append(f"Canonical gate: {report['gate']}")
    lines.append(f"Portfolio contribution: {report['portfolio_contribution']}")
    lines.append(f"Canonical breakdown: {report['strict_1h_stop']['breakdown']}")
    lines.append(f"Winner concentration: {report['strict_1h_stop']['winner_concentration']}")
    lines.append(f"Daily counterfactual concentration: {report['daily_close_baseline']['winner_concentration']}")
    if not report["gate"]["passes_live_like_baseline_gate"]:
        lines.append("Decision: canonical live-like baseline is not robustly positive; stop strategy promotion")
    return lines
