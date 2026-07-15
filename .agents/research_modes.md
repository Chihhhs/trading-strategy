# Research Modes And Strategy Promotion

Last updated: 2026-07-15

This document defines the two permitted strategy-research modes. It is the detailed companion to `.agents/current_decisions.md`; the current decision register remains the routing authority.

## Shared Safety Rules

Protection, order execution, reconciliation, and logging are shared live-safety concerns, not a third research mode. Research evidence never changes live configuration automatically. Exchange positions and open orders remain the live truth.

## `optimize_existing_trend`

Purpose: improve the currently executable daily Trend strategy without replacing its alpha source.

Allowed changes:

- Trend entry-quality filters, BTC regime gating, universe selection, and existing context blockers.
- Market Context entry filtering and Momentum-Decay Time Limit.
- Research-only position-control changes supported by a separate decision and evidence.

Required baseline: a frozen `live_like_trend_baseline` snapshot built from `src/trading_strategy/live/config.py` plus `apps/live_config.py` overrides. It must use daily decisions, BTC/ETH/BNB, the active leverage, risk, max-position, and derivatives settings, 4.5 bps fee, 2 bps slippage, causal 1h hard-SL replay, and mark-to-market drawdown.

`experiments/live_trend_baseline.json` is an historical research manifest. It is not the live runtime, and it is not the promotion authority until the frozen live-like baseline and replay adapter exist.

Promotion path:

```text
live-like backtest
-> frozen window and universe gate
-> shadow mode
-> bounded paper
-> explicit live review
```

Shadow mode may consume real market data, but it records only baseline and candidate signals, block reasons, intended actions, and their differences. It must not submit orders or alter TP/SL protection.

Backtest success permits shadow mode only. Shadow success permits bounded paper only. A live configuration change always requires an explicit manual review of fills, slippage, protection, state separation, and observability.

## `new_alpha_research`

Purpose: discover and measure alpha that is not a modification of the current Trend strategy.

In scope:

- Intraday momentum, VWAP reversion, funding/basis, order flow, and L2/microstructure.

Each candidate owns a baseline compatible with its frequency, fixture, execution model, costs, OOS split, and minimum event count. A 15-minute result must not use the live Trend baseline for performance comparison or promotion.

Current status:

- `intraday_momentum` is a rejected wiring baseline and negative control.
- VWAP reversion is a research candidate only.
- Funding/basis, order flow, and L2 remain research or observe-only until their own evidence is sufficient.

Promotion path:

```text
research report
-> OOS, random-baseline, and cost gate
-> bounded paper review
-> separate strategy approval
```

A candidate cannot progress merely because it loses less than a negative baseline. It needs adequate event count, acceptable absolute cost-adjusted performance, non-worsening drawdown, and no single-coin, session, or window concentration.

## Baseline Ownership

| Candidate type | Mode | Required comparison |
| --- | --- | --- |
| Market Context / Momentum-Decay | `optimize_existing_trend` | Frozen live-like Trend baseline only |
| BTC regime / universe / entry filters | `optimize_existing_trend` | Frozen live-like Trend baseline only |
| 15m momentum / VWAP | `new_alpha_research` | Matching short-cycle frozen baseline and random controls |
| Funding, basis, order flow, L2 | `new_alpha_research` | Candidate-specific replay or observation baseline |

## Next Infrastructure Work

The next implementation task is to create `live_like_trend_baseline` and an experiment adapter that applies causal 1h replay and MTM drawdown. Only then may the Market Context baseline and its entry-only, time-limit-only, and combined candidates be re-run for promotion evidence.
