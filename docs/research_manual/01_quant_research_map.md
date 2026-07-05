# Quant Research Map

- Date: 2026-07-05
- Data range: Research synthesis plus current repo observations through 2026-07-05
- Applicable markets: Multi-asset quant research mapped into crypto trading decisions
- Last updated: 2026-07-05

## Three Strategic Directions To Track

### 1. Crypto Trend

- Claim: 趨勢追蹤與 time-series momentum 是目前最適合作為 repo 主線的策略家族。
- Evidence level: A
- Market applicability: Liquid crypto majors, especially BTC-led markets.
- Time horizon: Multi-day swing to medium-horizon systematic trading.
- Known failure modes: Sideways chopping, abrupt reversals, crowded momentum unwind.
- Cost sensitivity: Moderate.
- Implementation implication: 應作為目前主線，優先補短期失敗退出、universe selection、walk-forward、成本模型。
- Decision for this repo: Keep as the main strategy track.
- Sources:
  - [A Decade of Evidence of Trend Following Investing in Cryptocurrencies](https://arxiv.org/abs/2009.12155)
  - [Trend-Following Strategies via Dynamic Momentum Learning](https://arxiv.org/abs/2106.08420)
  - [Enhancing Time Series Momentum Strategies Using Deep Neural Networks](https://arxiv.org/abs/1904.04912)
  - [Systematic Trend-Following with Adaptive Portfolio Construction: Enhancing Risk-Adjusted Alpha in Cryptocurrency Markets](https://arxiv.org/abs/2602.11708)

### 2. Carry / Funding / Basis

- Claim: 對 crypto 來說，carry、funding、basis 是很有代表性的 crypto-native alpha，但和目前 repo 的方向單架構不同。
- Evidence level: B
- Market applicability: Perpetual futures and derivatives-heavy environments.
- Time horizon: Funding cycles to medium holding periods.
- Known failure modes: Funding regime change, basis collapse, borrow or execution frictions.
- Cost sensitivity: Moderate to high.
- Implementation implication: 這是值得記錄的第二主線，但不應混入目前的 trend-only live 策略。
- Decision for this repo: Track for future expansion, not current mainline.
- Sources:
  - [Fundamentals of Perpetual Futures](https://arxiv.org/abs/2212.06888)
  - [Designing funding rates for perpetual futures in cryptocurrency markets](https://arxiv.org/abs/2506.08573)

### 3. Microstructure / Order Flow

- Claim: 如果未來要做更 crypto-native 的短週期 alpha，order flow imbalance 與 microstructure 比單純 chart pattern 更有研究根據。
- Evidence level: A
- Market applicability: Intraday or very short-horizon strategies with richer exchange data.
- Time horizon: Intraday to sub-minute.
- Known failure modes: Data granularity mismatch, spread drag, adverse selection.
- Cost sensitivity: Very high.
- Implementation implication: 這是長期方向，但需要 order book / trade-level data，暫時不適合直接落在現在 candle-based repo。
- Decision for this repo: Track as future research, not current implementation path.
- Sources:
  - [The Price Impact of Order Book Events](https://arxiv.org/abs/1011.6402)
  - [The Price Impact of Generalized Order Flow Imbalance](https://arxiv.org/abs/2112.02947)
  - [Explainable Patterns in Cryptocurrency Microstructure](https://arxiv.org/abs/2602.00776)

## Supporting Research Areas

### Volatility Management

- Claim: 波動度感知的 sizing 與 stop 管理，通常比單純提高 leverage 更可靠。
- Evidence level: B
- Market applicability: Broad, especially crypto.
- Time horizon: Cross-horizon.
- Known failure modes: ATR lag, false precision, leverage semantics mismatch.
- Cost sensitivity: Moderate.
- Implementation implication: 保留 ATR-linked risk control，但不要把目前 leverage 參數當成已驗證優勢來源。
- Decision for this repo: Keep.

### Regime Filter

- Claim: 趨勢策略在有 regime awareness 時通常更穩定，尤其是 crypto 這種 BTC 主導市場。
- Evidence level: B
- Market applicability: Crypto directional portfolios.
- Time horizon: Multi-day regime transitions.
- Known failure modes: Filter lag, missed reversals, threshold instability.
- Cost sensitivity: Low.
- Implementation implication: 保留 BTC filter，但要重測閾值。
- Decision for this repo: Keep, but retest.

### FVG / Practitioner Pattern Logic

- Claim: FVG 類訊號更像 practitioner heuristic，而非已穩健驗證的因子。
- Evidence level: C
- Market applicability: Discretionary or semi-systematic swing trading.
- Time horizon: Short-to-medium.
- Known failure modes: Narrative overfitting, chart-resolution dependence, cost fragility.
- Cost sensitivity: Moderate to high.
- Implementation implication: 僅保留作歷史研究背景，不再作為現行策略開發分支。
- Decision for this repo: Removed from active strategy scope.
