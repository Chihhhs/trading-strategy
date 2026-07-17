"""Research-only BTC-regime attribution helpers for frozen trend experiments."""

from collections import defaultdict
from datetime import datetime, timezone


REGIMES = ("bull", "bear", "neutral")
DIRECTIONS = ("long", "short")


def timestamp_ms(value):
    """Normalize an ISO timestamp or epoch value without consulting wall-clock time."""
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def btc_regime_at(btc_bars, entry_time, *, lookback_days=7, threshold_pct=3.0):
    """Classify using only completed BTC daily bars at or before an entry timestamp."""
    entry_ms = timestamp_ms(entry_time)
    if entry_ms is None:
        return "neutral"
    completed = [bar for bar in btc_bars if timestamp_ms(bar.get("time", bar.get("open_time"))) <= entry_ms]
    if len(completed) < lookback_days:
        return "neutral"
    change_pct = (float(completed[-1]["close"]) / float(completed[-lookback_days]["close"]) - 1.0) * 100.0
    if change_pct > threshold_pct:
        return "bull"
    if change_pct < -threshold_pct:
        return "bear"
    return "neutral"


def _group_key(regime, direction):
    return f"{regime}:{direction}"


def _empty_bucket():
    return {
        "trades": 0,
        "net_pnl": 0.0,
        "gross_pnl": 0.0,
        "cost": 0.0,
        "win_rate": 0.0,
        "average_hold_bars": 0.0,
        "exit_reason_counts": {},
        "max_drawdown_cash": 0.0,
        "coin_concentration": {"top_1": None, "top_3": [], "top_1_absolute_share": None, "top_3_absolute_share": None, "largest_trade_absolute_share": None, "leave_one_coin_out": []},
        "insufficient_sample": True,
    }


def _concentration(trades):
    contributions = defaultdict(float)
    for trade in trades:
        contributions[str(trade.get("coin"))] += float(trade.get("pnl") or 0.0)
    ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
    absolute_total = sum(abs(value) for value in contributions.values())
    trade_absolute_total = sum(abs(float(trade.get("pnl") or 0.0)) for trade in trades)
    top = [{"coin": coin, "net_pnl": round(value, 6)} for coin, value in ranked[:3]]
    top_one = top[0] if top else None
    return {
        "top_1": top_one,
        "top_3": top,
        "top_1_absolute_share": round(abs(top_one["net_pnl"]) / absolute_total, 6) if top_one and absolute_total else None,
        "top_3_absolute_share": round(sum(abs(row["net_pnl"]) for row in top) / absolute_total, 6) if absolute_total else None,
        "largest_trade_absolute_share": round(max((abs(float(trade.get("pnl") or 0.0)) for trade in trades), default=0.0) / trade_absolute_total, 6) if trade_absolute_total else None,
        "leave_one_coin_out": [
            {"excluded_coin": coin, "net_pnl_without_coin": round(sum(contributions.values()) - value, 6)}
            for coin, value in ranked
        ],
    }


def _portfolio_bucket(trades, min_trades):
    if not trades:
        return _empty_bucket()
    ordered = sorted(trades, key=lambda item: timestamp_ms(item.get("exit_time")) or 0)
    cumulative = peak = 0.0
    max_drawdown = 0.0
    reasons = defaultdict(int)
    for trade in ordered:
        cumulative += float(trade.get("pnl") or 0.0)
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
        reasons[str(trade.get("exit_reason") or "unknown")] += 1
    wins = sum(float(trade.get("pnl") or 0.0) > 0.0 for trade in trades)
    return {
        "trades": len(trades),
        "net_pnl": round(sum(float(trade.get("pnl") or 0.0) for trade in trades), 6),
        "gross_pnl": round(sum(float(trade.get("gross_pnl") or 0.0) for trade in trades), 6),
        "cost": round(sum(float(trade.get("cost") or 0.0) for trade in trades), 6),
        "win_rate": round(wins / len(trades) * 100.0, 4),
        "average_hold_bars": round(sum(float(trade.get("hold_bars") or 0.0) for trade in trades) / len(trades), 4),
        "exit_reason_counts": dict(sorted(reasons.items())),
        "max_drawdown_cash": round(max_drawdown, 6),
        "coin_concentration": _concentration(trades),
        "insufficient_sample": len(trades) < min_trades,
    }


