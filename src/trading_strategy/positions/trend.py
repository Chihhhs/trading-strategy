"""Reusable trend-position state and stop helpers."""


def _safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _infer_sl_stage(pos):
    entry = _safe_float((pos or {}).get("entry"), default=None)
    sl = _safe_float((pos or {}).get("sl"), default=None)
    initial_risk = _safe_float((pos or {}).get("initial_risk"), default=None)
    direction = (pos or {}).get("direction")
    if entry is None or sl is None or initial_risk is None or initial_risk <= 0:
        return 0
    half_r_target = entry + initial_risk * 0.5 if direction == "long" else entry - initial_risk * 0.5
    if direction == "long":
        if sl >= half_r_target:
            return 2
        if sl >= entry:
            return 1
        return 0
    if direction == "short":
        if sl <= half_r_target:
            return 2
        if sl <= entry:
            return 1
    return 0


def initialize_trend_position_state(pos):
    if ((pos or {}).get("exit_policy") or {}).get("name") != "trend_sl_only":
        return
    entry = _safe_float((pos or {}).get("entry"), default=None)
    sl = _safe_float((pos or {}).get("sl"), default=None)
    current_price = _safe_float((pos or {}).get("current_price"), default=None)
    if (pos or {}).get("initial_risk") is None and entry is not None and sl is not None:
        pos["initial_risk"] = abs(entry - sl)
    if (pos or {}).get("sl_stage") is None:
        pos["sl_stage"] = _infer_sl_stage(pos)
    if (pos or {}).get("best_price") is None:
        pos["best_price"] = current_price if current_price is not None else entry


def compute_trend_progress(pos):
    initialize_trend_position_state(pos)
    entry = _safe_float((pos or {}).get("entry"), default=None)
    current_price = _safe_float((pos or {}).get("current_price"), default=None)
    initial_risk = _safe_float((pos or {}).get("initial_risk"), default=None)
    direction = (pos or {}).get("direction")
    if entry is None or current_price is None or initial_risk is None or initial_risk <= 0:
        return None

    best_price = _safe_float((pos or {}).get("best_price"), default=None)
    if best_price is None:
        best_price = current_price
    if direction == "long":
        best_price = max(best_price, current_price)
        progress_r = (best_price - entry) / initial_risk
    elif direction == "short":
        best_price = min(best_price, current_price)
        progress_r = (entry - best_price) / initial_risk
    else:
        return None

    pos["best_price"] = best_price
    return {"best_price": best_price, "progress_r": progress_r, "initial_risk": initial_risk}


def compute_dynamic_sl_target(pos):
    progress = compute_trend_progress(pos)
    if progress is None:
        return None

    entry = _safe_float((pos or {}).get("entry"), default=None)
    current_stage = int((pos or {}).get("sl_stage") or 0)
    target_stage = current_stage
    target_sl = _safe_float((pos or {}).get("sl"), default=None)
    progress_r = progress["progress_r"]
    initial_risk = progress["initial_risk"]
    direction = (pos or {}).get("direction")

    if progress_r >= 1.5:
        target_stage = max(target_stage, 2)
    elif progress_r >= 1.0:
        target_stage = max(target_stage, 1)

    if target_stage >= 2:
        target_sl = entry + initial_risk * 0.5 if direction == "long" else entry - initial_risk * 0.5
    elif target_stage >= 1:
        target_sl = entry

    return {
        "sl": target_sl,
        "stage": target_stage,
        "progress_r": progress_r,
        "best_price": progress["best_price"],
        "source": "dynamic_stage",
    }


def compute_atr_trailing_result(
    pos,
    *,
    current_atr,
    enabled=False,
    atr_activation_r=1.5,
    atr_trailing_mult=2.0,
):
    result = {
        "enabled": bool(enabled),
        "active": False,
        "triggered": False,
        "should_update": False,
        "target_sl": None,
        "progress_r": None,
        "best_price": None,
        "current_atr": _safe_float(current_atr, default=None),
        "source": "atr_trail",
    }
    progress = compute_trend_progress(pos)
    if not enabled or progress is None:
        return result

    current_atr = _safe_float(current_atr, default=None)
    current_sl = _safe_float((pos or {}).get("sl"), default=None)
    current_price = _safe_float((pos or {}).get("current_price"), default=None)
    direction = (pos or {}).get("direction")
    if current_atr is None or current_atr <= 0 or current_price is None:
        return result

    result["progress_r"] = progress["progress_r"]
    result["best_price"] = progress["best_price"]
    if progress["progress_r"] < float(atr_activation_r):
        return result

    result["active"] = True
    if direction == "long":
        target_sl = progress["best_price"] - current_atr * float(atr_trailing_mult)
        is_more_protective = current_sl is None or target_sl > current_sl
        is_crossed = current_price <= target_sl
    elif direction == "short":
        target_sl = progress["best_price"] + current_atr * float(atr_trailing_mult)
        is_more_protective = current_sl is None or target_sl < current_sl
        is_crossed = current_price >= target_sl
    else:
        return result

    result["target_sl"] = target_sl
    result["effective_atr_trailing_mult"] = float(atr_trailing_mult)
    result["should_update"] = bool(is_more_protective)
    result["triggered"] = bool(is_crossed)
    return result


def resolve_trend_stop_target(
    pos,
    *,
    current_atr,
    atr_trailing_enabled=False,
    atr_activation_r=1.5,
    atr_trailing_mult=2.0,
):
    dynamic_target = compute_dynamic_sl_target(pos)
    atr_result = compute_atr_trailing_result(
        pos,
        current_atr=current_atr,
        enabled=atr_trailing_enabled,
        atr_activation_r=atr_activation_r,
        atr_trailing_mult=atr_trailing_mult,
    )

    chosen_sl = (dynamic_target or {}).get("sl")
    chosen_source = (dynamic_target or {}).get("source")
    direction = (pos or {}).get("direction")
    atr_target_sl = atr_result.get("target_sl")
    if atr_target_sl is not None:
        if chosen_sl is None:
            chosen_sl = atr_target_sl
            chosen_source = atr_result.get("source")
        elif direction == "long" and atr_target_sl > chosen_sl:
            chosen_sl = atr_target_sl
            chosen_source = atr_result.get("source")
        elif direction == "short" and atr_target_sl < chosen_sl:
            chosen_sl = atr_target_sl
            chosen_source = atr_result.get("source")

    should_update = False
    current_sl = _safe_float((pos or {}).get("sl"), default=None)
    if chosen_sl is not None:
        if direction == "long":
            should_update = current_sl is None or chosen_sl > current_sl
        elif direction == "short":
            should_update = current_sl is None or chosen_sl < current_sl

    return {
        "sl": chosen_sl,
        "source": chosen_source,
        "dynamic_target": dynamic_target,
        "atr_result": atr_result,
        "should_update": should_update,
    }


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
            current_price < entry_breakout_level and current_price < current_ema20
        )
        return result
    if direction == "short":
        result["triggered"] = (
            current_price > entry_breakout_level and current_price > current_ema20
        )
        return result

    return result
