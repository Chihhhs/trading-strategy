# Awesome Quant：Trading & Backtesting 技術選型

- Date: 2026-07-15
- Scope: [`awesome-quant`](https://github.com/wilsonfreitas/awesome-quant) 的 **Trading & Backtesting** 類別；本文件將其主要 Python、crypto 與 execution 相關資源納入盤點。
- Decision status: research guidance only. It does not authorize dependency installation, a runtime change, paper promotion, or live trading.

## Executive Decision

`awesome-quant` 是工具索引，不是本 repo 的架構藍圖。本 repo 保留既有的
`PortfolioBacktester`、experiment manifests 與 Hyperliquid runtime；新工具只有在
**獨立驗證、績效歸因或可重播 execution evidence** 三種缺口中證明價值時才可引入。

| Decision | Resources | Why |
|---|---|---|
| Evaluate first | VectorBT, QuantStats / jQuantStats | Respectively provide an independent vectorized research check and a presentation layer for existing trade/equity data. Neither becomes execution truth. |
| Architecture reference | Freqtrade, Jesse, NautilusTrader, LEAN, Lumibot, AutoTrader | Learn interfaces and operations; do not run a second bot or replace Hyperliquid protection. |
| Future research only | hftbacktest, PyLOB, CCXT, Qlib, FinRL, PyPortfolioOpt / skfolio | Require different data, a validated alpha problem, or a portfolio mandate that the repo does not yet have. |
| Do not adopt | archived / stale frameworks, opaque AI-agent bots, martingale bots | Their maintenance, assumptions, or decision opacity conflict with reproducible and safety-first operation. |

## Non-Negotiable Evaluation Contract

All tools are judged against the current repository contract, not their marketing claims.

1. **Research is not promotion.** The path is research -> cost-adjusted backtest -> gate -> bounded paper observation -> explicit live review.
2. **Use fixed costs.** Default research comparisons use `fee_bps=4.5` and `slippage_bps=2` per side (about 13 bps round trip). A zero-cost result is a diagnostic only.
3. **Keep the current truth boundary.** Exchange positions and open orders are live truth; runtime configuration is strategy truth. Local state and a third-party bot database are never authority.
4. **Keep execution semantics explicit.** A tool that fills at bar close, cannot model a hard stop, or has no deterministic intrabar policy is not a live-like validation engine.
5. **Protect before entering.** Unknown, missing, or ambiguous TP/SL blocks new entry. No candidate tool may auto-cancel or auto-replace ambiguous protection.
6. **Demand out-of-sample evidence.** Trend changes need the 50-coin causal replay and fixed walk-forward evidence. Intraday candidates additionally need turnover, fee drag, MFE/MAE, re-entry gap, session and direction attribution.

The canonical entrypoint remains `backtest/backtest_runner.py`; a third-party tool can read exported research data but must not be inserted into the paper/live path during evaluation.

## Priority Experiments

### 1. VectorBT — independent research validator

- **Classification:** evaluate first; research-only.
- **What it is:** a NumPy/pandas-based, Numba/Rust-accelerated quant research package intended to run many portfolio combinations quickly ([official docs](https://vectorbt.dev/)).
- **Useful gap:** fast, independent parameter and universe screening. It can expose whether conclusions depend on the repo engine's cost, sizing, or signal interpretation.
- **Do not use it for:** final hard-SL ordering, Hyperliquid fill behavior, protection management, or live execution. Vectorized entries/exits can conceal intrabar ordering and partial-fill assumptions.
- **First PoC:** export the *already decided* 50-coin Trend entry-attribution events and daily close series. Reproduce only a frozen baseline and one pre-declared entry filter, with the same timestamps, fee/slippage, no look-ahead, and walk-forward folds.
- **Success gate:** signs of net PnL and drawdown deltas agree with the canonical engine across frozen folds. A discrepancy is a research finding to explain, not a reason to choose the more favorable result.
- **Stop condition:** the implementation requires copying live strategy logic, changes fill semantics, or the conclusion changes solely because of unmodelled intrabar exits.

### 2. QuantStats and jQuantStats — reporting, not a new risk engine

- **Classification:** evaluate first; offline reporting adapter only.
- **What they are:** QuantStats produces return statistics, plots and HTML tear sheets; its three modules cover metrics, visualizations and reports ([project](https://github.com/ranaroussi/quantstats)). jQuantStats is a modern variation listed by awesome-quant ([catalog entry](https://github.com/wilsonfreitas/awesome-quant)).
- **Useful gap:** a consistent human-readable report for closed-trade/equity curves after the repo has calculated source-of-truth PnL.
- **Integration boundary:** create a pure exporter from an experiment result to a timestamped net-return series plus a trade table. Do not let either package calculate position sizes, fees, or closed-trade truth.
- **First PoC:** generate one static HTML/CSV report from `experiments/trend_baseline.json`, showing net return, drawdown, turnover, total fees/slippage, trade count, win/loss distribution, and per-coin contribution.
- **Success gate:** every headline metric reconciles to existing result fields; report adds attribution readability without altering the result.
- **Stop condition:** it expects daily equity while available data is sparse and forces interpolation, or it obscures the fee/slippage assumptions.

### 3. hftbacktest and PyLOB — execution realism after data readiness

- **Classification:** future research; never a shortcut around the existing L2 observe-only gate.
- **What they are:** hftbacktest models full tick/order-book data, limit-order queue position and latency ([project listing](https://github.com/wilsonfreitas/awesome-quant), [latency documentation](https://hft.readthedocs.io/en/latest/latency_models.html)); PyLOB is a functioning Python limit-order-book implementation.
- **Useful gap:** testing whether spread, top depth, imbalance and adverse selection predict a materially better entry or avoid bad fills.
- **Entry requirement:** versioned, venue-specific snapshots/deltas and trades; event and receive timestamps; reconnect/gap markers; a deterministic book reconstruction and the exact order type being evaluated.
- **First PoC:** replay **one venue and one liquid market** only. Compare the current observe-only microstructure guard with no guard; report forward returns, fill probability, spread paid, adverse selection, and event count. It must not feed a live blocker.
- **Success gate:** effect survives out-of-sample and is larger than data/replay uncertainty after costs.
- **Stop condition:** only OHLCV is available, snapshots cannot be reconstructed, or the result is based on chart-pattern labels rather than executable book events.

### 4. CCXT — portable collection adapter, not the Hyperliquid trading layer

- **Classification:** future research / data acquisition adapter.
- **What it is:** a multi-language crypto exchange API supporting more than 100 exchanges according to the awesome-quant catalog ([catalog entry](https://github.com/wilsonfreitas/awesome-quant)).
- **Useful gap:** standardized historical OHLCV, funding, or market-metadata collection for research fixtures from non-Hyperliquid venues.
- **Integration boundary:** a fetch-and-normalize command writes immutable, provenance-labelled fixture files. It does not place live orders, reconcile positions, or manage TP/SL.
- **First PoC:** download one frozen BTC/ETH OHLCV/funding fixture from one named venue; persist request parameters, exchange timestamps, missing bars and checksum.
- **Success gate:** the fixture is reproducible and aligns with the repo schema without silently filling gaps.
- **Stop condition:** it would replace direct Hyperliquid order/reconciliation calls or cannot preserve the required exchange-specific fields.

## Architecture References — Extract Principles, Do Not Migrate

### Freqtrade

Free Python crypto bot with backtesting, dry-run, optimization and exchange support ([official repository](https://github.com/freqtrade/freqtrade)). Its maintainers explicitly recommend dry-run before risking money. Its bar-data backtest is useful as a comparative research surface, but its SQLite state, strategy class and exchange adapters would create a competing live authority here.

**Extract:** config validation, dry-run separation, look-ahead and recursive-analysis checks, strategy discovery conventions, exportable backtest artifacts.  
**Do not extract:** live execution, persistent trade state, Telegram control, or protection lifecycle.  
**PoC if needed:** run no bot; translate one of its look-ahead-analysis ideas into a repo-local test against a frozen signal fixture.

### Jesse, OctoBot, OctoBot Script and Catalyst

These are crypto-focused full applications/frameworks. Jesse is described as an advanced Python crypto bot; OctoBot targets crypto strategies from backtest to optimization to live; Catalyst is an older crypto algorithmic library.

**Decision:** architecture-reference only for Jesse/OctoBot; no adoption. Catalyst is not a candidate without a maintenance and exchange-compatibility requalification.  
**Reason:** all require a strategy/exchange lifecycle of their own, while this repo already has strategy adapters and a safety-specific Hyperliquid engine.  
**Extract:** multi-timeframe data boundaries, strategy parameter serialization and dry-run UX only.

### NautilusTrader

Production-grade, Rust-native, event-driven infrastructure intended to share domain/execution semantics between deterministic simulation and live trading ([official documentation](https://nautilustrader.io/docs/)). Its current implementation has legacy v1 and developing Rust/PyO3 v2 paths, so adoption also incurs API-change risk ([implementation status](https://nautilustrader.io/docs/latest/concepts/rust/)).

**Decision:** strong long-term architecture reference; do not migrate in the current trend-validation phase.  
**When it becomes viable:** the repo has multiple venues/strategies, a durable market-data catalog, and evidence that maintaining separate simulation/live domain models is the bottleneck.  
**PoC:** a disposable, read-only replay of recorded events—not a Hyperliquid adapter or a live strategy port.  
**Stop condition:** it delays P0 protection observability or introduces a second live node.

### LEAN / QuantConnect

LEAN is a modular, event-driven engine for local research, backtests and live algorithms across asset classes ([official repository](https://github.com/QuantConnect/Lean)). It is mature and broad, but assumes the LEAN data/broker/integration model and has a substantial Docker/C# operational surface.

**Decision:** reference for pluggable models, portfolio construction and algorithm lifecycle; not an implementation candidate for this Hyperliquid-first Python repo.  
**When viable:** only if the product decision changes to multi-asset institutional research and a separate integration team accepts the operating model.  
**Do not use:** as evidence that a crypto signal is live-ready; data normalization and fill semantics still require independent validation.

### Lumibot, Blankly, AutoTrader, the0, aat, basana, algobroker, fast-trade

These cover unified backtest/live APIs, scheduled or async engines, or execution engines. They are legitimate design references for an abstraction boundary, but each asks the repository to adopt its lifecycle and broker model.

**Decision:** no adoption.  
**Extract:** idempotent order intent, async cancellation/error surfaces, event-loop ownership, and a narrow broker adapter interface.  
**Reason:** the current bottleneck is research evidence and protection reliability, not an absent generic scheduler.

### Backtesting.py, Backtrader, bt, pybacktest, pyqstrat, finmarketpy, QSTrader, Zipline / Zipline-reloaded, Moonshot, pyalgotrade, pylivetrader, pipeline-live, pinkfish, NowTrade, quantitative, analyzer, pythalesians, pyqstrat

This group spans simple bar backtests, older event-driven engines and Zipline-compatible stacks. `Backtesting.py` is explicitly a Python strategy backtester, while `backtrader` is a general Python library ([catalog](https://github.com/wilsonfreitas/awesome-quant)).

**Decision:** no production adoption; `Backtesting.py` is the only optional lightweight cross-check after VectorBT, and only for a deliberately simple, no-intrabar-exit signal.  
**Why not migrate:** they duplicate the repo backtest engine but do not carry the repo's experiment manifests, current cost contract, causal hard-SL replay or Hyperliquid protection invariants. Several are legacy/compatibility stacks, so maintenance must be verified at the time of any trial.  
**PoC:** if used, reproduce a fixed close-to-close toy strategy to validate accounting only—not the active Trend strategy.

## ML, RL and Agent Systems

### Qlib, FinRL, AlphaPy, PyBroker, bulbea and ML example repositories

Qlib is Microsoft's AI-oriented investment platform with data, modelling, risk, portfolio and execution components ([official repository](https://github.com/microsoft/qlib)); FinRL supplies RL trading environments and examples ([paper](https://arxiv.org/abs/2011.09607)).

**Decision:** future research only.  
**Reason:** these systems make the most sense for a labelled cross-sectional prediction/ranking problem. The present priority is causal trend-entry attribution, universe selection and live-like replay—not model capacity. RL also makes cost, non-stationarity and reward leakage easier to hide.  
**Entry requirement:** a frozen feature/label schema, purged walk-forward splits, a simple linear/tree baseline, benchmarked costs, and a decision about whether the output is a ranking, an entry filter or an exposure modifier.  
**First PoC:** offline prediction of the pre-defined 1/3/5/10-day Trend attribution labels; no order intent and no live configuration.  
**Stop condition:** it cannot beat a simple baseline OOS across universes, or feature availability is not causal.

### AI Quant Agents, TradeSight, Orallexa, Vibe-Trading, DeepAlpha, PRISM-INSIGHT, FinClaw, OpenFinClaw, TradeClaw, TBV1 and similar agent bots

These projects package LLM agents, dashboards, ML claims, natural-language strategy generation or automatic execution. The awesome-quant list reports some very large claimed performance figures; those claims are not evidence for this repository.

**Decision:** do not adopt as a decision maker or execution path.  
**Permitted use:** offline research assistant for source summarization, hypothesis bookkeeping, report drafting or invoking deterministic local tools with persisted inputs/outputs.  
**Required proof before any broader use:** complete code/data availability, timestamp-causal inputs, fixed costs, OOS splits, event count, and repeatable execution.  
**Hard prohibition:** an LLM may not cancel/recreate protection, override a safety gate, or originate live order parameters without deterministic policy and explicit human authorization.

## Portfolio, Risk and Data Infrastructure

### PyPortfolioOpt, skfolio, ffn and pysystemtrade

These tools address portfolio optimization, cross-validation and systematic portfolio construction. `skfolio` offers sklearn-compatible portfolio modelling; PyPortfolioOpt covers efficient-frontier and related methods ([catalog](https://github.com/wilsonfreitas/awesome-quant)).

**Decision:** future research only.  
**When useful:** after the repo has more than one independently validated return stream and must allocate a shared risk budget. They cannot repair a negative single-strategy edge.  
**First PoC:** use only net, cost-adjusted and synchronized experiment return series; compare equal-risk baseline against a constrained allocator with turnover limits.  
**Stop condition:** inputs are overlapping versions of the same Trend signal or weights change too frequently after costs.

### zvt, QuantSoftware Toolkit, qf-lib, Hikyuu, RQAlpha, QUANTAXIS and cross-language engines

These are broader research/data platforms, often market-specific or language-specific.

**Decision:** not applicable now.  
**Reason:** their data models and target markets do not solve the active crypto trend validation problem. Consider only with a deliberate market-expansion decision, owned data licensing and a new execution review.

## Catalog Coverage

The following covers the notable Python/crypto/engine items in the catalog's Trading & Backtesting section. “Reference” means read source/docs for ideas; it does **not** imply installation.

| Cluster | Resources | Repo decision |
|---|---|---|
| Independent research and reporting | VectorBT, Backtesting.py, QuantStats, jQuantStats, pybacktest, bt, pyqstrat, pytrendseries | VectorBT and one reporting adapter are candidates; all other engines are optional accounting cross-checks or no-adopt. |
| Event-driven / general engines | Backtrader, Zipline, Zipline-reloaded, QSTrader, pyalgotrade, aat, basana, Lumibot, Blankly, AutoTrader, fast-trade, LEAN, NautilusTrader, Barter | Learn architecture; retain the current engine and Hyperliquid runtime. |
| Crypto applications | Freqtrade, Jesse, Catalyst, OctoBot, OctoBot Script, Kelp, qtpylib, TBV1 | Freqtrade/Jesse/OctoBot are architecture references; none becomes a live path. Catalyst requires requalification; Kelp/TBV1 are out of scope. |
| Execution and exchange adapters | CCXT, algobroker, the0, capitalcom-cli, mx-trader-bridge, Tai, Workbench, Prop | CCXT can be a read-only research-fixture adapter; other execution layers are out of scope or market-specific. |
| ML / automated research | Qlib, FinRL-Library, AlphaPy, PyBroker, bulbea, machine-learning-for-trading, algorithmic-trading-with-python, AutoHypothesis | Offline future research only, after a causal prediction problem and simple baseline exist. |
| Agent / autonomous products | AI Quant Agents, TradeSight, Orallexa, Vibe-Trading, DeepAlpha, PRISM-INSIGHT, FinClaw, OpenFinClaw, TradeClaw | No autonomous strategy or execution adoption; use only deterministic-tool research assistance if needed. |
| L2 / HFT | hftbacktest, PyLOB, LFEST, OrderMatchingEngine, flashalpha-fill-simulator | Require tick/book data and replay; remain observe-only. |
| Market/portfolio platforms | pysystemtrade, QuantSoftware Toolkit, qf-lib, zvt, RQAlpha, Hikyuu, QUANTAXIS, rqalpha | Not applicable without an explicit broader-market or multi-sleeve product decision. |
| Clearly excluded patterns | binary-martingale, opaque signal bots, unmaintained/archived packages | Do not use. Martingale contradicts bounded-risk operation; stale code needs a new maintenance review before even a research trial. |

Some catalog entries are listings of educational repositories, country-specific applications, or non-Python implementations rather than reusable libraries. They are intentionally grouped above because their adoption decision is determined by the same boundary: no new live authority, and no broader-market pivot without an explicit product decision.

### Per-resource decision register

This register gives every named resource above an explicit disposition. “Later” means a data or product prerequisite is missing; “reference” means source/design reading is useful but no package evaluation is authorized.

| Resource | Disposition | Specific reason and next boundary |
|---|---|---|
| VectorBT | Evaluate | Independent, high-throughput replication of frozen research only; never final intrabar/live truth. |
| QuantStats | Evaluate | Read-only net-return/trade reporting adapter; metrics must reconcile to repo results. |
| jQuantStats | Compare later | Consider only if QuantStats lacks a needed maintained reporting feature; choose one, not both. |
| Backtesting.py | Optional cross-check | Use only for a simple close-to-close accounting test, not active stop/protection logic. |
| backtrader | Reference | Event-loop/indicator API reference; no migration from existing backtester. |
| bt | Do not adopt | Portfolio-allocation focus does not fill the current Trend evidence gap. |
| pybacktest | Do not adopt | Duplicates vectorized accounting without a stronger validation role. |
| pyqstrat | Reference | Transparent backtest design may inform tests; no direct need. |
| finmarketpy | Do not adopt | Broad market toolkit overlaps current research infrastructure without a crypto-specific gain. |
| QSTrader | Reference | Read portfolio/account separation patterns only. |
| Zipline | Do not adopt | Legacy ecosystem and non-crypto assumptions add migration cost. |
| Zipline-reloaded | Reference | Same conclusion; re-evaluate only for a named data/broker integration. |
| pyalgotrade | Do not adopt | Older general event engine; no unique capability for the current workflow. |
| pylivetrader | Do not adopt | Zipline-compatible live layer would create a second execution authority. |
| pipeline-live | Do not adopt | Equity pipeline/live extension is outside the crypto/Hyperliquid boundary. |
| Moonshot | Do not adopt | QuantRocket/Pandas stack is not a justified replacement for local experiments. |
| pinkfish | Do not adopt | Spreadsheet-oriented security analysis is not an execution-realism tool. |
| NowTrade | Do not adopt | Generic technical-strategy backtester with no required gap. |
| quantitative / analyzer / pythalesians | Do not adopt | General-purpose duplicates; require a concrete missing feature before reconsideration. |
| Freqtrade | Reference | Extract dry-run, look-ahead and recursive analysis ideas; never run it alongside live runtime. |
| Jesse | Reference | Extract crypto strategy organization/multi-timeframe patterns only. |
| OctoBot / OctoBot Script | Reference | UI/strategy packaging ideas only; do not introduce its execution or state layer. |
| Catalyst | Exclude pending requalification | Older crypto library: require current maintenance and exchange review before research use. |
| qtpylib | Do not adopt | Full trading stack overlaps existing runtime and does not solve the evidence gap. |
| Kelp / TBV1 | Do not adopt | Different exchange/product assumptions and no incremental research value. |
| Lumibot / Blankly / AutoTrader / fast-trade | Reference | Study unified lifecycle semantics only; no broker/runtime replacement. |
| aat / basana / Barter | Reference | Async/event model references if future concurrency architecture is deliberately redesigned. |
| algobroker / the0 | Do not adopt | Generic execution engines cannot own Hyperliquid reconciliation or protection. |
| capitalcom-cli / mx-trader-bridge | Exclude | Wrong broker/market and an unnecessary order-placement surface. |
| Tai / Workbench / Prop | Exclude | Different language and distributed-platform scope; no current product need. |
| NautilusTrader | Long-term reference | Candidate only after multi-venue, data-catalog and shared-domain-model needs are proven. |
| LEAN | Long-term reference | Mature multi-asset benchmark, but its operational model is disproportionate to the current task. |
| Hikyuu / RQAlpha / QUANTAXIS / rqalpha | Exclude | Target-market/data assumptions are outside the current crypto scope. |
| zvt / QuantSoftware Toolkit / qf-lib | Do not adopt | General research platforms; current repo already owns its experiment contract. |
| CCXT | Later | May collect immutable research fixtures; cannot replace exchange-specific live calls. |
| hftbacktest | Later | Needs replayable tick/book data, latency inputs and an adverse-selection evaluation. |
| PyLOB / LFEST / OrderMatchingEngine | Later | Useful only after a specific order-book simulation requirement and data contract exist. |
| flashalpha-fill-simulator | Later | Consider for a narrowly specified limit-order-fill question, not market-order Trend replay. |
| Qlib | Later | Requires a causal ML/ranking research problem and simple OOS baseline. |
| FinRL-Library | Later | RL is inappropriate before a stable, cost-aware supervised/rule baseline exists. |
| AlphaPy / PyBroker / bulbea | Later | ML tooling may support an offline benchmark; no strategy or execution ownership. |
| machine-learning-for-trading / algorithmic-trading-with-python | Reference | Educational material only; no production dependency. |
| AutoHypothesis | Later | Agentic idea generation is permissible only as reproducible offline hypothesis bookkeeping. |
| AI Quant Agents / TradeSight / Orallexa / Vibe-Trading | Exclude as decision systems | LLM/agent claims do not satisfy the causal, cost and safety contract. |
| DeepAlpha / PRISM-INSIGHT / FinClaw / OpenFinClaw / TradeClaw | Exclude as decision systems | Marketing metrics or autonomous workflow are not evidence and must not reach live order flow. |
| PyPortfolioOpt / skfolio / ffn / pysystemtrade | Later | Need several independent, validated net return streams before allocation is meaningful. |
| binary-martingale | Exclude | Martingale violates the repo's bounded-risk and explainability philosophy. |

## Adoption Sequence

1. Finish P0 protection reliability and run-summary observability first.
2. Add a read-only result exporter and trial one performance-reporting tool against a frozen existing experiment.
3. Run a separate VectorBT replication of the frozen Trend attribution baseline; document all semantic differences.
4. Only after a 50-coin 1h replay fixture exists, decide whether any research tool contributed a robust entry/universe hypothesis.
5. Collect L2 data and evaluate hftbacktest-style replay only after the data contract is satisfied; keep the existing microstructure guard observe-only until it passes its own gate.

## Source Notes

- [awesome-quant Trading & Backtesting catalog](https://github.com/wilsonfreitas/awesome-quant)
- [VectorBT documentation](https://vectorbt.dev/)
- [QuantStats project](https://github.com/ranaroussi/quantstats)
- [Freqtrade project and dry-run guidance](https://github.com/freqtrade/freqtrade)
- [NautilusTrader documentation](https://nautilustrader.io/docs/)
- [LEAN project](https://github.com/QuantConnect/Lean)
- [Qlib project](https://github.com/microsoft/qlib)
- [hftbacktest documentation](https://hft.readthedocs.io/)

External descriptions establish each project's stated scope. They do not validate its performance, exchange support, security posture or compatibility with this repository; those require a time-bounded PoC under the evaluation contract above.
