from dataclasses import dataclass

from .data import get_coin_series
from .derivatives import _safe_float, merge_derivatives_into_price_data


DEFAULT_CARRY_SET = ("funding_carry", "basis_compression")
DEFAULT_TREND_FORWARD_DAYS = (1, 3, 7, 14)


@dataclass(frozen=True)
class CarryConfig:
    coins: tuple[str, ...]
    max_days: int | None = None
    carry_set: tuple[str, ...] = DEFAULT_CARRY_SET
    funding_entry_abs: float = 0.00008
    funding_exit_abs: float = 0.00002
    basis_entry_abs_pct: float = 0.04
    basis_exit_abs_pct: float = 0.01
    max_hold_days: int = 14
    fee_bps: float = 4.5
    slippage_bps: float = 2.0
    funding_periods_per_day: int = 3
    trend_forward_days: tuple[int, ...] = DEFAULT_TREND_FORWARD_DAYS
    trend_price_lookback_days: int = 3
    trend_funding_z_lookback: int = 30
    trend_funding_z_threshold: float = 0.75
    trend_basis_abs_threshold_pct: float = 0.03


def parse_csv_tuple(raw_value, cast=str):
    values = []
    for item in str(raw_value or "").split(","):
        item = item.strip()
        if item:
            values.append(cast(item))
    return tuple(values)


def _slice_bars(bars, max_days):
    bars = list(bars or [])
    return bars[-max_days:] if max_days is not None else bars


def _bar_time(bar):
    return (bar or {}).get("time") or (bar or {}).get("timestamp") or (bar or {}).get("date")


def _transaction_cost_pct(config):
    # Delta-neutral spread entry exits two legs, then closes two legs.
    return 4.0 * (float(config.fee_bps or 0.0) + float(config.slippage_bps or 0.0)) / 100.0


def _close(bar):
    value = _safe_float((bar or {}).get("close"))
    return value


def _pct_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _std(values):
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def _empty_summary(name, coin, diagnostics=None):
    return {
        "name": name,
        "coin": coin,
        "trades": 0,
        "win_rate": 0.0,
        "gross_pnl_pct": 0.0,
        "cost_pct": 0.0,
        "net_pnl_pct": 0.0,
        "avg_trade_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "profit_factor": None,
        "avg_hold_days": 0.0,
        "diagnostics": diagnostics or {},
        "trades_detail": [],
    }


def _summarize(name, coin, trades):
    if not trades:
        return _empty_summary(name, coin)
    wins = [trade for trade in trades if trade["net_pnl_pct"] > 0]
    losses = [trade for trade in trades if trade["net_pnl_pct"] < 0]
    gross_profit = sum(trade["net_pnl_pct"] for trade in wins)
    gross_loss = abs(sum(trade["net_pnl_pct"] for trade in losses))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade["net_pnl_pct"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "name": name,
        "coin": coin,
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100.0, 2),
        "gross_pnl_pct": round(sum(trade["gross_pnl_pct"] for trade in trades), 4),
        "cost_pct": round(sum(trade["cost_pct"] for trade in trades), 4),
        "net_pnl_pct": round(sum(trade["net_pnl_pct"] for trade in trades), 4),
        "avg_trade_pct": round(sum(trade["net_pnl_pct"] for trade in trades) / len(trades), 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "avg_hold_days": round(sum(trade["hold_days"] for trade in trades) / len(trades), 2),
        "diagnostics": {},
        "trades_detail": trades,
    }


def _run_funding_carry_for_coin(coin, bars, config):
    usable = [bar for bar in _slice_bars(bars, config.max_days) if isinstance(bar, dict)]
    if not usable:
        return _empty_summary("funding_carry", coin, {"missing_derivatives_data": True})
    if not any(_safe_float(bar.get("funding_rate")) is not None for bar in usable):
        return _empty_summary("funding_carry", coin, {"missing_funding_rate": len(usable)})

    trades = []
    position = None
    cost_pct = _transaction_cost_pct(config)
    for index, bar in enumerate(usable):
        funding = _safe_float(bar.get("funding_rate"))
        if funding is None:
            continue
        if position is None:
            if abs(funding) < config.funding_entry_abs:
                continue
            position = {
                "entry_index": index,
                "entry_time": _bar_time(bar),
                "direction": "short_perp_receive_funding" if funding > 0 else "long_perp_receive_funding",
                "funding_sign": 1.0 if funding > 0 else -1.0,
                "entry_funding_rate": funding,
                "funding_pnl_pct": 0.0,
            }
            continue

        position["funding_pnl_pct"] += position["funding_sign"] * funding * 100.0 * config.funding_periods_per_day
        hold_days = index - position["entry_index"]
        should_exit = abs(funding) <= config.funding_exit_abs or hold_days >= config.max_hold_days
        if should_exit:
            gross_pnl = position["funding_pnl_pct"]
            trades.append(
                {
                    "entry_time": position["entry_time"],
                    "exit_time": _bar_time(bar),
                    "direction": position["direction"],
                    "entry_funding_rate": position["entry_funding_rate"],
                    "exit_funding_rate": funding,
                    "hold_days": hold_days,
                    "gross_pnl_pct": round(gross_pnl, 4),
                    "cost_pct": round(cost_pct, 4),
                    "net_pnl_pct": round(gross_pnl - cost_pct, 4),
                    "exit_reason": "funding_normalized" if abs(funding) <= config.funding_exit_abs else "max_hold",
                }
            )
            position = None
    return _summarize("funding_carry", coin, trades)


