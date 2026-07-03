# Rebuild Context

## Naming

- `src/trading_strategy/` is the canonical Python package.
- `apps/` is the top-level entrypoint directory.
- `backtest/` only hosts runner entrypoints and legacy wrapper compatibility.

## Architecture Rules

- Reusable logic belongs only in `src/trading_strategy/`.
- `src` code uses absolute imports only.
- `sys.path.insert(...)` is allowed only in top-level runners or compatibility wrappers.
- Do not reintroduce reusable helpers into `apps/` or `backtest/`.

## Canonical Entry Commands

```bash
python apps/runners/live_runner.py --live
python apps/runners/paper_runner.py
python backtest/backtest_runner.py --coins BTC,ETH --strategy both --max-days 240
```

## Legacy Compatibility

- `apps/fvg_live_strategy.py` wraps `trading_strategy.live`.
- `apps/fvg_paper_trader.py` wraps `trading_strategy.paper`.
- `backtest/backtest_v6.py` wraps `trading_strategy.backtest`.

## Important Constraint

- If future refactors add modules, place them under `src/trading_strategy/` first, then expose them through runners only if needed.
