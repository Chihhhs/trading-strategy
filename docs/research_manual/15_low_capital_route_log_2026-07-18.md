# Low-capital strategy route log

Date: 2026-07-18

## Research contract

- Target account: below 100 USDC; research baseline 50 USDC.
- Hyperliquid minimum order: 10 USDC.
- At most one position for the short-cycle search, with 50% target notional and no leverage multiplier.
- Costs: 6.5 bps one way normally and 10 bps one way under stress, plus actual Hyperliquid funding.
- Every route keeps its hypothesis, fixed parameter grid, fold evidence, gate failures, and review. Failed routes remain negative evidence.
- No order API is imported and every artifact records `execution_authorized: false`.

## Route 0: multi-leg cross-sectional momentum

Decision: unsuitable for the user's capital, retained only as a larger-account candidate.

The seven-leg opening plan first becomes complete around 450 USDC. Below 100 USDC it loses several intended legs and develops material directional exposure. Scaling it down would change the strategy rather than preserve it.

Review: a market-neutral portfolio can pass return gates and still be operationally wrong for a small account. Minimum-notional feasibility is now a strategy-selection constraint, not a deployment detail.

## Route 1: low-capital long-cycle time-series momentum

Decision: deferred before holdout because the cycle does not match the user's preference.

Fresh Binance USD-M 4h prices and Hyperliquid funding were tested at 50 USDC across 28 predeclared candidates. Only ETH 56-day time-series momentum passed the five 120-day development folds: 4/5 positive under normal and stressed costs, stressed median return +19.01%, and stressed worst drawdown 18.62%.

Review: the result establishes that a one-leg account can satisfy minimum-order constraints, but it does not answer the requested short-cycle objective. The final 180-day holdout remains locked and the candidate is not promoted.

## Route 2: 1h prior-range breakout

Decision: rejected in development.

The best fixed candidate was ETH with a 48-hour range and 12-hour maximum hold. It produced only 3/6 positive folds. Normal median return was +1.49% with Sharpe 0.37; stressed median return fell to -1.26% and stressed worst drawdown rose to 20.96%.

Review: the route generated 875 orders across the folds, so the issue was not insufficient activity. Breakout persistence was inconsistent and transaction friction removed the already-small median edge.

## Route 3: 1h mean reversion

Decision: rejected in development.

The best fixed candidate was SOL with a 48-hour reference window, two-sigma entry, and 12-hour maximum hold. It produced 3/6 positive normal folds and 2/6 positive stressed folds. Median return was -0.74% normally and -3.42% under stress.

Review: large hourly dislocations did not revert reliably within the allowed holding window. Costs worsened the result but the normal-cost median was already negative.

## Route 4: 1h volatility-scaled return momentum

Decision: rejected in the locked 90-day holdout.

Only one of 32 fixed candidates passed development: ETH, 24-hour return, 1.5 volatility threshold, and 12-hour maximum hold. It produced 5/6 positive normal and stressed folds, with normal median return +2.84%, normal median Sharpe 0.72, stressed median return +1.44%, and stressed worst drawdown 15.34%.

The once-opened 90-day holdout returned -10.27% after normal costs, Sharpe -3.05, and 12.04% maximum drawdown across 80 orders. With fees removed it still returned -7.91%, proving that the failure was a reversal of raw signal edge rather than minimum-order friction or trading cost alone.

Review: a strong development majority did not survive the next regime. This exact route and holdout are closed; no threshold, lookback, or holding-period tuning may use the opened interval.

## Multi-hour short-cycle routes under test

The next independent check still uses hourly K-lines and keeps every holding period below one day, but decisions occur every two or four hours to reduce noise and turnover. It compares:

1. two/four-hour volatility-scaled momentum decisions;
2. the same signal only when its direction agrees with a 72/168-hour trend.

Because the latest 90-day interval is now open, it is excluded from this new route. Development remains the six middle 90-day folds; a previously unused early 180-day interval is the locked validation segment. Results and failure reviews are appended after the development run.

## Route 5: two/four-hour decision momentum

Decision: rejected in development.

The best candidate used ETH, four-hour decisions, a 12-hour return, one-sigma threshold, and 12-hour maximum hold. Normal and stressed results were positive in only 4/6 folds. Despite a +11.81% normal median, normal worst drawdown was 29.96%; stressed worst drawdown reached 31.84%.

Review: reducing decision frequency raised the median but did not stabilize regime dependence. High median performance cannot compensate for two losing folds and drawdown above the fixed gate.

## Route 6: trend-aligned multi-hour momentum

Decision: rejected in development.

The best candidate used ETH, four-hour decisions, a 12-hour signal, 168-hour trend alignment, and 18-hour maximum hold. It again produced only 4/6 positive folds. Normal worst drawdown was 21.49% and stressed worst drawdown 22.22%.

