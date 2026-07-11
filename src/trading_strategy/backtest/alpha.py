import random
from statistics import median

from trading_strategy.indicators import atr, ema

from .data import get_coin_series
from .derivatives import merge_derivatives_into_price_data


DEFAULT_ALPHA_SET = (
    "btc_regime_trend",
    "funding_extreme_reversion",
    "oi_expansion_confirmation",
)
DEFAULT_FORWARD_BARS = (1, 3, 6, 12, 24, 72)
DEFAULT_RANDOM_SEED = 42


def parse_csv_tuple(raw_value, cast=str):
    values = []
    for item in str(raw_value or "").split(","):
        item = item.strip()
        if item:
            values.append(cast(item))
    return tuple(values)


def _safe_float(value):
    try:
        if value is None:
            return None
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted


def _close(bar):
    return _safe_float((bar or {}).get("close"))


def _high(bar):
    return _safe_float((bar or {}).get("high")) or _close(bar)


def _low(bar):
    return _safe_float((bar or {}).get("low")) or _close(bar)


def _field(bar, name):
    return _safe_float((bar or {}).get(name))


def _pct_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def _mean(values):
    values = [float(value) for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _std(values):
    values = [float(value) for value in values if value is not None]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance**0.5


def _percentile_rank(window, value):
    values = sorted(float(item) for item in window if item is not None)
    if not values or value is None:
        return None
    below_or_equal = sum(1 for item in values if item <= value)
    return below_or_equal / len(values)


def _is_high_atr(atr_pcts, index, lookback=60):
    value = atr_pcts[index] if index < len(atr_pcts) else None
    average = _mean(atr_pcts[max(0, index - lookback) : index])
    if value is None or average is None:
        return False
    return value >= average


def _bucket_events(events, bucket_count):
    valid = [event for event in events if event.get("feature_value") is not None]
    valid.sort(key=lambda event: event["feature_value"])
    total = len(valid)
    if not total:
        return {}
    buckets = {}
    for rank, event in enumerate(valid):
        bucket = min(int(rank * bucket_count / total), bucket_count - 1) + 1
        buckets.setdefault(bucket, []).append(event)
    return buckets


def _forward_signed_return(series, index, forward_bars, direction):
    current = _close(series[index])
    future_index = index + int(forward_bars)
    if current in (None, 0) or future_index >= len(series):
        return None
    future = _close(series[future_index])
    raw_return = _pct_change(future, current)
    if raw_return is None:
        return None
    sign = 1.0 if direction == "long" else -1.0
    return raw_return * sign


def _build_btc_regime_events(coin, series, btc_series, max_forward):
    if not btc_series:
        return [], {"missing_btc_data": 1}
    count = min(len(series), len(btc_series))
    if count <= 80 + max_forward:
        return [], {"insufficient_bars": 1}

    coin_closes = [_close(bar) for bar in series[:count]]
    btc_closes = [_close(bar) for bar in btc_series[:count]]
    highs = [_high(bar) for bar in series[:count]]
    lows = [_low(bar) for bar in series[:count]]
    coin_atr = atr(highs, lows, coin_closes, 14)
    btc_ema20 = ema(btc_closes, 20)
    btc_ema50 = ema(btc_closes, 50)
    atr_pcts = [
        (value / close * 100.0) if value is not None and close not in (None, 0) else None
        for value, close in zip(coin_atr, coin_closes)
    ]

    events = []
    for index in range(60, count - max_forward):
        btc_close = btc_closes[index]
        coin_close = coin_closes[index]
        if btc_close in (None, 0) or coin_close in (None, 0):
            continue
        btc_return20 = _pct_change(btc_close, btc_closes[index - 20])
        coin_return20 = _pct_change(coin_close, coin_closes[index - 20])
        ema20 = btc_ema20[index]
        ema50 = btc_ema50[index]
        if btc_return20 is None or coin_return20 is None or ema20 is None or ema50 in (None, 0):
            continue
        btc_score = btc_return20 + (ema20 / ema50 - 1.0) * 100.0
        if btc_score > 1.0:
            direction = "long"
            regime = "btc_up_high_atr" if _is_high_atr(atr_pcts, index) else "btc_up_low_atr"
        elif btc_score < -1.0:
            direction = "short"
            regime = "btc_down_high_atr" if _is_high_atr(atr_pcts, index) else "btc_down_low_atr"
        else:
            continue
        feature_value = abs(btc_score) + max(coin_return20 * (1 if direction == "long" else -1), 0)
        events.append(
            {
                "alpha": "btc_regime_trend",
                "coin": coin,
                "index": index,
                "direction": direction,
                "feature_value": feature_value,
                "regime": regime,
            }
        )
    return events, {}


def _build_funding_events(coin, series, max_forward):
    if len(series) <= 40 + max_forward:
        return [], {"insufficient_bars": 1}
    events = []
    missing = 0
    closes = [_close(bar) for bar in series]
    for index in range(30, len(series) - max_forward):
        funding = _field(series[index], "funding_rate")
        if funding is None:
            missing += 1
            continue
        funding_window = [_field(bar, "funding_rate") for bar in series[index - 30 : index]]
        funding_mean = _mean(funding_window)
        funding_std = _std(funding_window)
        if funding_mean is None or not funding_std:
            continue
        z_score = (funding - funding_mean) / funding_std
        if abs(z_score) < 0.5:
            continue
        direction = "short" if z_score > 0 else "long"
        price_return10 = _pct_change(closes[index], closes[index - 10])
        trend_label = "trend_continuation" if (
            price_return10 is not None
            and ((price_return10 > 0 and direction == "short") or (price_return10 < 0 and direction == "long"))
        ) else "sideways_or_stalled"
        regime = ("positive_funding_" if funding >= 0 else "negative_funding_") + trend_label
        events.append(
            {
                "alpha": "funding_extreme_reversion",
                "coin": coin,
                "index": index,
                "direction": direction,
                "feature_value": abs(z_score),
                "regime": regime,
            }
        )
    diagnostics = {}
    if missing:
        diagnostics["missing_funding_bars"] = missing
    return events, diagnostics


def _build_oi_events(coin, series, max_forward):
    if len(series) <= 20 + max_forward:
        return [], {"insufficient_bars": 1}
    events = []
    missing = 0
    closes = [_close(bar) for bar in series]
    for index in range(10, len(series) - max_forward):
        current_oi = _field(series[index], "open_interest")
        previous_oi = _field(series[index - 5], "open_interest")
        if current_oi is None or previous_oi in (None, 0):
            missing += 1
            continue
        oi_change = _pct_change(current_oi, previous_oi)
        price_return5 = _pct_change(closes[index], closes[index - 5])
        if oi_change is None or oi_change <= 0 or price_return5 is None or abs(price_return5) < 0.1:
            continue
        direction = "long" if price_return5 > 0 else "short"
        funding = _field(series[index], "funding_rate")
        funding_label = "high_funding" if funding is not None and abs(funding) >= 0.0005 else "low_funding"
        phase = "early_trend" if abs(oi_change) < 10.0 else "late_crowded_trend"
        events.append(
            {
                "alpha": "oi_expansion_confirmation",
                "coin": coin,
                "index": index,
                "direction": direction,
                "feature_value": max(oi_change, 0.0),
                "regime": f"{phase}_{funding_label}",
            }
        )
    diagnostics = {}
    if missing:
        diagnostics["missing_open_interest_bars"] = missing
    return events, diagnostics


def _summarize_returns(values):
    values = [value for value in values if value is not None]
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "hit_rate": None,
            "downside_tail": None,
        }
    sorted_values = sorted(values)
    tail_index = max(int(len(sorted_values) * 0.05), 0)
    return {
        "count": len(values),
        "mean": round(sum(values) / len(values), 4),
        "median": round(median(values), 4),
        "hit_rate": round(sum(1 for value in values if value > 0) / len(values) * 100.0, 2),
        "downside_tail": round(sorted_values[tail_index], 4),
    }


