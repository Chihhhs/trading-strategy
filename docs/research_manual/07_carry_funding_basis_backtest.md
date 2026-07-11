# Carry / Funding / Basis Backtest

- Date: 2026-07-11
- Data: `data/derivatives/binance_futures_240d_BTC_ETH_BNB.json`
- Coins: BTC, ETH, BNB
- Window: 240 daily bars
- Scope: Delta-neutral research model only. This is not live execution logic.

## Data Coverage

- Funding rate: 240 / 240 bars for BTC, ETH, BNB.
- Basis proxy: 240 / 240 bars for BTC, ETH, BNB.
- Open interest: 19 / 240 bars for BTC, ETH, BNB, so OI is not reliable enough for primary rules yet.

The basis field is a perp premium/index proxy from Binance futures data, not a dated-futures calendar basis. Treat the current basis backtest as `perp basis compression`, not full calendar arbitrage.

## Backtest Rules

### Funding Carry

- Enter short perp / long spot when funding is positive and `abs(funding_rate) >= 0.00008`.
- Enter long perp / short spot when funding is negative and `abs(funding_rate) >= 0.00008`.
- Exit when `abs(funding_rate) <= 0.00002` or after 14 days.
- Funding PnL assumes 3 funding periods per day.
- Cost assumes a two-leg spread opened and closed, so per-trade cost is `4 * (fee_bps + slippage_bps)`.

### Basis Compression

- Enter short perp / long spot when basis is positive and `abs(basis_pct) >= 0.04`.
- Enter long perp / short spot when basis is negative and `abs(basis_pct) >= 0.04`.
- Exit when `abs(basis_pct) <= 0.01` or after 14 days.
- PnL combines basis compression plus funding carry while held.
- Cost uses the same two-leg open/close assumption.

## Commands Run

```bash
python backtest/backtest_runner.py --carry-report --coins BTC,ETH,BNB --max-days 240 --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --fee-bps 4.5 --slippage-bps 2
```

```bash
python backtest/backtest_runner.py --carry-report --coins BTC,ETH,BNB --max-days 240 --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --fee-bps 1.5 --slippage-bps 0.5 --funding-entry-abs 0.00008 --basis-entry-abs-pct 0.04
```

```bash
python backtest/backtest_runner.py --carry-report --coins BTC,ETH,BNB --max-days 240 --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --fee-bps 0 --slippage-bps 0 --funding-entry-abs 0.00008 --basis-entry-abs-pct 0.04
```

## Results

### Conservative Cost: 4.5 bps fee + 2 bps slippage

Per spread trade cost: 0.26%.

| Track | Coin | Trades | Net PnL | Gross PnL | Decision |
|---|---|---:|---:|---:|---|
| Funding carry | BTC | 6 | -0.9145% | +0.6455% | Not viable after cost |
| Basis compression | BTC | 15 | -5.0787% | -1.1787% | Reject current rule |
| Funding carry | ETH | 15 | -3.3809% | +0.5191% | Not viable after cost |
| Basis compression | ETH | 15 | -4.6955% | -0.7955% | Reject current rule |
| Funding carry | BNB | 4 | -0.9619% | +0.0781% | Not viable after cost |
| Basis compression | BNB | 21 | -3.6859% | +1.7741% | Gross works, cost kills it |

### Low-Cost Maker-Like Scenario: 1.5 bps fee + 0.5 bps slippage

Per spread trade cost: 0.08%.

| Track | Coin | Trades | Net PnL | Gross PnL | Decision |
|---|---|---:|---:|---:|---|
| Funding carry | BTC | 6 | +0.1655% | +0.6455% | Weak positive, monitor only |
| Basis compression | BTC | 15 | -2.3787% | -1.1787% | Reject current rule |
| Funding carry | ETH | 15 | -0.6809% | +0.5191% | Not enough edge |
| Basis compression | ETH | 15 | -1.9955% | -0.7955% | Reject current rule |
| Funding carry | BNB | 4 | -0.2419% | +0.0781% | Not enough edge |
| Basis compression | BNB | 21 | +0.0941% | +1.7741% | Weak positive, monitor only |

