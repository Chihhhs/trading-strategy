#!/usr/bin/env python3
"""Run fixed-38 Hyperliquid-aligned simulated execution in an isolated state."""

import os
import sys


CURRENT_DIR = os.path.dirname(__file__)
APPS_DIR = os.path.dirname(CURRENT_DIR)
if APPS_DIR not in sys.path:
    sys.path.insert(0, APPS_DIR)

from _live_bootstrap import load_live_main


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    os.environ["PAPER_PROFILE"] = "execution"
    route = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--research-route=")), None)
    if route is None and "--research-route" in argv:
        index = argv.index("--research-route")
        if index + 1 < len(argv):
            route = argv[index + 1]
    if route is not None:
        # Apply the normal app-side config overrides, then dispatch to the
        # isolated research paper implementation.  Default execution paper
        # remains unchanged when no route flag is provided.
        load_live_main()
        from trading_strategy.live.research_paper import main as research_main

        return research_main(route, argv)
    return load_live_main()()


if __name__ == "__main__":
    main()
