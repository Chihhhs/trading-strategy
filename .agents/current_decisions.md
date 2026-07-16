# Current Decisions For Agents

Last updated: 2026-07-16

Purpose: this file is the current decision register for repo agents. Prefer it over older narrative sections in `.agents/improve_plan.md` or historical research docs when deciding what is allowed next.

Research modes are defined in `.agents/research_modes.md`: `optimize_existing_trend` is the only path that can improve the current live Trend strategy; `new_alpha_research` has independent baselines and approval.

## Operating Rules

- Exchange positions and exchange open orders are the live truth. Local state files are cached context, not authority.
- Runtime config is the active strategy truth. Do not infer live intent from stale `live_state.json.params`.
- Research reports may summarize evidence, but they must not overwrite live or paper state.
- Live uses the fixed 38-coin `LIVE_UNIVERSE` in `apps/live_config.py`: the
  20 still-active historical members plus the 2026-07-16 market-cap leaders
  that have active Hyperliquid perps. It is a deliberate static contract, not
  a daily ranking. Paper deliberately has no configured universe and loads all
  active Hyperliquid perps from `meta` for data collection. Do not substitute
  the old 3-coin override or the historical 50-coin research fixture for live.
- Paper and live prefer Hyperliquid market data for the fixed 38-coin universe.
  A coin with missing Hyperliquid price or K-lines may fall back to Binance USDⓈ-M
  Futures, with its paper cache marked per coin by the source actually used.
  Market-data coverage does not establish
  Hyperliquid order eligibility: execution must separately verify that a coin
  is active and tradable on Hyperliquid before submitting an order.
- Live unit-test event records are isolated in an OS temporary directory; do
  not treat them as paper or live observation evidence.
- Position capacity is mode-specific: paper permits 10 concurrent simulated
  positions for evidence collection; live remains capped at 2.
- Paper refreshes every active Hyperliquid perp K-line cache before checking
  its position limit, so a full paper portfolio cannot stop offline-data accumulation.
- Live entry is blocked when protection status is unknown, ambiguous, or unverified.
- Unknown or ambiguous protection orders must not be automatically canceled or replaced.
- Strategy promotion path is always: research -> cost-adjusted backtest -> gate -> bounded paper observation -> explicit live review.
- No research candidate may change live config without a separate live-safety review.

## Current Work Priority

| Priority | Area | Current decision | Allowed next action | Evidence |
|---|---|---|---|---|
| P0 | Protection reliability | Implemented and safety-critical. Unknown, ambiguous, missing, or unverified protection blocks entry. The current state snapshot has three protected positions and six managed protection orders; its last event summary is older, so do not call it fresh operational evidence. | Before paper/live operation, run regression tests and inspect the current run's events. Open new work only for a concrete failing safety case. | `docs/research_manual/05_dual_track_execution.md`, live tests |
| P0 | Run summary observability | Implemented. Summary exposes blockers, positions, protection state, fee/slippage, turnover, exit reasons, MFE/MAE, and drawdown when available. | Validate each operational run; do not expand schema without a demonstrated observability gap. | `docs/research_manual/05_dual_track_execution.md` |
| P1 | Live decision architecture | Implemented in observe-only mode. Each signal path emits a reason-coded `Decision` event and summary aggregation without changing entry behavior. Live uses the frozen 38-coin contract; paper loads every active Hyperliquid perp and source-tags any per-coin fallback cache. Paper-mode K-line cache may resolve pending observations while offline; it never supplies a live decision or entry price. | Continue collecting paper observations through `apps/runners/paper_runner.py`; keep Hyperliquid execution eligibility explicit and do not equate fallback data coverage with order eligibility. | `apps/live_config.py`, `apps/runners/paper_runner.py`, `src/trading_strategy/live/decision.py`, `src/trading_strategy/live/market.py`, Hyperliquid public `meta` |
| P1 | Live market context | Implemented as a hypothetical annotation in `Decision`; it is not a live gate. | Compare observed hypothetical outcomes only after enough normal-run samples exist. | `src/trading_strategy/live/decision.py`, `docs/research_manual/09_trend_market_context_candidate.md` |
| Later | Module cleanup | Deferred maintenance only. Reduce duplication and obsolete compatibility paths after current safety and research work is quiet. | Take one narrow module at a time with targeted tests; preserve runner commands and persisted schemas. | `docs/restruct.md`, live/backtest tests |
| P1 | Trend strategy | `optimize_existing_trend`: canonical 50-coin causal replay is complete, but the baseline fails the performance and drawdown gate. | Do not create a paper candidate. Develop one new pre-defined entry, BTC-regime, or universe hypothesis only after attribution evidence supports it. | `data/research_artifacts/live_trend_baseline_1h_replay_50coin.json`, `docs/research_manual/09_trend_market_context_candidate.md` |
| P1 | Trend market context | `optimize_existing_trend` research-only candidate: causal regime entry filter plus momentum-decay time limit. | Blocked: attribution produced no cross-fold hypothesis and the canonical baseline is negative with severe MTM drawdown. No shadow or promotion. | `data/research_artifacts/trend_entry_attribution_50coin.json`, `data/research_artifacts/live_trend_baseline_1h_replay_50coin.json` |
| P1 | Intraday momentum | `new_alpha_research`; rejected for paper/live. Keep only as a wiring baseline and negative control. | Measurement integrity, frozen short-cycle baselines, one-factor ablation, and research reports only. | `.agents/research_modes.md`, `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md` |
| P1 | Intraday turnover | Turnover reduction alone is not enough. Current issue is negative or weak raw edge plus 13 bps round-trip cost. | Collect per-trade diagnostics and compare frozen candidates. Do not promote if net PnL remains negative. | `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md` |
| P1 | VWAP reversion | Research candidate only. Recent 12/24-bar windows improved, older windows failed. | Test regime/session-conditioned variants with OOS and random baseline. | `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md` |
| P2 | Funding/basis/OI | Monitor and research context. Not standalone live alpha. | Improve data coverage, test as blocker/confidence modifier, keep live disabled. | `docs/research_manual/07_carry_funding_basis_backtest.md` |
| P2 | L2/microstructure | Observe-only unless replay evidence proves value. | Collect spread, depth, imbalance, and adverse-selection diagnostics. | `docs/research_manual/06_alpha_discovery_plan.md` |

