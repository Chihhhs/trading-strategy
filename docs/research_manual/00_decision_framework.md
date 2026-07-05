# Quant Research Decision Framework

- Date: 2026-07-05
- Data range: Current repo behavior plus local backtest observations available on 2026-07-05
- Applicable markets: Crypto spot/perps, with current emphasis on liquid major coins
- Last updated: 2026-07-05

## Goal

這份手冊不是純研究筆記，而是用來支持策略的 `保留 / 降權 / 淘汰 / 待驗證` 決策。

## Evidence Levels

### A

- 多篇學術或實證研究支持。
- 可以直接映射到目前 repo 的策略問題。
- 預設可作為主線研究骨架。

### B

- 單篇或較新的研究支持，或跨市場證據可合理外推到 crypto。
- 適合保留，但要搭配 walk-forward、成本與參數穩定性驗證。

### C

- 主要來自 practitioner 經驗、社群方法或微結構直覺。
- 缺少穩健學術驗證。
- 只能當實驗模組，不能直接當主線策略核心。

## Required Entry Template

每個研究條目都應使用同一格式：

- Claim
- Evidence level
- Market applicability
- Time horizon
- Known failure modes
- Cost sensitivity
- Implementation implication
- Decision for this repo
- Sources

## Repo Decision Rules

### Keep

- 證據等級為 `A` 或強 `B`，且目前 repo 結果不明顯衝突。

### Downgrade

- 概念可能有價值，但目前證據或本地結果不足以繼續放在主策略核心。

### Remove

- 證據弱，且本地表現差或高度重疊，繼續維護的價值低。

### Validate Further

- 概念合理，但受限於缺少 walk-forward、成本模型、或 live/backtest 語義一致性。

## Current Repo Baseline

- `trend + BTC regime filter + ATR/EMA/ADX + dynamic stop` 是目前最合理的主線。
- `FVG` 已從現行策略面移除，只保留歷史研究背景。
- `both` 已隨 FVG 移除，不再視為現行策略選項。
- `docs/backtest_results.md` 是歷史回測記錄，不應直接當研究事實來源。
- `docs/exit_rules.md` 是目前 live / paper 行為規格來源。
