# Research Manual Index

The research manual is the evidence layer for strategy decisions. It records what was tested, under which contract, and what remains allowed. It is not a live configuration surface.

## Reading order

1. [Decision framework](00_decision_framework.md)
2. [Quant research map](01_quant_research_map.md)
3. [Current strategy review](02_current_strategy_review.md)
4. [Research backlog](03_research_backlog.md)
5. [Two research modes and promotion](05_dual_track_execution.md)
6. Read the dated report for the specific candidate or workflow.

For the current permission boundary, read [`../../.agents/current_decisions.md`](../../.agents/current_decisions.md) first. For the active execution queue, read [`../../.agents/improve_plan.md`](../../.agents/improve_plan.md).

## Core framework and planning

| File | Role | Status |
| --- | --- | --- |
| [00_decision_framework](00_decision_framework.md) | Evidence levels and decision rules | Current framework |
| [01_quant_research_map](01_quant_research_map.md) | Research directions and dependencies | Current map |
| [02_current_strategy_review](02_current_strategy_review.md) | Baseline and historical component review | Context; verify against current decisions |
| [03_research_backlog](03_research_backlog.md) | Candidate work queue | Planning context |
| [04_intraday_strategy_candidates](04_intraday_strategy_candidates.md) | Earlier candidate catalogue | Historical context; superseded by 08 for short-cycle status |
| [05_dual_track_execution](05_dual_track_execution.md) | Research modes and promotion boundary | Current workflow |
| [06_alpha_discovery_plan](06_alpha_discovery_plan.md) | Discovery funnel and candidate ranking | Research planning |

## Candidate and execution evidence

| File | Role | Status |
| --- | --- | --- |
| [07_carry_funding_basis_backtest](07_carry_funding_basis_backtest.md) | Carry/funding/basis evidence | Research-only |
| [08_short_cycle_strategy_diagnosis](08_short_cycle_strategy_diagnosis_2026-07-14.md) | Cost-aware short-cycle diagnosis and gate | Current short-cycle gate |
| [09_trend_market_context_candidate](09_trend_market_context_candidate.md) | Trend market-context candidate | Observe/research-only; not a live gate |
| [10_awesome_quant_trading_backtesting_selection](10_awesome_quant_trading_backtesting_selection.md) | External tooling selection | Decision record; not a runtime authority |
| [11_live_trend_38_entry_quality_diagnostic](11_live_trend_38_entry_quality_diagnostic_2026-07-17.md) | Fixed-38 Trend entry diagnostic | Latest Trend evidence; not promotable by itself |
| [12_clean_room_cross_sectional_strength](12_clean_room_cross_sectional_strength_2026-07-17.md) | Clean-room selector evaluation | Rejected; preserve as negative evidence |
| [12_live_trend_rsi_btc_regime_attribution](12_live_trend_rsi_btc_regime_attribution_2026-07-17.md) | Fixed-38 Trend RSI/BTC attribution | Research-only; insufficient promotion evidence |
| [13_independent_tradeable_strategy_search](13_independent_tradeable_strategy_search_2026-07-17.md) | Independent strategy search | Early rejected stage; later shadow result is in 14 |
| [14_cross_sectional_momentum_shadow](14_cross_sectional_momentum_shadow_2026-07-17.md) | Cross-sectional momentum shadow candidate | Bounded paper ledger only; no exchange orders |
| [15_low_capital_route_log](15_low_capital_route_log_2026-07-18.md) | Route history and forward observation contract | Routes 30/31 observation; freeze new variants |
| [16_low_capital_snowball_route](16_low_capital_snowball_route_2026-07-22.md) | Route 37 capital-feasibility baseline | Requires matched-contract comparison before further sizing work |
| [17_non_crypto_hyperliquid_news_strategy](17_non_crypto_hyperliquid_news_strategy_2026-07-24.md) | HIP-3 stock/oil news research line | Separate `new_alpha_research`; paper/research only |
| [18_entry_quality_routes](18_entry_quality_routes_2026-07-24.md) | Entry-continuation routes 38-40 | Forward research-only; no exchange orders |

## Status rules

- A dated report is evidence, not permission.
- A research-only or observe-only result must not be wired into paper/live behavior without the explicit promotion sequence.
- The fixed 38-coin Trend contract is the active research/live-like comparison boundary; older 50-coin results remain historical evidence.
- When a report and the decision register disagree, the decision register wins.
