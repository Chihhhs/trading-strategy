"""Isolated paper runner for the validated and research-only selectors.

This module is intentionally separate from the normal paper/live engine.  It
only simulates one long Hyperliquid-aligned position from completed 4h bars,
keeps its state under ``data/paper_execution/routeXX``, and never submits an
order.  The selector parameters are copied from the holdout-passing research
artifacts; changing them requires a new research route and review.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path

from . import config
from .market import get_current_prices, get_klines


FIXED_LIVE_UNIVERSE = (
    "BTC", "ETH", "BNB", "NEO", "LTC", "ADA", "XRP", "IOTA", "XLM", "TRX",
    "ETC", "LINK", "FET", "ZEC", "DASH", "ATOM", "ALGO", "DOGE", "HBAR", "STX",
    "SOL", "HYPE", "XMR", "CC", "BCH", "SUI", "AVAX", "NEAR", "UNI", "TAO",
    "PAXG", "WLFI", "ASTER", "ONDO", "AAVE", "SKY", "DOT", "WLD",
)

INTERVAL = "4h"
INTERVAL_MS = 4 * 60 * 60 * 1000
BAR_LIMIT = 240
MIN_ORDER_USD = 10.0
ALLOCATION_PER_POSITION = 0.5
VOLATILITY_LOOKBACK = 42
VOLATILITY_STATE_LOOKBACK = 168
VOLUME_LOOKBACK = 24
VOLATILITY_FLOOR = 0.5
FEE_BPS = 10.0
DEFAULT_CAPITAL = 50.0
FORWARD_MIN_COMPLETED_BARS = 300
FORWARD_MIN_EXITS = 20

ROUTE_CONFIGS = {
    "30": {
        "name": "selector_m12_t42_raw_s0.0_w0.01_trend0.01_vol0.015",
        "label": "stateful cross-sectional momentum selector",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_score": 0.0,
        "min_trend": 0.01,
        "switch_margin": 0.01,
        "volatility_target": 0.015,
        "state_mode": "any",
        "research_artifact": "data/research_artifacts/backtesting_py_live38_4h_single_selector.json",
    },
    "31": {
        "name": "volume_state_m12_t42_raw_high_volume_vol0.015",
        "label": "high-volume stateful momentum selector",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_score": 0.0,
        "min_trend": 0.01,
        "switch_margin": 0.01,
        "volatility_target": 0.015,
        "state_mode": "high_volume",
        "research_artifact": "data/research_artifacts/backtesting_py_live38_4h_volume_state_state_only.json",
    },
    "38": {
        "name": "selector_m12_t42_raw_s0.0_w0.01_trend0.01_confirm2_vol0.015",
        "label": "two-bar leader-persistence entry-quality selector",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_score": 0.0,
        "min_trend": 0.01,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 2,
        "volatility_target": 0.015,
        "state_mode": "any",
        "research_artifact": "data/research_artifacts/backtesting_py_live38_4h_single_selector.json",
    },
    "39": {
        "name": "selector_m12_t42_raw_s0.0_w0.02_trend0.01_vol0.015",
        "label": "higher-switch-margin entry-quality selector",
        "momentum_bars": 12,
        "trend_bars": 42,
        "score_mode": "raw",
        "min_score": 0.0,
        "min_trend": 0.01,
        "switch_margin": 0.02,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
        "state_mode": "any",
        "research_artifact": "data/research_artifacts/backtesting_py_live38_4h_single_selector.json",
    },
    "40": {
        "name": "selector_m12_t84_raw_s0.0_w0.01_trend0.01_vol0.015",
        "label": "longer-trend-confirmation entry-quality selector",
        "momentum_bars": 12,
        "trend_bars": 84,
        "score_mode": "raw",
        "min_score": 0.0,
        "min_trend": 0.01,
        "switch_margin": 0.01,
        "entry_confirmation_bars": 1,
        "volatility_target": 0.015,
        "state_mode": "any",
        "research_artifact": "data/research_artifacts/backtesting_py_live38_4h_single_selector.json",
    },
}


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _sample_std(values):
    values = [float(value) for value in values if _finite(value) is not None]
    return statistics.stdev(values) if len(values) >= 2 else None


def _median(values):
    values = [float(value) for value in values if _finite(value) is not None]
    return statistics.median(values) if values else None


def _common_bars(bars_by_coin):
    """Align bars by timestamp and return ``times, closes, volumes`` arrays."""
    maps = {}
    for coin, bars in bars_by_coin.items():
        rows = {}
        for bar in bars or []:
            timestamp = _finite((bar or {}).get("time"))
            close = _finite((bar or {}).get("close"))
            volume = _finite((bar or {}).get("volume"))
            if timestamp is None or close is None or close <= 0:
                continue
            rows[int(timestamp)] = {"close": close, "volume": volume or 0.0}
        if not rows:
            return [], {}, {}
        maps[coin] = rows
    if not maps:
        return [], {}, {}
    times = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    closes = {coin: [maps[coin][timestamp]["close"] for timestamp in times] for coin in maps}
    volumes = {coin: [maps[coin][timestamp]["volume"] for timestamp in times] for coin in maps}
    return times, closes, volumes


def _rolling_volatility(values, index, window=VOLATILITY_LOOKBACK):
    if index < window:
        return None
    returns = [values[pos] / values[pos - 1] - 1.0 for pos in range(index - window + 1, index + 1)]
    return _sample_std(returns)


def _state_ratio(values, index, *, window, denominator_window):
    if index < window - 1:
        return None
    current = _median(values[index - window + 1 : index + 1])
    if current is None or current <= 0:
        return None
    return values[index] / current


def _volatility_ratio(volatilities, index):
    if index >= len(volatilities) or volatilities[index] is None:
        return None
    start = index - VOLATILITY_STATE_LOOKBACK + 1
    if start < 0:
        return None
    baseline = _median(volatilities[start : index + 1])
    if baseline in (None, 0):
        return None
    return volatilities[index] / baseline


def _state_allows(volume_ratio, volatility_ratio, state_mode):
    if state_mode == "any":
        return True
    if state_mode == "high_volume":
        return volume_ratio is not None and volume_ratio >= 1.10
    if state_mode == "normal_volatility":
        return volatility_ratio is not None and volatility_ratio <= 1.50
    if state_mode == "low_volatility":
        return volatility_ratio is not None and volatility_ratio <= 1.00
    if state_mode == "expansion_confirmation":
        return (
            volume_ratio is not None
            and volatility_ratio is not None
            and volume_ratio >= 1.10
            and 1.00 <= volatility_ratio <= 2.00
        )
    raise ValueError(f"unsupported state mode: {state_mode}")


def compute_selector_decisions(
    bars_by_coin,
    route_id,
    *,
    initial_incumbent=None,
    after_bar_time=None,
    initial_pending_candidate=None,
    initial_pending_streak=0,
):
    """Compute chronological causal targets after an optional processed bar."""
    route = ROUTE_CONFIGS[str(route_id)]
    times, closes, volumes = _common_bars(bars_by_coin)
    coins = list(closes)
    if not times:
        raise ValueError("no common completed bars across the fixed universe")

    momentum_bars = int(route["momentum_bars"])
    trend_bars = int(route["trend_bars"])
    state_mode = route["state_mode"]
    confirmation_bars = max(1, int(route.get("entry_confirmation_bars", 1)))
    warmup = max(momentum_bars, trend_bars, VOLATILITY_LOOKBACK)
    if state_mode != "any":
        warmup = max(warmup, VOLUME_LOOKBACK, VOLATILITY_STATE_LOOKBACK)

    volatilities = {
        coin: [_rolling_volatility(closes[coin], index) for index in range(len(times))]
        for coin in coins
    }
    incumbent = str(initial_incumbent).upper() if initial_incumbent in coins else None
    pending_candidate = (
        str(initial_pending_candidate).upper()
        if initial_pending_candidate in coins
        else None
    )
    pending_streak = max(0, int(initial_pending_streak or 0))
    decisions = []
    for index, timestamp in enumerate(times):
        scores = {}
        trends = {}
        volume_ratios = {}
        volatility_ratios = {}
        eligible = {}
        for coin in coins:
            if index < momentum_bars or index < trend_bars:
                continue
            momentum = closes[coin][index] / closes[coin][index - momentum_bars] - 1.0
            trend = closes[coin][index] / closes[coin][index - trend_bars] - 1.0
            scores[coin] = momentum
            trends[coin] = trend
            volume_ratios[coin] = _state_ratio(volumes[coin], index, window=VOLUME_LOOKBACK, denominator_window=VOLUME_LOOKBACK)
            volatility_ratios[coin] = _volatility_ratio(volatilities[coin], index)
            eligible[coin] = (
                index >= warmup
                and trend >= float(route["min_trend"])
                and momentum >= float(route["min_score"])
                and _state_allows(volume_ratios[coin], volatility_ratios[coin], state_mode)
            )

        if index < warmup or (after_bar_time is not None and int(timestamp) <= int(after_bar_time)):
            continue

        ranked = sorted((coin for coin in coins if eligible.get(coin, False)), key=lambda coin: scores[coin], reverse=True)
        best = ranked[0] if ranked else None
        if best is not None and best == pending_candidate:
            pending_streak += 1
        else:
            pending_candidate = best
            pending_streak = 1 if best is not None else 0
        confirmed_best = best if pending_streak >= confirmation_bars else None
        if incumbent is None:
            incumbent = confirmed_best
        elif not bool(trends.get(incumbent, float("-inf")) >= float(route["min_trend"])):
            incumbent = confirmed_best
        elif confirmed_best is not None and confirmed_best != incumbent:
            lead = scores[confirmed_best] - scores.get(incumbent, float("-inf"))
            if lead >= float(route["switch_margin"]):
                incumbent = confirmed_best

        decisions.append(
            {
                "bar_time": int(timestamp),
                "target": incumbent,
                "best": best,
                "score": _finite(scores.get(incumbent)),
                "trend": _finite(trends.get(incumbent)),
                "volume_ratio": _finite(volume_ratios.get(incumbent)),
                "volatility_ratio": _finite(volatility_ratios.get(incumbent)),
                "volatility": _finite(volatilities.get(incumbent, [None] * len(times))[index]) if incumbent else None,
                "eligible": bool(eligible.get(incumbent, False)) if incumbent else False,
                "ranked": ranked[:5],
                "entry_confirmed": bool(confirmed_best == best and best is not None),
                "entry_confirmation_streak": pending_streak if best is not None else 0,
                "entry_confirmation_required": confirmation_bars,
                "pending_candidate": pending_candidate,
                "common_bars": len(times),
            }
        )
    if after_bar_time is None and not decisions:
        raise ValueError(f"need at least {warmup + 1} common completed {INTERVAL} bars; got {len(times)}")
    return decisions


def compute_selector_decision(bars_by_coin, route_id, *, initial_incumbent=None):
    """Return the latest target for a fresh paper ledger or observation."""
    return compute_selector_decisions(
        bars_by_coin,
        route_id,
        initial_incumbent=initial_incumbent,
    )[-1]


def _state_path(route_id):
    return Path(config.get_state_dir()) / f"route{route_id}" / "state.json"


def _events_path(route_id):
    return Path(config.get_state_dir()) / f"route{route_id}" / "events.jsonl"


def _empty_state(route_id, capital):
    route = ROUTE_CONFIGS[str(route_id)]
    return {
        "schema_version": 1,
        "route_id": str(route_id),
        "route_name": route["name"],
        "route_label": route["label"],
        "paper_profile": "execution",
        "execution_authorized": False,
        "market_data_source": config.get_market_data_source(),
        "interval": INTERVAL,
        "initial_capital": float(capital),
        "cash": float(capital),
        "position": None,
        "last_processed_bar": None,
        "paper_start_bar": None,
        "completed_bars_observed": 0,
        "peak_equity": float(capital),
        "max_drawdown_pct": 0.0,
        "cycles": 0,
        "entries": 0,
        "exits": 0,
        "skipped_entries_below_min_order": 0,
        "realized_pnl": 0.0,
        "last_decision": None,
        "pending_candidate": None,
        "pending_candidate_streak": 0,
        "last_snapshot": None,
        "events": [],
    }


def _load_state(route_id, capital):
    path = _state_path(route_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema_version") == 1 and state.get("route_id") == str(route_id):
            if "paper_start_bar" not in state:
                state["paper_start_bar"] = state.get("last_processed_bar")
            if "completed_bars_observed" not in state:
                state["completed_bars_observed"] = 1 if state.get("last_processed_bar") is not None else 0
            return state
    except (OSError, ValueError, TypeError):
        pass
    return _empty_state(route_id, capital)


def _save_state(route_id, state):
    path = _state_path(route_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _append_event(route_id, event):
    path = _events_path(route_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _position_pnl(position, price):
    return float(position["qty"]) * (float(price) - float(position["entry_price"]))


def _equity(state, prices):
    position = state.get("position")
    if not position:
        return float(state.get("cash", 0.0))
    price = _finite(prices.get(position["coin"])) or float(position["entry_price"])
    return float(state.get("cash", 0.0)) + _position_pnl(position, price)


def _record_event(state, route_id, event):
    state.setdefault("events", []).append(event)
    state["events"] = state["events"][-200:]
    _append_event(route_id, event)


def forward_gate_status(state, *, min_completed_bars=FORWARD_MIN_COMPLETED_BARS, min_exits=FORWARD_MIN_EXITS):
    snapshot = state.get("last_snapshot") or {}
    initial = float(state.get("initial_capital", 0.0))
    equity = float(snapshot.get("equity", initial))
    checks = {
        "completed_bars": int(state.get("completed_bars_observed", 0)) >= int(min_completed_bars),
        "closed_trades": int(state.get("exits", 0)) >= int(min_exits),
        "positive_net_return": equity > initial,
        "drawdown_within_25pct": float(state.get("max_drawdown_pct", 0.0)) > -25.0,
        "zero_minimum_order_skips": int(state.get("skipped_entries_below_min_order", 0)) == 0,
    }
    return {
        "ready_for_manual_review": all(checks.values()),
        "execution_authorized": False,
        "checks": checks,
        "observed_completed_bars": int(state.get("completed_bars_observed", 0)),
        "required_completed_bars": int(min_completed_bars),
        "closed_trades": int(state.get("exits", 0)),
        "required_closed_trades": int(min_exits),
        "net_return_pct": (equity / initial - 1.0) * 100.0 if initial else 0.0,
    }


def _close_position(state, route_id, price, reason, bar_time, *, execution_bar_time=None, price_source="current_mid"):
    position = state.get("position")
    if not position:
        return None
    price = float(price)
    exit_notional = float(position["qty"]) * price
    fee = exit_notional * FEE_BPS / 10000.0
    pnl = _position_pnl(position, price)
    state["cash"] = float(state.get("cash", 0.0)) + pnl - fee
    state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + pnl - fee - float(position.get("entry_fee", 0.0))
    state["exits"] = int(state.get("exits", 0)) + 1
    event = {
        "event": "exit",
        "route_id": str(route_id),
        "time": int(time.time() * 1000),
        "bar_time": int(bar_time),
        "execution_bar_time": int(execution_bar_time) if execution_bar_time is not None else None,
        "price_source": price_source,
        "coin": position["coin"],
        "price": price,
        "reason": reason,
        "pnl": pnl,
        "fee": fee,
        "return_pct": (pnl / float(position["notional"]) * 100.0) if position.get("notional") else 0.0,
        "execution_authorized": False,
    }
    state["position"] = None
    _record_event(state, route_id, event)
    return event


def _open_position(state, route_id, coin, price, decision, bar_time, *, execution_bar_time=None, price_source="current_mid"):
    if not coin or price is None or price <= 0:
        return None
    volatility = _finite(decision.get("volatility")) or 0.015
    scale = max(VOLATILITY_FLOOR, min(1.0, 0.015 / max(volatility, 1e-9)))
    notional = float(state.get("cash", 0.0)) * ALLOCATION_PER_POSITION * scale
    if notional < MIN_ORDER_USD:
        state["skipped_entries_below_min_order"] = int(state.get("skipped_entries_below_min_order", 0)) + 1
        event = {
            "event": "entry_skipped",
            "route_id": str(route_id),
            "time": int(time.time() * 1000),
            "bar_time": int(bar_time),
            "execution_bar_time": int(execution_bar_time) if execution_bar_time is not None else None,
            "price_source": price_source,
            "coin": coin,
            "reason": "below_min_order",
            "notional": notional,
            "min_order_usd": MIN_ORDER_USD,
            "execution_authorized": False,
        }
        _record_event(state, route_id, event)
        return event
    fee = notional * FEE_BPS / 10000.0
    state["cash"] = float(state.get("cash", 0.0)) - fee
    state["position"] = {
        "coin": coin,
        "entry_price": float(price),
        "entry_time": int(time.time() * 1000),
        "entry_bar_time": int(bar_time),
        "execution_bar_time": int(execution_bar_time) if execution_bar_time is not None else None,
        "price_source": price_source,
        "qty": notional / float(price),
        "notional": notional,
        "entry_fee": fee,
        "volatility": volatility,
        "scale": scale,
        "protection_status": "paper_research_only_no_exchange_orders",
    }
    state["entries"] = int(state.get("entries", 0)) + 1
    event = {
        "event": "entry",
        "route_id": str(route_id),
        "time": int(time.time() * 1000),
        "bar_time": int(bar_time),
        "execution_bar_time": int(execution_bar_time) if execution_bar_time is not None else None,
        "price_source": price_source,
        "coin": coin,
        "price": float(price),
        "notional": notional,
        "fee": fee,
        "scale": scale,
        "decision": decision,
        "execution_authorized": False,
    }
    _record_event(state, route_id, event)
    return event


def _fetch_completed_bars(universe):
    now_ms = int(time.time() * 1000)
    result = {}
    for coin in universe:
        raw = get_klines(f"{coin}USDT", limit=BAR_LIMIT, interval=INTERVAL) or []
        completed = []
        for bar in raw:
            timestamp = _finite((bar or {}).get("time"))
            if timestamp is None or timestamp + INTERVAL_MS > now_ms:
                continue
            completed.append(bar)
        if len(completed) < VOLATILITY_STATE_LOOKBACK + VOLATILITY_LOOKBACK:
            raise RuntimeError(f"{coin}: only {len(completed)} completed {INTERVAL} bars available")
        result[coin] = completed
    return result


def _universe():
    configured = tuple(str(value).upper() for value in config.STRATEGY.get("coin_universe") or ())
    if configured == FIXED_LIVE_UNIVERSE:
        return configured
    return FIXED_LIVE_UNIVERSE


def _prices_at_bar(bars_by_coin, bar_time, field):
    prices = {}
    for coin, bars in bars_by_coin.items():
        row = next((bar for bar in bars if int(_finite((bar or {}).get("time")) or -1) == int(bar_time)), None)
        value = _finite((row or {}).get(field))
        if value is None or value <= 0:
            raise RuntimeError(f"{coin}: missing {field} for replay bar {bar_time}")
        prices[coin] = value
    return prices


def _validate_replay_continuity(last_processed_bar, decisions):
    expected = int(last_processed_bar) + INTERVAL_MS
    for decision in decisions:
        observed = int(decision["bar_time"])
        if observed != expected:
            raise RuntimeError(
                f"paper replay history gap: expected completed bar {expected}, got {observed}; "
                f"available cache window is {BAR_LIMIT} bars"
            )
        expected += INTERVAL_MS


def _update_drawdown(state, prices):
    equity = _equity(state, prices)
    peak = max(float(state.get("peak_equity", state.get("initial_capital", 0.0))), equity)
    state["peak_equity"] = peak
    state["max_drawdown_pct"] = min(
        float(state.get("max_drawdown_pct", 0.0)),
        (equity / peak - 1.0) * 100.0 if peak else 0.0,
    )
    return equity


def _apply_decision(state, route_id, decision, prices, *, execution_bar_time, price_source):
    events = []
    position = state.get("position")
    desired = decision.get("target")
    current_coin = position.get("coin") if position else None
    if current_coin and current_coin != desired:
        event = _close_position(
            state,
            route_id,
            prices[current_coin],
            "selector_target_changed",
            decision["bar_time"],
            execution_bar_time=execution_bar_time,
            price_source=price_source,
        )
        if event:
            events.append(event)
    if desired and not state.get("position"):
        event = _open_position(
            state,
            route_id,
            desired,
            prices[desired],
            decision,
            decision["bar_time"],
            execution_bar_time=execution_bar_time,
            price_source=price_source,
        )
        if event:
            events.append(event)
    return events


def run_once(route_id, *, capital=DEFAULT_CAPITAL):
    route_id = str(route_id)
    if route_id not in ROUTE_CONFIGS:
        raise ValueError(f"unsupported research route: {route_id}")
    state = _load_state(route_id, capital)
    universe = _universe()
    bars = _fetch_completed_bars(universe)
    common_times, _, _ = _common_bars(bars)
    last_processed_bar = state.get("last_processed_bar")
    if last_processed_bar is not None and int(common_times[-1]) < int(last_processed_bar):
        raise RuntimeError(
            f"paper replay data regressed: latest completed bar {common_times[-1]} "
            f"is older than processed bar {last_processed_bar}"
        )
    incumbent = (state.get("last_decision") or {}).get("target") or (state.get("position") or {}).get("coin")
    if last_processed_bar is None:
        decisions = [compute_selector_decision(bars, route_id, initial_incumbent=incumbent)]
    else:
        decisions = compute_selector_decisions(
            bars,
            route_id,
            initial_incumbent=incumbent,
            after_bar_time=last_processed_bar,
            initial_pending_candidate=state.get("pending_candidate"),
            initial_pending_streak=state.get("pending_candidate_streak", 0),
        )
        _validate_replay_continuity(last_processed_bar, decisions)
    prices = get_current_prices([{"name": coin, "symbol": f"{coin}USDT"} for coin in universe]) or {}
    latest_prices = {
        coin: _finite(prices.get(coin)) or float(bars[coin][-1]["close"])
        for coin in universe
    }
    time_positions = {int(value): index for index, value in enumerate(common_times)}
    decision = decisions[-1] if decisions else state.get("last_decision") or compute_selector_decision(bars, route_id, initial_incumbent=incumbent)
    bar_time = int(decision["bar_time"])
    is_new_bar = bool(decisions)
    events = []
    historical_replay_bars = 0
    for replay_decision in decisions:
        replay_bar_time = int(replay_decision["bar_time"])
        if state.get("paper_start_bar") is None:
            state["paper_start_bar"] = replay_bar_time
        state["completed_bars_observed"] = int(state.get("completed_bars_observed", 0)) + 1
        _update_drawdown(state, _prices_at_bar(bars, replay_bar_time, "close"))
        position = time_positions[replay_bar_time]
        if position + 1 < len(common_times):
            execution_bar_time = int(common_times[position + 1])
            execution_prices = _prices_at_bar(bars, execution_bar_time, "open")
            price_source = "next_bar_open_replay"
            historical_replay_bars += 1
        else:
            execution_bar_time = None
            execution_prices = latest_prices
            price_source = "current_mid_or_latest_close"
        events.extend(
            _apply_decision(
                state,
                route_id,
                replay_decision,
                execution_prices,
                execution_bar_time=execution_bar_time,
                price_source=price_source,
            )
        )
        _update_drawdown(state, execution_prices)
        state["last_processed_bar"] = replay_bar_time
        state["last_decision"] = replay_decision
        state["pending_candidate"] = replay_decision.get("pending_candidate")
        state["pending_candidate_streak"] = int(replay_decision.get("entry_confirmation_streak", 0))
        _save_state(route_id, state)

    equity = _update_drawdown(state, latest_prices)
    position = state.get("position")
    state["last_snapshot"] = {
        "time": int(time.time() * 1000),
        "bar_time": bar_time,
        "equity": equity,
        "cash": float(state.get("cash", 0.0)),
        "unrealized_pnl": _position_pnl(position, latest_prices[position["coin"]]) if position else 0.0,
        "position": position,
        "price": latest_prices.get(position["coin"]) if position else None,
        "new_bar": is_new_bar,
        "processed_new_bars": len(decisions),
        "historical_replay_bars": historical_replay_bars,
    }
    state["cycles"] = int(state.get("cycles", 0)) + 1
    _save_state(route_id, state)
    return {
        "route_id": route_id,
        "route_name": ROUTE_CONFIGS[route_id]["name"],
        "new_bar": is_new_bar,
        "processed_new_bars": len(decisions),
        "historical_replay_bars": historical_replay_bars,
        "bar_time": bar_time,
        "target": decision.get("target"),
        "equity": equity,
        "cash": float(state.get("cash", 0.0)),
        "position": position,
        "events": events,
        "entries": state["entries"],
        "exits": state["exits"],
        "skipped_entries_below_min_order": state["skipped_entries_below_min_order"],
        "max_drawdown_pct": state["max_drawdown_pct"],
        "execution_authorized": False,
        "forward_gate": forward_gate_status(state),
        "state_path": str(_state_path(route_id)),
    }


def main(route_id, argv=None):
    parser = argparse.ArgumentParser(description=f"Run isolated Route{route_id} paper simulation")
    parser.add_argument("--once", action="store_true", help="run one cycle (the default)")
    parser.add_argument("--loop", action="store_true", help="poll indefinitely")
    parser.add_argument("--interval-minutes", type=float, default=240.0)
    parser.add_argument("--capital", type=float, default=float(os.getenv("PAPER_RESEARCH_CAPITAL", DEFAULT_CAPITAL)))
    filtered = []
    skip_route_value = False
    for arg in (argv or []):
        if skip_route_value:
            skip_route_value = False
            continue
        if arg == "--research-route":
            skip_route_value = True
            continue
        if arg.startswith("--research-route="):
            continue
        filtered.append(arg)
    args = parser.parse_args(filtered)
    if args.capital <= 0:
        raise SystemExit("--capital must be positive")
    while True:
        try:
            result = run_once(route_id, capital=args.capital)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:  # keep a background paper process alive and visible
            print(json.dumps({"route_id": str(route_id), "error": str(exc), "execution_authorized": False}), flush=True)
            if not args.loop:
                raise
        if not args.loop:
            return 0
        time.sleep(max(60.0, float(args.interval_minutes) * 60.0))
