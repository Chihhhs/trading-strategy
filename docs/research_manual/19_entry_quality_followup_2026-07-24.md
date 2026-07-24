# Entry-quality follow-up routes 41-44

Date: 2026-07-24

## Scope

The paper review found that losing trades were dominated by initial entry
failure. Routes 41-44 test separate entry-quality hypotheses in the existing
fixed 38-coin, 4h selector. They are pure historical backtests only: they do
not create paper state, submit exchange orders, or change live configuration.

## Predeclared hypotheses

| Route | Hypothesis | Change from Route 30 |
| --- | --- | --- |
| 41 | Reject weak momentum leaders before they become entries. | Require 12-bar momentum of at least 1%. |
| 42 | A stronger momentum floor improves entry quality further. | Require 12-bar momentum of at least 2%. |
| 43 | Rank momentum by realized volatility so noisy moves are penalized. | Rank `12-bar momentum / 42-bar realized volatility`, with a 0.25 score lead to switch. |
| 44 | A coin that just lost leadership should not immediately re-enter. | Block re-entry for two completed bars after an incumbent change. |

All routes retain the Route 30 capital, universe, sizing, volatility target,
and 10/15 bps normal/stress cost contract.

## Diagnostic replay

The existing `hyperliquid_live38_1h.json` fixture was resampled to 4h and
replayed with three 300-bar development folds plus a 300-bar holdout. This is
the same known fixture used for Routes 38-40, so the result is hypothesis
diagnosis rather than a new OOS promotion test.

| Route | Holdout return at 10 bps | Holdout return at 15 bps | 15 bps MTM DD | Entries at 15 bps |
| --- | ---: | ---: | ---: | ---: |
| 30 baseline | +2.72% | +0.43% | -20.03% | 63 |
| 41 momentum floor 1% | +9.16% | +7.02% | -14.79% | 56 |
| 42 momentum floor 2% | +8.98% | +6.89% | -14.90% | 56 |
| 43 volatility-normalized rank | +8.72% | +5.56% | -14.42% | 75 |
| 44 re-entry cooldown 2 bars | +5.85% | +3.48% | -19.55% | 63 |

All four candidates were positive on each of the three development folds under
15 bps stress. Route 41 is the strongest first candidate by stressed return;
Route 42 is nearly identical and tests whether the extra floor is robust;
Route 43 has the best stressed drawdown in this table but also the highest
entry count and fee drag; Route 44 provides only a modest improvement over the
baseline.

## Decision

Routes 41-43 are worth a new, predeclared OOS validation. Do not open paper
ledgers from these results yet: the fixture was already inspected, the result
is not independent evidence, and the paper gate still requires at least 300
newly completed 4h bars, 20 closed trades, positive net paper return, drawdown
better than -25%, and zero minimum-order skips. Any later paper observation
must retain `execution_authorized=false` and remain isolated from Route 30/31.

The next bounded comparison is Route 30 versus Routes 41, 42, and 43 on a new
fingerprinted boundary with the same universe, capital, bar construction, and
10/15 bps costs. Route 44 should remain diagnostic unless the cooldown effect
appears consistently in that comparison.

## Artifacts

- Script: `backtest/backtesting_py_live38_4h_entry_quality_routes.py`
- Result: `data/research_artifacts/backtesting_py_live38_4h_entry_quality_routes_2026-07-24.json`
