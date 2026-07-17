# Trend Market-Context Candidate

This is an `optimize_existing_trend` research candidate. It does not change paper or live configuration.

## Components

- Market-context entry filter: classifies completed daily OHLCV as trend, range, compression, breakout, exhaustion, reversal, or unknown. It blocks new trend entries in range, compression, exhaustion, and unknown states.
- Momentum-decay time limit: when an open trend position remains directionally valid but enters confirmed exhaustion, it sets a one-time three-bar deadline. It does not alter TP/SL, staged stop progression, ATR trailing, or position size.

## Active 38-Coin Evaluation Contract

The active live-parity reference is the fixed 38-coin `apps/live_config.py::LIVE_UNIVERSE` contract, represented by `experiments/live_trend_baseline_38.json`. It uses matching daily, derivatives, and strict causal 1h replay fixtures, mark-to-market drawdown, 4.5 bps fee, and 2 bps slippage.

The corresponding research-only manifests are:

- `experiments/trend_market_context_entry_38.json`
- `experiments/trend_momentum_decay_time_limit_38.json`
- `experiments/trend_market_context_combined_38.json`

They exist to preserve a comparable experiment surface. They do not authorize a replay run, shadow mode, paper execution, or a live entry gate until a new pre-defined hypothesis passes the frozen 38-coin gate.

## Invalidated Three-Coin Result

The previous BTC/ETH/BNB strict-replay comparison is invalidated. It did not use the declared live universe, so it cannot reject or promote Market Context or Momentum-Decay. It remains an implementation smoke test only.

## Historical 50-Coin Evidence

The older `experiments/live_trend_baseline.json`, `trend_market_context_*.json` manifests, and 50-coin artifacts are retained as historical evidence. They are not rewritten or deleted, and are not active promotion authority.

### Trend Entry Attribution Prerequisite (2026-07-15)

The historical attribution report records raw Trend candidates and their existing eligibility outcome, applies a 13 bps forward-label cost, and reports fixed walk-forward consistency. It does not authorize Market Context or Momentum-Decay to enter shadow.


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

The historical baseline fails the cost-adjusted performance and non-worsening-drawdown gates. No paper candidate, shadow configuration, live-review bundle, or live configuration update may be created from it. Any future Market Context hypothesis must be pre-defined and compare against the active 38-coin contract.
