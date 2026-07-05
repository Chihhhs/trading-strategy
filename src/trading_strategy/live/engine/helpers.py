from trading_strategy.core.exit_policy import build_exit_policy
from trading_strategy.core.signals import generate_trend_signal

from .. import config
from ..market import get_klines


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    ema = sum(closes[:period]) / period
    weight = 2 / (period + 1)
    for close in closes[period:]:
        ema = close * weight + ema * (1 - weight)
    return ema


def calc_atr(highs, lows, closes, period=14):
    trs = [
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, len(highs))
    ]
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def generate_signal(klines, min_score=4):
    return generate_trend_signal(
        klines,
        min_score=min_score,
        tp_mult=config.STRATEGY["tp_mult"],
        sl_mult=config.STRATEGY["sl_mult"],
    )


def check_trend_reversal(pos, klines):
    if not klines or len(klines) < 30:
        return False
    closes = [d["close"] for d in klines]
    e20 = calc_ema(closes, 20)
    e50 = calc_ema(closes, 50)
    e20_prev = calc_ema(closes[:-1], 20)
    e50_prev = calc_ema(closes[:-1], 50) if len(closes) > 50 else e50
    cur = closes[-1]
    if pos["direction"] == "long":
        return cur < e20 and e20 < e50 and e20_prev >= e50_prev
    return cur > e20 and e20 > e50 and e20_prev <= e50_prev


def estimate_position_margin(pos, leverage):
    if leverage <= 0:
        return 0.0
    entry = _safe_float(pos.get("entry"), default=None)
    size = _safe_float(pos.get("size"), default=None)
    if entry is None or size is None or size <= 0:
        return 0.0
    return abs(entry * size) / leverage


def get_available_entry_balance(state, leverage):
    balance = _safe_float((state or {}).get("balance"), default=0.0)
    if balance <= 0:
        return 0.0
    reserved_margin = sum(
        estimate_position_margin(pos, leverage) for pos in (state or {}).get("positions", [])
    )
    return max(balance - reserved_margin, 0.0)


def ensure_position_targets(pos, data_cache=None):
    exit_policy = build_exit_policy(position=pos)
    if pos.get("sl") is not None and (not exit_policy.get("requires_tp") or pos.get("tp") is not None):
        return pos.get("tp"), pos.get("sl")
    klines = None
    if isinstance(data_cache, dict):
        klines = data_cache.get(pos["coin"])
    if not klines:
        klines = get_klines(f'{pos["coin"]}USDT', 60)
        if isinstance(data_cache, dict) and klines:
            data_cache[pos["coin"]] = klines
    entry = _safe_float(pos.get("entry"))
    atr = None
    if klines and len(klines) >= 2:
        atr = calc_atr(
            [d["high"] for d in klines],
            [d["low"] for d in klines],
            [d["close"] for d in klines],
        )
    if not atr:
        atr = entry * 0.03
    if pos.get("direction") == "long":
        tp = pos.get("tp") or (entry + atr * config.STRATEGY["tp_mult"])
        sl = pos.get("sl") or (entry - atr * config.STRATEGY["sl_mult"])
    else:
        tp = pos.get("tp") or (entry - atr * config.STRATEGY["tp_mult"])
        sl = pos.get("sl") or (entry + atr * config.STRATEGY["sl_mult"])
    pos["tp"] = tp if exit_policy.get("requires_tp") else None
    pos["sl"] = sl
    return pos.get("tp"), sl


def _infer_sl_stage(pos):
    entry = _safe_float(pos.get("entry"), default=None)
    sl = _safe_float(pos.get("sl"), default=None)
    initial_risk = _safe_float(pos.get("initial_risk"), default=None)
    if entry is None or sl is None or initial_risk is None or initial_risk <= 0:
        return 0
    half_r_target = entry + initial_risk * 0.5 if pos.get("direction") == "long" else entry - initial_risk * 0.5
    if pos.get("direction") == "long":
        if sl >= half_r_target:
            return 2
        if sl >= entry:
            return 1
        return 0
    if sl <= half_r_target:
        return 2
    if sl <= entry:
        return 1
    return 0


def initialize_dynamic_sl_state(pos):
    exit_policy = build_exit_policy(position=pos)
    if exit_policy.get("name") != "trend_sl_only":
        return
    entry = _safe_float(pos.get("entry"), default=None)
    sl = _safe_float(pos.get("sl"), default=None)
    current_price = _safe_float(pos.get("current_price"), default=None)
    if pos.get("initial_risk") is None and entry is not None and sl is not None:
        pos["initial_risk"] = abs(entry - sl)
    if pos.get("sl_stage") is None:
        pos["sl_stage"] = _infer_sl_stage(pos)
    if pos.get("best_price") is None:
        pos["best_price"] = current_price if current_price is not None else entry


def compute_dynamic_sl_target(pos):
    initialize_dynamic_sl_state(pos)
    exit_policy = build_exit_policy(position=pos)
    if exit_policy.get("name") != "trend_sl_only":
        return None
    entry = _safe_float(pos.get("entry"), default=None)
    current_price = _safe_float(pos.get("current_price"), default=None)
    initial_risk = _safe_float(pos.get("initial_risk"), default=None)
    if entry is None or current_price is None or initial_risk is None or initial_risk <= 0:
        return None

    best_price = _safe_float(pos.get("best_price"), default=None)
    if best_price is None:
        best_price = current_price
    if pos.get("direction") == "long":
        best_price = max(best_price, current_price)
        progress_r = (best_price - entry) / initial_risk
    else:
        best_price = min(best_price, current_price)
        progress_r = (entry - best_price) / initial_risk
    pos["best_price"] = best_price

    current_stage = int(pos.get("sl_stage") or 0)
    target_stage = current_stage
    target_sl = _safe_float(pos.get("sl"), default=None)

    if progress_r >= 1.5:
        target_stage = max(target_stage, 2)
    elif progress_r >= 1.0:
        target_stage = max(target_stage, 1)

    if target_stage >= 2:
        target_sl = entry + initial_risk * 0.5 if pos.get("direction") == "long" else entry - initial_risk * 0.5
    elif target_stage >= 1:
        target_sl = entry

    return {"sl": target_sl, "stage": target_stage, "progress_r": progress_r, "best_price": best_price}