### Zero-Cost Diagnostic

Zero-cost results are positive for funding carry and BNB basis compression, but this is not tradable evidence. It only confirms that execution cost is the main hurdle for this version.

## Decision

Do not promote carry/funding/basis to live or paper execution yet.

The current research version is useful as a monitor and data-collection workflow. It does not yet prove a robust tradeable strategy after realistic two-leg costs.

## Paper Trade Plan

Run a 3-7 day paper observation loop before any execution work:

- Snapshot BTC, ETH, BNB once per funding interval or at least daily.
- Record `funding_rate`, `basis_pct`, `open_interest`, mark/index source, timestamp, and estimated two-leg cost.
- Only mark hypothetical entries when funding or basis exceeds threshold for two consecutive snapshots.
- Track hypothetical entry spread, expected funding received/paid, basis change, and exit reason.
- Compare taker, maker-like, and zero-cost assumptions separately.
- Require positive net expectancy after maker-like costs before building execution logic.

## Next Research Step

- Improve data first: fetch full OI history and, if possible, venue-specific Hyperliquid funding/basis snapshots.
- Add stricter entry filters: larger funding/basis threshold, minimum expected carry vs cost, and OI confirmation once data coverage is reliable.
- Keep this track separate from directional `trend`; it is a relative-value monitor until proven otherwise.

## Short-Term Trend Filter Extension

Added a separate funding/basis trend report:

```bash
python backtest/backtest_runner.py --funding-trend-report --coins BTC,ETH,BNB --max-days 240 --data-path data/historical_prices/1000d_50coins.json --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --trend-forward-days 1,3,7,14 --trend-funding-z-threshold 0.75 --trend-basis-abs-threshold-pct 0.03
```

This report is not an arbitrage backtest. It classifies funding/basis context into short-term directional labels and then checks future 1d / 3d / 7d / 14d signed returns.

Labels:

- `long_basis_support`: funding is unusually negative and basis supports a long-side directional read.
- `short_basis_crowded`: funding is unusually positive and basis suggests the long side may be crowded, so the signed test is short.
- `crowded_long_risk` / `crowded_short_risk`: funding and recent price action are already one-sided; treat as reversal or squeeze-risk context.
- `neutral`: funding z-score is not extreme enough to provide a directional read.

Latest 240d run:

| Coin | Latest label | Direction | Funding z | Basis | Read |
|---|---|---|---:|---:|---|
| BTC | `long_basis_support` | Long | -1.1959 | -0.04032% | Mild long-support context, but historical 7d/14d edge is weak. |
| ETH | `long_basis_support` | Long | -0.8947 | -0.05441% | Long-support context, but historical forward returns are weak/negative for this label. |
| BNB | `long_basis_crowded` | Long | -1.1142 | +0.06335% | Conflicted: funding supports long, basis says long side is crowded. Historically this label is poor beyond 1d. |

Most useful historical label in this sample:

- BTC `short_basis_crowded`: 48 samples, 3d mean +1.0658%, 7d mean +2.3111%, 14d mean +4.0488%.
- ETH `short_basis_crowded`: 49 samples, 3d mean +1.5074%, 7d mean +2.3393%, 14d mean +5.9902%.

Interpretation:

- Funding/basis looks more useful as a short-term trend or crowding filter than as a standalone carry trade under realistic costs.
- Current BTC/ETH latest labels lean long, but the historical edge for `long_basis_support` is not strong enough to use alone.
- The stronger result is on the short/crowding side: positive funding plus basis crowding has historically helped identify short-side continuation or long unwind risk in this sample.

Decision:

- Keep `--funding-trend-report` as a research monitor.
- Do not wire it into live entries yet.
- Next implementation step should test using `short_basis_crowded` as a blocker or confidence modifier for trend longs, not as an independent trade trigger.

## Trend Integration Test

Added a disabled-by-default trend exit:

```bash
--enable-derivatives-crowding-exit
```

Behavior:

- Only affects open trend positions.
- Does not create entries.
- Does not change live behavior unless explicitly wired later.
- Long positions exit early on `short_basis_crowded`.
- Short positions exit early on `long_basis_crowded`.

