# Dual-Track Strategy Execution

- Date: 2026-07-11
- Purpose: Run existing-strategy optimization and new-strategy research in parallel without mixing unproven ideas into live execution.

## Operating Model

The repo now treats strategy work as two parallel tracks:

| Track | Goal | Default Action |
| --- | --- | --- |
| `optimize_existing` | Improve the current trend baseline with cost-aware risk, exits, and portfolio controls. | Can graduate toward paper/live after walk-forward validation. |
| `new_strategy` | Explore new alpha such as intraday momentum, funding/basis, and order flow. | Research-only until data, costs, and replay/backtest evidence are strong. |

## Current Report Candidates

Run:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB,SOL --max-days 240 --research-report
```

The report includes:

- `trend_control`: single-coin trend baseline, currently the control.
- `trend_controlled_portfolio`: lower-risk basket version with max position limits.
- `intraday_momentum_probe`: first runnable new-strategy probe; only meaningful on intraday candle data.
- `funding_basis_monitor`: pending data pipeline.
- `order_flow_imbalance`: pending L2/order-book infrastructure.

## Promotion Rules

- Existing-strategy candidates must beat `trend_control` on score, drawdown, and net PnL before being considered for paper/live.
- New-strategy candidates stay research-only until they pass cost-adjusted backtests on appropriate data.
- Funding/basis and order-flow tracks should start as reports, not live execution branches.
- Any intraday result must include realistic fee, slippage, and turnover checks.

