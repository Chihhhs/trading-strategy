# Repository Guidelines

## Project Structure & Module Organization
Core library code lives in `src/trading_strategy/`. Use `core/` for reusable signal, risk, exit, and state logic; use `live/` for Hyperliquid runtime code such as CLI flow, order handling, exchange sync, and persistence. App-style entrypoints live in `apps/`, especially `apps/runners/live_runner.py` and `apps/runners/paper_runner.py`. Backtest scripts live in `backtest/`. Tests are currently concentrated in `tests/test_live.py`. Runtime data and historical fixtures live under `data/`; treat live state files there as generated artifacts, not hand-edited source.

## Build, Test, and Development Commands
Create an environment and install dependencies with `pip install -r requirements.txt`.

- `python -m unittest tests.test_live` runs the current regression suite.
- `python -m compileall src tests` catches syntax and import-level issues quickly.
- `python apps/runners/paper_runner.py` starts paper trading.
- `python apps/runners/live_runner.py --live` runs one live cycle.
- `python apps/runners/live_runner.py --live --loop` runs the live loop.
- `python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240` runs a representative backtest.

## Agent Workflow
Use this repo with a trading-safety-first workflow inspired by `obra/superpowers`: clarify the real goal first, turn it into a concrete spec, write a small implementation plan, then execute and verify in tight loops. Before editing code, read `AGENTS.md`, `.agents/project_detail.md`, and `.agents/improve_plan.md` to understand the current live runtime, recent fixes, and known risk areas. When the task touches strategy behavior, also inspect `src/trading_strategy/strategies/` and the relevant runner or live module before proposing changes.

Follow this execution order:

1. Classify the task as `backtest`, `paper`, `live`, or `strategy architecture`.
2. Restate the goal as a short spec: affected workflow, expected behavior, constraints, and non-goals.
3. Identify the canonical entrypoint that exercises the affected behavior.
4. Write a small plan with concrete files, smallest safe steps, and verification per step.
5. Prefer the exchange state and runtime config as truth; do not assume persisted state files are authoritative.
6. Implement in small increments, keeping TP/SL protection, reconciliation, and event logging intact.
7. Review the result against the original spec before considering the task done.

When a task is ambiguous, spend effort refining the spec before changing code. When a task is high risk, prefer narrower changes, explicit assumptions, and validation checkpoints over speed.

For live-trading changes, inspect these paths first:

- `src/trading_strategy/live/cli.py`
- `src/trading_strategy/live/account.py`
- `src/trading_strategy/live/engine/`
- `src/trading_strategy/live/orders.py`
- `src/trading_strategy/live/config.py`
- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`

Validation expectations:

- Spec and plan quality matter. Avoid jumping straight to code when requirements, market assumptions, or safety constraints are still fuzzy.
- Strategy or shared-logic changes: run `python -m unittest tests.test_live` and `python -m compileall src tests`.
- Backtest changes: run at least one representative `backtest/backtest_runner.py` command for the touched strategy.
- Live execution changes: verify tests, confirm syntax, and check that run summaries, protection status, and TP/SL behavior still make sense in logs or mocked flows.

## Superpower Skills
This repo includes custom skills under `.agents/skills/`. Treat them as force multipliers and proactively use them when the task matches. The goal is not only better answers, but a repeatable development method: spec first, plan second, targeted skill use during execution, and review before completion.

- `crypto-strategy-backtest`: Use for strategy research, parameter tuning, cross-coin comparison, backtest interpretation, and performance tradeoff analysis.
- `hyperliquid-trading`: Use for Hyperliquid perp workflow, TP/SL logic, market structure questions, live position handling, and exchange-specific constraints.
- `trend-framework-dev`: Use for end-to-end trend framework development, strategy wiring, market regime rules, coin selection, and backtest-to-live SOP decisions.

Skill selection rules:

- If the user asks about backtest results, optimization, or strategy comparison, start with `crypto-strategy-backtest`.
- If the task involves live orders, exchange sync, protection orders, or Hyperliquid behavior, start with `hyperliquid-trading`.
- If the task spans architecture decisions from signal generation through deployment workflow, start with `trend-framework-dev`.
- When a task crosses boundaries, combine skills in this order: framework design → backtest validation → live trading constraints.

Suggested activation flow:

1. Use `trend-framework-dev` to shape the spec when the task changes strategy behavior or repo workflow.
2. Use `crypto-strategy-backtest` to validate assumptions with historical evidence before promoting an idea.
3. Use `hyperliquid-trading` to pressure-test live execution details, protection orders, exchange semantics, and operational risk.
4. Finish by checking that the final code and verification still match the approved spec and do not weaken live safety controls.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for functions and variables, `UPPER_SNAKE_CASE` for module constants, and short, focused helper functions. Keep modules narrow in responsibility; live-trading exchange calls belong in `live/`, not `core/`. Match the repository preference for plain standard-library testing and minimal abstraction. There is no dedicated formatter config in the repo, so keep edits consistent with surrounding code.

## Testing Guidelines
Add or update `unittest` coverage for behavior changes, especially in `tests/test_live.py` when touching live execution, reconciliation, TP/SL protection, or order normalization. Name new tests `test_<behavior>`. Prefer mocks over network calls and verify emitted summaries or state mutations, not just happy-path returns.

## Commit & Pull Request Guidelines
Recent commits use short imperative subjects such as `Refactor live runtime into package` and `Fix live position adoption and TP/SL protection`. Keep commit titles concise, capitalized, and action-oriented. PRs should describe the trading workflow affected, list validation steps you ran, and call out any `.env`, exchange, or state-file impacts. Include sample commands or logs when changing live-run behavior.

## Security & Configuration Tips
Copy `.env-template` to `.env` and keep secrets out of commits. Never hardcode API credentials or commit generated files such as live logs, debug logs, or local state snapshots from `data/`.
