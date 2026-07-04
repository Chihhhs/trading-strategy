#!/usr/bin/env python3
import os
import sys


"""bash
bash -lc '
cd /mnt/d/code/trading-strategy
python3 -m apps.runners.live_runner --live --loop
'
"""

CURRENT_DIR = os.path.dirname(__file__)
APPS_DIR = os.path.dirname(CURRENT_DIR)
if APPS_DIR not in sys.path:
    sys.path.insert(0, APPS_DIR)

from _live_bootstrap import load_live_main


live_main = load_live_main()


def main():
    return live_main()


if __name__ == "__main__":
    main()
