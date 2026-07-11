from trading_strategy.strategies import get_strategy, get_trend_structure_context
from trading_strategy.strategies.base import StrategyContext

from .. import config
from ..market import enrich_klines_with_derivatives_context, get_klines


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_active_strategy_name():
    return str(config.STRATEGY.get("name") or "trend")


def get_active_strategy():
    return get_strategy(get_active_strategy_name())


def get_position_strategy(pos):
    strategy_name = (pos or {}).get("strategy_name") or get_active_strategy_name()
    return get_strategy(strategy_name)


def build_strategy_context(coin, klines, *, price=None, balance=0.0, open_positions=(), diagnostics=None):
    window = list(klines or [])
    current_bar = window[-1] if window else None
    return StrategyContext(
        coin=coin,
        window=window,
        current_bar=current_bar,
        balance=float(balance or 0.0),
        open_positions=tuple(open_positions or ()),
        config=config.STRATEGY,
        mode=config.MODE,
        price=price,
        diagnostics=diagnostics,
    )


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
    strategy = get_active_strategy()
    strategy_config = dict(config.STRATEGY)
    strategy_config["min_score"] = min_score
    return strategy.generate_signal(
        StrategyContext(
            coin="",
            window=list(klines or []),
            current_bar=(klines or [None])[-1],
            config=strategy_config,
            mode=config.MODE,
        )
    )


def check_trend_reversal(pos, klines):
    evaluation = evaluate_open_position(pos, klines)
    return bool(evaluation.get("reversal_detected"))


def should_enrich_derivatives_context():
    return bool(config.STRATEGY.get("derivatives_crowding_exit_enabled"))


def prepare_position_klines(pos, klines):
    if not klines or not should_enrich_derivatives_context():
        return klines
    current_bar = klines[-1] if klines else {}
    if current_bar.get("funding_rate") is not None and current_bar.get("basis_pct") is not None:
        return klines
    lookback = int(config.STRATEGY.get("derivatives_crowding_funding_z_lookback") or 30) + 1
    return enrich_klines_with_derivatives_context(pos.get("coin", ""), klines, lookback=lookback)


def evaluate_open_position(pos, klines):
    strategy = get_position_strategy(pos)
    diagnostics = pos.setdefault("strategy_diagnostics", {})
    return strategy.evaluate_open_position(
        pos,
        build_strategy_context(
            pos.get("coin", ""),
            klines,
            price=pos.get("current_price"),
            diagnostics=diagnostics,
        ),
    )


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
    strategy = get_position_strategy(pos)
    exit_policy = strategy.build_exit_policy(position=pos)
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
    strategy = get_position_strategy(pos)
    strategy.initialize_position(
        pos,
        None,
        build_strategy_context(
            pos.get("coin", ""),
            [],
            price=pos.get("current_price") or pos.get("entry"),
        ),
    )


def compute_dynamic_sl_target(pos):
    strategy = get_position_strategy(pos)
    stop_target = strategy.resolve_stop_target(
        pos,
        build_strategy_context(
            pos.get("coin", ""),
            [],
            price=pos.get("current_price"),
        ),
    )
    return (stop_target or {}).get("dynamic_target")


def compute_trend_stop_target(pos, klines):
    strategy = get_position_strategy(pos)
    return strategy.resolve_stop_target(
        pos,
        build_strategy_context(
            pos.get("coin", ""),
            klines,
            price=pos.get("current_price"),
        ),
    )


def check_atr_trailing_exit(pos, klines):
    evaluation = evaluate_open_position(pos, klines)
    return evaluation.get("atr_trail_result") or {"triggered": False}


def check_trend_failure_exit(pos, klines):
    evaluation = evaluate_open_position(pos, klines)
    return evaluation.get("failure_exit") or {
        "triggered": False,
        "bars_since_entry": 0,
        "entry_breakout_level": None,
        "current_ema20": None,
    }
