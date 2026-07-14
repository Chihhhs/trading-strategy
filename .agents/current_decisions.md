# Current Decisions For Agents

Last updated: 2026-07-14

Purpose: this file is the current decision register for repo agents. Prefer it over older narrative sections in `.agents/improve_plan.md` or historical research docs when deciding what is allowed next.

## Operating Rules

- Exchange positions and exchange open orders are the live truth. Local state files are cached context, not authority.
- Runtime config is the active strategy truth. Do not infer live intent from stale `live_state.json.params`.
- Research reports may summarize evidence, but they must not overwrite live or paper state.
- Live entry is blocked when protection status is unknown, ambiguous, or unverified.
- Unknown or ambiguous protection orders must not be automatically canceled or replaced.
- Strategy promotion path is always: research -> cost-adjusted backtest -> gate -> bounded paper observation -> explicit live review.
- No research candidate may change live config without a separate live-safety review.

## Current Work Priority

| Priority | Area | Current decision | Allowed next action | Evidence |
|---|---|---|---|---|
| P0 | Protection reliability | Safety-critical. Improve order identity, ambiguous matching, verification status, and run summary observability. | Implement and test matching, repair, verification, and entry-blocking behavior. | `docs/research_manual/05_dual_track_execution.md`, live tests, recent protection work |
| P0 | Run summary observability | Required for live operations. Summary must expose blockers, positions, protection state, fee/slippage, turnover, and failure reasons. | Extend event and summary schema with tests. | `docs/research_manual/05_dual_track_execution.md` |
| P1 | Trend strategy | Executable, but not validated as live alpha under canonical live-like baseline. | Research entry quality, BTC regime, and universe selection against strict hard-SL plus MTM baseline. | `docs/research_manual/01_quant_research_map.md`, `.agents/improve_plan.md` |
| P1 | Intraday momentum | Rejected for paper/live. Keep only as a wiring baseline and negative control. | Measurement integrity, frozen baselines, one-factor ablation, and research reports only. | `docs/research_manual/08_short_cycle_strategy_diagnosis_2026-07-14.md` |
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