Review: longer-trend agreement reduced turnover and drawdown relative to unfiltered multi-hour momentum, but it did not fix fold instability and still failed the absolute drawdown limit. The early validation segment remained locked.

## Context-driven short-cycle routes under test

The next predeclared routes are operationally distinct rather than another momentum threshold adjustment:

1. fade extreme observed Hyperliquid funding and hold for 6-12 hours;
2. follow or fade volatility-scaled ETH/SOL/BNB strength relative to BTC, using one executable altcoin leg.

## Route 7: momentum with post-entry trend extension

Decision: rejected in development.

This route implemented explicit `flat`, `impulse_entry`, `base_hold`, `strong_trend`, `decay_exit`, and `safety_exit` states. The best candidate used ETH 24-hour momentum, a 12-hour base hold, 168-hour trend confirmation, and up to 48 hours total holding. It produced a +2.61% normal median and +1.41% stressed median, with stressed worst drawdown 17.15%, but only 4/6 folds were positive under either cost model.

Review: conditional continuation reduced turnover from the fixed-hold route, but filtering only after entry allowed low-quality impulses to enter first. The early validation segment remained locked. The next route moves trend and efficiency classification to the entry boundary; range-state impulses remain flat.

## Route 8: entry-gated regime momentum

Decision: rejected in development.

Requiring impulse, 168-hour trend, and 24-hour path efficiency to agree before entry improved the best stressed worst drawdown to 11.33% and reduced orders to 302. The best BNB candidate retained a +2.46% stressed median and 0.70 stressed median Sharpe, but only 4/6 folds were positive.

Review: classification materially improved risk but did not remove regime instability. The result does not justify relaxing the 5/6 gate.

## Route 9: extreme funding fade

Decision: rejected in development as a standalone strategy; retained only as a possible crowding label.

The best ETH route faded absolute hourly funding of at least 0.005% and held at most 12 hours. Normal and stressed medians were +1.88% and +1.62%, with stressed worst drawdown 15.07%, but only 4/6 folds were positive.

Review: funding contains some directional context but is not sufficiently stable as the primary entry signal.

## Route 10: BTC-relative momentum and reversion

Decision: both rejected in development.

The best relative-momentum candidate produced only 3/6 positive folds and a -0.35% stressed median. The best relative-reversion candidate had a -4.38% normal median and -6.34% stressed median.

Review: an unhedged altcoin leg does not reliably monetize relative BTC strength. Neither relative route will be used as a momentum classifier.

## Funding-gated momentum under test

One final context combination is allowed: the entry-gated momentum state machine remains the primary signal, while an observed funding rate may block entries whose direction is already paying extreme funding. Funding cannot create a trade by itself.

## Route 11: funding-gated regime momentum

Decision: rejected in locked early validation.

Exactly one development candidate passed: BNB 12-hour momentum, 168-hour trend, 24-hour path efficiency of at least 0.4, and funding used only to block crowded entries. It produced 5/6 positive normal and stressed folds, a +0.96% stressed median, and 14.55% stressed worst drawdown. The blocker fired 34-174 times per fold and did not silently become a no-op.

The previously untouched early 180-day validation returned -10.92% after normal costs, Sharpe -2.15, and 14.77% maximum drawdown across 82 orders, with no minimum-order skips.

Review: funding context improved the selected development window but did not generalize across time. This exact combination is closed. A remaining structural hypothesis is asymmetric momentum: crypto's positive drift may support full-size long momentum while bearish states should be cash or smaller shorts rather than a symmetric reversal.

## Asymmetric momentum under test

Hourly state classification remains unchanged. Upward confirmed momentum targets 50% notional; bearish confirmed momentum is predeclared as either cash or a 25% short. A separate, still-unused 180-day interval between the opened early validation and development windows is reserved for validation.

## Route 12: asymmetric hourly momentum

Decision: rejected in development.

The best candidate was ETH long/cash: 12-hour impulse, 72-hour trend, 24-hour efficiency of at least 0.4, and up to 48 hours of strong-trend continuation. It produced a +3.89% normal median, +3.34% stressed median, and 10.66% stressed worst drawdown, but only 4/6 folds were positive. The two losing folds returned approximately -4.1% and -7.6% normally.

Review: long/cash asymmetry improved median return, turnover, and drawdown but retained clear time instability. The reserved validation interval remains locked.

## Route 13: fixed-limit multi-hour asymmetric momentum

Decision: not run; rejected by the operating requirement before evaluation.

The planned route would have reclassified every two/four hours but forced an exit after 48 hours. The user explicitly requires holding decisions to depend on current market state rather than elapsed holding time, so the fixed-limit experiment and its implementation were removed before seeing any result.

Review: holding-period limits can simplify risk, but they alter the requested strategy concept. Subsequent candidates may use 1h/4h decision cadence, but neither minimum nor maximum holding time.

