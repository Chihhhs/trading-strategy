# Route 37: low-capital snowball research

Date: 2026-07-22

Status: baseline measured; no Route 37 candidate has been promoted.

## Objective

Study whether an account below 100 USDC can compound quickly through a
cost-adjusted, executable strategy while respecting Hyperliquid's minimum
order size. "Snowball" means maximizing net geometric equity growth through
reinvestment of available equity. It does not mean adding leverage, relaxing
protection, or maximizing an unconstrained backtest return.

The route must report both growth and survivability:

- net geometric growth after fees, slippage, and funding where available;
- mark-to-market maximum drawdown and worst losing sequence;
- time to recover and time to double, when the sample is long enough;
- minimum-order skips, turnover, fee drag, and concentration by coin and
  direction.

No single metric can authorize paper or live execution. A fast result that is
not executable at small notional, or that depends on ruin-level drawdown, is a
failed route.

## Clean-room contract

This route inherits the clean-room boundary used by the isolated Route 30/31
4h selector research:

- Use the fixed live-38 universe and completed Hyperliquid-native 4h bars for
  the first comparable baseline. The universe is a frozen contract, not a
  daily ranking.
- Read existing source data only. Do not edit, append to, re-save, or
  otherwise mutate any original fixture, cache, live state, paper state, or
  existing research artifact.
- Create any derived output in a new Route 37 artifact or state directory and
  record the input path, timestamp boundary, source, and data fingerprint.
- Declare development, validation, and forward-observation boundaries before
  inspecting the result. Do not tune parameters or reopen a failed route on a
  boundary that has already been inspected.
- Use a fixed candidate grid and a route-specific baseline. Do not compare a
  new-alpha result to the live Trend baseline as if they were the same
  strategy.
- Start from 50 USDC research capital, one position maximum, 50% target
  notional, no leverage multiplier, a 10 USDC minimum order, next-bar-open
  execution, and no elapsed-time exit unless a separate hypothesis declares
  one before the run.
- Model 6.5 bps one-way normal cost and 10 bps one-way stress cost, plus
  actual Hyperliquid funding when the input is available. Missing cost inputs
  must be marked incomplete, not silently set to zero.
- Do not import an order API, call the normal live engine, submit exchange
  orders, alter live or paper configuration, or set
  `execution_authorized=true`. Every artifact and event must persist
  `execution_authorized=false`.

## Research sequence

1. Freeze a new input snapshot or a clearly unused forward segment without
   changing the source data.
2. Define one executable baseline and the compounding/sizing hypothesis before
   running candidates.
3. Run the fixed development grid under normal and stressed costs.
4. Require sufficient events, positive cost-adjusted absolute performance,
   acceptable mark-to-market drawdown, zero minimum-order skips, and no
   unacceptable coin or direction concentration before unlocking the clean
   holdout.
5. Run the locked holdout once. A failed holdout closes the route; it is not a
   prompt to tune against that data.
6. If the route passes, use a new isolated paper ledger only after explicit
   review. Passing research still does not authorize exchange execution.

## Non-goals

- No change to the current Trend strategy, live universe, paper candidate set,
  protection rules, or exchange runtime.
- No leverage-based account growth experiment.
- No reuse of the known Route 30/31 benchmark as a fresh holdout.
- No claim that a positive backtest proves rapid real-account compounding.

## First clean-room baseline

The first baseline used a newly fetched 38-coin Hyperliquid 1h snapshot with
exclusive end boundary `2026-07-22T15:00:00Z`, resampled causally to 4h. The
input SHA-256 is recorded in the result artifact. The existing Route 30
selector was used only as an executable feasibility baseline; this is not a
Route 37 alpha result or a paper approval.

The fixed 192-candidate development grid selected the 12-bar raw momentum,
42-bar positive trend, 1% switch margin, and 1.5% volatility-target candidate.
At 50 USDC it was positive in all three development folds under 10 bps stress,
with stressed drawdowns from -10.21% to -12.70% and zero minimum-order skips.
The locked 300-bar holdout then returned +3.97% under 10 bps stress, with
-18.44% mark-to-market drawdown, 63 entries, zero skips, and 2.54 USDC total
fees. Equal-weight buy-and-hold returned -17.91% in the same segment.

The 25 USDC replay is not executable under this contract: it returned -5.66%
under stress and skipped 200 minimum-order entries in the holdout. The 100
USDC replay had the same percentage return as 50 USDC because the position
size is proportional to current equity. The baseline therefore proves a
50-USDC feasibility floor for this signal, not rapid compounding alpha.

Artifacts:

- `data/research_artifacts/route37_hyperliquid_live38_1h_snapshot_2026-07-22.json`
- `data/research_artifacts/route37_capital_feasibility_baseline_holdout_2026-07-22.json`

## Current live-like diagnostic

The canonical `live_trend_baseline_38` was also run read-only. Its existing
Binance 38-coin fixture returned -39.7% / -49.1% / -12.6% net PnL over the
120d / 180d / 240d windows, with MTM drawdowns of 53.09% / 64.22% / 53.45%.
That result is a useful warning about the current baseline, but it is not a
promotion comparison: it uses Binance daily decisions plus strict 1h exits,
1000 USDC, 5x leverage, and a different historical fixture, while Route 37
uses Hyperliquid 4h decisions, 50 USDC, and no leverage multiplier.

Route 37 cannot claim to beat live until both paths are replayed on the same
38-coin input boundary with an explicitly matched capital, cost, and execution
contract. The current live diagnostic does not authorize a live change.

## Next predeclared hypothesis

The next Route 37 experiment will hold the selected signal constant and test
only current-equity allocation fractions of 25%, 50%, 75%, and 90% at the
same 50-USDC starting balance. No leverage multiplier, pyramiding, averaging
down, or stop/protection change is allowed. The 50% result above is the fixed
reference baseline.

This sizing grid is not allowed to use the inspected 300-bar holdout for
selection. It must run on a newly fingerprinted forward boundary with the same
10-USDC minimum-order and normal/stressed cost contract. A larger allocation
passes only if it improves net geometric growth without exceeding -25% MTM
drawdown, creating minimum-order skips, or increasing concentration beyond the
declared gate.

## Initial decision

Route 37 remains research-only. The first clean-room baseline passed the
50-USDC feasibility check, but no Route 37 candidate, paper ledger, or live
wiring is approved. The next candidate must declare a compounding or sizing
hypothesis and beat this baseline on a separately locked clean-room boundary.