def _run_basis_compression_for_coin(coin, bars, config):
    usable = [bar for bar in _slice_bars(bars, config.max_days) if isinstance(bar, dict)]
    if not usable:
        return _empty_summary("basis_compression", coin, {"missing_derivatives_data": True})
    if not any(_safe_float(bar.get("basis_pct")) is not None for bar in usable):
        return _empty_summary("basis_compression", coin, {"missing_basis_pct": len(usable)})

    trades = []
    position = None
    cost_pct = _transaction_cost_pct(config)
    for index, bar in enumerate(usable):
        basis = _safe_float(bar.get("basis_pct"))
        funding = _safe_float(bar.get("funding_rate")) or 0.0
        if basis is None:
            continue
        if position is None:
            if abs(basis) < config.basis_entry_abs_pct:
                continue
            position = {
                "entry_index": index,
                "entry_time": _bar_time(bar),
                "direction": "short_perp_long_spot" if basis > 0 else "long_perp_short_spot",
                "basis_sign": 1.0 if basis > 0 else -1.0,
                "entry_basis_pct": basis,
                "funding_pnl_pct": 0.0,
            }
            continue

        position["funding_pnl_pct"] += position["basis_sign"] * funding * 100.0 * config.funding_periods_per_day
        hold_days = index - position["entry_index"]
        basis_pnl = position["basis_sign"] * (position["entry_basis_pct"] - basis)
        should_exit = abs(basis) <= config.basis_exit_abs_pct or hold_days >= config.max_hold_days
        if should_exit:
            gross_pnl = basis_pnl + position["funding_pnl_pct"]
            trades.append(
                {
                    "entry_time": position["entry_time"],
                    "exit_time": _bar_time(bar),
                    "direction": position["direction"],
                    "entry_basis_pct": position["entry_basis_pct"],
                    "exit_basis_pct": basis,
                    "hold_days": hold_days,
                    "basis_pnl_pct": round(basis_pnl, 4),
                    "funding_pnl_pct": round(position["funding_pnl_pct"], 4),
                    "gross_pnl_pct": round(gross_pnl, 4),
                    "cost_pct": round(cost_pct, 4),
                    "net_pnl_pct": round(gross_pnl - cost_pct, 4),
                    "exit_reason": "basis_normalized" if abs(basis) <= config.basis_exit_abs_pct else "max_hold",
                }
            )
            position = None
    return _summarize("basis_compression", coin, trades)


def _classify_funding_trend(bar, funding_z, price_return, config):
    funding = _safe_float((bar or {}).get("funding_rate"))
    basis = _safe_float((bar or {}).get("basis_pct"))
    if funding is None or funding_z is None or price_return is None:
        return None, None

    if abs(funding_z) < config.trend_funding_z_threshold:
        label = "neutral"
        direction = None
    elif funding_z > 0 and price_return > 0:
        label = "crowded_long_risk"
        direction = "short"
    elif funding_z < 0 and price_return < 0:
        label = "crowded_short_risk"
        direction = "long"
    elif funding_z > 0 and price_return <= 0:
        label = "short_trend_support"
        direction = "short"
    else:
        label = "long_trend_support"
        direction = "long"

    if basis is not None and abs(basis) >= config.trend_basis_abs_threshold_pct:
        if basis > 0 and direction == "long":
            label = "long_basis_crowded"
        elif basis < 0 and direction == "short":
            label = "short_basis_crowded"
        elif basis > 0 and direction == "short":
            label = "short_basis_support"
        elif basis < 0 and direction == "long":
            label = "long_basis_support"
    return label, direction


def _signed_forward_return(bars, index, forward_days, direction):
    current = _close(bars[index])
    future_index = index + int(forward_days)
    if future_index >= len(bars):
        return None
    forward = _pct_change(_close(bars[future_index]), current)
    if forward is None:
        return None
    if direction == "short":
        return -forward
    return forward


