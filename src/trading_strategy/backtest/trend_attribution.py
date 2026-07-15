"""Causal, research-only attribution for raw daily Trend candidates."""

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from trading_strategy.market_context import MarketContextDetector
from trading_strategy.strategies.trend import (
    evaluate_trend_entry_eligibility,
    generate_raw_trend_candidate,
)


DEFAULT_HORIZONS = (1, 3, 5, 10)
ROUND_TRIP_COST_BPS = 13.0
MIN_GROUP_SAMPLE = 10


@dataclass(frozen=True)
class TrendSignalObservation:
    coin: str
    timestamp: Any
    bar_index: int
    direction: str
    score: float
    baseline_allowed: bool
    blocked_reasons: tuple[str, ...]
    btc_direction: str
    market_context_regime: str
    features: dict[str, Any]
    forward_net_returns: dict[int, float | None]

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TrendAttributionReport:
    observations: tuple[TrendSignalObservation, ...]
    summary: dict[str, Any]
    coin_concentration: dict[str, Any]
    feature_buckets: dict[str, Any]
    walk_forward: dict[str, Any]

    def to_dict(self):
        return {
            "observations": [observation.to_dict() for observation in self.observations],
            "summary": self.summary,
            "coin_concentration": self.coin_concentration,
            "feature_buckets": self.feature_buckets,
            "walk_forward": self.walk_forward,
        }


def _value(config, key, default):
    return getattr(config, key, default)


def _timestamp(bar, fallback):
    return bar.get("open_time", bar.get("time", bar.get("timestamp", fallback)))


def _net_return(entry, future, direction, cost_bps):
    if not entry:
        return None
    signed = ((future / entry) - 1.0) * 100.0
    if direction == "short":
        signed *= -1.0
    return signed - (float(cost_bps) / 100.0)


def _bucket(feature, value):
    if feature in ("market_context_regime", "btc_direction"):
        return str(value or "unknown")
    if value is None:
        return "missing"
    value = float(value)
    boundaries = {
        "adx": (20.0, 25.0, 35.0),
        "atr_pct": (2.0, 5.0, 8.0),
        "rsi": (40.0, 50.0, 60.0, 70.0),
        "ema_slope": (-0.1, 0.1),
        "price_position": (0.25, 0.5, 0.75),
        "roc60": (0.0, 30.0, 60.0),
        "volume_ratio": (0.75, 1.25, 1.5),
    }[feature]
    for threshold in boundaries:
        if value < threshold:
            return f"<{threshold:g}"
    return f">={boundaries[-1]:g}"


def _metrics(observations, horizon, *, min_sample=MIN_GROUP_SAMPLE):
    values = [observation.forward_net_returns.get(horizon) for observation in observations]
    values = [value for value in values if value is not None]
    count = len(values)
    return {
        "observations": count,
        "win_rate": round(sum(value > 0 for value in values) / count, 6) if count else None,
        "average_net_return_pct": round(mean(values), 6) if count else None,
        "insufficient_sample": count < min_sample,
    }


def _group(observations, key, horizon):
    groups = {}
    for observation in observations:
        if key == "direction":
            label = observation.direction
        elif key == "baseline_entry":
            label = "allowed" if observation.baseline_allowed else "blocked"
        elif key == "coin":
            label = observation.coin
        else:
            value = observation.market_context_regime if key == "market_context_regime" else observation.btc_direction if key == "btc_direction" else observation.features.get(key)
            label = _bucket(key, value)
        groups.setdefault(label, []).append(observation)
    return {label: _metrics(items, horizon) for label, items in sorted(groups.items())}


def _concentration(observations, horizon):
    contributions = {}
    for observation in observations:
        value = observation.forward_net_returns.get(horizon)
        if value is not None:
            contributions[observation.coin] = contributions.get(observation.coin, 0.0) + value
    ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
    total_absolute = sum(abs(value) for value in contributions.values())
    top = [{"coin": coin, "net_return_sum_pct": round(value, 6)} for coin, value in ranked[:3]]
    return {
        "horizon_bars": horizon,
        "top_3": top,
        "top_3_absolute_concentration": round(sum(abs(row["net_return_sum_pct"]) for row in top) / total_absolute, 6) if total_absolute else None,
    }


def _walk_forward(observations, *, bars, warmup, train_bars, test_bars, horizon, min_sample):
    folds = []
    start = warmup
    while start + train_bars + test_bars <= bars and len(folds) < 3:
        train_end = start + train_bars
        test_end = train_end + test_bars
        train = [item for item in observations if start <= item.bar_index < train_end]
        test = [item for item in observations if train_end <= item.bar_index < test_end]
        folds.append({
            "train": {"start": start, "end": train_end, "feature_buckets": {feature: _group(train, feature, horizon) for feature in _FEATURES}},
            "test": {"start": train_end, "end": test_end, "feature_buckets": {feature: _group(test, feature, horizon) for feature in _FEATURES}},
        })
        start += test_bars
    hypotheses = []
    for feature in _FEATURES:
        labels = {label for fold in folds for label in fold["test"]["feature_buckets"][feature]}
        for label in sorted(labels):
            tests = [fold["test"]["feature_buckets"][feature].get(label, {}) for fold in folds]
            if tests and all(not row.get("insufficient_sample", True) and (row.get("average_net_return_pct") or 0.0) >= 0.0 for row in tests):
                hypotheses.append({"feature": feature, "bucket": label, "status": "research_hypothesis"})
    return {"warmup_bars": warmup, "train_bars": train_bars, "test_bars": test_bars, "folds": folds, "research_hypotheses": hypotheses}


