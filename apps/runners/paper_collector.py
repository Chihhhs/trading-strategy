#!/usr/bin/env python3
"""Refresh all active Hyperliquid paper-market caches without evaluating entries."""

import os
import sys


CURRENT_DIR = os.path.dirname(__file__)
APPS_DIR = os.path.dirname(CURRENT_DIR)
if APPS_DIR not in sys.path:
    sys.path.insert(0, APPS_DIR)

from _live_bootstrap import load_live_main


def main():
    os.environ["PAPER_PROFILE"] = "collector"
    sys.argv.append("--collector")
    return load_live_main()()


if __name__ == "__main__":
    main()
