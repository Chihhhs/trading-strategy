# Research Backlog

- Date: 2026-07-05
- Data range: Current repo behavior, cited research, and existing 50-coin research notes
- Applicable markets: Current crypto majors and future liquid-coin expansions
- Last updated: 2026-07-14

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

### 0.1 Trend Anti-Chase Entry Filters

- Claim: Trend entries should avoid buying at the top of the recent range, shorting at the bottom, entering at extreme RSI, and entering during abnormal ATR spikes.
- Evidence level: B
- Market applicability: Liquid crypto majors and trend baskets.
- Time horizon: Entry quality for swing trend trades.
- Known failure modes: 過濾太嚴會錯過 breakout continuation；過濾太鬆會追高後被回調洗掉。
- Cost sensitivity: Moderate, because lower-quality entries create avoidable stop churn.
- Implementation implication: `trend` now supports configurable RSI, ATR%, price-position, and 60-bar overextension filters. Use `--disable-trend-entry-filter` for old-behavior A/B checks.
- Decision for this repo: Validate further.

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

### 6. Short-Cycle Measurement And Ablation

- Claim: 現有 `intraday_momentum` 的問題不是單純 turnover，而是成本前 edge 偏弱、八根 bar 內再入場負期望、short side 與 volume confirmation 失準，以及回測/live 執行語義不一致。
- Evidence level: B
- Market applicability: BTC, ETH, SOL, BNB 15m fixture；尚未證明可外推。
- Time horizon: 15m entries, intraday to multi-hour holds.
- Known failure modes: Relative-only promotion gate、MFE/MAE R 缺失、no-op candidate、同一窗口挑選 cooldown。
- Cost sensitivity: Very high.
- Implementation implication: 先補量測與 absolute gate，再做 refractory period、direction、score component、session 的單因素消融。
- Decision for this repo: Highest-priority short-cycle workstream; research-only. See [08_short_cycle_strategy_diagnosis_2026-07-14.md](08_short_cycle_strategy_diagnosis_2026-07-14.md).

### 7. Regime-Conditioned VWAP Reversion

- Claim: VWAP reversion 在最近 rolling/train-test window 的 12/24-bar forward return 與 random delta 轉正，但全樣本與較早窗口仍為負。
- Evidence level: B/C
- Market applicability: High-liquidity crypto majors；需 session、liquidity 與 event-time conditioning。
- Time horizon: 15m signal, 3-24 bars forward horizon.
- Known failure modes: Window dependence, strong trends, liquidation cascades, cost drag, session concentration.
- Cost sensitivity: Very high.
- Implementation implication: 在 frozen OOS、random baseline 與 live-like cost model 下獨立研究；不可直接取代目前策略或接 paper/live。
- Decision for this repo: Primary alternative-alpha candidate after measurement integrity is fixed.

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
