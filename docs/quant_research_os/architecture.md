# Architecture And Contracts

## Target

Keep the current repository and clarify its boundaries. Do not migrate to an
external trading framework.

```text
Market data -> features -> strategy signal -> decision and risk
            -> order intent -> backtest, paper, or Hyperliquid adapter
```

`shared/`, `strategies/`, and `positions/` stay deterministic and exchange-agnostic. `live/` owns Hyperliquid
translation, reconciliation, order verification, and TP/SL protection.

## Useful External Patterns

| Reference | Adopt locally | Do not adopt |
|---|---|---|
| VectorBT / QuantStats | fast screening and reports | live decision path |
| LEAN | alpha, risk, and execution boundaries | LEAN runtime |
| NautilusTrader | common domain contracts | a second execution engine |
| Freqtrade / Jesse | focused strategy API | bot state or executor |
| Qlib | reproducible experiment artifacts | ML before a causal use case |
| Hummingbot | order tracking and reconciliation ideas | connector model in shared strategy logic |

## Shared Contract Direction

Introduce these names only when a concrete change needs them. They are a
behavior-preserving naming and boundary guide, not a required refactor.

| Contract | Responsibility |
|---|---|
| `MarketFeatures` | computed inputs shared by strategies and policies |
| `StrategySignal` | a strategy proposal and rationale |
| `RegimeResult` | market context; never an execution command |
| `Decision` | policy result after signal, regime, and portfolio context |
| `OrderIntent` | final request handed to an execution adapter |

An `OrderIntent` may only be created after existing risk controls. A strategy or
regime rule must not bypass leverage, daily-loss, exposure, liquidation-buffer,
or protection checks.

## First Integration Slice

Use fast screening or reporting against repository-produced artifacts, then
validate each candidate in the existing cost-aware backtest. No framework
becomes a runtime dependency and no live behavior changes.
