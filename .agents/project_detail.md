# Project Detail For Agents

Last updated: 2026-07-15

This file is the concise current map for agents working in this repository. For current decisions, read `.agents/current_decisions.md` first. For historical evidence, use `docs/research_manual/`.

## Mission Context

This repository builds and validates crypto trading workflows with a safety-first path from research to paper to live. The software must make trading decisions explainable, reproducible, and auditable before any promotion.

Current stance:

- Live runtime safety and observability have priority over alpha experiments.
- Protection reliability and `run_summary` quality are P0.
- Current trend logic is executable, but it has not passed the canonical live-like baseline gate.
- `intraday_momentum` is rejected for paper/live and remains only a research wiring baseline.
- Funding, basis, OI, and L2 data are research and monitoring inputs, not validated live alpha.

## Source Of Truth

- Exchange positions and exchange open orders are live truth.
- Runtime config is strategy truth.
- Local state files under `data/` are generated cache and audit context.
- Research reports are evidence, not state.
- Paper state and live state must stay separated.
- Paper K-line cache is research evidence only: it can replay previously fetched
  bars to resolve pending observations offline, but must never be used as a
  live price, live market-data fallback, or exchange-truth substitute.

Do not:

- Treat `live_state.json.params` as active runtime intent.
- Promote research manifests into live config without an explicit live review.
- Assume unknown or ambiguous protection means protected.
- Cancel or replace ambiguous protection orders automatically.

## Repository Map

- `src/trading_strategy/core/`: reusable signal, risk, exit, and state logic.
- `src/trading_strategy/strategies/`: strategy registry and strategy hooks.
- `src/trading_strategy/live/`: Hyperliquid live runtime, CLI flow, exchange sync, orders, protection, persistence.
- `src/trading_strategy/experiments/`: typed experiment manifests, adapters, results, and promotion decisions.
- `apps/runners/live_runner.py`: live runner entrypoint.
- `apps/runners/paper_runner.py`: paper runner entrypoint.
- `backtest/backtest_runner.py`: research and backtest CLI.
- `docs/research_manual/`: research evidence, decision framework, and current diagnosis docs.
- `.agents/`: agent-facing current state, plans, and repo skills.

## Live Runtime Flow

Canonical live entrypoint:

```bash
python apps/runners/live_runner.py --live
```

High-level `run_once()` order:

1. Load local state.
2. Sync state with Hyperliquid balance and positions.
3. Check live perp balance.
4. Log config mismatch if state and runtime disagree.
5. Ensure open position protection.
6. Load universe and current prices.
7. Update positions.
8. Evaluate exits and protection.
9. Check entries only after safety gates.
10. Emit `run_summary`.

Live safety invariants:

- Perp account value, not spot value, controls live eligibility.
- Existing exchange positions can be adopted, but must be marked with source metadata.
- Missing, unknown, or ambiguous protection blocks new entry.
- Repair or replace failures must be visible in event logs.
- Protection state must be summarized per run.

Primary live files:

- `src/trading_strategy/live/cli.py`
- `src/trading_strategy/live/account.py`
- `src/trading_strategy/live/engine/`
- `src/trading_strategy/live/orders.py`
- `src/trading_strategy/live/config.py`
- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`

## Current Strategy State

Research modes are defined in `.agents/research_modes.md`. `optimize_existing_trend` is the only mode that may progress toward the current Trend live configuration; `new_alpha_research` has independent baselines and approval.

Trend:

- Capability exists in backtest, paper, and live wiring.
- Current canonical live-like baseline is not good enough for live alpha promotion.
- The declared live universe is the 50-coin `experiments/live_trend_baseline.json` reference. The checked-in launcher override currently specifies BTC/ETH/BNB, which conflicts with that declaration and broad-universe live cache evidence; do not treat either as promotion authority until a live-safety review reconciles them.
- Next research should target entry quality, BTC regime, and universe selection.
- Stop-stage, ATR trail, close-confirmed stop, and failure-exit tuning are not the priority unless new evidence changes the baseline.

Intraday:

- `intraday_momentum` is rejected for paper/live.
- The problem is not only turnover. Raw edge is weak or negative, and current costs are about 13 bps round trip.
- Short-cycle work should collect trade diagnostics, build frozen comparisons, and keep candidates research-only until OOS gates pass.
- Do not add a live `STRATEGY_OVERRIDES` snippet for `intraday_momentum`.

Relative value and derivatives context:

- Carry/funding/basis execution is research-only; current two-leg costs erase the standalone edge.
- Funding/basis/OI may be useful as context, blocker, or confidence modifier, but this is not validated live alpha.
- L2 and microstructure data are observe-only until replay evidence proves value.

## Canonical Commands

Regression checks:

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

Live and paper:

```bash
python apps/runners/live_runner.py --live
python apps/runners/live_runner.py --live --loop
python apps/runners/paper_runner.py
```

Representative trend backtest:

```bash
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240
```

Experiment workflow:

```bash
python backtest/backtest_runner.py run --experiment experiments/trend_baseline.json
python backtest/backtest_runner.py compare --experiments experiments/trend_baseline.json experiments/intraday_momentum_rejected.json
python backtest/backtest_runner.py promote --experiment experiments/trend_paper_candidate.json
python apps/runners/paper_runner.py --experiment experiments/trend_paper_candidate.json --approval-result /tmp/trend_promotion.json
```

Short-cycle research:

```bash
python backtest/backtest_runner.py --short-cycle-alpha-report --coins BTC,ETH,SOL,BNB --data-path data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json --max-days 8640 --fee-bps 4.5 --slippage-bps 2 --bucket-count 5 --random-baseline-runs 50 --short-cycle-splits rolling_30,train60_test30 --short-cycle-min-events 100 --short-cycle-focus-alpha intraday_vwap_reversion
```

Trend live-like replay research:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --derivatives-data-path data/derivatives/bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json --enable-trend-position-control --enable-atr-trailing --fee-bps 4.5 --slippage-bps 2 --trend-exit-replay-report --exit-replay-data-path data/historical_prices/binance_1h_240d_BTC_ETH_BNB.json
```

## Event And Summary Fields To Preserve

Live event logs should make these recoverable:

- account snapshot and balance source
- config mismatch
- exchange position adoption
- state/exchange mismatch
- entry skipped, attempted, rejected, not filled
- protection match source and confidence
- protection verification status
- missing TP/SL detection
- repair or replace attempt and result
- failure reason and raw exchange message when available
- run summary

Shared research/live summaries should converge on:

- strategy and parameter fingerprint
- timeframe and universe
- signals observed
- entries attempted, filled, rejected
- blocker counts
- positions count
- protection status
- turnover
- fee and slippage
- exit reason counts
- MFE/MAE
- drawdown

## Documentation Authority

- Current decisions: `.agents/current_decisions.md`
- Active roadmap: `.agents/improve_plan.md`
- Decision framework: `docs/research_manual/00_decision_framework.md`
- Quant research map: `docs/research_manual/01_quant_research_map.md`
- Carry/funding/basis status: `docs/research_manual/07_carry_funding_basis_backtest.md`
- Short-cycle diagnosis: `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md`

Older docs may contain historical hypotheses. Treat them as evidence snapshots, not current permission to promote.
