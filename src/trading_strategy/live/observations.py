"""Paper-only signal observation lifecycle for entry-context research."""

from trading_strategy.strategies.base import signal_value


_PENDING_KEY = "_signal_observations_pending"
_STATS_KEY = "_signal_observation_stats"


def _stats(state):
    return state.setdefault(
        _STATS_KEY,
        {"signals_observed": 0, "outcomes_observed": 0},
    )


def _bar_time(bar):
    return (bar or {}).get("time")


def _bar_close(bar):
    try:
        return float((bar or {}).get("close"))
    except (TypeError, ValueError):
        return None


def record_signal_observation(
    state,
    *,
    coin,
    signal,
    window,
    derivatives_context=None,
    microstructure_context=None,
    horizons=(1, 3, 6),
):
    """Persist one signal context, deduplicated by its completed candle."""
    if not window:
        return None
    entry_bar = window[-1]
    entry_bar_time = _bar_time(entry_bar)
    entry_close = _bar_close(entry_bar)
    direction = signal_value(signal, "direction")
    if entry_bar_time is None or entry_close in (None, 0) or direction not in ("long", "short"):
        return None

    pending = state.setdefault(_PENDING_KEY, [])
    observation_id = f"{coin}:{entry_bar_time}:{direction}"
    if any(item.get("observation_id") == observation_id for item in pending):
        return None

    derivatives_context = derivatives_context or {}
    microstructure_context = microstructure_context or {}
    normalized_horizons = sorted({int(value) for value in horizons if int(value) > 0})
    if not normalized_horizons:
        return None
    observation = {
        "observation_id": observation_id,
        "coin": coin,
        "direction": direction,
        "signal_score": signal_value(signal, "score"),
        "signal_reason": signal_value(signal, "reason"),
        "entry_bar_time": entry_bar_time,
        "entry_close": entry_close,
        "funding_rate": derivatives_context.get("funding_rate"),
        "basis_pct": derivatives_context.get("basis_pct"),
        "open_interest": derivatives_context.get("open_interest"),
        "derivatives_source": derivatives_context.get("source"),
        "microstructure_allowed": microstructure_context.get("allowed", True),
        "would_block": not microstructure_context.get("allowed", True),
        "would_block_reason": microstructure_context.get("reason"),
        "best_bid": microstructure_context.get("best_bid"),
        "best_ask": microstructure_context.get("best_ask"),
        "spread_bps": microstructure_context.get("spread_bps"),
        "top_depth_usd": microstructure_context.get("top_depth_usd"),
        "book_imbalance": microstructure_context.get("book_imbalance"),
        "horizons": normalized_horizons,
        "completed_horizons": [],
    }
    pending.append(observation)
    _stats(state)["signals_observed"] += 1
    return observation


def advance_signal_observations(state, bars_by_coin):
    """Resolve any pending horizons whose completed candles are now available."""
    pending = state.setdefault(_PENDING_KEY, [])
    remaining = []
    outcomes = []
    for observation in pending:
        bars = list((bars_by_coin or {}).get(observation.get("coin")) or [])
        anchor_index = next(
            (index for index, bar in enumerate(bars) if _bar_time(bar) == observation.get("entry_bar_time")),
            None,
        )
        if anchor_index is None:
            remaining.append(observation)
            continue
        completed = set(observation.get("completed_horizons") or [])
        for horizon in observation.get("horizons") or []:
            if horizon in completed or anchor_index + horizon >= len(bars):
                continue
            future_close = _bar_close(bars[anchor_index + horizon])
            entry_close = observation.get("entry_close")
            if future_close is None or entry_close in (None, 0):
                continue
            raw_return_pct = (future_close / entry_close - 1.0) * 100.0
            forward_return_pct = raw_return_pct if observation.get("direction") == "long" else -raw_return_pct
            outcomes.append(
                {
                    **observation,
                    "forward_bars": horizon,
                    "forward_close": future_close,
                    "forward_return_pct": round(forward_return_pct, 6),
                }
            )
            completed.add(horizon)
        observation["completed_horizons"] = sorted(completed)
        if len(completed) < len(observation.get("horizons") or []):
            remaining.append(observation)

    state[_PENDING_KEY] = remaining
    _stats(state)["outcomes_observed"] += len(outcomes)
    return outcomes


def summarize_signal_observations(state, min_samples=30):
    stats = _stats(state)
    signals_observed = int(stats.get("signals_observed") or 0)
    minimum_signals = max(int(min_samples or 0), 0)
    return {
        "signals_observed": signals_observed,
        "outcomes_observed": int(stats.get("outcomes_observed") or 0),
        "pending_observations": len(state.get(_PENDING_KEY) or []),
        "minimum_signals": minimum_signals,
        "remaining_signals": max(minimum_signals - signals_observed, 0),
    }
