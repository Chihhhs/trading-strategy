import argparse
import json
from dataclasses import replace

from .backtest_adapter import BacktestExperimentAdapter
from .results import build_config_diff, evaluate_candidate
from .spec import load_experiment


def _print_json(payload):
    print(json.dumps(payload, sort_keys=True))


def run_command(argv):
    parser = argparse.ArgumentParser(prog="backtest experiment")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--experiment", required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--experiments", nargs="+", required=True)
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--experiment", required=True)
    args = parser.parse_args(argv)
    adapter = BacktestExperimentAdapter()
    if args.command == "run":
        spec = load_experiment(args.experiment)
        rows = adapter.run(spec)
        payload = [row.to_dict() for row in rows]
        _print_json(payload)
        return rows
    if args.command == "compare":
        results = {}
        baseline_spec = None
        for path in args.experiments:
            spec = load_experiment(path)
            rows = adapter.run(spec)
            if baseline_spec is None:
                baseline_spec = spec
            else:
                diff = build_config_diff(baseline_spec, spec)
                rows = [replace(row, config_diff=diff) for row in rows]
            results[spec.name] = [row.to_dict() for row in rows]
        _print_json(results)
        return results
    candidate_spec = load_experiment(args.experiment)
    if not candidate_spec.evaluation.baseline:
        parser.error("promotion requires evaluation.baseline")
    baseline_spec = load_experiment(candidate_spec.evaluation.baseline)
    decision = evaluate_candidate(
        adapter.run(baseline_spec),
        adapter.run(candidate_spec),
        candidate_spec.evaluation,
    )
    decision = replace(decision, config_diff=build_config_diff(baseline_spec, candidate_spec))
    _print_json(decision.to_dict())
    return decision
