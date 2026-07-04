# Project Detail For Agents

這份文檔是給代理、協作型自動化工具與後續工程師快速建立上下文用的內部說明。目標不是教學，而是讓接手者能在幾分鐘內定位 live 主流程、狀態來源、排查入口與高風險修改區域。

## 專案定位

目前 repo 的主線能力分成三塊：

- `src/trading_strategy/backtest.py`：離線回測
- `src/trading_strategy/paper.py`：Binance 資料驅動的 paper trading
- `src/trading_strategy/live/`：Hyperliquid live trading

最近的變更重心集中在 `live/`：

- 以交易所持倉為權威來源接管本地部位
- 以 `perp` 資金而非 `spot` 餘額決定是否可 live 開倉
- 用事件型 JSONL log 提升可觀測性
- 啟動時自動檢查並補掛 TP/SL

## Canonical Entrypoints

- `python apps/runners/live_runner.py --live`
- `python apps/runners/live_runner.py --live --loop`
- `python apps/runners/paper_runner.py`
- `python backtest/backtest_runner.py --coins BTC,ETH --strategy both --max-days 240`

## Live 模組地圖

### `src/trading_strategy/live/config.py`

- 定義 `MODE`
- 定義 `STATE_DIR`、`API_LOG_PATH`、`TRADE_LOG_PATH`
- 定義 runtime `STRATEGY` 與 `CIRCUIT`
- `config.STRATEGY` 是 runtime 真相來源

重要路徑：

- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`
- `data/paper_strategies_live/live_api_debug.log`

### `src/trading_strategy/live/cli.py`

- live 的 CLI 與主執行流程
- `run_once()` 是 live 核心入口
- `run_loop()` 是輪詢模式

目前 `run_once()` 的關鍵順序：

1. `load_state()`
2. `sync_state_with_hl_balance()`
3. `ensure_live_perp_balance()`
4. `maybe_log_config_mismatch()`
5. `ensure_position_protection()`
6. `load_coin_list()` / `get_current_prices()`
7. `update_positions()`
8. 若存在未受保護持倉則跳過新開倉
9. 否則進入 `check_entries()`
10. 寫出 `run_summary`

### `src/trading_strategy/live/account.py`

- 負責 Hyperliquid 帳戶資訊同步
- 提取 `perp` 與 `spot` 資金
- 取得交易所 open orders 與持倉資訊
- 最終會呼叫 `sync_state_with_exchange_positions()`

關鍵原則：

- live 能否開倉以 `_perp_account_value` 為準
- `spot` 僅作觀測，不代表可開 perp 部位

### `src/trading_strategy/live/engine.py`

- 進出場主邏輯
- 持倉接管與保護單檢查
- 每輪摘要聚合

關鍵函式：

- `sync_state_with_exchange_positions()`
  - 交易所持倉為權威
  - 可接管本地未知部位
  - 會標記 `position_source`、`adopted_at`、`exchange_position_state`
- `ensure_position_protection()`
  - 檢查 TP/SL 是否已存在
  - 若缺失則呼叫 `place_hl_tpsl_orders()`
  - 若仍失敗，`unprotected_positions_count` 會上升
- `check_entries()`
  - 只在沒有未受保護持倉時執行
  - 會為 skip / reject / fail 寫出事件 log
- `build_run_summary()` / `finalize_run_summary()`
  - 聚合 blocker、rejection reason、TP/SL 保護統計

### `src/trading_strategy/live/orders.py`

- entry 單、trigger TP/SL、close order
- Hyperliquid order 結果摘要與 verify 邏輯
- tick-aware 價格正規化

關鍵函式：

- `place_hl_order()`
- `place_hl_trigger_order()`
- `place_hl_tpsl_orders()`
- `normalize_hl_order_params()`
- `normalize_trigger_order_prices()`

注意：

- TP/SL 不能再用固定 8 位小數假設價格合法
- trigger order 的 `triggerPx` 與 `limit_px` 都需要符合交易所 tick 規則

### `src/trading_strategy/live/market.py`

- live 幣池來源與價格抓取
- `load_coin_list()` 會快取到 `coin_list.json`
- live 預設市場資料來源會偏向 Hyperliquid universe

## Runtime 真相來源

以下規則很重要：

- runtime 參數以 `config.STRATEGY` 為準
- `live_state.json.params` 是持久化快照，不是當前執行真相
- 若兩者不同，系統會記 `config_mismatch`

不要做的事：

- 不要從 `live_state.json.params` 反推當前 `entry_order_type`
- 不要讓本地 state 覆蓋交易所持倉真相

## Live state 與 log 形狀

### `live_state.json`

常見重要欄位：

- `balance`
- `_balance_source`
- `_perp_account_value`
- `_spot_account_value`
- `_balance_warning`
- `_frontend_open_orders`
- `positions`

單一 position 常見重要欄位：

- `coin`
- `direction`
- `entry`
- `size`
- `tp`
- `sl`
- `entry_time`
- `entry_time_source`
- `position_source`
- `adopted_at`
- `exchange_position_state`
- `tp_order`
- `sl_order`
- `protection_status`

`protection_status` 常見值：

- `protected`
- `missing_tpsl`
- `repair_failed`

### `live_trading_records.jsonl`

優先排查這份檔案。常見重要事件：

- `run_started`
- `account_snapshot`
- `config_mismatch`
- `entry_skipped`
- `entry_order_attempted`
- `entry_order_rejected`
- `entry_order_not_filled`
- `position_opened`
- `position_adopted`
- `state_exchange_mismatch`
- `tpsl_missing_detected`
- `tpsl_repair_attempted`
- `tpsl_repair_failed`
- `tpsl_repaired`
- `run_summary`

近期與 TP/SL 相關的關鍵欄位：

- `requested_trigger_px`
- `trigger_px`
- `requested_limit_px`
- `limit_px`
- `tick_size`
- `order_side`
- `price_source`
- `rejection_reason`

### `live_api_debug.log`

第二層排查檔。當 `live_trading_records.jsonl` 只看到高層結果時，再回來看這份：

- `hl_order_submit`
- `hl_trigger_order_submit`
- `hl_order_verify`
- 帳戶餘額同步相關事件

## Live 控制原則

### 資金判定

- live 只接受 `perp` 可交易資金
- 若 `_perp_account_value <= 0`，即使 `spot` 有錢也不應開新倉

### 交易所持倉優先

- 重啟後先讀交易所持倉，再與本地 state 對齊
- 若交易所有部位、本地沒有，應接管為本地 position
- 若本地有部位、交易所沒有，可能會被標記為 stale / mismatch

### 保護單優先於新開倉

- 每輪開始先檢查持倉保護
- TP/SL 缺失時先補掛
- 還有未受保護持倉時，跳過新開倉

## 常見排查路徑

### 1. 沒有下單

先看 `run_summary` 與 `entry_skipped`：

- `top_blockers`
- `missing_price_count`
- `entry_rejected_reasons`
- `size_zero`
- `btc_filtered`

### 2. 有進單但交易所拒絕

看 `entry_order_rejected`：

- `message`
- `rejection_reason`
- `resolved_price`
- `raw_price`
- `normalized_price`
- `best_bid`
- `best_ask`
- `price_source`

### 3. 有持倉但沒有 TP/SL

看：

- `tpsl_missing_detected`
- `tpsl_repair_attempted`
- `tpsl_repair_failed`
- `tpsl_repaired`

再對照 state 裡的：

- `tp_order`
- `sl_order`
- `protection_status`

### 4. 帳戶看起來有錢但 live 不開倉

看 `account_snapshot` 與 state：

- `_perp_account_value`
- `_spot_account_value`
- `_balance_warning`

## 高風險修改區域

以下區域改動時要特別保守：

- `orders.py` 的 tick size 推導與 trigger order 價格正規化
- `engine.py` 的持倉接管與保護單修復順序
- `account.py` 的 Hyperliquid balance / position / open order 同步
- `market.py` 的幣池來源與快取策略
- `core/state.py` 的 state 持久化欄位裁切

## Agent 修改守則

- 不要讓本地 state 覆蓋交易所持倉真相
- 改下單或保護單邏輯時，同步更新 `tests/test_live.py`
- 新增 skip / reject / repair 分支時，要同步補 log 事件
- 優先維持 `run_summary` 可快速判斷 blocker
- live 問題先看 `live_trading_records.jsonl`，再看 `live_api_debug.log`
- 若更動 state 欄位，確認 `core/state.py` 仍會安全持久化需要的資訊

## 建議的最小驗證

修改 live 流程後，至少跑：

```bash
python -m unittest tests.test_live
python -m compileall src tests
```

若環境的 `python` 不在 PATH，使用實際可用的 Python 執行檔，但測試內容不變。
