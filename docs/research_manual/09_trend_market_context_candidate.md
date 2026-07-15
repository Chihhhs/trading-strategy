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

The canonical 50-coin 1h replay fixture is `data/historical_prices/binance_1h_240d_live_50coins.json`, with an integrity sidecar at `data/historical_prices/binance_1h_240d_live_50coins.json.metadata.json`. It contains 5,760 contiguous bars for each declared coin and is required for MTM replay. Shadow mode remains unavailable unless a separate candidate improves this baseline.

## Invalidated Three-Coin Result

The previous BTC/ETH/BNB strict-replay comparison is invalidated. It did not use the declared 50-coin live universe, so it cannot reject or promote Market Context or Momentum-Decay. It remains an implementation smoke test only.
# Trend Entry Attribution Prerequisite (2026-07-15)

Before changing the Trend entry filter, run `backtest/backtest_runner.py --trend-entry-attribution-report`. The report uses the checked-in 50-coin `live_trend_baseline.json` only as a research configuration reference; it is not live runtime or promotion authority. It records raw Trend candidates and their existing eligibility outcome, applies a 13 bps forward-label cost, and reports fixed walk-forward consistency. Neither Market Context nor Momentum-Decay may enter shadow from this report.


## Attribution And Replay Result (2026-07-15)

- Artifact: `data/research_artifacts/trend_entry_attribution_50coin.json`.
- Raw candidates: 1,815. Existing eligibility allowed 573 and blocked 1,242.
- Three fixed 90/30 folds produced no cross-fold research hypothesis. The 10-day net forward-label average was -0.2533% after the 13 bps round-trip cost.
- Hyperliquid 1h collection produced 18 of the declared 50 markets and reported 32 unavailable markets in `data/historical_prices/hyperliquid_1h_240d_live_50coins.json`.

This evidence blocks the next filter-hypothesis step and all shadow promotion. It does not permit a silent universe reduction for promotion.

## Canonical Causal Replay Baseline (2026-07-15)

- Artifact: `data/research_artifacts/live_trend_baseline_1h_replay_50coin.json`.
- The Binance 1h fixture has all 50 declared coins, 5,760 contiguous bars per coin, zero gaps, and a matching SHA-256 metadata checksum.
- Strict causal replay with 4.5 bps fee and 2.0 bps slippage produced: 120d `-11.3%` net / `59.3214%` MTM drawdown; 180d `-23.1%` / `60.6270%`; 240d `-1.0%` / `40.4937%`.

The baseline fails the cost-adjusted performance and non-worsening-drawdown gates. No paper candidate, shadow configuration, live-review bundle, or live configuration update may be created from it. A future candidate must state one pre-defined hypothesis and compare against this exact fixture, manifest, costs, and universe.
