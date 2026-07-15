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

Required evidence order for a new Trend entry filter: raw 50-coin attribution -> fixed walk-forward consistency -> one pre-defined hypothesis -> 50-coin causal 1h replay -> shadow. Attribution labels completed 1/3/5/10-day forward returns after 13 bps round-trip cost, is diagnostic-only, and never changes runtime eligibility.

Declared live universe: 50 coins, represented by `experiments/live_trend_baseline.json`. It uses daily decisions, the active leverage, risk, max-position, and derivatives settings, 4.5 bps fee, and 2 bps slippage.

The checked-in `apps/live_config.py` currently narrows the launcher to BTC/ETH/BNB, while the declared live universe and existing live cache show broad-universe operation. This is a configuration-drift finding, not permission to change live config. Runtime intent must be reconciled in a dedicated live-safety task.

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

## Current Trend Candidate Status

The Market Context entry-only, Momentum-Decay time-limit-only, and combined manifests now compare with the declared 50-coin baseline as diagnostics. Their promotion gates are intentionally impossible to satisfy until a full 50-coin causal 1h replay fixture exists.

The former BTC/ETH/BNB replay result is invalidated because it used the wrong universe. It must not be used to reject or promote the candidate.