## State-only momentum under test

Every decision is now state-driven. Entry requires momentum, longer-trend alignment, price-path efficiency, and acceptable funding crowding. A position remains open without a time limit while those conditions stay aligned; decay, conflict, or an opposite impulse causes exit or reversal. Long exposure is 50%; bearish states are cash or a 25% short.

## Route 14: 1h state-only momentum

Decision: rejected in locked Hyperliquid cross-venue replay.

Exactly one development candidate passed and then passed the unused Binance early validation: ETH long/cash, four-hour classification over 1h bars, 12-hour impulse, 168-hour trend, and no holding-time limit. Development had 5/6 positive folds; stressed median return was +0.61% with 8.61% worst drawdown. The 180-day validation returned +3.36% normally and +2.97% stressed, with 1.62% maximum drawdown. It remained executable from 25 USDC and observed a 28-hour maximum hold without a programmed cap.

The locked Hyperliquid-native latest 180-day replay then returned -3.21% normally and -3.97% stressed across 46 orders. No order was skipped for minimum notional, so execution constraints did not cause the failure.

Review: the state-only design met the user's holding rule and generalized to one separate time segment, but it did not transfer to recent venue-native prices. It cannot enter paper. The next route keeps state-only exits but raises the signal bar to native Hyperliquid 4h candles to reduce hourly noise.

## Route 15: native Hyperliquid 4h state-only momentum

Decision: rejected in development; holdout remains locked.

The best BNB route used a 12-hour impulse, seven-day trend, and 24-hour path efficiency. Normal results were positive in 4/5 folds with a +1.64% median and 2.43% worst drawdown. Stress results were positive in only 3/5 folds, with a +1.26% median and 2.74% worst drawdown.

One failed fold was already -2.43% under normal costs, while another moved from +0.24% normally to -0.17% stressed. The route therefore contains both genuine signal failure and one cost-sensitive marginal fold.

Review: 4h bars materially reduced drawdown, but the fixed entry/exit strength boundary caused marginal churn. The next route predeclares state hysteresis: entry remains strict while an existing trend may persist through moderate strength decay. No elapsed-time exit is introduced.

## Route 16: native 4h state hysteresis

Decision: rejected in development; holdout remains locked.

Using a stricter entry state and a looser continuation state did not repair the fold instability. The best BNB candidate produced positive normal and stressed returns in only 3/5 folds, although median returns remained +1.78% normally and +1.44% stressed with less than 2.5% worst drawdown.

Review: the earlier churn diagnosis was incomplete. Allowing trends more room changed the return distribution but did not turn the two weak regimes into reliable positive folds.

## Route 17: native 4h entry-volume confirmation

Decision: rejected in development; holdout remains locked.

Entry required current Hyperliquid volume to equal or exceed either 1.0 or 1.5 times the previous 42-bar median. Volume was not required after entry, so a strong price trend could continue without a time limit. The best ETH candidate returned a +1.41% normal median and +1.38% stressed median with less than 2% worst drawdown, but only 3/5 folds were positive and it generated just 14 orders across all five folds.

Review: volume confirmation removed risk mainly by removing trades. This is insufficient evidence of a tradable edge. The next distinct route uses a price-state channel: enter only on a 4h close breakout and remain invested until a trailing close channel confirms trend failure.

## Route 18: native 4h close-channel state momentum

Decision: rejected in the locked 120-day holdout.

Three of 36 development candidates passed, all neighboring BTC channel variants. The selected 24-bar entry and six-bar exit channel produced 4/5 positive folds, +3.27% normal and +3.04% stressed median return, and 3.23% stressed worst drawdown across 40 orders. This local parameter neighborhood was stronger evidence than an isolated optimum.

The once-opened holdout returned -2.29% normally and -2.62% stressed across 20 orders, with no minimum-order skips. Removing the extra stress cost explains only about 0.34 percentage points, so false breakouts rather than fees caused the failure. The longest observed hold was 33 four-hour bars, confirming that the implementation imposed no elapsed-time exit.

Review: a trailing channel can preserve a strong trend for days, but the entry state still lacks enough information to distinguish continuation from false breakout. This exact route and opened interval are closed. Any additional entry-quality hypothesis must use a separately declared validation source rather than reusing this holdout.

## Route 19: native 4h moving-average state momentum

Decision: rejected in the locked holdout.

The new fixture was fetched independently after the close-channel route. One of 144 candidates passed development: BNB with a six-bar fast average, 42-bar slow average, and 12-bar slow-average slope. It produced 4/5 positive folds, +2.92% normal and +2.72% stressed median return, 13.40% stressed worst drawdown, and 73 orders.