def _random_baseline(events, series_by_coin, forward_bars, cost_pct, runs, seed):
    if not events or runs <= 0:
        return {"runs": 0, "mean": None}
    rng = random.Random(seed)
    samples = []
    for _ in range(runs):
        returns = []
        for event in events:
            series = series_by_coin.get(event["coin"], [])
            upper = len(series) - int(forward_bars) - 1
            if upper <= 1:
                continue
            random_index = rng.randint(0, upper)
            random_direction = "long" if rng.random() >= 0.5 else "short"
            value = _forward_signed_return(series, random_index, forward_bars, random_direction)
            if value is not None:
                returns.append(value - cost_pct)
        if returns:
            samples.append(sum(returns) / len(returns))
    return {
        "runs": len(samples),
        "mean": round(sum(samples) / len(samples), 4) if samples else None,
    }


def _summarize_alpha(alpha_name, events, series_by_coin, forward_bars, bucket_count, cost_pct, random_runs, seed):
    rows = []
    for bars in forward_bars:
        event_returns = []
        for event in events:
            value = _forward_signed_return(series_by_coin.get(event["coin"], []), event["index"], bars, event["direction"])
            if value is not None:
                enriched = dict(event)
                enriched["forward_return"] = value
                enriched["net_forward_return"] = value - cost_pct
                event_returns.append(enriched)
        gross = _summarize_returns([event["forward_return"] for event in event_returns])
        net = _summarize_returns([event["net_forward_return"] for event in event_returns])
        baseline = _random_baseline(event_returns, series_by_coin, bars, cost_pct, random_runs, seed + int(bars))
        bucket_rows = []
        for bucket, bucket_events in sorted(_bucket_events(event_returns, bucket_count).items()):
            summary = _summarize_returns([event["net_forward_return"] for event in bucket_events])
            feature_values = [event["feature_value"] for event in bucket_events]
            bucket_rows.append(
                {
                    "bucket": bucket,
                    "feature_min": round(min(feature_values), 4),
                    "feature_max": round(max(feature_values), 4),
                    **summary,
                }
            )
        regime_rows = []
        regimes = sorted({event["regime"] for event in event_returns})
        for regime in regimes:
            regime_events = [event for event in event_returns if event["regime"] == regime]
            regime_rows.append({"regime": regime, **_summarize_returns([event["net_forward_return"] for event in regime_events])})
        rows.append(
            {
                "forward_bars": bars,
                "events": len(event_returns),
                "gross": gross,
                "net": net,
                "random_baseline": baseline,
                "random_delta": round(net["mean"] - baseline["mean"], 4)
                if net["mean"] is not None and baseline["mean"] is not None
                else None,
                "buckets": bucket_rows,
                "regimes": regime_rows,
            }
        )
    return {"name": alpha_name, "events": len(events), "forward": rows}


