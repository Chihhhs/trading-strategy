#!/usr/bin/env python3
import os
import sys


CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from trading_strategy.paper import main as paper_main


def main():
    return paper_main(sys.argv[1:])


if __name__ == "__main__":
    main()
