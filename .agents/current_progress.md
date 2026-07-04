# Current Progress

## 2026-07-04

### Completed

- Implemented exchange-first daily live reconciliation for `run_once()`.
- Live startup now rebuilds the active working set from exchange data:
  - live positions
  - frontend open orders
  - managed open order records in local state
- Added `managed_orders` to persisted live state.
- Added order-role classification during reconciliation:
  - `protection_sl`
  - `protection_tp`
  - `entry_pending`
  - `orphan_unknown`
- Added orphan-order detection and automatic cancel flow.
- Added `trend_sl_only` single-SL replacement flow:
  - detect better SL
  - cancel old SL first
  - submit replacement SL only after cancel succeeds
- Completed `trend_sl_only` dynamic SL rules:
  - store `initial_risk`
  - store `sl_stage`
  - store `best_price`
  - `+1R` moves SL to break-even
  - `+1.5R` moves SL to `+0.5R`
  - stage only moves forward, never backward
- Added event coverage for:
  - `open_orders_synced`
  - `order_adopted`
  - `orphan_order_detected`
  - `orphan_order_cancel_attempted`
  - `orphan_order_canceled`
  - `orphan_order_cancel_failed`
  - `sl_replace_attempted`
  - `sl_replaced`
  - `sl_replace_failed`

### Validation

- `python -m unittest tests.test_live` passed using the bundled runtime python.
- `python -m compileall src tests` passed using the bundled runtime python.

### Notes

- Current inference for exchange-adopted positions is:
  - `SL only` protection => infer `trend_sl_only`
  - `SL + TP` protection => infer `fixed_tpsl`
- Dynamic SL currently uses ATR only for the initial SL definition.
- After entry, `trend_sl_only` no longer trails by ATR; it now promotes SL by R-multiples using `initial_risk`.
- `fvg` and `both` are still supported by the new reconciliation framework, but their exit behavior is not changed in this step.
