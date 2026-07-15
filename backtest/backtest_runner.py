#!/usr/bin/env python3
"""Compatibility wrapper for the shared offline backtest module in src/."""

import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from trading_strategy.backtest import DATA_PATH, DEFAULT_COINS, load_historical_data, main, run_backtest_for_coin

__all__ = [
    "DATA_PATH",
    "DEFAULT_COINS",
    "load_historical_data",
    "main",
    "run_backtest_for_coin",
]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in {"run", "compare", "promote"}:
        from trading_strategy.experiments.cli import run_command

        run_command(sys.argv[1:])
    else:
        main()
