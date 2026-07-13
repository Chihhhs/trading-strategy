import json
import math


DERIVATIVE_FIELDS = ("funding_rate", "open_interest", "basis_pct", "mark_price", "index_price")


def _safe_float(value):
    try:
        if value is None:
            return None
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(converted) or math.isinf(converted):
        return None
    return converted


def _bar_time(bar):
    if not isinstance(bar, dict):
        return None
    return bar.get("time") or bar.get("timestamp") or bar.get("date") or bar.get("ts")


def normalize_derivatives_data_map(data_map, *, max_days=None):
    normalized = {}
    for coin, bars in (data_map or {}).items():
        if not isinstance(bars, list):
            continue
        usable = bars[-max_days:] if max_days is not None else list(bars)
        normalized_bars = []
        for bar in usable:
            if not isinstance(bar, dict):
                continue
            item = {}
            timestamp = _bar_time(bar)
            if timestamp is not None:
                item["time"] = timestamp
            for field in DERIVATIVE_FIELDS:
                item[field] = _safe_float(bar.get(field))
            normalized_bars.append(item)
        normalized[str(coin).upper()] = normalized_bars
    return normalized


def load_derivatives_data(path, *, max_days=None):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data_map = json.load(handle)
    return normalize_derivatives_data_map(data_map, max_days=max_days)


def merge_derivatives_into_price_data(price_data_map, derivatives_data_map, diagnostics=None):
    if not derivatives_data_map:
        return {coin: list(bars or []) for coin, bars in (price_data_map or {}).items()}

    merged = {}
    missing = []
    partial = {}
    for coin, price_bars in (price_data_map or {}).items():
        derivative_bars = list((derivatives_data_map or {}).get(coin, []))
        if not derivative_bars:
            missing.append(coin)
            merged[coin] = list(price_bars or [])
            continue
        by_time = {
            _bar_time(bar): bar
            for bar in derivative_bars
            if _bar_time(bar) is not None
        }
        aligned = []
        missing_count = 0
        for index, bar in enumerate(price_bars or []):
            derivative_bar = None
            timestamp = _bar_time(bar)
            if timestamp is not None:
                derivative_bar = by_time.get(timestamp)
            if derivative_bar is None and index < len(derivative_bars):
                derivative_bar = derivative_bars[index]
            enriched = dict(bar)
            if derivative_bar:
                for field in DERIVATIVE_FIELDS:
                    if derivative_bar.get(field) is not None:
                        enriched[field] = derivative_bar[field]
            else:
                missing_count += 1
            aligned.append(enriched)
        if missing_count:
            partial[coin] = missing_count
        merged[coin] = aligned

    if diagnostics is not None:
        if missing:
            diagnostics["missing_derivatives_data_coins"] = missing
        if partial:
            diagnostics["partial_derivatives_data_bars"] = partial
    return merged


def _increment(diagnostics, key):
    if diagnostics is not None:
        diagnostics[key] = int(diagnostics.get(key) or 0) + 1


def _last_numeric(window, field):
    for bar in reversed(window or []):
        value = _safe_float((bar or {}).get(field))
        if value is not None:
            return value
    return None


def _oi_change_pct(window, lookback):
    if not window:
        return None
    current = _last_numeric(window, "open_interest")
    if current is None:
        return None
    numeric = [_safe_float((bar or {}).get("open_interest")) for bar in window]
    numeric = [value for value in numeric if value is not None]
    if len(numeric) <= max(int(lookback or 1), 1):
        return None
    previous = numeric[-int(lookback or 1) - 1]
    if not previous:
        return None
    return (current / previous - 1.0) * 100.0


def describe_derivatives_context(window, *, oi_lookback=5):
    funding = _last_numeric(window, "funding_rate")
    basis = _last_numeric(window, "basis_pct")
    open_interest = _last_numeric(window, "open_interest")
    return {
        "funding_rate": funding,
        "basis_pct": basis,
        "open_interest": open_interest,
        "oi_change_pct": _oi_change_pct(window, oi_lookback),
        "has_derivatives_data": any(
            _last_numeric(window, field) is not None
            for field in ("funding_rate", "basis_pct", "open_interest")
        ),
    }


