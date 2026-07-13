from datetime import datetime, timezone


HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def timestamp_ms(bar):
    for key in ("open_time", "ts", "timestamp"):
        value = bar.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    value = bar.get("time") or bar.get("date")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def effective_stop(position):
    stops = effective_stop_candidates(position)
    if not stops:
        return None
    if str(position.get("direction") or "").lower() == "short":
        return min(stops, key=lambda item: item[0])[0]
    return max(stops, key=lambda item: item[0])[0]


def effective_stop_candidates(position):
    return [
        (value, reason)
        for value, reason in (
            (_number(position.get("sl")), "SL"),
            (_number(position.get("atr_trailing_stop")), "ATR_TRAIL"),
        )
        if value is not None
    ]


def resolve_hourly_stop_fill(position, bar, *, mode="strict"):
    candidates = effective_stop_candidates(position)
    if not candidates:
        return None
    if str(position.get("direction") or "").lower() == "short":
        stop, reason = min(candidates, key=lambda item: item[0])
    else:
        stop, reason = max(candidates, key=lambda item: item[0])
    open_price = _number(bar.get("open"))
    high = _number(bar.get("high"))
    low = _number(bar.get("low"))
    if stop is None or open_price is None or high is None or low is None:
        return None
    if str(position.get("direction") or "").lower() == "short":
        if open_price >= stop:
            return {"price": open_price, "reason": reason, "fill_type": "gap"}
        if mode == "close_confirmed":
            close = _number(bar.get("close"))
            if close is not None and close >= stop:
                return {"price": close, "reason": reason, "fill_type": "confirmed"}
            return None
        if high >= stop:
            return {"price": stop, "reason": reason, "fill_type": "stop"}
        return None
    if open_price <= stop:
        return {"price": open_price, "reason": reason, "fill_type": "gap"}
    if mode == "close_confirmed":
        close = _number(bar.get("close"))
        if close is not None and close <= stop:
            return {"price": close, "reason": reason, "fill_type": "confirmed"}
        return None
    if low <= stop:
        return {"price": stop, "reason": reason, "fill_type": "stop"}
    return None


def normalize_hourly_data(data_map):
    normalized = {}
    for coin, bars in (data_map or {}).items():
        usable = []
        seen = set()
        for bar in bars if isinstance(bars, list) else []:
            open_time = timestamp_ms(bar)
            if open_time is None or open_time in seen:
                continue
            seen.add(open_time)
            item = dict(bar)
            item["open_time"] = open_time
            usable.append(item)
        normalized[str(coin).upper()] = sorted(usable, key=lambda item: item["open_time"])
    return normalized


def is_replayable_hourly_bar(bar):
    open_time = timestamp_ms(bar)
    if open_time is None or open_time % HOUR_MS:
        return False
    return all(_number(bar.get(key)) is not None for key in ("open", "high", "low", "close"))
