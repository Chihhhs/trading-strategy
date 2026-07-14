---
name: hyperliquid-trading
description: Hyperliquid live and paper trading workflow for this repository. Use for exchange sync, live positions, TP/SL protection, order verification, and operational risk.
---

# Hyperliquid Trading

Use this skill when the task touches Hyperliquid, live orders, exchange sync, TP/SL protection, position adoption, live state, or live operational risk.

Read first:

- `.agents/current_decisions.md`
- `.agents/project_detail.md`
- `.agents/improve_plan.md`

## Current Safety Stance

- Exchange positions and open orders are live truth.
- Runtime config is strategy truth.
- Local live state is cache and audit context.
- Unknown protection is not protected.
- Ambiguous protection must not be canceled or replaced automatically.
- Missing, ambiguous, or verification-unknown protection blocks new entries.
- Research results do not authorize live config changes.

## Live Files To Inspect

- `src/trading_strategy/live/cli.py`
- `src/trading_strategy/live/account.py`
- `src/trading_strategy/live/engine/`
- `src/trading_strategy/live/orders.py`
- `src/trading_strategy/live/config.py`
- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`

## Hyperliquid Notes

- `allMids` prices are strings and must be converted before numeric comparison.
- Perp balance, not spot balance, controls live trading eligibility.
- `openOrders` can include order types that require careful classification.
- Reduce-only TP/SL identity should use order id when available, plus coin, reduce-only flag, TP/SL type, and trigger price fallback.
- Trigger price normalization and tick size handling must be logged when placing or repairing orders.
- Rate limits and transient API failures should be treated as verification uncertainty, not as permission to trade.

## Protection Workflow

When reconciling protection:

1. Read exchange positions.
2. Read exchange open orders.
3. Match existing protection conservatively.
4. Mark ambiguous or unknown matches explicitly.
5. Repair only clearly missing protection.
6. Do not cancel ambiguous orders automatically.
7. Block new entries until protection is verified.
8. Emit enough event data to reconstruct the decision.

Expected statuses:

- `protected`
- `missing_sl`
- `missing_tpsl`
- `repair_failed`
- `update_failed`
- `ambiguous_protection`
- `verification_unknown`

## Event Evidence

Relevant live events include:

- `run_started`
- `account_snapshot`
- `config_mismatch`
- `position_adopted`
- `state_exchange_mismatch`
- `entry_skipped`
- `entry_order_attempted`
- `entry_order_rejected`
- `entry_order_not_filled`
- `tpsl_missing_detected`
- `tpsl_repair_attempted`
- `tpsl_repair_failed`
- `tpsl_repaired`
- `run_summary`

Protection events should include:

- match source
- match confidence
- verify status
- failure reason
- requested and normalized trigger prices
- order side
- tick size
- exchange message when available

## Canonical Commands

Regression checks:

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

Live one-cycle:

```bash
python apps/runners/live_runner.py --live
```

Live loop:

```bash
python apps/runners/live_runner.py --live --loop
```

Paper runner:

```bash
python apps/runners/paper_runner.py
```

## Promotion Boundary

Do not treat a strategy research result as a live instruction. Live promotion must separately confirm:

- protection matching and verification
- entry safety gate
- run summary fields
- exchange account mode and perp balance
- state directory separation
- manual approval