def should_block_signal_for_derivatives(signal, window, config, diagnostics=None):
    if not bool(getattr(config, "derivatives_filter_enabled", False)):
        return False
    context = describe_derivatives_context(
        window,
        oi_lookback=getattr(config, "derivatives_oi_lookback", 5),
    )
    direction = getattr(signal, "direction", None)
    if isinstance(signal, dict):
        direction = signal.get("direction")
    direction = str(direction or "").lower()

    if not context["has_derivatives_data"]:
        _increment(diagnostics, "derivatives_missing_context_signals")
        return False

    funding = context.get("funding_rate")
    basis = context.get("basis_pct")
    oi_change = context.get("oi_change_pct")

    if direction == "long":
        if funding is not None and funding > float(getattr(config, "derivatives_funding_upper", 0.0005)):
            _increment(diagnostics, "derivatives_funding_filtered_signals")
            return True
        if basis is not None and basis > float(getattr(config, "derivatives_basis_upper", 1.0)):
            _increment(diagnostics, "derivatives_basis_filtered_signals")
            return True
        if oi_change is not None and oi_change < float(getattr(config, "derivatives_min_oi_change_long", -10.0)):
            _increment(diagnostics, "derivatives_oi_filtered_signals")
            return True
    if direction == "short":
        if funding is not None and funding < float(getattr(config, "derivatives_funding_lower", -0.0005)):
            _increment(diagnostics, "derivatives_funding_filtered_signals")
            return True
        if basis is not None and basis < float(getattr(config, "derivatives_basis_lower", -1.0)):
            _increment(diagnostics, "derivatives_basis_filtered_signals")
            return True
        if oi_change is not None and oi_change > float(getattr(config, "derivatives_max_oi_change_short", 10.0)):
            _increment(diagnostics, "derivatives_oi_filtered_signals")
            return True
    return False


def should_block_signal_for_oi_entry_filter(signal, window, config, diagnostics=None):
    if not bool(getattr(config, "oi_entry_filter_enabled", False)):
        return False
    lookback = int(getattr(config, "oi_entry_filter_lookback", 5) or 5)
    if not window or len(window) <= lookback:
        _increment(diagnostics, "oi_entry_filter_missing_context_signals")
        return True

    current = window[-1]
    previous = window[-lookback - 1]
    current_oi = _safe_float((current or {}).get("open_interest"))
    previous_oi = _safe_float((previous or {}).get("open_interest"))
    current_close = _safe_float((current or {}).get("close"))
    previous_close = _safe_float((previous or {}).get("close"))
    if current_oi is None or previous_oi in (None, 0) or current_close is None or previous_close in (None, 0):
        _increment(diagnostics, "oi_entry_filter_missing_context_signals")
        return True

    oi_change = (current_oi / previous_oi - 1.0) * 100.0
    price_return = (current_close / previous_close - 1.0) * 100.0
    direction = getattr(signal, "direction", None)
    if isinstance(signal, dict):
        direction = signal.get("direction")
    direction = str(direction or "").lower()
    price_direction = "long" if price_return > 0 else "short" if price_return < 0 else None
    min_oi_change = float(getattr(config, "oi_entry_filter_min_change_pct", 0.0) or 0.0)
    min_price_move = float(getattr(config, "oi_entry_filter_min_price_move_pct", 0.1) or 0.0)

    if oi_change < min_oi_change or abs(price_return) < min_price_move or price_direction != direction:
        _increment(diagnostics, "oi_entry_filter_unconfirmed_signals")
        return True

    if bool(getattr(config, "oi_entry_filter_block_late_crowded", True)):
        funding = _safe_float((current or {}).get("funding_rate"))
        funding_extreme = abs(float(getattr(config, "oi_entry_filter_funding_extreme_abs", 0.0005) or 0.0005))
        if oi_change >= 10.0 and funding is not None and abs(funding) >= funding_extreme:
            _increment(diagnostics, "oi_entry_filter_late_crowded_blocks")
            return True

    _increment(diagnostics, "oi_entry_filter_confirmed_signals")
    return False


def build_derivatives_monitor(data_map, *, coins, oi_lookback=5):
    rows = []
    for coin in coins:
        bars = list((data_map or {}).get(coin, []))
        context = describe_derivatives_context(bars, oi_lookback=oi_lookback)
        funding_values = [_safe_float(bar.get("funding_rate")) for bar in bars if isinstance(bar, dict)]
        funding_values = [value for value in funding_values if value is not None]
        basis_values = [_safe_float(bar.get("basis_pct")) for bar in bars if isinstance(bar, dict)]
        basis_values = [value for value in basis_values if value is not None]
        rows.append(
            {
                "coin": coin,
                "bars": len(bars),
                "derivative_bars": sum(
                    1
                    for bar in bars
                    if isinstance(bar, dict)
                    and any(_safe_float(bar.get(field)) is not None for field in DERIVATIVE_FIELDS)
                ),
                "latest_funding_rate": context.get("funding_rate"),
                "avg_funding_rate": round(sum(funding_values) / len(funding_values), 8) if funding_values else None,
                "latest_basis_pct": context.get("basis_pct"),
                "avg_basis_pct": round(sum(basis_values) / len(basis_values), 4) if basis_values else None,
                "latest_open_interest": context.get("open_interest"),
                "oi_change_pct": round(context["oi_change_pct"], 2) if context.get("oi_change_pct") is not None else None,
            }
        )
    return rows
