from datetime import datetime, timezone


HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS


def classify_stop_kind(position, stop_source):
    if stop_source == "ATR_TRAIL":
        return "atr"
    stage = int((position or {}).get("sl_stage") or 0)
    if stage >= 2:
        return "half_r"
    if stage == 1:
        return "breakeven"
    return "initial"


def build_mark_to_market_point(
    *,
    balance,
    positions,
    prices,
    timestamp_ms,
    fee_bps=0.0,
    slippage_bps=0.0,
):
    positions = list(positions or [])
    if any(position.get("coin") not in prices for position in positions):
        return None
    rate = (float(fee_bps or 0.0) + float(slippage_bps or 0.0)) / 10000.0
    unrealized = 0.0
    estimated_cost = 0.0
    gross_exposure = 0.0
    for position in positions:
        entry = float(position.get("entry") or 0.0)
        size = abs(float(position.get("size") or 0.0))
        current = float(prices[position["coin"]])
        direction = position.get("direction")
        unrealized += (current - entry) * size if direction == "long" else (entry - current) * size
        estimated_cost += (abs(entry) + abs(current)) * size * rate
        gross_exposure += abs(current) * size
    equity = float(balance or 0.0) + unrealized - estimated_cost
    return {
        "timestamp_ms": int(timestamp_ms),
        "timestamp": datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc).isoformat(),
        "equity": round(equity, 8),
        "realized_balance": round(float(balance or 0.0), 8),
        "unrealized_pnl": round(unrealized, 8),
        "estimated_exit_cost": round(estimated_cost, 8),
        "gross_exposure": round(gross_exposure, 8),
        "open_positions": len(positions),
    }


def drawdown_diagnostics(points):
    peak_equity = None
    peak_time = None
    max_drawdown = 0.0
    max_peak_time = None
    max_trough_time = None
    for point in points or []:
        equity = float(point["equity"])
        timestamp = int(point["timestamp_ms"])
        if peak_equity is None or equity > peak_equity:
            peak_equity = equity
            peak_time = timestamp
        if peak_equity and peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity * 100.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_peak_time = peak_time
                max_trough_time = timestamp
    if max_peak_time is None:
        duration = 0.0
    else:
        recovery = next(
            (
                int(point["timestamp_ms"])
                for point in points
                if int(point["timestamp_ms"]) > max_trough_time
                and float(point["equity"])
                >= next(item["equity"] for item in points if int(item["timestamp_ms"]) == max_peak_time)
            ),
            int(points[-1]["timestamp_ms"]),
        )
        duration = (recovery - max_peak_time) / HOUR_MS
    return {
        "max_drawdown_pct": round(max_drawdown, 4),
        "peak_timestamp_ms": max_peak_time,
        "trough_timestamp_ms": max_trough_time,
        "drawdown_duration_hours": round(duration, 2),
    }


def summarize_mark_to_market(points):
    points = list(points or [])
    report = drawdown_diagnostics(points)
    daily_points = [point for point in points if int(point["timestamp_ms"]) % DAY_MS == 0]
    daily_report = drawdown_diagnostics(daily_points)
    report.update(
        {
            "points": len(points),
            "daily_points": len(daily_points),
            "daily_max_drawdown_pct": daily_report["max_drawdown_pct"],
            "max_gross_exposure": round(max((float(point["gross_exposure"]) for point in points), default=0.0), 2),
            "max_open_positions": max((int(point["open_positions"]) for point in points), default=0),
            "max_unrealized_profit": round(max((float(point["unrealized_pnl"]) for point in points), default=0.0), 2),
            "max_unrealized_loss": round(min((float(point["unrealized_pnl"]) for point in points), default=0.0), 2),
            "ending_equity": round(float(points[-1]["equity"]), 2) if points else None,
            "ending_realized_balance": round(float(points[-1]["realized_balance"]), 2) if points else None,
            "ending_unrealized_pnl": round(float(points[-1]["unrealized_pnl"]), 2) if points else None,
            "ending_estimated_exit_cost": round(float(points[-1]["estimated_exit_cost"]), 2) if points else None,
        }
    )
    return report
