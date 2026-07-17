#!/usr/bin/env python3
"""Compare one fixed entry-quality candidate without granting promotion authority."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from trading_strategy.backtest import PortfolioBacktester, load_derivatives_data, load_historical_data
from trading_strategy.backtest.regime_attribution import compare_buckets, portfolio_attribution, research_verdict, signal_attribution
from trading_strategy.backtest.trend_attribution import run_trend_entry_attribution_report
from trading_strategy.experiments import BacktestExperimentAdapter, build_config_diff, load_experiment


def build_diagnostic(baseline_spec, candidate_spec, baseline_rows, candidate_rows):
    comparable = (
        baseline_spec.dataset == candidate_spec.dataset
        and baseline_spec.coins == candidate_spec.coins
        and baseline_spec.costs == candidate_spec.costs
        and baseline_spec.execution == candidate_spec.execution
    )
    baseline_by_window = {row.window: row for row in baseline_rows}
    comparisons = []
    for candidate in candidate_rows:
        baseline = baseline_by_window.get(candidate.window)
        if baseline is None:
            continue
        improved = (
            not baseline.missing_data_coins
            and not candidate.missing_data_coins
            and candidate.net_pnl_pct >= baseline.net_pnl_pct
            and candidate.max_drawdown_pct <= baseline.max_drawdown_pct
        )
        comparisons.append({
            "window": candidate.window,
            "improved": improved,
            "net_pnl_pct_delta": round(candidate.net_pnl_pct - baseline.net_pnl_pct, 6),
            "max_drawdown_pct_delta": round(candidate.max_drawdown_pct - baseline.max_drawdown_pct, 6),
            "trades_delta": candidate.trades - baseline.trades,
            "turnover_delta": round(candidate.turnover - baseline.turnover, 6),
            "baseline": baseline.to_dict(),
            "candidate": candidate.to_dict(),
        })
    passed = sum(row["improved"] for row in comparisons)
    status = "research_follow_up" if comparable and comparisons and passed >= (len(comparisons) // 2 + 1) else "rejected"
    return {
        "schema_version": 1,
        "kind": "entry_quality_diagnostic",
        "research_only": True,
        "does_not_authorize": ["observer", "paper_execution", "live"],
        "status": status,
        "passed_windows": passed,
        "compared_windows": len(comparisons),
        "config_diff": build_config_diff(baseline_spec, candidate_spec),
        "comparisons": comparisons,
    }


def _run_with_trades(spec, adapter):
    data_map = load_historical_data(spec.dataset.path)
    derivatives = load_derivatives_data(spec.dataset.derivatives_path)
    hourly = adapter._load_exit_replay_data(
        spec.execution.exit_replay_path,
        spec.execution.replay_metadata_path,
        required_coins=spec.coins if spec.execution.drawdown_source == "mark_to_market" else (),
    )
    results = {}
    for window in spec.evaluation.windows:
        config = adapter.build_config(spec, max_days=window)
        results[window] = PortfolioBacktester(
            config=config,
            derivatives_data_map=derivatives,
            exit_replay_data_map=hourly,
            exit_replay_mode=spec.execution.exit_replay_mode,
        ).run(data_map)
    return data_map, results


def build_regime_attribution(baseline_spec, candidate_spec, adapter):
    """Build a frozen-fixture, research-only attribution without any promotion path."""
    baseline_data, baseline_runs = _run_with_trades(baseline_spec, adapter)
    candidate_data, candidate_runs = _run_with_trades(candidate_spec, adapter)
    if baseline_data != candidate_data:
        raise ValueError("baseline and candidate must use the same fixture")
    comparable = (
        baseline_spec.dataset == candidate_spec.dataset
        and baseline_spec.coins == candidate_spec.coins
        and baseline_spec.costs == candidate_spec.costs
        and baseline_spec.execution == candidate_spec.execution
    )
    if not comparable:
        raise ValueError("regime attribution requires matching fixture, universe, costs, and execution")
    rows = {}
    for window in baseline_spec.evaluation.windows:
        baseline_config = adapter.build_config(baseline_spec, max_days=window)
        candidate_config = adapter.build_config(candidate_spec, max_days=window)
        baseline_signals = run_trend_entry_attribution_report(baseline_data, config=baseline_config, max_bars=window)
        candidate_signals = run_trend_entry_attribution_report(candidate_data, config=candidate_config, max_bars=window)
        baseline_portfolio = portfolio_attribution(baseline_runs[window].trades, baseline_data["BTC"])
        candidate_portfolio = portfolio_attribution(candidate_runs[window].trades, candidate_data["BTC"])
        rows[str(window)] = {
            "signal_layer": signal_attribution(baseline_signals.observations, candidate_signals.observations),
            "portfolio_layer": {
                "baseline": baseline_portfolio,
                "candidate": candidate_portfolio,
                "candidate_minus_baseline": compare_buckets(baseline_portfolio, candidate_portfolio),
            },
            "verdict": research_verdict(candidate_portfolio),
        }
    return {
        "schema_version": 1,
        "kind": "trend_btc_regime_entry_attribution",
        "research_only": True,
        "does_not_authorize": ["observer", "paper_execution", "live"],
        "btc_regime_definition": {"lookback_completed_daily_bars": 7, "threshold_pct": 3.0, "bull": ">3%", "bear": "<-3%", "neutral": "otherwise"},
        "minimum_bucket_trades": 10,
        "baseline_manifest_fingerprint": baseline_spec.fingerprint,
        "candidate_manifest_fingerprint": candidate_spec.fingerprint,
        "dataset_id": baseline_spec.dataset.id,
        "dataset_fingerprint": adapter._file_fingerprint(baseline_spec.dataset.path),
        "execution_fingerprint": adapter._file_fingerprint(baseline_spec.execution.exit_replay_path),
        "universe": list(baseline_spec.coins),
        "costs": {"fee_bps": baseline_spec.costs.fee_bps, "slippage_bps": baseline_spec.costs.slippage_bps},
        "windows": rows,
    }


def format_markdown(report):
    lines = [
        "# 38-coin Trend BTC-regime attribution",
        "",
        "Research-only. This artifact does not authorize observer, paper execution, or live trading.",
        "",
        f"- Dataset fingerprint: `{report['dataset_fingerprint']}`",
        f"- Baseline manifest: `{report['baseline_manifest_fingerprint']}`",
        f"- Candidate manifest: `{report['candidate_manifest_fingerprint']}`",
        f"- Execution fixture fingerprint: `{report['execution_fingerprint']}`",
        f"- BTC regime: completed 7-day close change; bull > 3%, bear < -3%; bucket sample floor = {report['minimum_bucket_trades']} trades.",
        "",
    ]
    for window, row in report["windows"].items():
        lines.extend([f"## {window} days", "", f"Verdict: `{row['verdict']}`. A small bucket is evidence-insufficient, not a promotion or rejection result.", "", "### Executed portfolio", "", "| BTC regime / direction | Baseline trades | Candidate trades | Candidate net PnL | Delta net PnL | Candidate top-1 coin |", "|---|---:|---:|---:|---:|---|"])
        baseline = row["portfolio_layer"]["baseline"]["buckets"]
        candidate = row["portfolio_layer"]["candidate"]["buckets"]
        delta = row["portfolio_layer"]["candidate_minus_baseline"]
        for key in sorted(candidate):
            top = candidate[key]["coin_concentration"]["top_1"]
            top_text = "-" if top is None else f"{top['coin']} ({top['net_pnl']})"
            lines.append(f"| {key} | {baseline[key]['trades']} | {candidate[key]['trades']} | {candidate[key]['net_pnl']} | {delta[key]['net_pnl_delta']} | {top_text} |")
        signal = row["signal_layer"]["buckets"]
        lines.extend(["", "### Raw entry opportunities before two-position capacity", "", "| BTC regime / direction | Raw | Baseline allowed | Candidate allowed | Retained | Removed |", "|---|---:|---:|---:|---:|---:|"])
        for key in sorted(signal):
            bucket = signal[key]
            lines.append(f"| {key} | {bucket['raw_opportunities']} | {bucket['baseline_allowed']} | {bucket['candidate_allowed']} | {bucket['retained_by_candidate']} | {bucket['removed_by_candidate']} |")
        total = row["portfolio_layer"]["candidate"]["total"]["coin_concentration"]
        lines.extend(["", f"Candidate total concentration: top-1={total['top_1']}; top-3 absolute share={total['top_3_absolute_share']}; largest trade absolute share={total['largest_trade_absolute_share']}.", ""])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--regime-attribution-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args(argv)
    baseline_spec = load_experiment(args.baseline)
    candidate_spec = load_experiment(args.candidate)
    adapter = BacktestExperimentAdapter()
    report = build_diagnostic(baseline_spec, candidate_spec, adapter.run(baseline_spec), adapter.run(candidate_spec))
    if args.regime_attribution_output:
        regime_report = build_regime_attribution(baseline_spec, candidate_spec, adapter)
        os.makedirs(os.path.dirname(args.regime_attribution_output), exist_ok=True)
        with open(args.regime_attribution_output, "w", encoding="utf-8") as handle:
            json.dump(regime_report, handle, sort_keys=True, indent=2)
        if args.markdown_output:
            os.makedirs(os.path.dirname(args.markdown_output), exist_ok=True)
            with open(args.markdown_output, "w", encoding="utf-8") as handle:
                handle.write(format_markdown(regime_report))
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, sort_keys=True, indent=2)
    print(json.dumps(report, sort_keys=True))
    return report


if __name__ == "__main__":
    main()
