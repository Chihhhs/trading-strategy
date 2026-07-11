# Research Backlog

- Date: 2026-07-05
- Data range: Current repo behavior, cited research, and existing 50-coin research notes
- Applicable markets: Current crypto majors and future liquid-coin expansions
- Last updated: 2026-07-10

## Priority 1: Crypto Trend Mainline

### 0. Dual-Track Research Report

- Claim: 現有策略優化與新策略研究應並行，但不能混在同一個 live 決策面。
- Evidence level: B
- Market applicability: Current repo research workflow.
- Time horizon: Every research cycle.
- Known failure modes: 新策略還沒證明就污染主策略；只看單一回測而忽略成本與 drawdown。
- Cost sensitivity: High for intraday and multi-coin candidates.
- Implementation implication: Use `python backtest/backtest_runner.py --research-report` as the standard first-pass report.
- Decision for this repo: Required workflow.

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

- Claim: Crypto trend and any future intraday strategy need cost-adjusted reporting before live expansion.
- Evidence level: B
- Market applicability: Spot and perp execution.
- Time horizon: Every trade.
- Known failure modes: Underestimated turnover cost, fake alpha in thinner coins.
- Cost sensitivity: High once moving outside BTC, and very high for 1m / 5m / 15m strategies.
- Implementation implication: Add configurable maker/taker fees, spread, and slippage assumptions to backtests before trusting shorter-horizon results.
- Decision for this repo: Required before intraday strategy validation.

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

## Priority 3: Intraday Automation Candidates

### 6. Intraday Momentum / Volatility Breakout

- Claim: Short-horizon momentum and volatility breakout are the most natural non-daily extension of the current trend mainline.
- Evidence level: B
- Market applicability: Liquid crypto majors, especially BTC and top-liquidity perps.
- Time horizon: 5m to 15m entries, intraday to multi-hour holds.
- Known failure modes: Choppy markets, false breakouts, crowded momentum unwind.
- Cost sensitivity: High.
- Implementation implication: Add timeframe-aware intraday data, conservative cost assumptions, and BTC-only validation before live use.
- Decision for this repo: First non-daily candidate after cost/slippage tooling.

### 7. Intraday Mean Reversion

- Claim: Short-horizon mean reversion may help in range-bound regimes, but it is more cost-fragile than intraday momentum.
- Evidence level: B/C
- Market applicability: High-liquidity coins during non-trending regimes.
- Time horizon: 1m to 15m entries, short holds.
- Known failure modes: Strong trends, liquidation cascades, repeated small losses, overfit thresholds.
- Cost sensitivity: Very high.
- Implementation implication: Test only after intraday momentum has a reliable BTC-only baseline and cost model.
- Decision for this repo: Secondary intraday candidate.

## Priority 4: Experimental Branches

### 8. Carry / Funding / Basis Track

- Claim: Carry/funding/basis is the most promising crypto-native non-trend direction worth recording.
- Evidence level: B
- Market applicability: Perpetuals and derivatives venues.
- Time horizon: Funding cycles to medium-term holds.
- Known failure modes: Regime shifts in funding, basis compression, execution friction.
- Cost sensitivity: Moderate to high.
- Implementation implication: Build first as a monitor/reporting track rather than forcing it into the current directional trend engine.
- Decision for this repo: Future expansion path, separate from trend live execution.

### 9. Microstructure / Order Flow Track

- Claim: If the repo ever moves shorter-term, microstructure is a more defensible path than chart-lore pattern mining.
- Evidence level: A
- Market applicability: Intraday perp markets with high-resolution data.
- Time horizon: Sub-minute to intraday.
- Known failure modes: Data mismatch, spread drag, adverse selection, execution complexity.
- Cost sensitivity: Very high.
- Implementation implication: Requires websocket order book capture, replayable market data, and conservative execution simulation before serious implementation.
- Decision for this repo: Long-term research track only.

### 10. Market Making Track

- Claim: Market making is the most HFT-like candidate, but it is not a near-term fit for the current candle-based repo.
- Evidence level: B
- Market applicability: Only top-liquidity assets with robust order book and inventory controls.
- Time horizon: Seconds to minutes.
- Known failure modes: Adverse selection, stale quotes, inventory drift, cancellation limits, queue-position uncertainty.
- Cost sensitivity: Extreme.
- Implementation implication: Requires a dedicated event-driven execution engine, inventory skew, quote refresh logic, and exchange-specific fee/rate-limit handling.
- Decision for this repo: Do not prioritize until order book infrastructure and simulated execution exist.
