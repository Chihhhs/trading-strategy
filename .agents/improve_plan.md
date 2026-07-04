# Improve Plan For Agents

這份文檔整理目前 live 交易流程的改善脈絡，讓後續 agent 或工程師可以快速知道：

- 已經修了什麼
- 現在系統的真實行為是什麼
- 下一步還值得優先改善哪些區塊
- 每次修改後應該怎麼驗證

## 1. Current Status

目前 live 主流程已具備以下能力：

- 以 Hyperliquid `perp` 可交易資金作為 live 開倉前檢查
- 啟動時同步交易所持倉，而不是只依賴本地 `live_state.json`
- 可接管交易所上存在但本地未知的持倉
- 啟動時檢查缺失的 reduce-only TP/SL
- 若 TP/SL 缺失，會自動補掛
- 若仍有未受保護持倉，會阻止新開倉
- 每輪執行會寫出 `run_started`、`account_snapshot`、`run_summary`
- entry / TP/SL / skip / reject 都有事件型 JSONL log

目前 canonical 入口：

- `python apps/runners/live_runner.py --live`
- `python apps/runners/live_runner.py --live --loop`

目前主要資料檔：

- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`
- `data/paper_strategies_live/live_api_debug.log`

## 2. Improvements Already Completed

### 2.1 資金判定修正

已完成：

- 帳戶資金拆成 `_perp_account_value` 與 `_spot_account_value`
- `balance_source` 會明確標示來源
- live 模式只接受 `perp` 可交易資金
- `spot-only` 狀態下會阻止 live 開倉

目的：

- 避免把統一帳戶或 spot 餘額誤判成可以開 perp 倉位的資金

### 2.2 交易所持倉接管

已完成：

- `sync_state_with_exchange_positions()` 會從交易所 `assetPositions` 重建本地部位
- 若本地沒有對應 coin，會建立 `position_adopted`
- 若本地有但交易所沒有，會記錄 `state_exchange_mismatch`

新增的重要 position 欄位：

- `position_source`
- `entry_time_source`
- `adopted_at`
- `exchange_position_state`
- `protection_status`

目的：

- 讓 live 程式重啟後仍能繼續管理交易所上的真實部位

### 2.3 TP/SL 成功判定與補掛

已完成：

- trigger order 不再以 `unknown` 視為成功
- TP/SL 會依真實 order status 判定 `ok`
- 啟動時會檢查交易所 open orders 是否存在 reduce-only TP/SL
- 若缺失會自動補掛
- 若補掛失敗，會阻止新開倉

新增的重要事件：

- `tpsl_missing_detected`
- `tpsl_repair_attempted`
- `tpsl_repaired`
- `tpsl_repair_failed`

### 2.4 TP/SL tick-aware 價格正規化

已完成：

- `place_hl_trigger_order()` 不再用固定 8 位小數處理 trigger price
- `triggerPx` 與 `limit_px` 都會依 order book 推導出的 tick size 正規化
- TP/SL 補掛 log 會保留 requested / normalized 價格與 `tick_size`

新增的重要欄位：

- `requested_trigger_px`
- `trigger_px`
- `requested_limit_px`
- `limit_px`
- `tick_size`
- `order_side`
- `price_source`

### 2.5 可觀測性與 summary

已完成：

- `check_entries()` 多數 skip path 都會寫 `entry_skipped`
- entry reject 會記錄價格上下文
- `run_summary` 會聚合 blocker、missing price、reject reason、TP/SL 保護狀態
- runtime 與 state snapshot 不一致時會寫 `config_mismatch`

## 3. Current Observations

從目前 log 可讀到幾個重要現象：

### 3.1 TP/SL 補掛已從失敗變成成功

早期 log 顯示：

- `tpsl_repair_failed`
- `message = "Order has invalid price."`

較新的 log 已顯示：

- `tpsl_repaired`
- ETH / LTC / kPEPE 都成功取得 TP 與 SL 的 `oid`
- `run_summary.tpsl_repaired_count = 3`
- `run_summary.unprotected_positions_count = 0`

這代表 TP/SL trigger price 正規化修正已經生效。

### 3.2 config/state 仍有漂移

目前 log 持續出現：

- `config_mismatch`

典型情況：

- state snapshot 的 `entry_order_type = "post_only"`
- runtime `entry_order_type = "ioc"`

這不是致命錯誤，但很容易誤導人工排查。

### 3.3 max positions 導致新一輪不再進單

目前較新的 `run_summary` 顯示主 blocker 常是：

- `max_positions_reached`

這代表「沒有新單」不一定是異常，也可能只是系統按設計停止加倉。

## 4. Next Improvements Worth Prioritizing

以下是下一輪最值得做的改善項目，依優先度排序。

### P1. 把 `project_detail.md` 修成穩定 UTF-8 可讀版本

現況：

- `.agents/project_detail.md` 目前內容可用，但閱讀結果看起來有編碼問題

建議：

- 重新以乾淨 UTF-8 重寫一遍
- 保留現有內容結構，但確保在一般編輯器與終端都可讀

原因：

- agent 文檔是後續維護入口，若亂碼會直接拖慢接手效率

### P1. 強化 `run_summary` 的持倉上下文

現況：

- `run_summary` 已有 blocker 與 TP/SL repair 統計
- 但對「為什麼這輪不掃描/不開倉」還可以更直接

建議擴充欄位：

- `positions_count`
- `protected_positions_count`
- `max_positions`
- `daily_loss_limit_hit`
- `has_unprotected_positions`

原因：

- 讓人只看 summary 就知道是資金問題、保護問題，還是加倉上限問題

### P1. 讓 open order 比對更嚴格

現況：

- `match_existing_protection_order()` 以 `coin + reduceOnly + tpsl` 為主

建議：

- 增加 size 或 trigger price 的合理比對
- 避免把同 coin 的舊 reduce-only 單誤認成目前持倉的保護單

原因：

- 持倉重複開平、部位大小變動時，單純靠 coin / tpsl 可能不夠保險

### P2. 增加保護單一致性巡檢

建議新增檢查：

- 本地 `tp_order/sl_order.oid` 是否真的仍存在於交易所
- 若交易所單子被取消、手動刪除、部分失效，能否標記 `stale_protection`

可新增事件：

- `tpsl_stale_detected`
- `tpsl_verification_failed`

原因：

- 現在系統已經會補掛缺失單，但還缺少持續確認「已保存的保護單是否仍然活著」

### P2. 明確區分 `verify_status = order` / `open` / `unknownoid`

現況：

- 新 log 裡可見某些 TP/SL `verify_status = "unknownoid"`，但仍被視為 `resting`

建議：

- 文件化這些狀態的意義
- 若必要，將 `unknownoid` 拉成一種需要後續再驗證的中間狀態

原因：

- 避免之後把「未完全確認」和「已穩定存在」混成同一類成功

### P2. 降低市場資料與交易 universe 漂移風險

現況：

- 先前曾出現 `missing_price` 很多、掃描 universe 與實際可交易 universe 不一致

建議：

- 持續把 live universe 以 Hyperliquid 可交易標的為準
- 若 `coin_list.json` metadata 不一致，強制重建
- 在 summary 中保留 `priced_ratio` 與 sample coins

原因：

- 這一塊已改善，但很容易回歸

## 5. Suggested Workstreams

可把後續改善拆成三個工作流：

### Workstream A: Protection Reliability

- 保護單存在性驗證
- stale order 檢測
- open order 比對更嚴格
- `unknownoid` 後續確認策略

### Workstream B: Observability

- 擴充 `run_summary`
- 補更清楚的 state / exchange mismatch 診斷欄位
- 補充針對保護單 lifecycle 的統計

### Workstream C: Documentation Hygiene

- 修正 `.agents/project_detail.md` 可讀性
- 維護 README 與 `.agents` 文檔同步
- 為 live 故障排查建立固定流程模板

## 6. Validation Checklist

每次碰 live 核心邏輯，至少做以下驗證：

### 自動化

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

### 手動 log 檢查

至少確認：

- `run_started`
- `account_snapshot`
- `config_mismatch` 是否合理
- `tpsl_missing_detected` / `tpsl_repaired` 是否符合預期
- `run_summary` 中的 `top_blockers`

### 實際狀態檢查

至少對照：

- `live_state.json`
- `live_trading_records.jsonl`
- 交易所 open orders / positions

## 7. Agent Rules For Future Changes

- 不要用本地 state 推翻交易所持倉真相
- 不要把 `spot` 餘額當成 live 可交易保證金
- 改 order 價格正規化時，要同時看 entry order 與 trigger order
- 改 log schema 時，要同步更新測試與文檔
- 若觀察到 log 與 state 不一致，先查 `save_state()` 的持久化裁切邏輯
