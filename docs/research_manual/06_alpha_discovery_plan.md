# Alpha Discovery Plan

- Date: 2026-07-11
- Scope: Crypto spot and perpetual futures alpha discovery
- Primary venue assumptions: liquid major coins first, Hyperliquid live constraints, Binance-style historical data for broader research
- Objective: Find statistically testable alpha signals with economic reasons, realistic costs, and clear failure modes.

## Research Principle

This plan treats an alpha as a forecastable market inefficiency, not as a finished trading strategy. A candidate only becomes a strategy after it survives:

- Economic rationale: who is forced, slow, benchmarked, levered, or structurally constrained?
- Predictive test: does the feature forecast forward returns after costs?
- Strategy test: does a simple rule monetize the forecast without fragile parameters?
- Robustness test: does it survive coins, exchanges, timeframes, regimes, bootstrap, permutation, and randomized-entry comparisons?
- Implementation test: can the current repo execute it without weakening live protection, TP/SL logic, reconciliation, or event logging?

## Discovery Funnel

### Stage 1: Idea Intake

Each alpha candidate must answer six questions before any backtest:

- Why should this alpha exist?
- Which market participants create it?
- Why has it not disappeared?
- Which regimes should help it?
- Which regimes should break it?
- What assumptions must hold?

Reject the idea early if the answer is only "the indicator crosses a threshold."

### Stage 2: Data Readiness

Use the lowest-friction data first:

- Tier 1: OHLCV, ATR, returns, volume, realized volatility, BTC regime.
- Tier 2: funding, open interest, basis, liquidation prints.
- Tier 3: trades, order book snapshots, volume delta, spread, imbalance.
- Tier 4: on-chain exchange flows, SOPR, MVRV, realized cap, whale transfers.
- Tier 5: social/news/search/developer activity.

Near-term repo implementation should prioritize Tier 1 and Tier 2. Tier 3+ needs dedicated capture and replay before live use.

### Stage 3: Signal Test Before Strategy Test

For each feature:

- Compute forward returns over 1, 3, 6, 12, 24, and 72 bars.
- Bucket feature values into deciles or percentiles.
- Measure monotonicity, hit rate, mean return, median return, downside tail, and turnover.
- Compare against randomized entry and same-volatility random-entry baselines.
- Run the same test by regime: bull, bear, sideways, high volatility, low volatility.

Only then build trading rules.

### Stage 4: Backtest Standard

Required validation for every promoted candidate:

- In-sample: first 60% of history, used for rough parameter ranges.
- Out-of-sample: final 40%, untouched during tuning.
- Walk-forward: rolling train/test windows, for example 180d train / 60d test or 365d train / 90d test.
- Cross-validation: split by time and by coin.
- Monte Carlo: trade-order reshuffling and return-path resampling.
- Transaction costs: maker/taker fees, spread, slippage, and funding costs.
- Stress costs: 1x, 2x, and 3x assumed cost levels.
- Robustness: parameter sensitivity, different coins, different exchanges, different timeframes, bull/bear markets, randomized entry, bootstrap, permutation test.

Core metrics:

- CAGR, Sharpe, Sortino, Calmar, profit factor, win rate, max drawdown, average trade, expectancy, turnover.

## Ranked Alpha Candidates

Scoring uses 1 to 5, where 5 is best. Higher total means more attractive. Decay risk is inverted: 5 means lower expected decay risk.

