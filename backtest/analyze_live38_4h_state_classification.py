"""Measure whether causal volume/volatility states separate momentum outcomes.

This is a diagnostic, not a strategy.  It defines one fixed four-state map,
reports future returns and state transitions, and never places orders or
selects parameters from the known benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.backtesting_py_live38_4h import load_frames


DEFAULT_DATA_PATH = Path("data/research_artifacts/hyperliquid_live38_1h.json")
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/live38_4h_state_classification.json")
VOLUME_BASELINE_BARS = 24
VOLATILITY_BARS = 12
VOLATILITY_BASELINE_BARS = 42
MOMENTUM_BARS = 12
TREND_BARS = 42
MIN_TREND = 0.01
HORIZONS = (1, 3, 6)
STATES = (
    "high_volume_high_volatility",
    "high_volume_low_volatility",
    "low_volume_high_volatility",
    "low_volume_low_volatility",
)


def classify_states(closes, volumes):
    """Return causal four-state labels; baselines exclude the current bar."""
    returns = closes.pct_change()
    realized_volatility = returns.rolling(VOLATILITY_BARS).std()
    volume_baseline = volumes.shift(1).rolling(VOLUME_BASELINE_BARS).median()
    volatility_baseline = realized_volatility.shift(1).rolling(VOLATILITY_BASELINE_BARS).median()
    high_volume = volumes >= volume_baseline
    high_volatility = realized_volatility >= volatility_baseline
    valid = volume_baseline.notna() & volatility_baseline.notna()
    states = pd.DataFrame(index=closes.index, columns=closes.columns, dtype="object")
    states[valid & high_volume & high_volatility] = STATES[0]
    states[valid & high_volume & ~high_volatility] = STATES[1]
    states[valid & ~high_volume & high_volatility] = STATES[2]
    states[valid & ~high_volume & ~high_volatility] = STATES[3]
    return states


def _metrics(values):
    array = np.asarray([value for value in values if pd.notna(value)], dtype=float)
    if not len(array):
        return {"count": 0, "mean_return_pct": None, "median_return_pct": None, "positive_rate": None}
    return {
        "count": int(len(array)),
        "mean_return_pct": float(array.mean() * 100.0),
        "median_return_pct": float(np.median(array) * 100.0),
        "positive_rate": float((array > 0.0).mean()),
    }


def summarize_segment(closes, states, start, end):
    momentum = closes / closes.shift(MOMENTUM_BARS) - 1.0
    trend = closes / closes.shift(TREND_BARS) - 1.0
    eligible = (momentum > 0.0) & (trend >= MIN_TREND)
    segment = slice(int(start), int(end))
    state_summary = {}
    selector_summary = {state: {str(horizon): [] for horizon in HORIZONS} for state in STATES}
    selector_transitions = {}

    for state in STATES:
        mask = (states == state) & eligible
        state_summary[state] = {}
        for horizon in HORIZONS:
            future = closes.shift(-horizon) / closes - 1.0
            values = future.iloc[segment].where(mask.iloc[segment]).stack().tolist()
            state_summary[state][str(horizon)] = _metrics(values)

    for index in range(max(int(start), TREND_BARS), min(int(end), len(closes))):
        ranked = momentum.iloc[index].where(eligible.iloc[index]).dropna().sort_values(ascending=False)
        if ranked.empty:
            continue
        coin = str(ranked.index[0])
        state = states.iloc[index].get(coin)
        if state not in STATES:
            continue
        previous_state = states.iloc[index - 1].get(coin)
        transition = f"{previous_state}->{state}" if previous_state in STATES else None
        if transition is not None:
            selector_transitions.setdefault(transition, {str(horizon): [] for horizon in HORIZONS})
        for horizon in HORIZONS:
            future_index = index + horizon
            if future_index < min(int(end), len(closes)):
                future_return = float(closes.iloc[future_index][coin] / closes.iloc[index][coin] - 1.0)
                selector_summary[state][str(horizon)].append(future_return)
                if transition is not None:
                    selector_transitions[transition][str(horizon)].append(future_return)

    transitions = {state: {target: 0 for target in STATES} for state in STATES}
    current = states.iloc[segment]
    following = states.shift(-1).iloc[segment]
    for state in STATES:
        for target in STATES:
            transitions[state][target] = int(((current == state) & (following == target)).sum().sum())

    return {
        "coin_opportunities": state_summary,
        "strongest_selector": {
            state: {horizon: _metrics(values) for horizon, values in horizons.items()}
            for state, horizons in selector_summary.items()
        },
        "strongest_selector_transitions": {
            transition: {horizon: _metrics(values) for horizon, values in horizons.items()}
            for transition, horizons in sorted(selector_transitions.items())
        },
        "transitions": transitions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--bars-per-fold", type=int, default=300)
    args = parser.parse_args(argv)
    if args.bars_per_fold <= 0:
        raise SystemExit("--bars-per-fold must be positive")

    frames = load_frames(args.data_path, bars_per_fold=args.bars_per_fold)
    closes = pd.DataFrame({coin: frame["Close"] for coin, frame in frames.items()})
    volumes = pd.DataFrame({coin: frame["Volume"] for coin, frame in frames.items()})
    states = classify_states(closes, volumes)
    boundaries = [
        ("development_1", 0, args.bars_per_fold),
        ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
        ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
        ("known_benchmark_diagnostic_only", args.bars_per_fold * 3, args.bars_per_fold * 4),
        ("post_boundary_observation", args.bars_per_fold * 4, len(closes)),
    ]
    segments = {
        name: summarize_segment(closes, states, start, end)
        for name, start, end in boundaries
        if start < min(end, len(closes))
    }
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "decision": "measurement_only",
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "source_timeframe": "1h",
        "decision_timeframe": "4h",
        "bars": len(closes),
        "coins": list(closes.columns),
        "state_definition": {
            "volume": f"current volume >= median of prior {VOLUME_BASELINE_BARS} completed bars",
            "volatility": (
                f"current {VOLATILITY_BARS}-bar realized volatility >= median of prior "
                f"{VOLATILITY_BASELINE_BARS} realized-volatility values"
            ),
            "states": list(STATES),
        },
        "momentum_observation": {
            "momentum_bars": MOMENTUM_BARS,
            "trend_bars": TREND_BARS,
            "minimum_trend": MIN_TREND,
            "future_horizons_bars": list(HORIZONS),
            "holding_rule": "diagnostic horizons only; no strategy holding-time rule is defined",
        },
        "segments": segments,
        "research_boundary": {
            "selection_allowed": ["development_1", "development_2", "development_3"],
            "known_benchmark_is_not_holdout": True,
            "post_boundary_is_observation_only_until_sample_is_sufficient": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": artifact["decision"], "bars": len(closes), "segments": list(segments)}, indent=2))
    return artifact


if __name__ == "__main__":
    main()
