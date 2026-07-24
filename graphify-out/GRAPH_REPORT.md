# Graph Report - D:\code\trading-strategy\docs  (2026-07-24)

## Corpus Check
- 30 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 30 nodes · 35 edges · 6 communities (4 shown, 2 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Research Evidence
- Runtime Documentation
- Research Planning
- Quant Research Bridge
- Historical Backtests
- HIP-3 News Research

## God Nodes (most connected - your core abstractions)
1. `Research Manual Index` - 19 edges
2. `Documentation Map` - 10 edges
3. `Short-Cycle Strategy Diagnosis` - 4 edges
4. `Quant Research OS` - 3 edges
5. `Quant Research Map` - 3 edges
6. `Intraday Strategy Candidates` - 3 edges
7. `回測結果紀錄` - 2 edges
8. `Quant Research Decision Framework` - 2 edges
9. `Current Strategy Review` - 2 edges
10. `Research Backlog` - 2 edges

## Surprising Connections (you probably didn't know these)
- `Documentation Map` --references--> `回測結果紀錄`  [EXTRACTED]
  README.md → backtest_results.md
- `Documentation Map` --references--> `backtesting.py Usage Notes`  [EXTRACTED]
  README.md → backtesting_py_usage_notes.md
- `Documentation Map` --references--> `Exit Rules`  [EXTRACTED]
  README.md → exit_rules.md
- `Documentation Map` --references--> `Experiment Workflow`  [EXTRACTED]
  README.md → experiment_workflow.md
- `Documentation Map` --references--> `Log And Record Paths`  [EXTRACTED]
  README.md → log_paths.md

## Communities (6 total, 2 thin omitted)

### Community 0 - "Research Evidence"
Cohesion: 0.17
Nodes (12): Alpha Discovery Plan, Carry / Funding / Basis Backtest, Trend Market-Context Candidate, Awesome Quant：Trading & Backtesting 技術選型, Fixed 38-Coin Trend Entry-Quality Diagnostic, Clean-room cross-sectional strength, 38-coin Trend BTC-regime attribution, Independent tradeable-strategy search (+4 more)

### Community 1 - "Runtime Documentation"
Cohesion: 0.25
Nodes (8): backtesting.py Usage Notes, Exit Rules, Experiment Workflow, Log And Record Paths, Documentation Map, Quant Research Decision Framework, Two Research Modes And Strategy Promotion, Restructure Notes

### Community 2 - "Research Planning"
Cohesion: 0.67
Nodes (4): Quant Research Map, Research Backlog, Intraday Strategy Candidates, Short-Cycle Strategy Diagnosis

### Community 3 - "Quant Research Bridge"
Cohesion: 0.67
Nodes (3): Architecture And Contracts, Research To Implementation Gate, Quant Research OS

## Knowledge Gaps
- **19 isolated node(s):** `backtesting.py Usage Notes`, `Exit Rules`, `Experiment Workflow`, `Log And Record Paths`, `Architecture And Contracts` (+14 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Research Manual Index` connect `Research Evidence` to `Runtime Documentation`, `Research Planning`, `Historical Backtests`?**
  _High betweenness centrality (0.744) - this node is a cross-community bridge._
- **Why does `Documentation Map` connect `Runtime Documentation` to `Research Evidence`, `Quant Research Bridge`, `Historical Backtests`?**
  _High betweenness centrality (0.482) - this node is a cross-community bridge._
- **Why does `Quant Research OS` connect `Quant Research Bridge` to `Runtime Documentation`?**
  _High betweenness centrality (0.131) - this node is a cross-community bridge._
- **What connects `backtesting.py Usage Notes`, `Exit Rules`, `Experiment Workflow` to the rest of the system?**
  _19 weakly-connected nodes found - possible documentation gaps or missing edges._