| Rank | Alpha | Category | Robustness | Scalability | Ease | Data | Low Decay Risk | Total | Near-Term Fit |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | BTC-Regime Trend Continuation | Trend | 5 | 5 | 5 | 5 | 4 | 24 | High |
| 2 | Funding Extremes Mean Reversion | Derivatives | 4 | 4 | 4 | 4 | 4 | 20 | High |
| 3 | OI Expansion With Price Confirmation | Derivatives / Trend | 4 | 4 | 4 | 4 | 3 | 19 | High |
| 4 | Volatility Compression Breakout | Trend / Volatility | 4 | 4 | 5 | 5 | 1 | 19 | High |
| 5 | Liquidation Cascade Reversal | Derivatives / Mean Reversion | 3 | 3 | 3 | 3 | 3 | 15 | Medium |
| 6 | Exchange Netflow Pressure | On-chain | 4 | 3 | 2 | 2 | 4 | 15 | Medium |
| 7 | ETH/BTC Rotation Momentum | Cross Market | 3 | 4 | 5 | 5 | 1 | 18 | Medium |
| 8 | VWAP Deviation Reversion In Range Regime | Mean Reversion | 3 | 3 | 5 | 5 | 2 | 18 | Medium |
| 9 | Order Flow Imbalance Continuation | Microstructure | 4 | 2 | 1 | 1 | 3 | 11 | Long-Term |
| 10 | Stablecoin Liquidity Impulse | Cross Market / On-chain | 3 | 4 | 2 | 2 | 4 | 15 | Long-Term |
| 11 | Sentiment Exhaustion Fade | Sentiment | 2 | 3 | 2 | 2 | 2 | 11 | Experimental |
| 12 | Calendar Basis Compression | Derivatives | 4 | 3 | 2 | 2 | 4 | 15 | Future Track |

### 1. BTC-Regime Trend Continuation

- Hypothesis: Crypto majors exhibit persistent time-series momentum because capital flows, benchmark behavior, leverage, and retail attention reinforce BTC-led trends.
- Market logic: When BTC trend, volume, and volatility confirm, alt majors often continue in the same direction until the regime weakens or leverage unwinds.
- Participants creating it: trend funds, retail momentum traders, miners/treasuries adjusting exposure, derivatives traders adding pro-cyclical leverage.
- Why it persists: crypto trades 24/7, information diffusion is uneven, forced deleveraging creates path dependence, and many participants are flow-driven rather than valuation-driven.
- Required data: OHLCV, BTC OHLCV, volume, ATR, realized volatility; optional funding and OI as confirmation.
- Feature engineering: EMA slope, return momentum, ATR percentile, rolling volume z-score, price position in recent range, BTC regime score.
- Trading rules: enter long when coin momentum and BTC regime are positive; enter short only when BTC regime is negative and coin trend confirms; exit on trend failure, ATR trailing stop, max hold, or BTC regime flip; stop loss 1.5x to 3.0x ATR; take profit via trailing stop rather than fixed target; size by ATR risk and cap correlated exposure; holding period 3 to 45 days.
- Market regime: works best in bull and bear trends, high directional volatility, and BTC-led markets; weaker in sideways chop and post-liquidation reversals.
- Risks: crowded momentum unwind, delayed regime filter, overextended entries, exchange-specific liquidity differences.
- Assumptions: BTC remains the dominant regime driver; trend continuation exceeds fees and slippage; entries avoid recent-range extremes.
- Validation: test daily and 4h bars across BTC, ETH, SOL, BNB, DOGE, BCH, OP, NEAR; run no-BTC-filter ablation; compare against buy-and-hold and randomized entries; include taker and maker cost scenarios.
- Robustness tests: EMA windows, ATR windows, BTC filter thresholds, coin universes, bull/bear splits, walk-forward, bootstrap, permutation.

### 2. Funding Extremes Mean Reversion

- Hypothesis: Extreme positive funding implies crowded longs; extreme negative funding implies crowded shorts. Crowded positioning raises the probability of adverse price moves or at least lower forward returns for the crowded side.
- Market logic: Funding transfers capital from crowded side to uncrowded side. When funding is extreme, marginal leverage is expensive and liquidation risk increases.
- Participants creating it: leveraged retail, basis arbitrage desks, directional perp traders, market makers hedging inventory.
- Why it persists: many traders optimize for directional exposure, not carry-adjusted returns; funding is path dependent and can stay extreme before mean reverting.
- Required data: perp funding, OHLCV, open interest, mark/index price, fees; optional basis and liquidation data.
- Feature engineering: funding z-score, funding percentile, cumulative funding over 1d/3d/7d, funding-price divergence, OI confirmation.
- Trading rules: fade extreme funding only when price momentum stalls; long when funding is deeply negative and price stops making new lows; short when funding is deeply positive and price fails to continue; exit when funding normalizes or price confirms trend continuation against the trade; stop loss by ATR; take profit at funding mean reversion or 1.5R to 2R; smaller sizing during high OI spikes; holding period 8h to 7d.
- Market regime: strongest in sideways or late-trend crowded conditions; dangerous in early strong trend where funding can remain extreme.
- Risks: "expensive for a reason" trends, data differences between exchanges, funding schedule changes, borrow or execution friction.
- Assumptions: funding reflects positioning pressure; the venue's funding data is reliable; carry plus price move beats transaction costs.
- Validation: separate price PnL, funding PnL, and total PnL; include funding payment timestamps; test top liquid perps; run trend-regime filters to avoid fading early breakouts.
- Robustness tests: funding thresholds, z-score windows, exchange splits, holding periods, funding-only vs price+funding, bootstrap, permutation.