def run_alpha_report(
    data_map,
    *,
    derivatives_data_map=None,
    coins,
    max_days=None,
    alpha_set=DEFAULT_ALPHA_SET,
    forward_bars=DEFAULT_FORWARD_BARS,
    bucket_count=10,
    random_baseline_runs=200,
    fee_bps=0.0,
    slippage_bps=0.0,
    random_seed=DEFAULT_RANDOM_SEED,
):
    alpha_set = tuple(alpha_set or DEFAULT_ALPHA_SET)
    forward_bars = tuple(int(value) for value in (forward_bars or DEFAULT_FORWARD_BARS) if int(value) > 0)
    max_forward = max(forward_bars or DEFAULT_FORWARD_BARS)
    coins = tuple(str(coin).strip().upper() for coin in coins if str(coin).strip())
    merge_diagnostics = {}
    merged = merge_derivatives_into_price_data(data_map or {}, derivatives_data_map or {}, merge_diagnostics)
    series_by_coin = {coin: get_coin_series(merged, coin, max_days=max_days) for coin in coins}
    if "BTC" in (merged or {}):
        series_by_coin["BTC"] = get_coin_series(merged, "BTC", max_days=max_days)
    btc_series = series_by_coin.get("BTC", [])
    cost_pct = (float(fee_bps or 0.0) + float(slippage_bps or 0.0)) / 100.0

    diagnostics = dict(merge_diagnostics)
    alpha_events = {name: [] for name in alpha_set}
    for coin in coins:
        series = series_by_coin.get(coin, [])
        if not series:
            diagnostics.setdefault("missing_price_data_coins", []).append(coin)
            continue
        if "btc_regime_trend" in alpha_events:
            events, diag = _build_btc_regime_events(coin, series, btc_series, max_forward)
            alpha_events["btc_regime_trend"].extend(events)
            for key, value in diag.items():
                diagnostics[f"btc_regime_trend_{coin}_{key}"] = value
        if "funding_extreme_reversion" in alpha_events:
            events, diag = _build_funding_events(coin, series, max_forward)
            alpha_events["funding_extreme_reversion"].extend(events)
            for key, value in diag.items():
                diagnostics[f"funding_extreme_reversion_{coin}_{key}"] = value
        if "oi_expansion_confirmation" in alpha_events:
            events, diag = _build_oi_events(coin, series, max_forward)
            alpha_events["oi_expansion_confirmation"].extend(events)
            for key, value in diag.items():
                diagnostics[f"oi_expansion_confirmation_{coin}_{key}"] = value

    reports = [
        _summarize_alpha(
            name,
            alpha_events.get(name, []),
            series_by_coin,
            forward_bars,
            int(bucket_count or 10),
            cost_pct,
            int(random_baseline_runs or 0),
            int(random_seed),
        )
        for name in alpha_set
    ]
    return {
        "alpha_set": alpha_set,
        "coins": coins,
        "forward_bars": forward_bars,
        "bucket_count": int(bucket_count or 10),
        "random_baseline_runs": int(random_baseline_runs or 0),
        "cost_pct": round(cost_pct, 6),
        "diagnostics": diagnostics,
        "alphas": reports,
    }


