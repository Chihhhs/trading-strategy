from dataclasses import replace

from trading_strategy.strategies import get_btc_direction_from_klines
from trading_strategy.strategies.base import StrategySignal, signal_value
from trading_strategy.strategies.trend import get_derivatives_crowding_context

from .derivatives import _safe_float


def _increment(diagnostics, key):
    if diagnostics is not None:
        diagnostics[key] = int(diagnostics.get(key) or 0) + 1


def _pct_change(current, previous):
    current = _safe_float(current)
    previous = _safe_float(previous)
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def _score_delta(direction, boost):
    boost = abs(float(boost or 0.0))
    return boost if direction == "long" else -boost


def _with_score_adjustment(signal, delta, reason):
    if not delta:
        return signal
    current_score = signal_value(signal, "score", 0.0) or 0.0
    new_score = current_score + delta
    raw = dict(signal_value(signal, "raw", {}) or {})
    overlays = list(raw.get("alpha_entry_overlays") or [])
    overlays.append(reason)
    raw["alpha_entry_overlays"] = overlays
    raw["pre_alpha_entry_score"] = current_score
    raw["score"] = new_score
    if isinstance(signal, StrategySignal):
        return replace(signal, score=new_score, raw=raw)
    adjusted = dict(signal)
    adjusted["score"] = new_score
    adjusted["raw"] = raw
    return adjusted


def _has_derivatives_context(window):
    current = (window or [{}])[-1] if window else {}
    return any(
        _safe_float((current or {}).get(field)) is not None
        for field in ("funding_rate", "basis_pct", "open_interest")
    )


def _btc_regime_action(coin, direction, btc_window):
    if str(coin or "").upper() == "BTC" or not btc_window:
        return None
    btc_direction = get_btc_direction_from_klines(btc_window)
    if btc_direction == "bull":
        return "support" if direction == "long" else "block"
    if btc_direction == "bear":
        return "support" if direction == "short" else "block"
    return None


def _funding_basis_action(direction, window, config):
    context = get_derivatives_crowding_context(window, config)
    if not context:
        return None, None
    label = context.get("label")
    if direction == "long":
        if label == "long_basis_support":
            return "support", context
        if label in ("short_basis_crowded", "crowded_long_risk"):
            return "block", context
    if direction == "short":
        if label == "short_basis_support":
            return "support", context
        if label in ("long_basis_crowded", "crowded_short_risk"):
            return "block", context
    return None, context


def _oi_confirmation_action(direction, window, config):
    lookback = int(getattr(config, "derivatives_oi_lookback", 5) or 5)
    if not window or len(window) <= lookback:
        return None
    current = window[-1]
    previous = window[-lookback - 1]
    current_oi = _safe_float((current or {}).get("open_interest"))
    previous_oi = _safe_float((previous or {}).get("open_interest"))
    if current_oi is None or previous_oi in (None, 0):
        return None
    oi_change = _pct_change(current_oi, previous_oi)
    price_return = _pct_change((current or {}).get("close"), (previous or {}).get("close"))
    if oi_change is None or oi_change <= 0 or price_return is None or abs(price_return) < 0.1:
        return None
    price_direction = "long" if price_return > 0 else "short"
    if price_direction != direction:
        return None
    funding = _safe_float((current or {}).get("funding_rate"))
    high_funding = funding is not None and abs(funding) >= abs(float(getattr(config, "derivatives_funding_upper", 0.0005) or 0.0005))
    late_crowded = oi_change >= 10.0 and high_funding
    return None if late_crowded else "support"


def apply_trend_alpha_entry_overlay(signal, context, config):
    if signal is None or not bool(getattr(config, "trend_alpha_entry_enabled", False)):
        return signal

    diagnostics = context.diagnostics
    direction = str(signal_value(signal, "direction", "") or "").lower()
    if direction not in ("long", "short"):
        return signal

    mode = str(getattr(config, "trend_alpha_mode", "combined") or "combined").lower()
    if mode not in ("filter", "score", "combined"):
        mode = "combined"
    allow_score = mode in ("score", "combined")
    allow_filter = mode in ("filter", "combined") and bool(getattr(config, "trend_alpha_block_crowded_entry", True))
    boost = float(getattr(config, "trend_alpha_score_boost", 1.0) or 0.0)
    supports = 0
    adjusted = signal

    btc_action = _btc_regime_action(context.coin, direction, context.btc_window)
    if btc_action == "block" and allow_filter:
        _increment(diagnostics, "trend_alpha_crowded_blocks")
        return None
    if btc_action == "support":
        supports += 1
        _increment(diagnostics, "trend_alpha_btc_regime_boosts")
        if allow_score:
            adjusted = _with_score_adjustment(adjusted, _score_delta(direction, boost), "btc_regime_trend")

    if not _has_derivatives_context(context.window):
        _increment(diagnostics, "trend_alpha_missing_derivatives_bars")
    else:
        funding_action, _funding_context = _funding_basis_action(direction, context.window, config)
        if funding_action == "block" and allow_filter:
            _increment(diagnostics, "trend_alpha_crowded_blocks")
            return None
        if funding_action == "support":
            supports += 1
            _increment(diagnostics, "trend_alpha_funding_basis_boosts")
            if allow_score:
                adjusted = _with_score_adjustment(adjusted, _score_delta(direction, boost), "funding_basis_trend_context")

        oi_action = _oi_confirmation_action(direction, context.window, config)
        if oi_action == "support":
            supports += 1
            _increment(diagnostics, "trend_alpha_oi_boosts")
            if allow_score:
                adjusted = _with_score_adjustment(adjusted, _score_delta(direction, boost), "oi_expansion_confirmation")

    if bool(getattr(config, "trend_alpha_require_confirmation", False)) and supports <= 0:
        _increment(diagnostics, "trend_alpha_unconfirmed_blocks")
        return None
    return adjusted