_FEATURES = ("adx", "atr_pct", "rsi", "ema_slope", "price_position", "roc60", "volume_ratio", "btc_direction", "market_context_regime")


def run_trend_entry_attribution_report(
    data_map,
    *,
    config,
    max_bars=240,
    horizons=DEFAULT_HORIZONS,
    round_trip_cost_bps=ROUND_TRIP_COST_BPS,
    warmup_bars=60,
    train_bars=90,
    test_bars=30,
    min_group_sample=MIN_GROUP_SAMPLE,
):
    """Report raw Trend candidates using completed bars only; never modifies a strategy."""
    coins = tuple(coin for coin in config.coins if coin in data_map)
    series = {coin: list(data_map[coin])[-max_bars:] for coin in coins}
    btc_series = series.get("BTC", list(data_map.get("BTC", []))[-max_bars:])
    detector = MarketContextDetector(config)
    observations = []
    for coin, bars in series.items():
        for index in range(warmup_bars, len(bars)):
            window = bars[: index + 1]
            btc_window = btc_series[: min(index + 1, len(btc_series))]
            context = detector.observe(coin, window, btc_window)
            candidate = generate_raw_trend_candidate(
                window,
                min_score=_value(config, "strategy_parameters", {}).get("min_score", _value(config, "min_score", 4)) if isinstance(_value(config, "strategy_parameters", {}), dict) else _value(config, "min_score", 4),
                tp_mult=_value(config, "strategy_parameters", {}).get("tp_mult", 1.5) if isinstance(_value(config, "strategy_parameters", {}), dict) else 1.5,
                sl_mult=_value(config, "strategy_parameters", {}).get("sl_mult", 1.0) if isinstance(_value(config, "strategy_parameters", {}), dict) else 1.0,
                price_position_lookback=_value(config, "trend_price_position_lookback", 60),
            )
            if candidate is None:
                continue
            eligibility = evaluate_trend_entry_eligibility(
                candidate["direction"], candidate,
                rsi_min_long=_value(config, "trend_rsi_min_long", 45.0), rsi_max_long=_value(config, "trend_rsi_max_long", 75.0),
                rsi_min_short=_value(config, "trend_rsi_min_short", 30.0), rsi_max_short=_value(config, "trend_rsi_max_short", 55.0),
                max_atr_pct=_value(config, "trend_max_atr_pct", 8.0),
                long_max_price_position=_value(config, "trend_long_max_price_position", 0.85), short_min_price_position=_value(config, "trend_short_min_price_position", 0.25),
                max_roc_60_long=_value(config, "trend_max_roc_60_long", 120.0), min_roc_60_short=_value(config, "trend_min_roc_60_short", -120.0),
            )
            features = {"adx": candidate["adx"], "atr_pct": candidate["atr_pct"], "rsi": candidate["rsi"], "ema_slope": candidate["ema_slope"], "price_position": candidate["price_position_60"], "roc60": candidate["roc60"], "volume_ratio": candidate["volume_ratio"]}
            outcomes = {horizon: _net_return(window[-1]["close"], bars[index + horizon]["close"], candidate["direction"], round_trip_cost_bps) if index + horizon < len(bars) else None for horizon in horizons}
            observations.append(TrendSignalObservation(coin, _timestamp(window[-1], index), index, candidate["direction"], candidate["score"], eligibility["allowed"], eligibility["reasons"], str(context.features.get("btc_direction", "unavailable")), context.regime.value, features, outcomes))
    primary = max(horizons)
    summary = {"raw_candidates": len(observations), "baseline_allowed": sum(item.baseline_allowed for item in observations), "baseline_blocked": sum(not item.baseline_allowed for item in observations), "round_trip_cost_bps": round_trip_cost_bps, "forward": {horizon: _metrics(observations, horizon, min_sample=min_group_sample) for horizon in horizons}, "by_direction": _group(observations, "direction", primary), "by_baseline_entry": _group(observations, "baseline_entry", primary), "by_coin": _group(observations, "coin", primary)}
    return TrendAttributionReport(tuple(observations), summary, _concentration(observations, primary), {feature: _group(observations, feature, primary) for feature in _FEATURES}, _walk_forward(observations, bars=max((len(values) for values in series.values()), default=0), warmup=warmup_bars, train_bars=train_bars, test_bars=test_bars, horizon=primary, min_sample=min_group_sample))


def format_trend_entry_attribution_lines(report):
    """Render the evidence report without implying a trading recommendation."""
    lines = ["Trend entry attribution (research only)"]
    summary = report.summary
    lines.append("raw={raw_candidates} allowed={baseline_allowed} blocked={baseline_blocked} cost={round_trip_cost_bps}bps".format(**summary))
    for horizon, metrics in summary["forward"].items():
        lines.append(f"forward={horizon}d n={metrics['observations']} mean_net_pct={metrics['average_net_return_pct']} win_rate={metrics['win_rate']} insufficient_sample={metrics['insufficient_sample']}")
    lines.append(f"top3_abs_concentration={report.coin_concentration['top_3_absolute_concentration']} top3={report.coin_concentration['top_3']}")
    lines.append(f"walk_forward_folds={len(report.walk_forward['folds'])} research_hypotheses={report.walk_forward['research_hypotheses']}")
    return lines