Default thresholds:

- Funding z-score lookback: 30 bars.
- Funding z-score threshold: 0.75.
- Basis absolute threshold: 0.03%.

Commands:

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --data-path data/historical_prices/1000d_50coins.json --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --enable-atr-trailing --enable-failure-exit --fee-bps 4.5 --slippage-bps 2
```

```bash
python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --data-path data/historical_prices/1000d_50coins.json --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --enable-atr-trailing --enable-failure-exit --enable-derivatives-crowding-exit --fee-bps 4.5 --slippage-bps 2
```

BTC/ETH/BNB result:

| Variant | Trades | Net PnL | Drawdown | Crowding exits | Read |
|---|---:|---:|---:|---:|---|
| Baseline trend | 9 | -18.6% | 27.1% | 0 | Weak, long losses dominate |
| Crowding exit on | 11 | -12.5% | 25.2% | 3 | Improved, but still negative |

BTC/ETH-only result:

| Variant | Trades | Net PnL | Drawdown | Crowding exits | Read |
|---|---:|---:|---:|---:|---|
| Baseline trend | 6 | -1.2% | 22.4% | 0 | Near flat but poor ETH longs |
| Crowding exit on | 8 | +5.9% | 20.4% | 3 | Better PnL and slightly lower drawdown |

Threshold sensitivity:

- Raising basis threshold to `0.05` removed all crowding exits and reverted to baseline behavior.
- Raising funding z-score threshold to `1.0` did not change this sample, because the three triggered exits were already above that threshold.

Current decision:

- `derivatives_crowding_exit` is promising as a risk-reduction mechanism, especially for avoiding crowded long continuation.
- Keep it off by default.
- Use it in backtest/paper research before live.
- Next useful improvement is partial reduction rather than full exit: reduce long exposure or tighten SL when `short_basis_crowded` appears.

## Trend Position Control Strategy

Added a research-only trend position control preset:

```bash
--enable-trend-position-control
```

This preset enables:

- Derivatives crowding detection.
- `reduce` action instead of full exit.
- 75% position reduction when the open trend position is on the wrong side of a crowding label.

Current rule:

- Long position + `short_basis_crowded` -> close 75% of the position and keep the remaining 25% with normal trend exits.
- Short position + `long_basis_crowded` -> close 75% of the position and keep the remaining 25% with normal trend exits.
- The same crowding label can only reduce the same position once.
- No new entries are created.
- Live execution is unchanged.

Command:

```bash
python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240 --data-path data/historical_prices/1000d_50coins.json --derivatives-data-path data/derivatives/binance_futures_240d_BTC_ETH_BNB.json --enable-atr-trailing --enable-failure-exit --enable-trend-position-control --fee-bps 4.5 --slippage-bps 2
```

BTC/ETH position-control comparison:

| Variant | Trades | Net PnL | Drawdown | Score | Read |
|---|---:|---:|---:|---:|---|
| Baseline trend | 6 | -1.2% | 22.4% | -12.40 | No position control |
| Full crowding exit | 8 | +5.9% | 20.4% | -4.30 | Helps, but removes all remaining upside |
| 25% reduce | 9 | +4.2% | 19.0% | -5.30 | Too small to cut risk enough |
| 50% reduce | 9 | +9.8% | 15.6% | +2.00 | Good balance |
| 75% reduce | 9 | +15.6% | 12.1% | +9.55 | Best current setting |

BTC/ETH/BNB with 75% reduce:

| Variant | Trades | Net PnL | Drawdown | Read |
|---|---:|---:|---:|---|
| Baseline trend | 9 | -18.6% | 27.1% | BNB remains a drag |
| 75% reduce | 12 | -9.4% | 20.7% | Improved, but universe still matters |

Decision:

- Use `--enable-trend-position-control` as the current best research setting for BTC/ETH.
- Do not enable for live yet.
- Treat BNB result as evidence that position control cannot fix a weak universe by itself.
- Next research step: combine position control with universe filtering and later implement live-safe partial reduce order handling.
