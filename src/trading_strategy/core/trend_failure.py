"""Shared trend-failure exit evaluation.

The original no-follow-through experiment underperformed and is no longer used
as the primary early-exit path. The active rule is breakout-failure only.
"""


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_trend_failure_exit(
    position,
    *,
    bars_since_entry,
    current_price,
    current_ema20,
    enabled=True,
    failure_exit_bars=3,
    failure_exit_mode="breakout_failure",
):
    result = {
        "triggered": False,
        "mode": failure_exit_mode,
        "bars_since_entry": int(bars_since_entry or 0),
        "entry_breakout_level": None,
        "current_ema20": None,
    }
    if not enabled:
        return result
    if (position or {}).get("exit_policy", {}).get("name") != "trend_sl_only":
        return result
    if str(failure_exit_mode or "breakout_failure") != "breakout_failure":
        return result

    current_price = _safe_float(current_price)
    current_ema20 = _safe_float(current_ema20)
    entry_breakout_level = _safe_float((position or {}).get("entry_breakout_level"))
    if current_price is None or current_ema20 is None or entry_breakout_level is None:
        return result

    result["entry_breakout_level"] = entry_breakout_level
    result["current_ema20"] = current_ema20

    if int(bars_since_entry or 0) > int(failure_exit_bars or 0):
        return result

    direction = (position or {}).get("direction")
    if direction == "long":
        result["triggered"] = (
            current_price < entry_breakout_level
            and current_price < current_ema20
        )
        return result
    if direction == "short":
        result["triggered"] = (
            current_price > entry_breakout_level
            and current_price > current_ema20
        )
        return result

    return result
