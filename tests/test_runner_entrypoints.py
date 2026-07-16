import importlib.util
import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def load_paper_runner():
    path = os.path.join(ROOT, "apps", "runners", "paper_runner.py")
    spec = importlib.util.spec_from_file_location("paper_runner_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PaperRunnerEntrypointTests(unittest.TestCase):
    def test_experiment_arguments_dispatch_to_experiment_runner(self):
        runner = load_paper_runner()
        argv = ["--experiment", "candidate.json", "--approval-result", "approval.json"]
        with patch("trading_strategy.paper.main") as experiment_main:
            runner.main(argv)
        experiment_main.assert_called_once_with(argv)

    def test_normal_paper_run_uses_hyperliquid_aligned_runner(self):
        runner = load_paper_runner()
        with patch.object(runner, "load_live_main") as load_live_main:
            live_main = load_live_main.return_value
            runner.main([])
        load_live_main.assert_called_once_with()
        live_main.assert_called_once_with()
