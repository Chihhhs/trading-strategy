# Improve Plan For Agents

Last updated: 2026-07-15

This is the active roadmap. Historical results belong in `docs/research_manual/`; this file should stay short enough that future agents can use it as working guidance.

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

## P0: Protection Reliability

Objective: make live entry safety depend on verified protection, not optimistic matching.

Required behavior:

- Match protection orders by stronger identity: order id when available, coin, reduce-only, TP/SL type, and trigger price fallback.
- Represent protection status explicitly: `protected`, `missing_sl`, `missing_tpsl`, `repair_failed`, `update_failed`, `ambiguous_protection`, `verification_unknown`.
- Treat unknown and ambiguous as not protected.
- Never auto-cancel or auto-replace ambiguous protection orders.
- Block new entries when any open position has unverified or missing protection.
- Emit match source, confidence, verify status, failure reason, repair result, and replace result.

Implementation areas:

- `src/trading_strategy/live/engine/protection.py`
- `src/trading_strategy/live/orders.py`
- `src/trading_strategy/live/engine/`
- `src/trading_strategy/live/cli.py`
- `tests/test_live.py`

Verification:

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

Acceptance:

- Unknown or ambiguous protection is not deleted.
- Unverified protection blocks new entry.
- Repair and replace failures can be reconstructed from event logs.
- `run_summary` exposes protection counts and statuses.

## P0: Run Summary Observability

Objective: one run summary should explain why live did or did not trade.

Required summary fields:

- strategy and parameter fingerprint
- timeframe and universe
- signals observed
- entries attempted, filled, rejected
- blocker counts
- positions count
- protection status
- turnover when available
- fee and slippage assumptions when available
- exit reason counts
- MFE/MAE when available
- drawdown when available

Acceptance:

- Entry skips and rejections have counted reasons.
- Protection status is visible without reading raw state.
- Summary separates live state truth from research report fields.

## P1: `optimize_existing_trend`

Objective: find whether the current live Trend strategy still has a valid live-like edge after realistic execution.

Current decision:

- Current trend wiring is executable but not validated live alpha.
- Canonical baseline is daily trend decisions plus causal 1h hard-SL execution and MTM drawdown.
- The frozen baseline must snapshot `src/trading_strategy/live/config.py` plus `apps/live_config.py` overrides; short-cycle or generic daily baselines are diagnostic only.
- Stop-stage, ATR trail, close-confirmed stop, and failure-exit tuning should not be the next priority without new evidence.

Allowed research:

- Entry quality filters.
- BTC regime gating.
- Universe selection and coin exclusion.
- Funding/basis/OI as blocker or confidence modifier, not as standalone alpha.

Required gate:

- Same windows, costs, universe, and live-like execution profile.
- Improve net PnL and drawdown versus canonical baseline.
- Avoid single-coin or single-window concentration.

Current research candidate:

- `market_context_enabled` filters only new trend entries; it does not change signal generation, sizing, or protection.
- `momentum_decay_time_limit_enabled` may set one earlier exit deadline when trend direction remains intact but momentum and ADX decay; it must not modify staged SL or ATR trailing.
- Rebase entry-only, time-limit-only, and combined manifests on the frozen live-like baseline before comparing them.
- A passing backtest enters no-trade shadow mode first; it records candidate versus baseline decisions before any bounded paper review.

## P1: `new_alpha_research` — Short-Cycle Measurement And Turnover

Objective: diagnose and reduce intraday churn only if an OOS edge survives costs.

Current decision:

- `intraday_momentum` is rejected for paper/live.
- It remains a negative control and wiring baseline.
- Its 15m results must never be used to judge an `optimize_existing_trend` candidate.
- Turnover reduction is research-only until absolute net performance and OOS gates pass.

Phase 0 measurement fixes:

- Store `initial_risk` for intraday positions.
- Report MFE/MAE R and best-close R.
- Record entry components, not only aggregate score.
- Record re-entry gap, direction, UTC session, ATR/range context, volatility context, and BTC regime.
- Mark no-op candidates when filters do not change the event set.
- Clarify `max_days=8640` bar semantics or add an explicit `max_bars`.

Phase 1 frozen baselines:

- BTC-only, BTC/ETH/BNB, BTC/ETH/SOL/BNB.
- first/middle/last 30-day, rolling 30-day, train60/test30.
- zero-cost and `fee_bps=4.5`, `slippage_bps=2` per side.
- close-fill and live-like intrabar profiles.
- same fixture, universe, random baseline, and minimum event count.

Phase 2 one-factor ablation:

- Refractory period `0/4/8/12/16/24` bars.
- Long-only and short-only.
- Asymmetric long/short thresholds.
- Volume confirmation on/off.
- Breakout, EMA, momentum, and volume component removals.
- Session buckets with frozen rules before OOS.

Promotion boundary:

- Passing research gates permits bounded paper observation only.
- Live requires separate fill, slippage, L2 adverse-selection, and safety review.

## P1: `new_alpha_research` — Alternative Short-Cycle Alpha

Current decision:

- Breakout continuation is a rejected/deprioritized control.
- Volatility expansion is a rejected/deprioritized control.
- VWAP reversion is the only current short-cycle research candidate, and only because recent 12/24-bar windows improved while older windows failed.

Next research:

- VWAP reversion with regime and session conditioning.
- L2 spread, depth, order-flow imbalance, and adverse-selection data if replayable.
- Event-time regime exclusions for FOMC, jumps, and liquidation cascades.

## P2: `new_alpha_research` — Funding, Basis, OI, And L2

Current decision:

- Carry/funding/basis is not viable as standalone execution after realistic two-leg costs.
- Funding/basis/OI may be useful as trend context, blocker, or exposure reducer.
- L2 microstructure guard is observe-only.

Next work:

- Improve OI and venue-specific funding/basis coverage.
- Test context as a blocker/confidence modifier in trend research.
- Keep live disabled until OOS and paper evidence exist.

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
