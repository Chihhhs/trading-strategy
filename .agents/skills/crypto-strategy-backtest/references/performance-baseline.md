# Archived Performance Baseline

Last updated: 2026-07-14

This reference replaces the older 2026-06-25 performance table. Do not use older high-PnL historical tables or unified-framework claims as current evidence for this repository.

Current authority:

- `.agents/current_decisions.md`
- `.agents/project_detail.md`
- `.agents/improve_plan.md`
- `docs/research_manual/01_quant_research_map.md`
- `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md`

## Current Decisions

- Trend is executable but has not passed the canonical live-like baseline gate.
- Intraday momentum is rejected for paper/live and remains only a wiring baseline.
- Short-cycle turnover reduction is research-only unless absolute OOS net performance survives realistic costs.
- VWAP reversion is a research candidate only.
- Funding/basis/carry is monitor and research context only.

## Standard Comparison Requirements

Use the same:

- fixture
- universe
- timeframe
- fee and slippage
- execution profile
- train/test split
- random baseline settings
- minimum event count

Default costs:

- `fee_bps=4.5`
- `slippage_bps=2`

## Canonical Evidence Pointers

- Short-cycle diagnosis: `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md`
- Carry/funding/basis status: `docs/research_manual/07_carry_funding_basis_backtest.md`
- Current research map: `docs/research_manual/01_quant_research_map.md`

Older high-PnL historical tables are archived hypotheses, not promotion evidence.
