# Two Research Modes And Strategy Promotion

- Last updated: 2026-07-15
- Purpose: Run current Trend optimization and new-alpha research in parallel without mixing their baselines or unproven ideas into live execution.

## Operating Model

The repo now treats strategy work as two parallel tracks:

| Track | Goal | Default Action |
| --- | --- | --- |
| `optimize_existing_trend` | Improve the currently executable daily Trend strategy with entry, regime, universe, and approved context changes. | Compare only with a frozen live-like Trend baseline; shadow, bounded paper, then explicit live review. |
| `new_alpha_research` | Explore new alpha such as intraday momentum, VWAP reversion, funding/basis, and order flow. | Use an independent frequency-matched research baseline; separate strategy approval is required. |

Protection, execution, reconciliation, and logging are shared live-safety requirements, not a third research mode. Detailed mode rules live in [`.agents/research_modes.md`](../../.agents/research_modes.md).

## `optimize_existing_trend` Baseline

The declared current live universe is the 50-coin `experiments/live_trend_baseline.json` reference. The checked-in `apps/live_config.py` still narrows the launcher to BTC/ETH/BNB, while historical live cache data shows broad-universe scanning. This is configuration drift: do not silently choose either source or change live config during research work.

The local repository contains only a BTC/ETH/BNB 1h fixture. Therefore 50-coin Market Context and Momentum-Decay comparisons are diagnostic only until a matching 50-coin causal 1h replay fixture exists. The former BTC/ETH/BNB replay result is invalidated because it used the wrong universe.

Promotion path:

```text
live-like backtest -> frozen gate -> shadow mode (no orders) -> bounded paper -> explicit live review
```

Shadow mode records baseline and candidate signals, block reasons, intended actions, and their differences. It never submits orders or changes TP/SL protection.

## `new_alpha_research` Candidates

Run:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB,SOL --max-days 240 --research-report
```

The report includes:

- `intraday_momentum_probe`: first runnable new-strategy probe; only meaningful on intraday candle data.
- `funding_basis_monitor`: runnable monitor-only Funding / OI / Basis report.
- `order_flow_imbalance`: pending L2/order-book infrastructure.

Optional derivatives data:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB,SOL --max-days 240 --research-report --derivatives-data-path data/derivatives/example.json
```

## Promotion Rules

- Existing Trend candidates must improve cost-adjusted net PnL and drawdown across frozen windows and universes against the live-like Trend baseline before shadow mode; a generic or short-cycle baseline is not valid.
- New-alpha candidates stay research-only until they pass cost-adjusted, frequency-matched OOS and random-baseline evidence. They cannot be promoted merely because they lose less than a negative baseline.
- Funding/basis and order-flow tracks should start as reports, not live execution branches.
- Any intraday result must include realistic fee, slippage, and turnover checks.
