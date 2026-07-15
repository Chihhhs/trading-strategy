# Restructure Notes

## Goals

- Make `src/trading_strategy/` the only reusable code location.
- Keep top-level folders focused on entrypoints, not business logic.
- Remove versioned and research scripts that caused duplicate logic and path confusion.

## Key Decisions

- `src/trading_strategy/` remains a package folder because Python's `src` layout needs a package root.
- The old top-level `strategy/` folder was renamed in role to `apps/` to avoid confusion with the package name.
- `apps/` now contains only thin runners, bootstrap glue, and compatibility wrappers.
- `backtest/` now contains only the canonical runner and one legacy wrapper.

## Canonical Entry Points

```bash
python apps/runners/live_runner.py --live
python apps/runners/paper_runner.py
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240
```

## App Imports

- `apps/runners/live_runner.py` does not implement trading logic itself; it bootstraps `trading_strategy.live.main`.
- `apps/runners/paper_runner.py` imports `trading_strategy.paper.main`.
- `apps/fvg_paper_trader.py` is a compatibility wrapper around `trading_strategy.paper.main`.
- `apps/hyperliquid_api.py` is a compatibility wrapper around `trading_strategy.hyperliquid`.
- `apps/live_config.py` remains an app-side override file and mutates `trading_strategy.live.config`.
  Its `LIVE_UNIVERSE` is the fixed 38-coin runtime entry contract (frozen
  2026-07-16); it is not a daily market-cap refresh and must be changed only
  through an explicit live-universe review.

In other words: `apps/` still imports from `src/trading_strategy/`, but it should stay thin and not become the home for reusable business logic.

## Reusable Modules

Current reusable module layout:

- `src/trading_strategy/shared/`
  - generic reusable helpers
  - `risk.py`
  - `state.py`
  - `trade_history.py`
- `src/trading_strategy/strategies/`
  - strategy registry and shared strategy interface
  - trend strategy implementation
- `src/trading_strategy/positions/`
  - position lifecycle snapshots / status
  - trend stop, trailing, and failure helpers
- `src/trading_strategy/backtest/`
  - reusable backtest package
- `src/trading_strategy/experiments/`
  - typed experiment specs, JSON manifest validation, result and promotion contracts
  - adapters translate one validated spec into backtest or approval-gated paper execution
  - research artifacts, isolated paper candidate sessions, and manual-only live-review bundles
- `src/trading_strategy/live/`
  - live runtime package
  - append-only Hyperliquid L2 observations; these remain observe-only research evidence
  - paper-mode K-line cache: online fetches merge timestamped bars locally;
    an offline paper run may replay only those cached bars to resolve pending
    observations. Live never falls back to cached market data.
  - paper market reads prefer Hyperliquid. If a coin lacks Hyperliquid price
    or K-lines, paper alone may use the Binance USDⓈ-M Futures fallback and
    tags that coin's cache with the actual source; live never does this.
- `src/trading_strategy/live/decision.py`
  - pure, reason-coded entry-decision records and Market Context annotations
  - observe-only: it must not gate orders, sizing, TP/SL, or protection
- `src/trading_strategy/market_data.py`
- `src/trading_strategy/market_context.py`
- `src/trading_strategy/hyperliquid.py`
- `src/trading_strategy/indicators.py`

## Compatibility Layer

- `src/trading_strategy/core/` is now transitional.
- Existing imports such as `trading_strategy.core.risk` and `trading_strategy.core.signals` still work.
- New reusable code should go into `shared/`, `strategies/`, or `positions/` instead of `core/`.
- Experiment orchestration belongs in `experiments/`; strategy-specific parameters belong beside strategy definitions, never in `core/`.
- `paper.py` still uses some `core/*` imports today, but those modules now re-export from the new locations.
- `market_context.py` is a research-only, causal classifier used by the backtest trend wrapper; it must not alter live behavior without a separate review.

## Cleanup Performed

- Removed old research/versioned backtest scripts from `backtest/`.
- Removed old helper and monitor scripts from the former `strategy/` area.
- Reduced remaining legacy files to wrappers only.
- Restricted `sys.path.insert(...)` to runner and compatibility entrypoints.

## Validation

- Imported `trading_strategy.shared`, `trading_strategy.strategies`, `trading_strategy.positions`, `trading_strategy.live`, `trading_strategy.paper`, `trading_strategy.backtest`.
- Ran paper reset through runner and legacy wrapper.
- Ran offline backtest smoke test from local historical JSON.
- Ran live `--report` through the runner to verify wrapper wiring.

## Experiment Dependency Direction

`runner -> experiments -> strategies/backtest/paper` is the allowed direction. Strategies do not import experiment runners, and live does not consume research manifests. `StrategyDefinition` describes a strategy's typed parameters and capabilities; `ExperimentSpec` is the research/paper setting truth; adapters are the only layer that translates it into environment-specific configuration.

Canonical experiment commands and promotion semantics are documented in `docs/experiment_workflow.md`.
