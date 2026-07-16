# Improve Plan For Agents

Last updated: 2026-07-16

This is the active execution queue. Historical results and detailed research backlogs belong in `docs/research_manual/` and `.agents/current_decisions.md`.

## Current Spec

Task class: strategy architecture, with live-safety documentation impact.

Goal:

- Keep live runtime safety first.
- Make current research decisions unambiguous for agents.
- Separate `optimize_existing_trend` from `new_alpha_research`.
- Prevent stale strategy evidence from being treated as live promotion authority.

Mode authority: `.agents/research_modes.md` defines baseline ownership and promotion paths. Protection reliability, execution, and observability remain shared live-safety work rather than a strategy-research mode.

Non-goals:

- Do not change live strategy config.
- Do not change TP/SL, signal, or exit policy in this documentation task.
- Do not promote `intraday_momentum`, funding/basis, or trend variants to paper/live.

## P0: Complete, Operationally Verified

Protection reliability and run-summary observability are implemented.

- Unknown, ambiguous, missing, or unverified protection blocks new entry.
- Protection repair/verification outcomes and entry blockers are recoverable from events and position snapshots.
- Run summaries include strategy fingerprint, universe, costs, protection statuses, blocker counts, turnover, exit reasons, MFE/MAE, and drawdown when available.

Before any paper or live operation, run the live regression suite and inspect the resulting runtime evidence. Do not open a new P0 implementation task unless a failing test or runtime record identifies a concrete safety gap.

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

## P1: Complete, Observe-Only Decision Record

- `live.decision.Decision` records allowed/action, ordered reason codes, signal
  context, BTC regime, Market Context, and safety blockers.
- `decision_observed` events and schema-v3 run summaries record skips, order
  attempts, order outcomes, protection failures, and opened positions after a
  signal exists.
- Market Context records a hypothetical allow/block result only. It does not
  gate entries or alter order, TP/SL, protection, sizing, or configuration.
- Tests cover warmup annotation, combined blockers, summary aggregation, and
  proof that observe-only recording does not place an order.

Normal paper/live runs now collect evidence for future research hypotheses.
Activation remains subject to the canonical live-like trend gate and a separate
live-safety review.

Paper market data may be cached while online and replayed only when an online
fetch fails. This permits pending observation horizons to resolve from already
captured bars during offline operation; it cannot create a new bar, use a
cached price for an entry, or affect live mode.

Universe contract (2026-07-16): `apps/live_config.py` fixes live entry
scanning to 38 coins: the 20 still-active members of the historical reference
plus 18 currently active Hyperliquid perps selected from the market-cap
ranking. Paper loads every active Hyperliquid perp from `meta` for broader data collection.
Paper and live prefer Hyperliquid K-lines and prices.
contract. Binance USDⓈ-M Futures is an explicit per-coin fallback only when
Hyperliquid market data is unavailable; its cache is source-tagged. Data coverage does not make a coin executable on Hyperliquid;
the exchange eligibility gate remains required before any order attempt.
Live unit tests write any unmocked event records only to an OS temporary
directory, never to `data/trade_history`.
Paper permits 10 concurrent simulated positions to maintain observation
coverage; the live cap remains 2.

## Complete: Module Cleanup

- Removed obsolete versioned and app compatibility wrappers.
- Removed `core` re-export modules after moving every internal caller to
  `shared/`, `strategies/`, or `positions/`.
- Kept canonical runners, persisted schemas, and the public `legacy_unified`
  negative-control strategy unchanged under `strategies/`.
- Validated with the full test suite, syntax checks, a canonical trend
  backtest, and `git diff --check`.

## Deferred Research

- Trend: the canonical 50-coin causal replay baseline failed its cost-adjusted performance and drawdown gate. No candidate exists until a new pre-defined entry, BTC-regime, or universe hypothesis is supported by attribution.
- Short-cycle alpha: `intraday_momentum` remains a negative control; VWAP is research-only. Follow the frozen OOS and random-baseline process in `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md`.
- Funding, basis, OI, and L2 remain context or observe-only inputs. See `.agents/current_decisions.md` for their evidence and constraints.

## Do Not Revisit Without New Evidence

- Live `intraday_momentum` override.
- Simple cooldown-only intraday promotion.
- Breakout continuation as primary short-cycle alpha.
- Volatility expansion as primary short-cycle alpha.
- Adaptive ATR trail promotion.
- Close-confirmed stop promotion.
- Intrabar stop-first as an intraday improvement.
- Standalone funding/basis carry execution.

## Validation Checklist

For documentation-only `.agents` updates:

```bash
git diff --check
rg "~/.hermes|unified_framework|FVG|STRATEGY_OVERRIDES|intraday_momentum.*live" .agents
```

For code or behavior updates:

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

For backtest changes:

```bash
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240
```

For short-cycle research:

```bash
python backtest/backtest_runner.py --short-cycle-alpha-report --coins BTC,ETH,SOL,BNB --data-path data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json --max-days 8640 --fee-bps 4.5 --slippage-bps 2 --bucket-count 5 --random-baseline-runs 50 --short-cycle-splits rolling_30,train60_test30 --short-cycle-min-events 100 --short-cycle-focus-alpha intraday_vwap_reversion
```
