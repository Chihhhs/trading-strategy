---
name: crypto-strategy-backtest
description: Crypto strategy backtest workflow for this repository. Use for strategy research, cost-aware comparison, candidate diagnostics, optimization, and promotion-gate interpretation.
---

# Crypto Strategy Backtest

Use this skill when the task involves backtest results, strategy comparison, optimization, short-cycle diagnostics, or promotion decisions.

Before using evidence, read:

- `.agents/current_decisions.md`
- `.agents/project_detail.md`
- `.agents/improve_plan.md`
- `docs/research_manual/00_decision_framework.md`

## Current Stance

- Backtest evidence must include fees, slippage, turnover, drawdown, and sample size before it can affect promotion.
- Zero-cost results are diagnostics only.
- Relative improvement is not enough when the baseline is deeply negative.
- A candidate that reduces turnover but remains negative after costs stays research-only.
- `intraday_momentum` is rejected for paper/live and should be treated as a negative control.
- Current trend logic has not passed the canonical live-like baseline gate.
- Funding/basis/carry is research and monitoring only; current standalone execution is not approved.

## Standard Cost Assumption

Use these defaults unless the user asks for a different scenario:

- `fee_bps=4.5`
- `slippage_bps=2`
- Round trip for one directional trade is approximately 13 bps.

When comparing candidates, keep constant:

- fixture
- universe
- fee and slippage
- timeframe
- train/test split
- random baseline settings
- minimum event count
- execution profile

## Canonical Commands

Trend representative baseline:

```bash
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240
```

Trend live-like replay:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --derivatives-data-path data/derivatives/bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json --enable-trend-position-control --enable-atr-trailing --fee-bps 4.5 --slippage-bps 2 --trend-exit-replay-report --exit-replay-data-path data/historical_prices/binance_1h_240d_BTC_ETH_BNB.json
```

Short-cycle alpha report:

```bash
python backtest/backtest_runner.py --short-cycle-alpha-report --coins BTC,ETH,SOL,BNB --data-path data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json --max-days 8640 --fee-bps 4.5 --slippage-bps 2 --bucket-count 5 --random-baseline-runs 50 --short-cycle-splits rolling_30,train60_test30 --short-cycle-min-events 100 --short-cycle-focus-alpha intraday_vwap_reversion
```

Experiment workflow:

```bash
python backtest/backtest_runner.py run --experiment experiments/trend_baseline.json
python backtest/backtest_runner.py compare --experiments experiments/trend_baseline.json experiments/intraday_momentum_rejected.json
python backtest/backtest_runner.py promote --experiment experiments/trend_paper_candidate.json
```

## How To Interpret Results

Always separate:

- gross PnL from net PnL
- zero-cost signal quality from cost-adjusted tradability
- close-fill backtests from live-like trigger execution
- in-sample improvements from OOS evidence
- paper approval from live approval

For intraday and short-cycle work, inspect:

- per-trade gross return
- fee drag
- turnover
- hold bars
- exit reason distribution
- re-entry gap
- direction split
- UTC session split
- MFE/MAE and initial risk
- no-op filters
- random baseline delta

## Promotion Rules

Research candidate can move to bounded paper observation only when:

- OOS net PnL after costs is acceptable under the documented gate.
- Drawdown does not worsen beyond threshold.
- Turnover and fee drag materially improve.
- Event count is sufficient.
- Candidate is not a no-op.
- Positive result is not concentrated in one coin, one session, or one split.

Live promotion requires a separate explicit review of live execution, protection, fill quality, and operational risk.