def _summarize_signal_returns(values):
    values = [value for value in values if value is not None]
    if not values:
        return {"count": 0, "mean": None, "hit_rate": None}
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "hit_rate": round(sum(1 for value in values if value > 0) / len(values) * 100.0, 2),
    }


def run_funding_trend_report(price_data_map, derivatives_data_map, *, config):
    diagnostics = {}
    price_subset = {
        coin: get_coin_series(price_data_map or {}, coin, max_days=config.max_days)
        for coin in config.coins
        if coin in (price_data_map or {})
    }
    merged = merge_derivatives_into_price_data(price_subset, derivatives_data_map or {}, diagnostics)
    rows = []
    for coin in config.coins:
        bars = get_coin_series(merged, coin, max_days=config.max_days)
        if not bars:
            rows.append(
                {
                    "coin": coin,
                    "signals": 0,
                    "diagnostics": {"missing_price_data": True},
                    "labels": [],
                    "forward": [],
                }
            )
            continue

        events = []
        start = max(config.trend_funding_z_lookback, config.trend_price_lookback_days)
        max_forward = max(config.trend_forward_days or DEFAULT_TREND_FORWARD_DAYS)
        for index in range(start, len(bars) - max_forward):
            funding_window = [_safe_float(bar.get("funding_rate")) for bar in bars[index - config.trend_funding_z_lookback : index]]
            funding_mean = _mean(funding_window)
            funding_std = _std(funding_window)
            funding = _safe_float(bars[index].get("funding_rate"))
            if funding is None or funding_mean is None or not funding_std:
                continue
            funding_z = (funding - funding_mean) / funding_std
            price_return = _pct_change(_close(bars[index]), _close(bars[index - config.trend_price_lookback_days]))
            label, direction = _classify_funding_trend(bars[index], funding_z, price_return, config)
            if label is None:
                continue
            events.append(
                {
                    "coin": coin,
                    "index": index,
                    "label": label,
                    "direction": direction,
                    "funding_z": round(funding_z, 4),
                    "funding_rate": funding,
                    "basis_pct": _safe_float(bars[index].get("basis_pct")),
                    "price_return": price_return,
                }
            )

        label_rows = []
        for label in sorted({event["label"] for event in events}):
            label_events = [event for event in events if event["label"] == label]
            direction_events = [event for event in label_events if event.get("direction")]
            label_rows.append(
                {
                    "label": label,
                    "signals": len(label_events),
                    "directional_signals": len(direction_events),
                    "avg_funding_z": round(sum(event["funding_z"] for event in label_events) / len(label_events), 4),
                }
            )

        forward_rows = []
        for days in config.trend_forward_days:
            for label in sorted({event["label"] for event in events}):
                label_events = [event for event in events if event["label"] == label and event.get("direction")]
                returns = [
                    _signed_forward_return(bars, event["index"], days, event["direction"])
                    for event in label_events
                ]
                forward_rows.append({"label": label, "forward_days": days, **_summarize_signal_returns(returns)})

        latest_directional = next((event for event in reversed(events) if event.get("direction")), None)
        rows.append(
            {
                "coin": coin,
                "signals": len(events),
                "diagnostics": {},
                "labels": label_rows,
                "forward": forward_rows,
                "latest_context": latest_directional or (events[-1] if events else None),
            }
        )
    return {
        "coins": config.coins,
        "max_days": config.max_days,
        "trend_forward_days": config.trend_forward_days,
        "trend_funding_z_threshold": config.trend_funding_z_threshold,
        "trend_basis_abs_threshold_pct": config.trend_basis_abs_threshold_pct,
        "diagnostics": diagnostics,
        "rows": rows,
    }


def run_carry_report(derivatives_data_map, *, config):
    rows = []
    for coin in config.coins:
        bars = list((derivatives_data_map or {}).get(coin, []))
        if "funding_carry" in config.carry_set:
            rows.append(_run_funding_carry_for_coin(coin, bars, config))
        if "basis_compression" in config.carry_set:
            rows.append(_run_basis_compression_for_coin(coin, bars, config))
    return {
        "coins": config.coins,
        "carry_set": config.carry_set,
        "max_days": config.max_days,
        "funding_entry_abs": config.funding_entry_abs,
        "basis_entry_abs_pct": config.basis_entry_abs_pct,
        "cost_per_trade_pct": round(_transaction_cost_pct(config), 4),
        "rows": rows,
        "paper_trade_plan": build_paper_trade_plan(rows),
    }


