# Cross-sectional momentum shadow candidate

Date: 2026-07-17

## Decision

`cross_sectional_momentum` passed the clean-room development, robustness, and locked holdout gates. It is approved for isolated shadow observation only. It does not replace the current live strategy yet and cannot place orders.

## Frozen strategy

- Venue and bars: Hyperliquid perpetuals, 4h.
- Universe: 10 currently active, liquid contracts with 5,000 common bars.
- Signal: rank each asset by its trailing 84-bar (14-day) return.
- Portfolio: long the strongest three and short the weakest three at half gross exposure per sleeve.
- Overlap: average seven cohorts spaced six bars apart; update once per day.
- Operational rebalance anchor: 00:00 UTC. All six 4h anchors remained positive on the already-open holdout; 00:00 UTC was chosen as a clock convention, not as the best result.
- Costs: 6.5 bps one way plus the exact hourly Hyperliquid funding paid or received by each historical position.
- Stress: 10 bps one way plus an additional 1 bp daily gross-exposure drag.
- No leverage multiplier, regime filter, stop tuning, or date-specific exception.

Positive funding is charged to long weights and credited to short weights. Funding events are aligned causally to the 4h return interval in which they settle. The local fixture contains about 20,000 hourly funding observations for each of the ten assets.

## Development evidence

The final candidate was selected without reading the final 720 bars. On the complete locked search schedule it produced:

| Gate | Result | Requirement |
|---|---:|---:|
| Positive development folds | 4/5 | at least 4/5 |
| Median fold Sharpe | 1.01 | above 0.50 |
| Worst fold drawdown | 20.41% | at most 25% |
| Worst positive-contribution concentration | 57.53% | at most 60% |
| Normal anchor scenarios | 24/30 | at least 23/30 |
| Stressed anchor scenarios | 24/30 | at least 23/30 |
| Stressed median net return | +5.40% | positive |
| Stressed median Sharpe | 0.81 | diagnostic |
| Stressed worst drawdown | 20.98% | at most 25% |

The adjacent 28/42/56/70/90-day momentum horizons did not pass the same process. The earlier 56-day reversal stayed rejected. A proposed strong-market filter also failed and was removed rather than retained as dormant tuning.

## Locked holdout

The final 120-day holdout was unlocked once, only after the development and robustness gates passed:

| Metric | Holdout |
|---|---:|
| Net return after costs and funding | +15.48% |
| Gross price return | +16.85% |
| Sharpe | 2.25 |
| Maximum drawdown | 7.07% |
| Turnover | 16.57x |
| Changed legs | 574 |
| Highest single-coin share of positive contribution | 32.56% |

The typed experiment adapter uses the fixed 00:00 UTC operational anchor. On the already-open holdout that anchor returned +15.42% net with 7.57% maximum drawdown; the six anchor results ranged from +13.61% to +19.78% net.

## Shadow boundary

The shadow runner emits desired portfolio weights and append-only observations. It never imports order handling and every snapshot contains `execution_authorized: false`.

```bash
python apps/runners/momentum_shadow_runner.py
python apps/runners/momentum_shadow_runner.py --fetch
```

The first command evaluates the saved fixture. `--fetch` refreshes the current active-universe 4h fixture before producing a new observation. Re-running the same source bar is idempotent for the append-only log.

## Remaining risks

- The universe is selected from assets active and liquid today, so delisted-asset survivorship bias remains.
- Hyperliquid's public candle endpoint limits the test to 5,000 4h bars, roughly 833 days.
- The untouched holdout is only 120 days and includes one market path.
- The portfolio needs simultaneous long and short legs; execution slippage, partial fills, margin usage, and portfolio-level protection are not yet proven by paper fills.
- A live replacement requires a bounded forward shadow/paper period, point-in-time universe evidence, execution reconciliation, and a separate live-safety review.

## Reproduce

```bash
python backtest/run_independent_lab.py --fixture data/clean_room/hyperliquid_4h_current.json --output data/research_artifacts/independent_strategy_search_4h_actual_funding.json --funding-input data/clean_room/hyperliquid_4h_funding.json
python backtest/run_independent_lab.py --fixture data/clean_room/hyperliquid_4h_current.json --output data/research_artifacts/independent_strategy_search_4h_actual_funding_holdout.json --funding-input data/clean_room/hyperliquid_4h_funding.json --unlock-holdout
```
