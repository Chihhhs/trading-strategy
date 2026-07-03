#!/usr/bin/env python3
"""Shared bootstrap for apps-side live entrypoints."""

import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def load_live_main():
    from trading_strategy.live import config as live_config

    try:
        from live_config import apply_overrides
    except ImportError:
        apply_overrides = None

    if apply_overrides is not None:
        apply_overrides(live_config)

    from trading_strategy.live import main

    return main