### 3. OI Expansion With Price Confirmation

- Hypothesis: Rising open interest with price movement indicates new leveraged participation, which can fuel continuation until positioning becomes unstable.
- Market logic: Price up plus OI up suggests new longs are entering; price down plus OI up suggests new shorts. Continuation is likely while liquidations do not interrupt the move.
- Participants creating it: leveraged directional traders, CTA-like momentum funds, market makers hedging perp inventory.
- Why it persists: OI growth is not purely public in trader decision loops, and many participants react after the move has started.
- Required data: OHLCV, open interest, funding, liquidation data if available.
- Feature engineering: OI percentage change, OI z-score, price return z-score, funding filter, OI/volume ratio.
- Trading rules: enter with price direction when OI expansion exceeds percentile threshold and funding is not yet extreme; exit on OI contraction, price reversal, funding extreme, or ATR stop; stop loss 1.5x ATR; take profit through trailing stop; size smaller when OI expansion is too large; holding period 4h to 10d.
- Market regime: works in breakout and early trend regimes; fails in liquidation cascades and crowded late trends.
- Risks: OI reporting inconsistency, false leverage build-up, exchange-specific noise.
- Assumptions: OI data is timely and comparable; OI expansion represents new risk, not only exchange accounting artifacts.
- Validation: test OI+price vs price-only; separate early-trend and late-trend regimes; include funding and liquidation cost effects.
- Robustness tests: OI windows, percentile thresholds, funding caps, coins, exchanges, timeframes, randomized entry.

### 4. Volatility Compression Breakout

- Hypothesis: After volatility compresses, stop orders and delayed participation accumulate around range boundaries. A real breakout can force re-pricing.
- Market logic: Low realized volatility reduces attention and liquidity; a range break triggers stop orders, momentum entries, and volatility targeting flows.
- Participants creating it: breakout traders, market makers reducing inventory, stop-loss clusters, volatility-targeted strategies.
- Why it persists: markets cycle between liquidity provision and liquidity demand; compression cannot eliminate future information shocks.
- Required data: OHLCV, volume, ATR, realized volatility; optional order book depth.
- Feature engineering: ATR percentile, Bollinger bandwidth percentile, range width, volume expansion, close location value.
- Trading rules: enter on close outside compressed range with volume expansion and BTC regime alignment; exit on failed breakout back into range, ATR trail, or max hold; stop loss inside range or 1.5x ATR; take profit via 2R partial plus trailing remainder; size inversely to ATR; holding period 1h to 10d depending timeframe.
- Market regime: strongest after low-volatility sideways periods; weaker during high-volatility chop and news-driven fakeouts.
- Risks: heavily watched signal, false breakouts, fees from repeated attempts.
- Assumptions: breakout follow-through is large enough to pay for failed attempts.
- Validation: explicitly measure false breakout rate, average follow-through, and cost-adjusted expectancy.
- Robustness tests: compression windows, breakout thresholds, volume filters, timeframes, randomized breakout dates.

### 5. Liquidation Cascade Reversal

