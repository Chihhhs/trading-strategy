# Entry-quality routes 38-40

Date: 2026-07-24

## Scope

Routes 38-40 are bounded forward-research ledgers for the fixed Hyperliquid
38-coin universe and completed 4h bars. They are separate from Routes 30/31,
never submit exchange orders, and persist `execution_authorized=false`.

They exist to test entry continuation quality after Route 30 attribution found
that initial failures, rather than delayed exits, explain most losing PnL.

## Predeclared hypotheses

| Route | Hypothesis | Change from Route 30 |
| --- | --- | --- |
| 38 | A leader that remains eligible for two consecutive bars is less likely to fail immediately. | Require a two-bar leader-persistence confirmation for a new target or switch. |
| 39 | A larger score lead avoids marginal switches and reduces entry churn. | Increase `switch_margin` from `0.01` to `0.02`. |
| 40 | A longer trend window removes short-lived leaders. | Increase `trend_bars` from `42` to `84`. |

All routes retain one position, 50% target allocation, 1.5% volatility target,
10 bps simulated fees, no elapsed-time exit, and the fixed 38-coin universe.
Route 38 persists its pending candidate and confirmation streak across process
restarts so the two-bar rule remains causal during replay recovery.

## Evaluation boundary

Do not tune these routes against the already-inspected historical fixture or
the current 13-bar forward sample. Compare each route against Route 30 using a
new fingerprinted boundary and fixed costs. Report net return, mark-to-market
drawdown, turnover, fee drag, minimum-order skips, initial-failure rate,
1/3/6-bar forward returns, and coin concentration.

The forward review gate remains at least 300 newly completed 4h bars and 20
closed trades, positive net paper return, drawdown better than -25%, and zero
minimum-order skips. Passing permits manual research review only; it does not
authorize exchange execution or live-config changes.

## Runner

```text
python apps/runners/paper_execution_runner.py --research-route=38 --once
python apps/runners/paper_execution_runner.py --research-route=39 --once
python apps/runners/paper_execution_runner.py --research-route=40 --once
```

State and events are isolated under `data/paper_execution/route38/`,
`route39/`, and `route40/`.

## Historical diagnostic replay

The fixed existing `hyperliquid_live38_1h.json` fixture was replayed at 4h
with 300-bar development folds, a 300-bar holdout, 50 USDC capital, and 10/15
bps normal/stress costs. This is a known-fixture diagnostic, not a fresh OOS
promotion test.

| Route | Holdout return at 10 bps | Holdout return at 15 bps | 15 bps MTM DD | Entries at 15 bps |
| --- | ---: | ---: | ---: | ---: |
| 30 baseline | +2.72% | +0.43% | -20.03% | 63 |
| 38 persistence | -6.38% | -7.73% | -23.85% | 41 |
| 39 switch margin 2% | +0.78% | -1.22% | -21.35% | 57 |
| 40 trend 84 bars | -5.14% | -7.48% | -27.75% | 72 |

None of the three improves Route 30 on the inspected holdout. Route 38 and
Route 39 reduce turnover, but remove enough profitable switches that the lower
fee drag does not compensate for the lost return. Route 40 fails the -25%
drawdown boundary under stress and is the weakest candidate. Keep all three
research-only, do not promote or retune them on this fixture, and treat the
forward ledgers as separate observations only.

The generated comparison artifact is
`data/research_artifacts/backtesting_py_live38_4h_entry_quality_routes_2026-07-24.json`.