def format_alpha_report_lines(report):
    lines = ["Alpha signal report"]
    lines.append(
        "coins={coins}, forward_bars={forward_bars}, bucket_count={bucket_count}, "
        "random_baseline_runs={random_baseline_runs}, cost_pct={cost_pct:.4f}".format(
            coins=",".join(report.get("coins") or ()),
            forward_bars=",".join(str(item) for item in report.get("forward_bars") or ()),
            bucket_count=report.get("bucket_count"),
            random_baseline_runs=report.get("random_baseline_runs"),
            cost_pct=float(report.get("cost_pct") or 0.0),
        )
    )
    diagnostics = report.get("diagnostics") or {}
    if diagnostics:
        lines.append(f"diagnostics={diagnostics}")
    for alpha in report.get("alphas") or []:
        lines.append(f"[{alpha['name']}] events={alpha['events']}")
        for row in alpha.get("forward") or []:
            net = row["net"]
            baseline = row["random_baseline"]
            lines.append(
                "forward={forward_bars}: events={events}, net_mean={net_mean}, net_median={net_median}, "
                "hit_rate={hit_rate}, downside_tail={downside_tail}, random_mean={random_mean}, "
                "random_delta={random_delta}".format(
                    forward_bars=row["forward_bars"],
                    events=row["events"],
                    net_mean=net["mean"],
                    net_median=net["median"],
                    hit_rate=net["hit_rate"],
                    downside_tail=net["downside_tail"],
                    random_mean=baseline["mean"],
                    random_delta=row["random_delta"],
                )
            )
            bucket_preview = row.get("buckets") or []
            if bucket_preview:
                rendered = []
                for bucket in bucket_preview[: min(len(bucket_preview), 5)]:
                    rendered.append(
                        "b{bucket}:n={count},mean={mean},hit={hit_rate},feature={feature_min}..{feature_max}".format(
                            **bucket
                        )
                    )
                lines.append("buckets " + "; ".join(rendered))
            regime_preview = row.get("regimes") or []
            if regime_preview:
                rendered = []
                for regime in regime_preview[: min(len(regime_preview), 5)]:
                    rendered.append(
                        "{regime}:n={count},mean={mean},hit={hit_rate}".format(
                            **regime
                        )
                    )
                lines.append("regimes " + "; ".join(rendered))
    return lines