- Hypothesis: Forced liquidations create temporary price dislocations when mechanical selling or buying exhausts available liquidity.
- Market logic: After a liquidation spike, marginal forced flow can dry up, allowing price to mean revert toward pre-cascade levels.
- Participants creating it: overleveraged perp traders, liquidation engines, market makers widening spreads, arbitrageurs.
- Why it persists: forced execution is not alpha-seeking and often occurs in poor liquidity.
- Required data: liquidation prints, OHLCV, funding, OI, spread or order book depth if available.
- Feature engineering: liquidation notional z-score, liquidation/volume ratio, OI drop, wick size, rebound volume.
- Trading rules: enter opposite the liquidation direction only after price stabilizes; exit at VWAP/reversion target, OI normalization, or time stop; stop loss beyond liquidation extreme; take profit 1R to 2R or VWAP; small sizing due tail risk; holding period minutes to 48h.
- Market regime: works after one-sided liquidation shocks; fails in genuine information-driven repricing.
- Risks: catching falling knives, incomplete liquidation data, extreme slippage.
- Assumptions: liquidation flow is temporary and observable quickly enough.
- Validation: event study around liquidation spikes; compare immediate fade vs delayed confirmation; include severe slippage.
- Robustness tests: event thresholds, confirmation delay, exchange source, bull/bear split, bootstrap event samples.

### 6. Exchange Netflow Pressure

- Hypothesis: Large exchange inflows often indicate potential sell supply; large outflows can indicate reduced liquid supply or accumulation.
- Market logic: Coins moving to exchanges are more likely to become available for sale; coins leaving exchanges may reduce near-term float.
- Participants creating it: whales, funds, market makers, custodians, miners, treasury managers.
- Why it persists: on-chain transfer intent is noisy but not instantly incorporated, especially outside BTC/ETH.
- Required data: exchange netflow, whale transfers, OHLCV, realized volatility.
- Feature engineering: netflow z-score, netflow/market-cap ratio, whale-transfer percentile, lagged return controls.
- Trading rules: reduce longs or short after large inflow with weak price action; long after outflow with trend confirmation; exit after flow signal decays or price invalidates; stop loss ATR-based; take profit at 1.5R to 3R; holding period 1d to 30d.
- Market regime: useful in slower spot-led markets; weaker during derivatives-led intraday moves.
- Risks: address labeling errors, internal exchange wallet movements, delayed data.
- Assumptions: flow labels are reliable and transfer intent has predictive content.
- Validation: event study by coin; lag analysis; distinguish stable exchange wallet reshuffling from true user flow.
- Robustness tests: provider comparison, flow thresholds, holding periods, BTC vs alt splits, permutation of event dates.

### 7. ETH/BTC Rotation Momentum

- Hypothesis: Capital rotates between BTC beta and ETH/high-beta crypto exposure. ETH/BTC trend can proxy risk appetite and sector rotation.
- Market logic: ETH outperforming BTC often coincides with broader risk-on crypto conditions; ETH underperformance implies defensive BTC-led regime.
- Participants creating it: crypto funds, relative-value traders, ecosystem allocation flows, ETF and institutional allocators.
- Why it persists: capital allocation changes occur gradually and are constrained by mandates, liquidity, and narratives.
- Required data: BTC and ETH OHLCV, alt basket OHLCV, dominance or market-cap data.
- Feature engineering: ETH/BTC returns, relative strength z-score, rolling correlation, dominance trend, sector basket momentum.
- Trading rules: overweight ETH/high-beta basket when ETH/BTC trend is positive; overweight BTC or reduce alt exposure when negative; exit on relative trend break; stop loss on basket ATR; position size by volatility and correlation; holding period 7d to 90d.
- Market regime: works in broad bull/risk-on rotations; fails during idiosyncratic ETH events or BTC-only macro shocks.
- Risks: structural ETH narrative changes, ETF flow distortions, alt liquidity collapse.
- Assumptions: ETH/BTC remains an informative risk appetite proxy.
- Validation: compare BTC-only, ETH-only, and dynamic rotation; test sector baskets; include turnover and rebalancing costs.
- Robustness tests: lookback windows, rebalance frequency, alt basket composition, bull/bear splits, bootstrap.

### 8. VWAP Deviation Reversion In Range Regime

