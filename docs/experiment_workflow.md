# Experiment Workflow

這份文件說明如何用同一份可重現的 experiment manifest 完成研究、成本後回測、候選比較、promotion gate 與 paper observation。Live 不會直接讀取 experiment manifest。

## 架構與設定真相

- `trading_strategy.strategies`：策略實作與 `StrategyDefinition` registry。Definition 宣告參數型別、能力、預設 timeframe 與最低資料量。
- `trading_strategy.experiments`：嚴格載入 JSON manifest，建立 `ExperimentSpec`，並透過 backtest/paper adapters 轉接既有引擎。
- `ExperimentSpec` 是研究與 paper 啟動的設定真相；paper state 中的 params 只是快照，不能覆蓋當次 spec。Experiment state 以安全名稱與 manifest fingerprint 共同定址，修改 manifest 會建立隔離 state，不會接管舊部位。
- `ExperimentResult` 與 `PromotionDecision` 都有 `version=1`，可序列化供報告與 promotion 使用。
- Paper session 沿用 manifest 的 fee/slippage；完整平倉與 partial reduction 都按 entry + exit notional 扣除成本，避免 paper balance 比 promotion 過度樂觀。
- Live runtime 仍以 `trading_strategy.live.config.STRATEGY` 為真相，研究結果不能自動改 live。

## Manifest 欄位

必要欄位包括 `version`、`name`、`dataset`、`coins` 與 `strategy`。建議每份 manifest 都明示：

- `dataset.id/path/derivatives_path`：資料識別與來源。
- `strategy.name/parameters/required_capabilities`：registry 策略、該策略允許的 typed parameters，以及 experiment 必須具備的能力。
- `portfolio`：初始資金、槓桿、單筆風險與最大持倉。
- `costs`：fee 與 slippage，promotion 不使用 gross PnL。
- `execution`：optional replay profile. `exit_replay_path` loads causal hourly bars, `exit_replay_mode` is `strict` or `close_confirmed`, and `drawdown_source=mark_to_market` makes promotion compare MTM drawdown. Existing manifests default to close-balance drawdown.
- `evaluation`：baseline 路徑、窗口、幣池、每組最低交易數、最低合格比較組數與多數 gate。
- `target_environment`：只允許 `research` 或 `paper`。

Loader 會拒絕未知欄位、未知策略參數、錯誤容器或 primitive 型別、非有限數值、空幣池、非正窗口、非法版本與不完整 gate，不會靜默 fallback。

短週期策略的 definition 可宣告有限 `context_bars`。例如 `intraday_momentum` 僅重算最近 90 bars，但 backtest engine 仍保留全域 bar index，避免 O(N²) 指標重算拖慢迭代或破壞持倉時間語義。日線 trend 目前不截斷 context，以維持既有數值。

## Canonical Commands

執行單一 experiment：

```bash
python backtest/backtest_runner.py run --experiment experiments/trend_baseline.json
```

比較多份 experiment：

```bash
python backtest/backtest_runner.py compare --experiments experiments/trend_baseline.json experiments/intraday_momentum_rejected.json
```

執行 promotion gate 並保存核准結果：

```bash
python backtest/backtest_runner.py promote --experiment experiments/trend_paper_candidate.json > /tmp/trend_promotion.json
```

只有輸出狀態為 `approved_for_paper`，且 decision 的 `candidate_fingerprint` 與目前 manifest 完全一致，才能啟動 paper：

```bash
python apps/runners/paper_runner.py --experiment experiments/trend_paper_candidate.json --approval-result /tmp/trend_promotion.json
```

若交易樣本不足，decision 會是 `rejected` 並包含 `insufficient eligible comparisons`；paper adapter 會拒絕啟動。負結果應保留，不得以缺資料解釋成弱 alpha。

目前附帶的 `trend_paper_candidate.json` 只有一組比較達到每組五筆交易，低於 `min_eligible_comparisons=3`，因此預期會被拒絕；它用來驗證 gate，不是可部署候選。

## 新增策略

1. 在 `src/trading_strategy/strategies/` 新增符合 strategy protocol 的小型策略模組。
2. 為策略建立 frozen parameter dataclass 與 `StrategyDefinition`，列出實際支援能力。
3. 新增 registry 與策略契約測試，再建立 baseline manifest。
4. 使用 `run` 與 `compare` 驗證多窗口、多幣池及成本後結果。
5. 只有通過 manifest 中 promotion gate 的候選才能改為 `target_environment=paper`。
6. 同步更新本文件、架構文件及 `.agents` 狀態文件；文件未同步不算完成。

新增策略不應修改 backtest CLI、optimizer、paper runner 或 live engine。若必須修改，代表策略能力或 adapter 邊界不足，應先重新檢視設計。
