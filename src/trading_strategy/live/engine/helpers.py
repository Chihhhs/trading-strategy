from trading_strategy.core.exit_policy import build_exit_policy
from trading_strategy.core.signals import generate_trend_signal, get_trend_structure_context
from trading_strategy.core.trend_trade import (
    compute_atr_trailing_result,
    compute_dynamic_sl_target as compute_shared_dynamic_sl_target,
    initialize_trend_position_state,
    resolve_trend_stop_target,
)
from trading_strategy.core.trend_failure import evaluate_trend_failure_exit

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


def initialize_dynamic_sl_state(pos):
    initialize_trend_position_state(pos)


def compute_dynamic_sl_target(pos):
    return compute_shared_dynamic_sl_target(pos)


def compute_trend_stop_target(pos, klines):
    current_atr = None
    if klines and len(klines) >= 2:
        current_atr = calc_atr(
            [d["high"] for d in klines],
            [d["low"] for d in klines],
            [d["close"] for d in klines],
        )
    return resolve_trend_stop_target(
        pos,
        current_atr=current_atr,
        atr_trailing_enabled=config.STRATEGY.get("atr_trailing_enabled", False),
        atr_activation_r=config.STRATEGY.get("atr_activation_r", 1.5),
        atr_trailing_mult=config.STRATEGY.get("atr_trailing_mult", 2.0),
    )


def check_atr_trailing_exit(pos, klines):
    current_atr = None
    if klines and len(klines) >= 2:
        current_atr = calc_atr(
            [d["high"] for d in klines],
            [d["low"] for d in klines],
            [d["close"] for d in klines],
        )
    return compute_atr_trailing_result(
        pos,
        current_atr=current_atr,
        enabled=config.STRATEGY.get("atr_trailing_enabled", False),
        atr_activation_r=config.STRATEGY.get("atr_activation_r", 1.5),
        atr_trailing_mult=config.STRATEGY.get("atr_trailing_mult", 2.0),
    )


def check_trend_failure_exit(pos, klines):
    if not klines:
        return {"triggered": False, "bars_since_entry": 0, "entry_breakout_level": None, "current_ema20": None}
    entry_klines_len = int(pos.get("entry_klines_len") or 0)
    bars_since_entry = max(len(klines) - entry_klines_len, 0) if entry_klines_len > 0 else 0
    current_price = _safe_float(pos.get("current_price"), default=None)
    structure = get_trend_structure_context(klines)
    return evaluate_trend_failure_exit(
        pos,
        bars_since_entry=bars_since_entry,
        current_price=current_price,
        current_ema20=(structure or {}).get("ema20"),
        enabled=config.STRATEGY.get("failure_exit_enabled", True),
        failure_exit_bars=config.STRATEGY.get("failure_exit_bars", 3),
        failure_exit_mode=config.STRATEGY.get("failure_exit_mode", "breakout_failure"),
    )
