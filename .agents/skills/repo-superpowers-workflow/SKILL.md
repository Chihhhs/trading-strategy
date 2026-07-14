---
name: repo-superpowers-workflow
description: Spec-first, safety-first workflow for this trading strategy repository. Use when Codex needs to shape or execute changes in backtest, paper, live, or strategy-architecture work for this repo, especially when the request is ambiguous, high-risk, or spans multiple modules.
---

# Repo Superpowers Workflow

Use this skill to adapt the Superpowers method to this repository.

## Core loop

1. Classify the task as `backtest`, `paper`, `live`, or `strategy architecture`.
2. Restate the goal as a short spec with:
   - affected workflow
   - expected behavior
   - constraints and safety rules
   - non-goals
3. Identify the canonical entrypoint that exercises the behavior.
4. Write a small implementation plan with concrete files, minimal safe steps, and verification per step.
5. Execute in small increments while preserving TP/SL protection, reconciliation, and event logging.
6. Verify against the original spec before calling the task done.

## Repo rules

- Read `AGENTS.md`, `.agents/current_decisions.md`, `.agents/project_detail.md`, and `.agents/improve_plan.md` before editing.
- Treat exchange state and runtime config as the source of truth. Do not assume persisted state files are authoritative.
- For strategy behavior changes, inspect `src/trading_strategy/strategies/` and the relevant runner or live module before proposing changes.
- For live-trading changes, inspect:
  - `src/trading_strategy/live/cli.py`
  - `src/trading_strategy/live/account.py`
  - `src/trading_strategy/live/engine/`
  - `src/trading_strategy/live/orders.py`
  - `src/trading_strategy/live/config.py`
  - `data/paper_strategies_live/live_state.json`
  - `data/paper_strategies_live/live_trading_records.jsonl`

## Skill routing

- Use `trend-framework-dev` first for strategy-shape and workflow changes.
- Use `crypto-strategy-backtest` for backtest evidence, parameter tradeoffs, and cross-coin comparisons.
- Use `hyperliquid-trading` for Hyperliquid execution, TP/SL behavior, reconciliation, and live safety constraints.
- For cross-boundary work, apply them in this order:
  1. framework design
  2. backtest validation
  3. live trading constraints

## Validation

- Shared logic or strategy changes:
  - `python -m unittest tests.test_live`
  - `python -m compileall src tests`
- Backtest changes:
  - run at least one representative `backtest/backtest_runner.py` command for the touched strategy
- Live execution changes:
  - verify tests and syntax
  - confirm summaries, protection state, and TP/SL behavior still make sense in logs or mocked flows

Read `references/workflow-checklists.md` when you need the canonical entrypoints, safety checklist, or task templates.