- Hypothesis: In non-trending liquid markets, extreme deviations from intraday VWAP often reflect temporary liquidity demand rather than new information.
- Market logic: Market makers, TWAP/VWAP execution, and arbitrageurs anchor short-horizon price around volume-weighted fair value when trend pressure is absent.
- Participants creating it: execution algorithms, liquidity takers, market makers, short-term discretionary traders.
- Why it persists: urgent flow pays immediacy costs; passive liquidity earns reversion when adverse selection is low.
- Required data: intraday OHLCV or trades, VWAP, spread if available, BTC regime.
- Feature engineering: VWAP deviation z-score, realized volatility, volume percentile, trend filter, distance from session high/low.
- Trading rules: fade large VWAP deviations only in sideways regime; exit at VWAP, time stop, or regime flip; stop loss beyond recent swing or 1x ATR; take profit at VWAP or 1R; use small size and strict turnover cap; holding period 15m to 12h.
- Market regime: works in low-trend sideways markets; fails during breakouts and liquidation cascades.
- Risks: cost fragility, adverse selection, overtrading.
- Assumptions: spread and taker/maker costs are low enough; regime filter avoids trend days.
- Validation: test with conservative cost model and turnover caps; compare maker-only vs taker execution.
- Robustness tests: VWAP window, z-score threshold, regime filter, timeframes, exchanges, randomized entries.

### 9. Order Flow Imbalance Continuation

- Hypothesis: Persistent aggressive buying or selling predicts short-term continuation because liquidity providers adjust quotes after toxic flow.
- Market logic: When market orders consume one side of the book faster than liquidity replenishes, price impact continues over short horizons.
- Participants creating it: informed traders, liquidation flow, urgent hedgers, market makers updating inventory.
- Why it persists: latency, inventory constraints, and asymmetric information prevent immediate full adjustment.
- Required data: trades, order book, bid/ask depth, spread, cancellations, volume delta.
- Feature engineering: order flow imbalance, volume delta, queue imbalance, spread expansion, depth depletion, trade sign classification.
- Trading rules: enter with imbalance when spread is controlled and depth confirms; exit on imbalance decay, spread expansion, or time stop; stop loss in ticks or micro ATR; take profit by short fixed horizon or opposite imbalance; position size by depth and spread; holding period seconds to minutes.
- Market regime: works in liquid high-activity periods; fails in thin books, news shocks, or latency-disadvantaged execution.
- Risks: data infrastructure, queue-position uncertainty, adverse selection, rapid decay.
- Assumptions: data is event-level and execution can be modeled realistically.
- Validation: order book replay, maker/taker fill simulation, latency sensitivity, adverse selection analysis.
- Robustness tests: venues, symbols, latency assumptions, spread buckets, randomized order flow signs.

### 10. Stablecoin Liquidity Impulse

- Hypothesis: Stablecoin supply and exchange inflows can proxy deployable crypto purchasing power.
- Market logic: Stablecoin minting or large exchange inflows may precede buying pressure; stablecoin redemptions can reduce risk appetite.
- Participants creating it: funds, OTC desks, stablecoin issuers, exchange users moving dry powder.
- Why it persists: capital deployment is staged and does not always happen instantly.
- Required data: stablecoin supply, exchange stablecoin balances, OHLCV, market-cap data.
- Feature engineering: stablecoin supply growth, exchange stablecoin inflow z-score, stablecoin market-cap ratio, lagged BTC returns.
- Trading rules: long BTC/major basket when stablecoin liquidity impulse is positive and BTC trend confirms; reduce risk when impulse turns negative; exit on liquidity reversal or BTC trend failure; ATR stop; holding period 7d to 60d.
- Market regime: works in macro liquidity-driven bull regimes; weak during idiosyncratic shocks.
- Risks: stablecoin data revisions, regulatory effects, issuer-specific events.
- Assumptions: stablecoin growth maps to deployable exchange liquidity.
- Validation: lagged predictive regressions and event studies; compare to BTC trend-only.
- Robustness tests: stablecoin universe definitions, lags, exchange-only vs total supply, bull/bear splits.

### 11. Sentiment Exhaustion Fade