The independent holdout returned -1.98% normally and -2.08% under stress across six orders, with no minimum-order skips. The route entered only three times in the holdout and failed because its state classification did not transfer to the new regime, not because of execution friction.

Review: a conventional trend state can be executable and cost-aware while still being regime-fragile. The full moving-average family is closed; the next route switches from continuation entries to trend-pullback reclaim entries.

## Route 20: native 4h trend-pullback reclaim

Decision: passed the locked holdout; paper candidate only.

This route enters only after a six-bar drawdown of at least 2% is followed by a positive reclaim while the preceding 84-bar trend remains positive. It exits when the six-bar return reaches zero or the longer trend turns negative. No elapsed-time condition exists in the research or typed strategy.

Two of 288 candidates passed development, and they were neighboring BNB variants. The selected candidate produced 4/5 positive folds, +1.61% normal and +1.44% stressed median return, 3.95% stressed worst drawdown, and 40 orders. Its fresh Hyperliquid holdout returned +0.95% normally and +0.84% under stress, with 0.47% stressed drawdown and no minimum-order skips.

The capital replay found the first executable balance at about $21: $20 and below produced no executable orders because the 50% target notional rounded below the $10 exchange minimum, while $21 and above executed all six holdout orders. The strategy is therefore paper-eligible from $25 with a small operational buffer, not from the user's lower balances.

Review: this is the first route with both development and independent holdout support, but the holdout contains only six trades. It is not a live replacement. The typed strategy and isolated paper manifest are added for observation; paper results must reach the existing 60-day/10-trade boundary before any live review.

## Routes 21-22: native 4h variants under test

Two new structures share one newly fetched Hyperliquid fixture, with their own fixed candidate grids and the same no-time-exit rule:

1. `native_4h_short_breakdown`: short-only continuation after a confirmed downtrend and downside acceleration; exit on recovery or trend reversal.
2. `native_4h_volatility_breakout`: long-only breakout only when realized volatility expands; exit on trailing channel or trend decay.

Each route will be independently ranked and can unlock the new holdout only if its own development gates pass. A failed route will be closed rather than repaired with its holdout.

## Route 21: native 4h short breakdown

Decision: passed the locked holdout; second paper candidate.

The route opens a 50% short only when the 84-bar trend is negative and the latest 12-bar return is below -1%, while funding is not too negative for a short. It exits on recovery or trend reversal, with no elapsed-time exit. Seven of 288 candidates passed development; the selected ETH candidate produced 4/5 positive folds, +7.30% stressed median return, 11.94% stressed worst drawdown, and 215 development orders.

The fresh holdout returned +8.69% normally and +8.01% under stress across 38 orders, with 6.15% stressed drawdown and no minimum-order skips. The longest observed hold was 42 four-hour bars.

Review: the result is materially different from the long-only pullback candidate and remains paper-only. A typed short state strategy must preserve the same no-time-limit rule and retain protective stops before paper starts.

## Route 22: native 4h volatility expansion breakout

Decision: rejected in the locked holdout.

Five of 288 candidates passed development, including a BTC breakout with 4/5 positive folds, +3.23% stressed median return, 2.02% stressed worst drawdown, and 40 orders. The fresh holdout returned -2.70% normally and -3.04% under stress across 20 orders.

Review: realized-volatility confirmation did not solve the false-breakout problem. This route is closed and will not be papered.

## Route 23: native 4h neutral-zone exhaustion reclaim

Status: development under test.

This route will only buy a sharp downside move that reclaims the prior bar while the longer trend remains inside a neutral range. It is deliberately a different regime hypothesis from both trend continuation routes; no time-based exit is allowed.

Decision: passed the locked holdout; third paper candidate.

Thirteen of 288 candidates passed development. The selected BTC candidate required a 12-bar drawdown of at least 2%, a 42-bar trend within +/-10%, and a 1% recovery target. All five development folds were positive, with +1.93% stressed median return, 5.91% stressed worst drawdown, and 40 orders.

The fresh holdout returned +6.70% normally and +6.30% under stress across 22 orders, with 2.18% stressed drawdown and no minimum-order skips. The longest observed hold was 24 four-hour bars. Capital replay had no skips at $25 and above.

Review: this is the third structurally distinct paper candidate. It is a neutral-regime exhaustion hypothesis, not a replacement for the trend candidates. Its paper session will be evaluated independently for 60 days and 10 closed trades.

## Paper candidate set

The current isolated paper set contains exactly three candidates, all with `max_hold_days = null` and protective stop loss only:

1. BNB `trend_pullback_reclaim` long, paper buffer $25.
2. ETH `short_breakdown` short, paper buffer $50 because the $25 replay still had two minimum-order skips.
3. BTC `neutral_exhaustion_reclaim` long, paper buffer $25.

All three have `execution_authorized: false`; live replacement remains blocked until each reaches the paper observation boundary.