## Rejected Or Retired Paths

| Path | Decision | Reason |
|---|---|---|
| Live `intraday_momentum` config override | Blocked | Baseline is strongly negative after costs and churns heavily. |
| Simple cooldown/regime filter promotion | Blocked | Reduces turnover in some windows but does not establish positive OOS edge. |
| Breakout continuation as primary short-cycle alpha | Deprioritized | Current 15m evidence is worse than random baseline after costs. |
| Volatility expansion as primary short-cycle alpha | Deprioritized | Current 15m evidence is net negative after costs. |
| Adaptive ATR trail promotion | Rejected for now | Did not pass robustness gates. Keep only as historical research. |
| Close-confirmed stop promotion | Rejected for now | Did not beat canonical live-like baseline. |
| Intrabar stop-first as an improvement | Rejected for intraday | It worsened churn and net results in the short-cycle diagnosis. |
| Funding/basis carry execution | Research-only | Two-leg costs erase current edge. |

## Promotion Gates

Protection reliability gate:

- Unknown or ambiguous protection never triggers cancel/replace.
- Missing or unverified protection blocks new entry.
- Repair, replace, verification, and failure reasons are recoverable from event logs.
- Summary includes protection counts and status.
- Live tests and compile checks pass.

Intraday research gate:

- Same 15m fixture, universe, fees, slippage, train/test split, random baseline, and minimum event count across candidates.
- Per-trade turnover, fee drag, gross/net PnL, exit reason, MFE/MAE, re-entry gap, direction, session, BTC regime, and volatility context are available.
- Candidate OOS net PnL after costs is positive or at least explicitly better under an approved absolute threshold.
- Drawdown does not worsen beyond threshold.
- Turnover and fee drag fall materially.
- Candidate is not a no-op and has enough events.
- Passing this gate permits bounded paper observation only, not live.

Trend research gate:

- Compare against canonical live-like baseline: daily trend decision plus causal 1h hard-SL execution and MTM drawdown.
- Candidate must improve net PnL and drawdown across frozen windows and universes.
- Entry/regime/universe changes are in scope. Further stop-stage or ATR tuning is not the priority without new evidence.
- Passing the gate permits shadow mode only; bounded paper and live require their subsequent, separate approvals.

Trend entry attribution is research evidence only. It records raw structural candidates before RSI/ATR/price-position/overextension eligibility, labels completed 1/3/5/10-day returns after a 13 bps round-trip cost, and runs fixed 90/30 walk-forward folds. It must not alter live config, signal generation, or shadow behavior.