def build_paper_trade_plan(rows):
    missing_or_empty = [row for row in rows if not row.get("trades")]
    if not missing_or_empty:
        return []
    return [
        "Run a daily derivatives snapshot for 3-7 days before promotion.",
        "Track funding_rate, open_interest, basis_pct, mark/index source, and timestamp per coin.",
        "Paper-enter only when funding or basis exceeds the report threshold for two consecutive snapshots.",
        "Record hypothetical spread entry, expected funding received/paid, basis change, and two-leg costs.",
        "Do not route to live execution until the monitor has real data and positive net expectancy after costs.",
    ]


def format_carry_report_lines(report):
    lines = ["Carry / Funding / Basis report"]
    lines.append(
        "coins={coins}, carry_set={carry_set}, max_days={max_days}, funding_entry_abs={funding_entry_abs}, "
        "basis_entry_abs_pct={basis_entry_abs_pct}, cost_per_trade_pct={cost_per_trade_pct}".format(
            coins=",".join(report.get("coins") or ()),
            carry_set=",".join(report.get("carry_set") or ()),
            max_days=report.get("max_days"),
            funding_entry_abs=report.get("funding_entry_abs"),
            basis_entry_abs_pct=report.get("basis_entry_abs_pct"),
            cost_per_trade_pct=report.get("cost_per_trade_pct"),
        )
    )
    for row in report.get("rows") or []:
        lines.append(
            "[{name}:{coin}] trades={trades}, win_rate={win_rate:.1f}%, net_pnl={net_pnl_pct:+.4f}%, "
            "gross_pnl={gross_pnl_pct:+.4f}%, cost={cost_pct:.4f}%, avg_trade={avg_trade_pct:+.4f}%, "
            "max_dd={max_drawdown_pct:.4f}%, pf={profit_factor}, avg_hold_days={avg_hold_days:.2f}".format(
                **row
            )
        )
        if row.get("diagnostics"):
            lines.append(f"{row['name']}:{row['coin']} diagnostics={row['diagnostics']}")
        for trade in (row.get("trades_detail") or [])[:3]:
            lines.append(
                "{name}:{coin} sample trade: direction={direction}, hold_days={hold_days}, "
                "net={net_pnl_pct:+.4f}%, exit={exit_reason}".format(
                    name=row["name"],
                    coin=row["coin"],
                    **trade,
                )
            )
    paper_plan = report.get("paper_trade_plan") or []
    if paper_plan:
        lines.append("[paper_trade_fallback]")
        lines.extend(f"- {item}" for item in paper_plan)
    return lines


def format_funding_trend_report_lines(report):
    lines = ["Funding / Basis short-term trend report"]
    lines.append(
        "coins={coins}, max_days={max_days}, forward_days={forward_days}, funding_z_threshold={funding_z}, "
        "basis_abs_threshold_pct={basis_threshold}".format(
            coins=",".join(report.get("coins") or ()),
            max_days=report.get("max_days"),
            forward_days=",".join(str(day) for day in report.get("trend_forward_days") or ()),
            funding_z=report.get("trend_funding_z_threshold"),
            basis_threshold=report.get("trend_basis_abs_threshold_pct"),
        )
    )
    if report.get("diagnostics"):
        lines.append(f"diagnostics={report['diagnostics']}")
    for row in report.get("rows") or []:
        lines.append(f"[{row['coin']}] signals={row['signals']}")
        if row.get("diagnostics"):
            lines.append(f"{row['coin']} diagnostics={row['diagnostics']}")
        latest = row.get("latest_context")
        if latest:
            lines.append(
                "{coin} latest: label={label}, direction={direction}, funding_z={funding_z}, "
                "funding_rate={funding_rate}, basis_pct={basis_pct}, price_return={price_return:.4f}".format(
                    coin=row["coin"],
                    label=latest.get("label"),
                    direction=latest.get("direction") or "none",
                    funding_z=latest.get("funding_z"),
                    funding_rate=latest.get("funding_rate"),
                    basis_pct=latest.get("basis_pct"),
                    price_return=float(latest.get("price_return") or 0.0),
                )
            )
        for label in row.get("labels") or []:
            lines.append(
                "{coin} label={label}, signals={signals}, directional={directional_signals}, avg_funding_z={avg_funding_z}".format(
                    coin=row["coin"],
                    **label,
                )
            )
        for forward in row.get("forward") or []:
            if not forward.get("count"):
                continue
            lines.append(
                "{coin} forward={forward_days}d label={label}: count={count}, mean={mean}, hit_rate={hit_rate}".format(
                    coin=row["coin"],
                    **forward,
                )
            )
    return lines
