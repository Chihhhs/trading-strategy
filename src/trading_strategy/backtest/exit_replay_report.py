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


def _summary(result):
    portfolio = result.portfolio
    diagnostics = portfolio.get("diagnostics") or {}
    trades = int(portfolio["trades"] or 0)
    return {
        "trades": trades,
        "win_rate": portfolio["win_rate"],
        "net_pnl_pct": portfolio["total_pnl_pct"],
        "gross_pnl_pct": portfolio["gross_pnl_pct"],
        "cost_pct": portfolio["total_cost_pct"],
        "max_drawdown": portfolio["max_drawdown"],
        "score": portfolio["score"],
        "average_trade_pct": round(float(portfolio["total_pnl_pct"]) / trades, 3) if trades else 0.0,
        "avg_hold_bars": portfolio["avg_hold_bars"],
        "exit_reasons": portfolio["exit_reason_counts"],
        "avg_mfe_r": _avg(result.trades, "mfe_r"),
        "avg_mae_r": _avg(result.trades, "mae_r"),
        "avg_best_close_r": _avg(result.trades, "best_close_r"),
        "stop_fills": int(diagnostics.get("exit_replay_stop_fills") or 0),
        "gap_fills": int(diagnostics.get("exit_replay_gap_fills") or 0),
        "confirmed_fills": int(diagnostics.get("exit_replay_confirmed_fills") or 0),
    }


def _coverage(result):
    diagnostics = result.portfolio.get("diagnostics") or {}
    expected = int(diagnostics.get("exit_replay_expected_hours") or 0)
    available = int(diagnostics.get("exit_replay_available_hours") or 0)
    missing = int(diagnostics.get("exit_replay_missing_hours") or 0)
    return {
        "expected_hours": expected,
        "available_hours": available,
        "missing_hours": missing,
        "eligible": expected > 0 and missing == 0,
        "coverage_pct": round(available / expected * 100, 2) if expected else 0.0,
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
    coverage = _coverage(confirmed)
    trade_ratio = confirmed_summary["trades"] / baseline_summary["trades"] if baseline_summary["trades"] else 0.0
    return {
        "coins": config.coins,
        "window": config.max_days,
        "daily_close_baseline": baseline_summary,
        "strict_1h_stop": strict_summary,
        "confirmed_1h_stop": confirmed_summary,
        "coverage": coverage,
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
    selected_mode="close_confirmed",
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
        and row["daily_close_baseline"]["trades"] >= min_trades
        and row["confirmed_1h_stop"]["trades"] >= min_trades
        and row["candidate_trade_ratio"] >= 0.8
    ]
    non_worse = [
        row
        for row in eligible
        if row["candidate_vs_baseline"]["net_pnl_pct"] >= 0
        and row["candidate_vs_baseline"]["max_drawdown"] <= 0
    ]
    required = next(
        (row for row in comparisons if row["window"] == 240 and row["coins"] == ("BTC", "ETH", "BNB")),
        None,
    )
    required_pass = bool(
        required
        and required in eligible
        and required["candidate_vs_baseline"]["net_pnl_pct"] >= 0
        and required["candidate_vs_baseline"]["max_drawdown"] <= 0
    )
    gate = {
        "comparisons": len(comparisons),
        "eligible_comparisons": len(eligible),
        "non_worse_comparisons": len(non_worse),
        "required_240d_multi_pass": required_pass,
        "passes_majority_gate": len(eligible) >= 3 and len(non_worse) >= (len(eligible) + 1) // 2 and required_pass,
    }
    return {
        **{key: primary[key] for key in ("daily_close_baseline", "strict_1h_stop", "confirmed_1h_stop", "coverage")},
        "primary": primary,
        "stop_sweep": stop_sweep,
        "comparisons": comparisons,
        "gate": gate,
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
            f"avg_trade={row['average_trade_pct']:+.3f}% avg_hold={row['avg_hold_bars']:.1f} "
            f"mfe_r={row['avg_mfe_r']} mae_r={row['avg_mae_r']} best_close_r={row['avg_best_close_r']}"
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
        delta = row["candidate_vs_baseline"]
        lines.append(
            f"coins={','.join(row['coins'])} window={row['window']}: "
            f"confirmed_vs_baseline net={delta['net_pnl_pct']:+.2f}pp "
            f"dd={delta['max_drawdown']:+.2f}pp trades_ratio={row['candidate_trade_ratio']:.2f} "
            f"coverage={row['coverage']['coverage_pct']:.2f}%"
        )
    lines.append(f"Gate: {report['gate']}")
    if not report["gate"]["passes_majority_gate"]:
        lines.append("Decision: REJECT confirmed 1h stop; do not promote to paper/live")
    return lines