- Hypothesis: Extremely one-sided social/news attention can indicate crowded positioning and late-stage retail participation.
- Market logic: When sentiment reaches extremes after a large price move, marginal buyers or sellers may already be committed.
- Participants creating it: retail traders, influencers, news-driven funds, short-term narrative traders.
- Why it persists: attention cycles are behavioral and recurring, but noisy.
- Required data: Twitter/X, Reddit, Telegram, Google Trends, Fear & Greed, news, OHLCV.
- Feature engineering: attention z-score, sentiment polarity, sentiment-price divergence, volume confirmation.
- Trading rules: fade extreme positive sentiment only when price momentum weakens; fade extreme negative sentiment only after forced-selling signs stabilize; exit on sentiment normalization or price invalidation; ATR stop; small size; holding period 1d to 14d.
- Market regime: works near late-stage euphoric or panic moves; fails during real repricing.
- Risks: noisy APIs, bot activity, survivorship bias, data availability changes.
- Assumptions: sentiment data is timestamped, representative, and not too delayed.
- Validation: event study around sentiment extremes; compare to price-only reversal; strict out-of-sample due overfit risk.
- Robustness tests: source splits, language filters, bot filters, event thresholds, permutation tests.

### 12. Calendar Basis Compression

- Hypothesis: Futures basis can become too rich or too cheap when leverage, hedging demand, or funding expectations become imbalanced.
- Market logic: Arbitrage capital compresses basis, but balance sheet limits and execution frictions slow the process.
- Participants creating it: cash-and-carry desks, leveraged funds, miners, structured product desks, market makers.
- Why it persists: capital, margin, and venue constraints prevent instant convergence.
- Required data: spot price, perp price, dated futures price, funding, borrow/financing estimates, fees.
- Feature engineering: annualized basis, basis z-score, carry after fees, funding-adjusted basis, calendar spread.
- Trading rules: enter relative-value spread when basis exceeds cost-adjusted threshold; exit on basis normalization, funding change, or risk limit; stop loss on spread widening and margin drawdown; size by spread volatility and collateral; holding period days to expiry.
- Market regime: works in derivatives dislocations and stable liquidity regimes; fails during exchange stress or sharp directional moves.
- Risks: margin/liquidation risk, execution complexity, exchange counterparty risk, borrow constraints.
- Assumptions: both legs can be executed and margined safely; basis data is synchronized.
- Validation: spread backtest with financing and funding; simulate margin calls and leg slippage.
- Robustness tests: venue pairs, expiry buckets, cost assumptions, stress basis widening, walk-forward.

## Recommended Top 3 For This Repo

### 1. BTC-Regime Trend Continuation

This is the best near-term implementation path because it matches the current repo architecture, existing daily trend strategy, and live safety design. It also has the best data availability and lowest infrastructure burden. The next useful research step is not a new indicator; it is a cleaner alpha report that measures whether BTC regime filters improve forward return distribution after costs.

### 2. Funding Extremes Mean Reversion

This is the strongest crypto-native alpha candidate that does not require order book infrastructure. It should be built as a research/reporting module first, with price PnL and funding PnL separated. It is also naturally compatible with Hyperliquid perp execution once validated.

### 3. OI Expansion With Price Confirmation

This is a practical bridge between trend and derivatives data. It can improve the current trend framework by distinguishing price moves with fresh leverage behind them from price moves on weak participation. It should be tested as a confirmation filter before becoming a standalone strategy.

## Implementation Roadmap

### Phase 1: Alpha Research Reports

- Add a reusable alpha report that computes feature buckets, forward returns, costs, and randomized-entry comparisons.
- Start with `btc_regime_trend`, `funding_extreme_reversion`, and `oi_expansion_confirmation`.
- Output CSV/Markdown summaries before adding any live-facing strategy code.

### Phase 2: Cost-Aware Backtests

- Extend backtest reporting with maker/taker fee, spread, slippage, and funding assumptions.
- Report gross PnL, cost drag, funding PnL, net PnL, turnover, and average trade.
- Reject intraday candidates whose average trade cannot survive 2x cost assumptions.

### Phase 3: Strategy Promotion

- Promote only one candidate at a time into `src/trading_strategy/strategies/`.
- Keep live execution protected by existing strategy hooks and TP/SL safeguards.
- Require paper-only deployment before any live use.

## Sources To Recheck During Implementation

- Hyperliquid fee tiers and maker/taker assumptions: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
- Binance USD-M funding history endpoint: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#get-funding-rate-history
- Binance USD-M open interest endpoint: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#open-interest
- Perpetual futures funding mechanics: https://arxiv.org/abs/2212.06888
- Open interest data reliability caveat: https://arxiv.org/abs/2310.14973
- Order flow imbalance research basis: https://arxiv.org/abs/2112.02947
