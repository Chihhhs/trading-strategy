---
name: trend-framework-dev
description: Trend strategy framework workflow for this repository. Use for trend entry, exit, regime, universe, backtest-to-paper, and paper-to-live decisions.
triggers:
  - "trend framework"
  - "trend strategy"
  - "trend entry"
  - "regime"
  - "universe"
---

# Trend Framework Development

Use this skill when a task changes or evaluates trend strategy behavior from signal generation through deployment workflow.

Read first:

- `.agents/current_decisions.md`
- `.agents/project_detail.md`
- `.agents/improve_plan.md`
- `docs/research_manual/01_quant_research_map.md`

## Current Stance

- Trend code is wired through backtest, paper, and live strategy hooks.
- Trend is not currently validated as live alpha under the canonical live-like baseline.
- The current priority is entry quality, BTC regime, and universe selection.
- Stop-stage, ATR trailing, close-confirmed stop, and failure-exit tuning are not the priority unless new evidence justifies reopening them.
- Funding/basis/OI may be tested as context or a blocker, not as standalone live alpha.

## Canonical Baseline

Use live-like evaluation for promotion decisions:

- Daily trend decision.
- Causal 1h hard-SL execution.
- Mark-to-market drawdown.
- Realistic fee and slippage assumptions.
- Frozen windows and universes.

Daily close-fill backtests are diagnostic only and must not be used as live promotion evidence.

## Development Flow

1. Classify the change: entry, exit, regime, universe, position control, or workflow.
2. State whether the change affects research, paper, or live.
3. Identify the canonical command that exercises the behavior.
4. Compare against the canonical live-like baseline.
5. Check trade count, drawdown, net PnL, exit reasons, and concentration.
6. Keep live config unchanged unless there is an explicit live review.

## Allowed Current Research

- BTC regime filters.
- Coin universe selection.
- Entry quality filters.
- Funding/basis/OI as blocker or confidence modifier.
- Position-control research in backtest or bounded paper only.

## Currently Rejected Or Paused

- Adaptive ATR trail promotion.
- Close-confirmed stop promotion.
- Intrabar stop-first as a trend improvement.
- Treating a single daily BTC winner as live edge.
- Treating funding/basis position control as validated live alpha.

## Canonical Commands

Representative trend backtest:

```bash
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240
```

Live-like trend replay:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --derivatives-data-path data/derivatives/bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json --enable-trend-position-control --enable-atr-trailing --fee-bps 4.5 --slippage-bps 2 --trend-exit-replay-report --exit-replay-data-path data/historical_prices/binance_1h_240d_BTC_ETH_BNB.json
```

Regression checks:

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

## Promotion Boundary

Backtest success can approve more research or bounded paper observation. Live promotion needs a separate review of:

- exchange protection behavior
- entry blocking
- run summary observability
- real fill and slippage assumptions
- state separation
- manual approval
