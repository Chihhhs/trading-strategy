# Trend Market-Context Candidate

This is an `optimize_existing_trend` research candidate. It does not change paper or live configuration.

## Components

- Market-context entry filter: classifies completed daily OHLCV as trend, range, compression, breakout, exhaustion, reversal, or unknown. It blocks new trend entries in range, compression, exhaustion, and unknown states.
- Momentum-decay time limit: when an open trend position remains directionally valid but enters confirmed exhaustion, it sets a one-time three-bar deadline. It does not alter TP/SL, staged stop progression, ATR trailing, or position size.

## Evaluation

The declared live reference is the 50-coin `experiments/live_trend_baseline.json`. A checked-in launcher override still specifies BTC/ETH/BNB; this mismatch is recorded as configuration drift and must be resolved separately from strategy research.

Compare these frozen manifests only against the 50-coin reference, with identical costs, windows, and universe:

- `experiments/trend_market_context_entry.json`
- `experiments/trend_momentum_decay_time_limit.json`
- `experiments/trend_market_context_combined.json`

The repository has no 50-coin 1h replay fixture. These comparisons are diagnostic only and their manifests require more eligible comparisons than they contain, preventing promotion. Shadow mode remains unavailable until causal hard-SL replay and MTM drawdown cover the same 50-coin universe.

## Invalidated Three-Coin Result

The previous BTC/ETH/BNB strict-replay comparison is invalidated. It did not use the declared 50-coin live universe, so it cannot reject or promote Market Context or Momentum-Decay. It remains an implementation smoke test only.
# Trend Entry Attribution Prerequisite (2026-07-15)

Before changing the Trend entry filter, run `backtest/backtest_runner.py --trend-entry-attribution-report`. The report uses the checked-in 50-coin `live_trend_baseline.json` only as a research configuration reference; it is not live runtime or promotion authority. It records raw Trend candidates and their existing eligibility outcome, applies a 13 bps forward-label cost, and reports fixed walk-forward consistency. Neither Market Context nor Momentum-Decay may enter shadow from this report.
