# Clean-room cross-sectional strength

Date: 2026-07-17

## Frozen hypothesis

- Rank 48 non-stablecoin assets by trailing 90-day close-to-close return.
- Rebalance weekly into the five strongest assets whose momentum is positive.
- Use equal weights, 1x gross exposure, and otherwise hold cash.
- Charge 4.5 bps fee plus 2 bps slippage on each unit of turnover.
- Keep this path research-only. It does not share signal parameters with the existing strategies and has no paper/live wiring.

## Evidence

| Version | Change | 300d net / DD | 600d net / DD | 1000d net / DD | Decision |
|---|---|---:|---:|---:|---|
| v1 | Positive-momentum ranking only | -48.71% / 67.10% | -67.17% / 71.67% | -24.88% / 72.98% | Rejected |
| v2 | Require a majority of the universe to have positive 90d momentum | -20.87% / 22.13% | -22.39% / 30.44% | +47.57% / 54.73% | Rejected |

The v1 failure is not primarily transaction cost: gross PnL is negative in every frozen window. The breadth rule reduces exposure and drawdown, but v2 remains negative in the two shorter windows. Its promotion comparison also has only two eligible windows because the 300-day slice records 18 changed asset legs, below the frozen minimum of 30.

The latest 300 days were inspected while diagnosing v1, so v2's 300-day result is not clean OOS evidence. No parameter sweep was run. Both versions remain negative evidence and must not be connected to paper or live.

## Reproduce

```bash
python backtest/backtest_runner.py run --experiment experiments/clean_room_cross_sectional_strength.json
python backtest/backtest_runner.py run --experiment experiments/clean_room_cross_sectional_strength_breadth.json
python backtest/backtest_runner.py promote --experiment experiments/clean_room_cross_sectional_strength_breadth.json
```

## Known limits

- The 48-asset fixture has survivorship bias and represents Binance spot closes.
- Close-to-close execution is causal but is not an intraday fill replay.
- Funding, borrow, and short execution are intentionally absent because the strategy is long-only.
- A genuinely new OOS period or forward observation is required before reopening this hypothesis.
