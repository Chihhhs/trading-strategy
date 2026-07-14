# Workflow Checklists

## Task spec template

Write the spec in four lines:

- Workflow: `backtest`, `paper`, `live`, or `strategy architecture`
- Behavior: what should change
- Constraints: trading-safety, runtime, and repo-specific limits
- Non-goals: what must not change

## Canonical entrypoints

- `python apps/runners/live_runner.py --live`
- `python apps/runners/live_runner.py --live --loop`
- `python apps/runners/paper_runner.py`
- `python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240`

## File-first inspection map

### Live

- `src/trading_strategy/live/cli.py`
- `src/trading_strategy/live/account.py`
- `src/trading_strategy/live/engine/`
- `src/trading_strategy/live/orders.py`
- `src/trading_strategy/live/config.py`
- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`

### Strategy behavior

- `src/trading_strategy/strategies/`
- relevant runner under `apps/runners/`
- touched shared logic in `src/trading_strategy/core/`

### Backtest

- `backtest/backtest_runner.py`
- strategy implementation under `src/trading_strategy/strategies/`
- experiment manifests under `experiments/` if promotion flow is involved

## Safety checklist

- Preserve TP/SL protection logic.
- Preserve reconciliation and position adoption behavior.
- Preserve structured event logging and `run_summary` semantics.
- Prefer narrower changes when live behavior is involved.
- Use runtime config and exchange state as truth over persisted snapshots.

## Verification checklist

### Shared logic or strategy change

- `python -m unittest tests.test_live`
- `python -m compileall src tests`

### Backtest change

- Run one representative backtest command for the touched strategy.
- Check whether the result still matches the intended workflow and constraints.

### Live execution change

- Run tests and syntax checks.
- Inspect emitted summaries or mocked logs for TP/SL protection, blockers, and reconciliation behavior.

## Suggested task plan shape

1. Inspect current entrypoint and touched modules.
2. Make the smallest safe change that satisfies the spec.
3. Add or update tests close to the behavior change.
4. Run the matching verification commands.
5. Compare the result to the original spec before finishing.
