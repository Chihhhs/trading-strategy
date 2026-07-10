# Intraday Strategy Candidates

- Date: 2026-07-10
- Data range: Current repo behavior, local research notes, Hyperliquid execution constraints, and cited market microstructure research through 2026-07-10
- Applicable markets: Liquid crypto perps, especially BTC and top-liquidity majors
- Last updated: 2026-07-10

## Scope

這份文件用來區分兩件事：

- `Short-horizon automation`: 1m / 5m / 15m 訊號、自動掃描、自動下單、自動風控。這是目前 repo 可以自然延伸的方向。
- `True HFT`: 秒級到毫秒級 order book / trade-level 策略，例如 market making、order flow imbalance、跨市場套利。這需要不同的資料管線與執行架構，不能直接用目前 candle-based live loop 承接。

目前 live loop 預設以分鐘級輪詢執行，回測策略入口也仍是 `trend`。因此短期策略研究應先落在 short-horizon automation，而不是直接重寫成真正 HFT 系統。

## Recommended Ranking

### 1. Intraday Momentum / Volatility Breakout

- Claim: 短週期動能與波動突破是目前最適合從 trend 主線延伸的非日線策略。
- Evidence level: B
- Market applicability: BTC, ETH, SOL and other highly liquid perps.
- Time horizon: 5m to 15m entries, intraday to multi-hour holds.
- Known failure modes: Choppy markets, false breakouts, crowded momentum unwind.
- Cost sensitivity: High.
- Implementation implication: Reuse current trend concepts, but add timeframe-aware data loading, cost/slippage reporting, and intraday-specific stop logic.
- Decision for this repo: First intraday candidate to implement after cost/slippage modeling.

### 2. Intraday Mean Reversion

- Claim: Short-horizon mean reversion can exploit range-bound markets, but only if spread, fees, and slippage are modeled conservatively.
- Evidence level: B/C
- Market applicability: High-liquidity coins during non-trending regimes.
- Time horizon: 1m to 15m entries, short holds.
- Known failure modes: Trending markets, catching liquidation cascades, repeated small losses.
- Cost sensitivity: Very high.
- Implementation implication: Treat as a second candidate after intraday momentum. Require regime filters, strict stop logic, and taker/maker cost assumptions before trusting results.
- Decision for this repo: Validate after the first intraday momentum baseline.

### 3. Funding / Basis Monitor

- Claim: Funding and basis are crypto-native alpha sources that fit automation well, but they are not the same architecture as directional trend trading.
- Evidence level: B
- Market applicability: Perpetual futures and spot/perp or perp/perp relative-value setups.
- Time horizon: Funding cycles to multi-day holds.
- Known failure modes: Funding regime change, basis compression, liquidation risk, execution friction.
- Cost sensitivity: Moderate to high.
- Implementation implication: Build this first as a monitor/reporting track, not as an immediate live execution branch.
- Decision for this repo: Create a separate research track after intraday cost tooling exists.
- Sources:
  - [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888)
  - [Designing funding rates for perpetual futures in cryptocurrency markets](https://arxiv.org/abs/2506.08573)

### 4. Order Flow Imbalance / Microstructure

- Claim: If this repo eventually moves toward true high-frequency trading, order flow imbalance is more defensible than chart-pattern scalping.
- Evidence level: A
- Market applicability: Liquid perp markets with order book and trade-level data.
- Time horizon: Sub-minute to intraday.
- Known failure modes: Data quality mismatch, adverse selection, latency, spread drag, model decay.
- Cost sensitivity: Very high.
- Implementation implication: Do not implement until websocket order book capture, replayable market data, and maker/taker execution simulation exist.
- Decision for this repo: Long-term research track only.
- Sources:
  - [The Price Impact of Order Book Events](https://arxiv.org/abs/1011.6402)
  - [The Price Impact of Generalized Order Flow Imbalance](https://arxiv.org/abs/2112.02947)
  - [Explainable Patterns in Cryptocurrency Microstructure](https://arxiv.org/abs/2602.00776)

### 5. Market Making

- Claim: Market making is the most HFT-like candidate, but it is not a near-term fit for the current repo.
- Evidence level: B
- Market applicability: Only the most liquid assets, and only with robust order book, inventory, and cancellation controls.
- Time horizon: Seconds to minutes.
- Known failure modes: Adverse selection, stale quotes, inventory drift, cancellation limits, queue-position uncertainty.
- Cost sensitivity: Extreme.
- Implementation implication: Requires a dedicated event-driven execution engine, inventory skew, quote refresh logic, and exchange-specific fee/rate-limit handling.
- Decision for this repo: Do not prioritize until the repo has order book infrastructure and conservative simulated execution.
- Sources:
  - [High-frequency trading in a limit order book](https://www.tandfonline.com/doi/abs/10.1080/14697680701381228)
  - [High-frequency market-making with inventory constraints and directional bets](https://arxiv.org/abs/1206.4810)
  - [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
  - [Hyperliquid tick and lot size](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size)

## Deprioritized Candidates

### FVG / Pure Chart Pattern Scalping

- Claim: FVG-style setups are weaker than trend, carry, or microstructure-backed signals as an automated strategy branch.
- Evidence level: C
- Market applicability: Discretionary or semi-systematic trading only.
- Time horizon: Short to medium.
- Known failure modes: Narrative overfitting, chart-resolution dependence, cost fragility.
- Cost sensitivity: High.
- Implementation implication: Keep only as historical context unless a new independent study proves value after fees and slippage.
- Decision for this repo: Do not restart as an active branch.

### Naked RSI / Indicator-Only Scalping

- Claim: Single-indicator scalping is unlikely to survive conservative crypto perp cost assumptions.
- Evidence level: C
- Market applicability: Limited.
- Time horizon: 1m to 15m.
- Known failure modes: Parameter overfit, high turnover, poor regime transfer.
- Cost sensitivity: Very high.
- Implementation implication: Only test as a component inside a broader regime-aware model, not as a standalone strategy.
- Decision for this repo: Do not prioritize.

## Implementation Sequence

1. Add configurable fee, spread, and slippage assumptions to backtests.
2. Add timeframe-aware market data loading for intraday candles.
3. Implement `intraday_momentum` as the first non-daily candidate.
4. Build paper reports comparing `trend` vs `intraday_momentum` on BTC-only first.
5. Add `intraday_mean_reversion` only after momentum has a reliable baseline.
6. Build funding/basis monitoring as a separate report path.
7. Delay order flow and market making until websocket order book capture and replay exist.
