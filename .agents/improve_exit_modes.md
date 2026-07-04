# Improve Notes: Exit Modes

## Current Direction

- `live` is moving first to a reusable exit-policy model instead of hard-coding one TP/SL workflow.
- `trend` is the first policy to switch to `SL-only` protection in live trading.
- `fvg` and `both` are intentionally left out of this first implementation.

## Implemented In This Step

- Added a reusable exit-policy helper in `src/trading_strategy/core/exit_policy.py`.
- `TREND_*` signals now resolve to:
  - `name = "trend_sl_only"`
  - `requires_tp = False`
  - `requires_sl = True`
- Non-trend signals currently resolve to:
  - `name = "fixed_tpsl"`
  - `requires_tp = True`
  - `requires_sl = True`
- Live protection submission now has two reusable paths:
  - `place_hl_sl_order(...)`
  - `place_hl_tpsl_orders(...)`

## Why Trend Goes First

- Trend trades already rely more on reversal and hold-time exits than on a fixed profit target.
- Removing fixed TP from trend is a strategy choice, not just a plumbing change.
- This gives a clean place to add dynamic SL later without forcing the same behavior onto `fvg`.

## Next Options For FVG

### Option A: Keep Fixed TP/SL

- Lowest risk.
- Matches current FVG behavior and expectations.
- Best default until there is evidence that SL-only exits improve FVG expectancy.

### Option B: Fixed TP + Dynamic SL

- Keep the current take-profit structure.
- Allow stop loss to tighten once price moves favorably.
- More complex because it combines partial trend-following behavior with target-based exits.

### Option C: FVG-Specific Exit Policy

- Separate the concept of `signal generation` from `exit mode`.
- Example future profile:
  - `name = "fvg_fixed_target"`
  - `requires_tp = True`
  - `requires_sl = True`
  - optional later flags for trailing or break-even behavior.

## Next Options For BOTH

### Recommended Direction

- Treat `both` as signal-source multiplexing, not as a third exit model.
- Resolve exit mode from the emitted signal type:
  - `TREND_*` -> `trend_sl_only`
  - `FVG_*` -> `fixed_tpsl`

### Why

- `both` mixes two different trade intents.
- A single hard-coded TP policy for both is likely to distort one side of the system.

## Follow-Up Work

- Add dynamic SL stages for `trend_sl_only`.
- Add backtest and paper-trading support for selectable exit modes.
- Compare:
  - `fixed_tpsl`
  - `trend_sl_only`
  - later `fvg_fixed_target + trailing_sl`
- Keep event/log naming aligned with the actual protection mode so observability stays accurate.