def portfolio_attribution(trades, btc_bars, *, min_trades=10):
    """Summarize executed trades by causal BTC regime and direction."""
    grouped = defaultdict(list)
    annotated = []
    for source in trades:
        trade = dict(source)
        regime = btc_regime_at(btc_bars, trade.get("entry_time"))
        direction = str(trade.get("direction") or "unknown")
        trade["btc_regime_at_entry"] = regime
        annotated.append(trade)
        if regime in REGIMES and direction in DIRECTIONS:
            grouped[_group_key(regime, direction)].append(trade)
    return {
        "trades": annotated,
        "buckets": {
            _group_key(regime, direction): _portfolio_bucket(grouped[_group_key(regime, direction)], min_trades)
            for regime in REGIMES for direction in DIRECTIONS
        },
        "total": _portfolio_bucket(annotated, min_trades),
    }


def signal_attribution(baseline_observations, candidate_observations, *, min_sample=10, horizon=10):
    """Compare raw pre-capacity candidates; observations are produced causally by trend attribution."""
    candidate_by_key = {(item.coin, item.timestamp, item.direction): item for item in candidate_observations}
    grouped = defaultdict(list)
    for baseline in baseline_observations:
        candidate = candidate_by_key.get((baseline.coin, baseline.timestamp, baseline.direction))
        if candidate is None:
            continue
        regime = str(baseline.btc_direction)
        if regime not in REGIMES or baseline.direction not in DIRECTIONS:
            continue
        grouped[_group_key(regime, baseline.direction)].append((baseline, candidate))
    buckets = {}
    for regime in REGIMES:
        for direction in DIRECTIONS:
            pairs = grouped[_group_key(regime, direction)]
            baseline_allowed = [pair[0] for pair in pairs if pair[0].baseline_allowed]
            candidate_allowed = [pair[1] for pair in pairs if pair[1].baseline_allowed]
            retained = [pair[1] for pair in pairs if pair[0].baseline_allowed and pair[1].baseline_allowed]
            removed = [pair[0] for pair in pairs if pair[0].baseline_allowed and not pair[1].baseline_allowed]
            def mean(items):
                values = [item.forward_net_returns.get(horizon) for item in items if item.forward_net_returns.get(horizon) is not None]
                return round(sum(values) / len(values), 6) if values else None
            buckets[_group_key(regime, direction)] = {
                "raw_opportunities": len(pairs),
                "baseline_allowed": len(baseline_allowed),
                "candidate_allowed": len(candidate_allowed),
                "retained_by_candidate": len(retained),
                "removed_by_candidate": len(removed),
                "baseline_forward_net_return_pct": mean(baseline_allowed),
                "candidate_forward_net_return_pct": mean(candidate_allowed),
                "retained_forward_net_return_pct": mean(retained),
                "removed_forward_net_return_pct": mean(removed),
                "insufficient_sample": len(pairs) < min_sample,
            }
    return {"forward_horizon_bars": horizon, "buckets": buckets}


def compare_buckets(baseline, candidate):
    """Return candidate-minus-baseline metrics for identically named portfolio buckets."""
    result = {}
    for key, candidate_row in candidate["buckets"].items():
        baseline_row = baseline["buckets"][key]
        result[key] = {
            "net_pnl_delta": round(candidate_row["net_pnl"] - baseline_row["net_pnl"], 6),
            "gross_pnl_delta": round(candidate_row["gross_pnl"] - baseline_row["gross_pnl"], 6),
            "cost_delta": round(candidate_row["cost"] - baseline_row["cost"], 6),
            "trades_delta": candidate_row["trades"] - baseline_row["trades"],
            "max_drawdown_cash_delta": round(candidate_row["max_drawdown_cash"] - baseline_row["max_drawdown_cash"], 6),
        }
    return result


def research_verdict(candidate_portfolio):
    """Evidence label only; deliberately never returns a promotion decision."""
    buckets = candidate_portfolio["buckets"]
    if any(row["insufficient_sample"] for row in buckets.values()):
        return "insufficient_sample"
    total = candidate_portfolio["total"]["net_pnl"]
    bear_short = buckets["bear:short"]
    concentration = candidate_portfolio["total"]["coin_concentration"]
    top_share = concentration["top_1_absolute_share"] or 0.0
    non_bear_trades = sum(row["trades"] for key, row in buckets.items() if not key.startswith("bear:"))
    if total > 0.0 and bear_short["net_pnl"] >= total * 0.7 and (non_bear_trades < 10 or top_share >= 0.5):
        return "bear_beta_dominated"
    return "rsi_selection_effect_visible"
