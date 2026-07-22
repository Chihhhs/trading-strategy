"""Measure whether market-adjusted momentum predicts continuation better than raw momentum."""

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
DEFAULT_OUTPUT_PATH = Path("data/research_artifacts/live38_4h_residual_momentum.json")
MOMENTUM_BARS = 12
TREND_BARS = 42
BETA_BARS = 42
MIN_TREND = 0.01
HORIZONS = (1, 3, 6)
SCORES = ("raw", "btc_beta_residual", "cross_sectional_excess")


def build_scores(closes):
    returns = closes.pct_change()
    raw = closes / closes.shift(MOMENTUM_BARS) - 1.0
    btc_returns = returns["BTC"]
    beta = returns.rolling(BETA_BARS).cov(btc_returns).div(btc_returns.rolling(BETA_BARS).var(), axis=0)
    residual_returns = returns.sub(beta.shift(1).mul(btc_returns, axis=0))
    btc_residual = (1.0 + residual_returns).rolling(MOMENTUM_BARS).apply(np.prod, raw=True) - 1.0
    cross_sectional = raw.sub(raw.median(axis=1), axis=0)
    return {"raw": raw, "btc_beta_residual": btc_residual, "cross_sectional_excess": cross_sectional}


def _metrics(values):
    array = np.asarray(values, dtype=float)
    if not len(array):
        return {"count": 0, "mean_return_pct": None, "median_return_pct": None, "positive_rate": None}
    return {
        "count": int(len(array)),
        "mean_return_pct": float(array.mean() * 100.0),
        "median_return_pct": float(np.median(array) * 100.0),
        "positive_rate": float((array > 0.0).mean()),
    }


def summarize_segment(closes, scores, start, end):
    raw = scores["raw"]
    trend = closes / closes.shift(TREND_BARS) - 1.0
    base_eligible = (raw > 0.0) & (trend >= MIN_TREND)
    result = {}
    for name, score in scores.items():
        values = {str(horizon): [] for horizon in HORIZONS}
        selected_coins = []
        for index in range(max(int(start), TREND_BARS + MOMENTUM_BARS), min(int(end), len(closes))):
            eligible = base_eligible.iloc[index] & score.iloc[index].notna()
            if name != "raw":
                eligible &= score.iloc[index] > 0.0
            ranked = score.iloc[index].where(eligible).dropna().sort_values(ascending=False)
            if ranked.empty:
                continue
            coin = str(ranked.index[0])
            selected_coins.append(coin)
            for horizon in HORIZONS:
                future_index = index + horizon
                if future_index < min(int(end), len(closes)):
                    values[str(horizon)].append(float(closes.iloc[future_index][coin] / closes.iloc[index][coin] - 1.0))
        counts = pd.Series(selected_coins).value_counts() if selected_coins else pd.Series(dtype=int)
        result[name] = {
            "horizons": {horizon: _metrics(items) for horizon, items in values.items()},
            "selection_count": int(len(selected_coins)),
            "top_coin_share": float(counts.iloc[0] / len(selected_coins)) if len(counts) else None,
            "top_coins": {str(coin): int(count) for coin, count in counts.head(5).items()},
        }
    return result


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
    scores = build_scores(closes)
    boundaries = [
        ("development_1", 0, args.bars_per_fold),
        ("development_2", args.bars_per_fold, args.bars_per_fold * 2),
        ("development_3", args.bars_per_fold * 2, args.bars_per_fold * 3),
        ("known_benchmark_diagnostic_only", args.bars_per_fold * 3, args.bars_per_fold * 4),
        ("post_boundary_observation", args.bars_per_fold * 4, len(closes)),
    ]
    segments = {
        name: summarize_segment(closes, scores, start, end)
        for name, start, end in boundaries
        if start < min(end, len(closes))
    }
    development_names = ("development_1", "development_2", "development_3")
    consistently_better = {
        mode: all(
            segments[segment][mode]["horizons"][str(horizon)]["mean_return_pct"]
            > segments[segment]["raw"]["horizons"][str(horizon)]["mean_return_pct"]
            for segment in development_names
            for horizon in HORIZONS
        )
        for mode in SCORES
        if mode != "raw"
    }
    artifact = {
        "schema_version": 1,
        "execution_authorized": False,
        "decision": "development_measurement_pass" if any(consistently_better.values()) else "rejected_no_consistent_measurement_improvement",
        "data_path": str(args.data_path),
        "data_sha256": hashlib.sha256(args.data_path.read_bytes()).hexdigest(),
        "source_timeframe": "1h",
        "decision_timeframe": "4h",
        "bars": len(closes),
        "scores": {
            "raw": "12-bar price return",
            "btc_beta_residual": "12-bar compounded coin return minus prior-42-bar beta times BTC return",
            "cross_sectional_excess": "12-bar return minus the same-bar live-38 median return",
        },
        "eligibility": f"raw momentum > 0 and {TREND_BARS}-bar trend >= {MIN_TREND}",
        "future_horizons_bars": list(HORIZONS),
        "segments": segments,
        "consistently_better_than_raw_in_development": consistently_better,
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
