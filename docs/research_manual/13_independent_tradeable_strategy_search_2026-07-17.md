# Independent tradeable-strategy search

Date: 2026-07-17

Status: this document records the first rejected search stage. The later actual-funding momentum result and shadow decision are in `14_cross_sectional_momentum_shadow_2026-07-17.md`.

## Objective

Find a strategy that is strong enough for forward paper observation without using the repository's existing trading strategy logic or conclusions. No candidate may reach paper/live merely because one backtest window is positive.

## Independent data

- Hyperliquid public `candleSnapshot` data fetched directly from the current active perp universe.
- Daily current-liquidity universe: 12 assets, 910 common bars.
- Daily long-history universe: 12 assets, 1,172 common bars.
- Four-hour current-liquidity universe: 10 assets, 5,000 common bars.
- Selection uses current day-notional-volume rank plus a minimum-history requirement. This is executable today but remains survivorship-biased.
- Coinbase cross-venue collection was attempted twice and abandoned after repeated TLS record-layer failures. TLS verification was not disabled.

Hyperliquid documents that `candleSnapshot` supports the intervals used here and returns at most the most recent 5,000 candles: <https://hyperliquid.gitbook.io/Hyperliquid-docs/for-developers/api/info-endpoint>.

## Frozen research contract

- One-way trading friction: 6.5 bps, equivalent to approximately 13 bps round trip.
- Market-neutral reversal also pays a 1 bp daily carry stress.
- Development evaluation uses sequential 120-day folds; the 4h path uses 720-bar folds, also 120 days.
- Initial gate: at least 75% positive folds, median Sharpe above 0.5, worst drawdown at most 25%, and maximum single-coin share of positive contribution at most 60%.
- Robustness gate: shift the rebalance anchor across every day of a week under both normal costs and stressed costs (10 bps one way and doubled carry). Both sets require 75% positive scenarios and the same drawdown/concentration limits.
- The final 120-day holdout stays locked until both gates pass.

## Families tested

- Time-series momentum.
- 7/14/28-day cross-sectional rotation.
- Dual-horizon momentum.
- Long-trend pullback.
- 56-day market-neutral cross-sectional reversal.
- Equal-weight and inverse-volatility diversified portfolio construction.

The reversal horizon follows published evidence that crypto momentum can switch to reversal beyond roughly one month and more recent evidence focused on 8-10 week formation windows. These papers motivate the family; they do not validate this implementation:

- <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3913263>
- <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6703978>

## Strongest result and rejection

`4h-reversal-56d` was the only provisional pass:

- Five of five development folds were positive after costs and carry stress.
- Fold net returns ranged from +1.94% to +16.52%.
- Median Sharpe was 0.81.
- Worst drawdown was 19.75%.
- Worst positive-contribution concentration was 57.39%.

It failed the mandatory rebalance-anchor robustness audit:

| Scenario | Positive | Required | Median net | Median Sharpe | Worst DD | Worst concentration |
|---|---:|---:|---:|---:|---:|---:|
| Normal cost | 24/35 | 27/35 | +4.90% | 0.71 | 24.91% | 58.61% |
| Stressed cost | 23/35 | 27/35 | +3.33% | 0.53 | 25.48% | 58.61% |

The candidate is rejected because its result depends too much on the weekly rebalance anchor. The final 720-bar holdout was never unlocked.

## Decision at this stage

No currently tested strategy qualifies as tradeable or ready for forward paper observation. The completed outcome is a stricter independent research harness and negative evidence, not a trading recommendation. Do not connect any candidate to paper/live and do not unlock the 4h holdout by hand.

This decision was superseded only after a new cross-sectional momentum family passed the frozen gates and its own holdout. The reversal candidate described here remains rejected and its holdout was not reused.

## Reproduce

```bash
python backtest/run_independent_lab.py --fixture data/clean_room/hyperliquid_daily_current.json --output data/research_artifacts/independent_strategy_search.json
python backtest/run_independent_lab.py --fixture data/clean_room/hyperliquid_daily_long_history.json --output data/research_artifacts/independent_strategy_search_long_history.json
python backtest/run_independent_lab.py --fixture data/clean_room/hyperliquid_4h_current.json --output data/research_artifacts/independent_strategy_search_4h.json
```
