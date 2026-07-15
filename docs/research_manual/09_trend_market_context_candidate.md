# Trend Market-Context Candidate

This is an `optimize_existing_trend` research candidate. It does not change paper or live configuration.

## Components

- Market-context entry filter: classifies completed daily OHLCV as trend, range, compression, breakout, exhaustion, reversal, or unknown. It blocks new trend entries in range, compression, exhaustion, and unknown states.
- Momentum-decay time limit: when an open trend position remains directionally valid but enters confirmed exhaustion, it sets a one-time three-bar deadline. It does not alter TP/SL, staged stop progression, ATR trailing, or position size.

## Evaluation

The current `experiments/trend_market_context_baseline.json` is a diagnostic baseline only. Do not use it for promotion because it does not yet freeze the effective live configuration or apply the canonical causal 1h replay profile.

Before rerunning this candidate, create `live_like_trend_baseline` from `src/trading_strategy/live/config.py` plus `apps/live_config.py` overrides. It must include BTC/ETH/BNB, daily decision cadence, live leverage/risk/position limits, derivatives settings, 4.5 bps fees, 2 bps slippage, causal 1h hard-SL replay, and MTM drawdown.

Rebase and compare these frozen manifests only against that live-like baseline, with identical costs, windows, universes, and execution profile:

- `experiments/trend_market_context_entry.json`
- `experiments/trend_momentum_decay_time_limit.json`
- `experiments/trend_market_context_combined.json`

Passing the live-like backtest gate approves shadow mode only. Shadow mode records baseline and candidate decision differences without submitting orders or modifying protection. Bounded paper and any live use need separate fill, protection, observability, and manual-review evidence.
