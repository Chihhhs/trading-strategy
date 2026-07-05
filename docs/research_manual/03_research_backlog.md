# Research Backlog

- Date: 2026-07-05
- Data range: Current repo behavior, cited research, and existing 50-coin research notes
- Applicable markets: Current crypto majors and future liquid-coin expansions
- Last updated: 2026-07-05

## Priority 1: Crypto Trend Mainline

### 1. Short-Term Failure Exit

- Claim: Live trend trading needs an explicit post-entry failure exit, not only SL, reversal, and max-hold exits.
- Evidence level: B
- Market applicability: Crypto trend live trading.
- Time horizon: First few bars after entry.
- Known failure modes: Overreacting to noise, too much churn, conflict with dynamic stop logic.
- Cost sensitivity: Moderate.
- Implementation implication: Design a rule such as "no follow-through within N bars" or "breakout re-enters range" and test it in backtest first.
- Decision for this repo: Next live-strategy improvement.

### 2. Walk-Forward Validation

- Claim: Trend should not be promoted from "best current implementation" to "trusted mainline" without out-of-sample validation.
- Evidence level: A/B
- Market applicability: Current major-coin universe.
- Time horizon: Rolling train/test windows.
- Known failure modes: Parameter luck, regime concentration, overfitting to recent periods.
- Cost sensitivity: Low direct sensitivity.
- Implementation implication: Add repeatable walk-forward tooling.
- Decision for this repo: Required.

### 3. Cost / Slippage Model

- Claim: Crypto trend is more robust than FVG, but it still needs cost-adjusted reporting before live expansion.
- Evidence level: B
- Market applicability: Spot and perp execution.
- Time horizon: Every trade.
- Known failure modes: Underestimated turnover cost, fake alpha in thinner coins.
- Cost sensitivity: High once moving outside BTC.
- Implementation implication: Add configurable spread/slippage assumptions to backtests.
- Decision for this repo: Required.

## Priority 2: Universe And Exposure

### 4. Universe Comparison

- Claim: `BTC-only` should be the research baseline, not necessarily the permanent universe.
- Evidence level: B
- Market applicability: BTC, ETH, BNB, SOL and future liquid majors.
- Time horizon: Current 240-day results plus future rolling windows.
- Known failure modes: Window-specific rankings, missed diversification benefits later.
- Cost sensitivity: High outside BTC.
- Implementation implication: Build repeatable reports for `BTC`, `BTC+ETH`, `BTC+BNB`, and full basket.
- Decision for this repo: Required before live universe expansion.

### 5. Sizing / Leverage Rewrite

- Claim: The leverage knob currently does not carry enough explanatory power to be trusted.
- Evidence level: B
- Market applicability: Entire repo.
- Time horizon: Every trade.
- Known failure modes: Flat optimizer rankings, misleading exposure assumptions.
- Cost sensitivity: Indirectly high.
- Implementation implication: Rewrite position sizing so leverage, margin, and risk budget are explicit.
- Decision for this repo: Required.

## Priority 3: Experimental Branches

### 6. Carry / Funding / Basis Track

- Claim: Carry/funding/basis is the most promising crypto-native non-trend direction worth recording.
- Evidence level: B
- Market applicability: Perpetuals and derivatives venues.
- Time horizon: Funding cycles to medium-term holds.
- Known failure modes: Regime shifts in funding, basis compression, execution friction.
- Cost sensitivity: Moderate to high.
- Implementation implication: Track as a future strategy family rather than forcing it into the current directional trend engine.
- Decision for this repo: Future expansion path.

### 7. Microstructure / Order Flow Track

- Claim: If the repo ever moves shorter-term, microstructure is a more defensible path than chart-lore pattern mining.
- Evidence level: A
- Market applicability: Intraday perp markets with high-resolution data.
- Time horizon: Intraday.
- Known failure modes: Data mismatch, spread drag, execution complexity.
- Cost sensitivity: Very high.
- Implementation implication: Requires order-book or trade-level data before serious implementation.
- Decision for this repo: Long-term research track only.
