# Exit Rules

## Goal

This document defines the current exit and protection rules for live and paper trading.
It is intended to keep the strategy behavior explicit before further tuning or code changes.

## Core Principle

- Separate `capital protection` from `profit capture`.
- Every live position should rely on exchange-side protection orders instead of manual exits.
- Trend-following positions should avoid rigid fixed take-profit targets that are easy to miss during short-term volatility.
- Mean-reversion or non-trend positions can keep fixed `TP/SL` because they are designed to realize gains faster.

## Exit Policy Types

The strategy currently uses two exit-policy modes:

### `trend_sl_only`

- Used for signals whose reason starts with `TREND_`.
- Submit a `reduce-only` stop-loss protection order.
- Do not require a fixed take-profit order.
- Protect open profit by moving the stop-loss only in the more protective direction.

### `fixed_tpsl`

- Used for non-trend signals.
- Submit both `reduce-only` take-profit and stop-loss protection orders.
- Keep the trade structure simple and deterministic for shorter-horizon setups.

## Entry-Time Protection Rules

### Trend positions

- Initial stop-loss is determined from signal generation, which currently uses volatility-based distance rather than a fixed percent.
- The current implementation derives `sl` from `ATR * sl_mult`.
- No fixed `tp` is required at entry.
- The position should be considered protected only after the exchange-side stop-loss order is active.

### Non-trend positions

- Initial stop-loss is determined from the signal.
- Initial take-profit is determined from the signal.
- The position should be considered protected only after both exchange-side `tp` and `sl` orders are active.

## Dynamic Stop Rules For Trend Positions

Trend positions should use staged stop management based on `R`, where:

- `initial_risk = abs(entry - initial_sl)`
- `1R` means unrealized profit equal to the initial risk

### Stage 0

- Starts immediately after entry.
- Stop-loss remains at the initial volatility-based stop.

### Stage 1

- Trigger condition: price reaches at least `+1.0R` in the favorable direction.
- Action: move stop-loss to `break-even` (`entry`).

### Stage 2

- Trigger condition: price reaches at least `+1.5R` in the favorable direction.
- Action: move stop-loss to `+0.5R`.

## ATR Trailing Extension For Trend Positions

- ATR trailing is the current research direction for short-term trend management.
- It is intended to replace the failed breakout-failure experiment as the primary early-exit path.
- This rule only applies to `trend_sl_only`.

### Activation

- Store `entry_atr` at entry.
- Keep the staged `R`-based stop logic before activation.
- Activate ATR trailing only after favorable progress reaches at least `+1.5R`.

### Trailing Rule

- Use the latest ATR estimate from the current market window.
- Long trailing stop: `best_price - current_atr * atr_trailing_mult`
- Short trailing stop: `best_price + current_atr * atr_trailing_mult`
- The default first-pass setting is `atr_trailing_mult = 2.0`.

### Constraints

- ATR trailing may only tighten risk.
- If the ATR-derived stop is not more protective than the current stop, no update should occur.
- Live protection should prefer replacing the exchange-side stop-loss order instead of market-closing immediately.
- If price is already through the intended trailing stop, the runtime may submit a defensive close with reason `ATR_TRAIL`.

## Stop Movement Constraints

- Stop-loss may only move toward lower risk.
- Stop-loss must never be widened after entry.
- The best favorable price seen since entry should be tracked and used to evaluate progress in `R`.
- If the newly desired stop is not more protective than the current stop, no replacement should occur.

## Short-Term Volatility Handling

To reduce the chance of missing exits during sharp short-term swings:

- Trend trades should prefer dynamic stop advancement over distant fixed take-profit targets.
- Protection orders should remain `reduce-only`.
- Exit logic should be automated and not depend on manual reaction time.
- When volatility expands, prefer smaller position size with a wider volatility-based stop rather than keeping position size unchanged and tightening the stop excessively.

## Protection Health Rules

- Missing protection orders should be treated as an actionable fault.
- For `trend_sl_only`, missing `sl` means the position is under-protected.
- For `fixed_tpsl`, missing either `tp` or `sl` means the position is under-protected.
- The runtime should attempt to repair missing protection orders on the next cycle.

## Current Code Alignment

This document matches the current structure in the codebase:

- `src/trading_strategy/strategies/trend.py`
  - Selects `trend_sl_only` for `TREND_*` signals and `fixed_tpsl` otherwise.
- `src/trading_strategy/strategies/trend.py`
  - Generates initial `tp` and `sl`, with trend entries currently using ATR-based distances.
- `src/trading_strategy/positions/trend.py` and `src/trading_strategy/live/engine/`
  - Tracks `initial_risk`, `sl_stage`, and `best_price` for trend positions.
  - Moves stop-loss to `break-even` at `+1R`.
  - Moves stop-loss to `+0.5R` at `+1.5R`.
  - Replaces stop-loss orders only when the new stop is more protective.
  - Repairs missing protection orders during live protection checks.

## Future Extension Direction

If the strategy needs more aggressive profit capture later, prefer one of these extensions:

- Partial take-profit plus trailing stop on the remaining size.
- Additional staged stop upgrades after `+2R`.
- Volatility-sensitive trailing logic that adapts to ATR expansion and contraction.

## Failed Experiment: Breakout Failure Exit

- `BREAKOUT_FAILURE` remains in the repo as a disabled experiment.
- The tested `--enable-failure-exit` path degraded win rate, total return, and drawdown in current local trend backtests.
- It should not be treated as the recommended trend-management path unless future independent research proves otherwise.
