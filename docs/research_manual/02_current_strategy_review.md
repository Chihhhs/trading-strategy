# Current Strategy Review

- Date: 2026-07-05
- Data range: Current repo code, local 240-day backtest snapshots, and historical 50-coin notes in `docs/backtest_results.md`
- Applicable markets: BTC, ETH, SOL, BNB plus prior 50-coin research context
- Last updated: 2026-07-05

## Current Local Baseline

- `trend`, 240 days, `BTC,ETH,SOL,BNB`, `risk=0.03`, `leverage=2.0`: `trades=21`, `win_rate=42.9%`, `pnl=+9.5%`, `drawdown=13.8%`
- `trend`, 240 days, `BTC` only, `risk=0.03`, `leverage=2.0`: `trades=9`, `win_rate=55.6%`, `pnl=+15.8%`, `drawdown=3.6%`
- Optimizer snapshot: top-ranked combinations were all `trend + btc_filter_on + risk_pct 0.03`, and `leverage=2/3/5` showed nearly identical results under the current sizing model.

## Historical 50-Coin Context

The older 50-coin backtest notes in [docs/backtest_results.md](/D:/code/trading-strategy/docs/backtest_results.md) are still useful as context:

- They suggest trend-oriented logic was stronger than pure FVG in the older research cycle.
- They suggest BTC filter, dynamic stop, and risk controls improved headline results.
- They also show very large drawdowns, so those results should be treated as research direction, not deployment proof.

## Strategy Component Decisions

### Trend Core

- Claim: Trend is currently the strongest implemented strategy family in this repo.
- Evidence level: A/B
- Market applicability: Liquid crypto majors.
- Time horizon: Multi-day swing horizons.
- Known failure modes: Choppy markets, late reversal response, unstable thresholds.
- Cost sensitivity: Moderate.
- Implementation implication: Keep as the primary line and focus new work here first.
- Decision for this repo: Keep.

### BTC Filter

- Claim: BTC is a reasonable regime proxy for a crypto trend strategy, but the threshold values are not yet settled.
- Evidence level: B
- Market applicability: Crypto directional trading.
- Time horizon: Multi-day regime shifts.
- Known failure modes: Late transitions, over-filtering, binary-state oversimplification.
- Cost sensitivity: Low direct sensitivity.
- Implementation implication: Keep the concept, retest lookback and threshold choices.
- Decision for this repo: Keep, but retest.

### ATR Stop / Dynamic Stop

- Claim: ATR-based stop placement plus staged stop upgrade is more defensible than rigid fixed TP for trend trades.
- Evidence level: A/B
- Market applicability: Trend-following in volatile markets.
- Time horizon: Entry through trend management lifecycle.
- Known failure modes: ATR lag, premature stop migration, live/backtest exit mismatch.
- Cost sensitivity: Moderate.
- Implementation implication: Keep the idea, but align backtest and live exit semantics.
- Decision for this repo: Keep.

### Short-Term Failure Exit

- Claim: The current live implementation has protection and reversal exits, but still lacks a dedicated short-term failed-breakout / no-follow-through exit.
- Evidence level: B
- Market applicability: Crypto trend live trading.
- Time horizon: Early post-entry bars.
- Known failure modes: Giving back edge in noisy pullbacks, capital getting stuck in weak trades.
- Cost sensitivity: Moderate.
- Implementation implication: Add a trend-specific short-term failure exit as the next live-trading improvement.
- Decision for this repo: Validate and implement.

### Leverage / Sizing Semantics

- Claim: Current leverage behavior should not be read as validated alpha, because optimizer output barely changes across leverage settings.
- Evidence level: B
- Market applicability: Entire repo.
- Time horizon: All trades.
- Known failure modes: Misleading optimization, wrong drawdown expectations, false confidence in exposure controls.
- Cost sensitivity: Indirectly high.
- Implementation implication: Downgrade leverage as a research knob until sizing semantics are corrected.
- Decision for this repo: Downgrade.

### FVG Signal

- Claim: FVG is weaker than trend both in evidence quality and in current repo status.
- Evidence level: C
- Market applicability: Pattern-based discretionary-style setups.
- Time horizon: Short-to-medium swing entries.
- Known failure modes: Overfitting, unstable definitions, cost fragility.
- Cost sensitivity: Moderate to high.
- Implementation implication: 不再作為現行程式碼中的策略分支；若未來重啟，只能在獨立研究分支中重新證明。
- Decision for this repo: Removed from active strategy scope.

### `both` Auto-Switching

- Claim: `both` is not independently validated alpha; it is only a composition rule.
- Evidence level: C
- Market applicability: Multi-regime composition problems.
- Time horizon: Whole strategy lifecycle.
- Known failure modes: One weak branch diluting one strong branch, hidden complexity, unstable regime boundaries.
- Cost sensitivity: Moderate.
- Implementation implication: 已隨 FVG 移除，不再作為現行策略組合方式。
- Decision for this repo: Removed from active strategy scope.

### Universe Selection

- Claim: BTC currently appears to carry most of the defensible edge, while ETH/BNB dilute results and SOL is inactive in the sampled local window.
- Evidence level: B
- Market applicability: Current major-coin universe.
- Time horizon: Current 240-day snapshot plus historical 50-coin context.
- Known failure modes: Window dependence, changing market leadership, liquidity regime change.
- Cost sensitivity: High beyond BTC and top-liquidity names.
- Implementation implication: Use `BTC-only` as the baseline, then re-add coins only if they improve risk-adjusted outcomes.
- Decision for this repo: Validate further.
