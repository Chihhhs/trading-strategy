# Restructure Notes

## Goals

- Make `src/trading_strategy/` the only reusable code location.
- Keep top-level folders focused on entrypoints, not business logic.
- Remove versioned and research scripts that caused duplicate logic and path confusion.

## Key Decisions

- `src/trading_strategy/` remains a package folder because Python's `src` layout needs a package root.
- The old top-level `strategy/` folder was renamed in role to `apps/` to avoid confusion with the package name.
- `apps/` now contains only thin runners and compatibility wrappers.
- `backtest/` now contains only the canonical runner and one legacy wrapper.

## Canonical Entry Points

```bash
python apps/runners/live_runner.py --live
python apps/runners/paper_runner.py
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240
```

## Reusable Modules

- `src/trading_strategy/core/signals.py`
- `src/trading_strategy/core/risk.py`
- `src/trading_strategy/core/state.py`
- `src/trading_strategy/market_data.py`
- `src/trading_strategy/hyperliquid.py`
- `src/trading_strategy/live.py`
- `src/trading_strategy/paper.py`
- `src/trading_strategy/backtest/`
- `src/trading_strategy/indicators.py`

## Cleanup Performed

- Removed old research/versioned backtest scripts from `backtest/`.
- Removed old helper and monitor scripts from the former `strategy/` area.
- Reduced remaining legacy files to wrappers only.
- Restricted `sys.path.insert(...)` to runner and compatibility entrypoints.

## Validation

- Imported `trading_strategy.core.signals`, `trading_strategy.live`, `trading_strategy.paper`, `trading_strategy.backtest`.
- Ran paper reset through runner and legacy wrapper.
- Ran offline backtest smoke test from local historical JSON.
- Ran live `--report` through the runner to verify wrapper wiring.
