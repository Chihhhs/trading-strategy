# Documentation Map

This directory is the repository's durable documentation surface. Use the current decision register for permission and the research manual for evidence; do not infer current strategy behavior from an old report.

## Start here

1. [Current decision register](../.agents/current_decisions.md) — what is allowed now, what is blocked, and the active promotion gates.
2. [Agent project map](../.agents/project_detail.md) — runtime truth, canonical entrypoints, and safety invariants.
3. [Decision framework](research_manual/00_decision_framework.md) — evidence levels and research rules.
4. [Research manual index](research_manual/README.md) — the chronological evidence map.

## Authority boundaries

| Question | Canonical document | Notes |
| --- | --- | --- |
| What may change now? | [`../.agents/current_decisions.md`](../.agents/current_decisions.md) | Current authority; overrides historical narrative. |
| What is the active execution queue? | [`../.agents/improve_plan.md`](../.agents/improve_plan.md) | Short roadmap, not a history log. |
| How is research evaluated? | [`research_manual/00_decision_framework.md`](research_manual/00_decision_framework.md) | Evidence levels and promotion rules. |
| Which research mode applies? | [`research_manual/05_dual_track_execution.md`](research_manual/05_dual_track_execution.md) | Separates existing-Trend work from new-alpha research. |
| How do live/paper exits behave? | [`exit_rules.md`](exit_rules.md) | Durable exit and protection behavior specification. |
| How are experiments run? | [`experiment_workflow.md`](experiment_workflow.md) | Manifest, adapter, and canonical command contract. |
| Where are module-boundary changes recorded? | [`restruct.md`](restruct.md) | Architecture and cleanup notes. |

## Document groups

### Research evidence

[`research_manual/`](research_manual/README.md) contains the decision framework, research map, experiment backlog, dated diagnostics, and promotion outcomes. Dated reports are evidence snapshots; they do not independently authorize paper or live changes.

### Quant Research OS bridge

[`quant_research_os/`](quant_research_os/README.md) is a thin bridge from approved research into repository contracts. If it conflicts with the decision register, the decision register wins.

### Runtime and operations

- [`exit_rules.md`](exit_rules.md) — exit policy, staged stops, trailing behavior, and protection health.
- [`experiment_workflow.md`](experiment_workflow.md) — experiment manifests and promotion workflow.
- [`log_paths.md`](log_paths.md) — live state, trade history, and exchange diagnostic paths.
- [`restruct.md`](restruct.md) — current module boundaries and canonical entrypoints.

### Historical notes

- [`backtest_results.md`](backtest_results.md) — historical 50-coin and earlier parameter results.
- [`backtesting_py_usage_notes.md`](backtesting_py_usage_notes.md) — research-sandbox notes for `backtesting.py`.

## Recommended workflow

1. Read the [current decision register](../.agents/current_decisions.md).
2. Read the relevant [research evidence](research_manual/README.md).
3. Confirm the runtime/config or experiment manifest that is the source of truth.
4. Make the smallest change within the approved boundary.
5. Run the validation commands documented in the affected workflow document.

