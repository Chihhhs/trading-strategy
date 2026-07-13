# Project Detail For Agents

這份文檔是給代理、協作型自動化工具與後續工程師快速建立上下文用的內部說明。目標不是教學，而是讓接手者能在幾分鐘內定位 live 主流程、狀態來源、排查入口與高風險修改區域。

## 專案定位

目前 repo 的主線能力分成三塊：

- `src/trading_strategy/backtest/`：離線回測
- `src/trading_strategy/paper.py`：Binance 資料驅動的 paper trading
- `src/trading_strategy/live/`：Hyperliquid live trading

目前的模組邊界已重構成：

- `src/trading_strategy/strategies/`：策略 registry、策略介面、`trend`、`intraday_momentum`
- `src/trading_strategy/positions/`：position lifecycle / snapshot / trend stop helper
- `src/trading_strategy/shared/`：risk / state / trade history 共用 helper
- `src/trading_strategy/core/`：相容層，舊 import 仍可用，但新實作不應再放進這裡

最近的變更重心集中在 live 安全性與策略架構：

- 以交易所持倉為權威來源接管本地部位
- 以 `perp` 資金而非 `spot` 餘額決定是否可 live 開倉
- live engine 的 paper mode 已與 live state 分離，避免 paper 觀測採用真實交易所倉位
- 用事件型 JSONL log 提升可觀測性
- 啟動時自動檢查並補掛 TP/SL
- backtest/live 透過 strategy hook 對齊出場語義
- backtest 支援 OI entry filter-only，僅過濾既有 trend 訊號，不加分、不單獨開倉
- live microstructure guard 目前為 observe-only，用於記錄 spread/depth/imbalance，不強制阻擋 entry
- backtest 支援 `--trend-evaluation-report`：固定比較多個窗口與幣池，輸出成本後績效、幣種貢獻、價格相關性與出場分組
- closed trade 會保留 `initial_risk`、`mfe_r`、`mae_r`、`best_close_r`，供日線 trend 出場研究區分 intrabar excursion 與收盤可執行的進展
- backtest 支援 `--trend-exit-replay-report`：日線只產生訊號與更新 stop，1h 僅重播前一個日線收盤已知的停損成交；此能力是研究工具，不改 live/paper
- adaptive ATR trail 是 backtest/paper 候選變體，依入場 ADX 使用較寬或較緊的 trail；預設關閉，未通過評估 gate 不接 live
- paper mode 可觀測 funding/basis/Bybit OI 與每個 trend signal 的完整 L2 context，寫入 `trend_signal_observed`；後續 K 線到位後寫入 1/3/6 bar 的 `trend_signal_outcome_observed`，不參與 entry；live mode 不會呼叫這個 OI/L2 研究 monitor
- paper observation 以 30 個去重 trend signals 為最低樣本門檻；`run_summary` 顯示已累積、pending 與剩餘樣本數，未達門檻不得將 OI/L2 觀測升級為 live guard
- 第一版短週期策略 `intraday_momentum` 已接線，但資料驗證顯示不可部署
- 後續主要研究線是獨立的 15m alpha discovery：先驗證 feature 的成本後 forward return，再建立策略；不得直接以日線 Funding/OI 或既有短週期 wiring 作為 live promotion 證據

## Canonical Entrypoints

- `python apps/runners/live_runner.py --live`
- `python apps/runners/live_runner.py --live --loop`
- `python apps/runners/paper_runner.py`
- `python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240`
- `python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --derivatives-data-path data/derivatives/bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json --enable-trend-position-control --enable-atr-trailing --enable-adaptive-atr-trail --trend-evaluation-report --fee-bps 4.5 --slippage-bps 2`
- `python backtest/backtest_runner.py --coins BTC,ETH,BNB --strategy trend --max-days 240 --derivatives-data-path data/derivatives/bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json --enable-trend-position-control --enable-atr-trailing --fee-bps 4.5 --slippage-bps 2 --trend-exit-replay-report --exit-replay-data-path data/historical_prices/binance_1h_240d_BTC_ETH_BNB.json`
- `python backtest/backtest_runner.py --coins BTC --strategy intraday_momentum --data-path data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json --max-days 8640`
- `python backtest/backtest_runner.py --coins BTC,ETH --optimize --strategy-grid trend,intraday_momentum`

Live 短週期策略切換應透過 `apps/live_config.py` 覆寫：

```python
STRATEGY_OVERRIDES = {
    "name": "intraday_momentum",
    "timeframe": "15m",
    "max_positions": 2,
    "risk_per_trade": 0.03,
}
```

## Live 模組地圖

### `src/trading_strategy/live/config.py`

- 定義 `MODE`
- 定義 `STATE_DIR`、`API_LOG_PATH`、`TRADE_LOG_PATH`
- 定義 runtime `STRATEGY` 與 `CIRCUIT`
- `config.STRATEGY` 是 runtime 真相來源
- `config.STRATEGY["name"]` 決定 active strategy
- `config.STRATEGY["timeframe"]` 決定 live K 線週期，預設 `1d`

重要路徑：

- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live_paper/live_state.json`
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
- paper mode 不會同步 Hyperliquid account，即使環境有 `HL_ACCOUNT_ADDRESS`

### `src/trading_strategy/live/engine/`

- 進出場主邏輯
- 持倉接管與保護單檢查
- 每輪摘要聚合

關鍵函式：

- `sync_state_with_exchange_positions()`
  - 交易所持倉為權威
  - 可接管本地未知部位
  - 會標記 `position_source`、`adopted_at`、`exchange_position_state`
- `ensure_position_protection()`
  - 依 strategy exit policy 檢查 TP/SL 或 SL-only 保護是否存在
  - 若缺失則呼叫 `place_hl_tpsl_orders()` 或 `place_hl_sl_order()`
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
- `get_klines()` 會讀 `config.STRATEGY["timeframe"]`

### `src/trading_strategy/strategies/`

- `BaseStrategy` 定義策略 hook：
  - `generate_signal()`
  - `build_exit_policy()`
  - `initialize_position()`
  - `should_block_for_btc()`
  - `evaluate_open_position()`
  - `resolve_stop_target()`
- `trend` 使用 `trend_sl_only`，live 預設只要求 SL，並由 strategy hook 管理 dynamic stop / ATR trail / failure exit。
- `intraday_momentum` 是短週期動能 / 波動突破 wiring baseline。它可在 5m / 15m / 1h K 線上運作，但目前資料驗證顯示 overtrade，不能部署。

## Runtime 真相來源

以下規則很重要：

- runtime 參數以 `config.STRATEGY` 為準
- `live_state.json.params` 是持久化快照，不是當前執行真相
- 若兩者不同，系統會記 `config_mismatch`
- live mode 使用 `data/paper_strategies_live/`
- live-engine paper mode 使用 `data/paper_strategies_live_paper/`
- 只有 live mode 會同步交易所帳戶與接管交易所持倉

不要做的事：

- 不要從 `live_state.json.params` 反推當前 `entry_order_type`
- 不要讓本地 state 覆蓋交易所持倉真相
- 不要把 paper mode 的觀測結果與 live adopted positions 混在一起解讀

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
- `live/engine/` 的持倉接管與保護單修復順序
- `account.py` 的 Hyperliquid balance / position / open order 同步
- `market.py` 的幣池來源、快取策略與 `timeframe` 行為
- `shared/state.py` 的 state 持久化欄位裁切
- `strategies/` 的 exit policy，因為它會同時影響 backtest 與 live protection

## 2026-07-10 Intraday Data Check

- 下載資料：`data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json`
- 範圍：2026-04-11 12:45 UTC 到 2026-07-10 12:30 UTC
- 每幣：8640 根 15m bars
- `intraday_momentum`, BTC-only, 90d, `risk=0.03`, `leverage=2`: `trades=573`, gross `pnl=-27.9%`, `drawdown=33.0%`
- 四幣同設定：`trades=2324`, gross `pnl=-59.1%`, `drawdown=77.5%`
- 費用估算：BTC-only turnover 約 `1866.7x` 起始資金，tier-0 taker fee drag 約 `84.0%`
- 結論：`intraday_momentum` 目前只能視為接線與研究 baseline，不能上 paper/live。

## 2026-07-13 Trend 1h Exit Replay

- 固定資料：`data/historical_prices/binance_1h_240d_BTC_ETH_BNB.json`，BTC/ETH/BNB 各 5,760 根，對齊日線 2025-11-03 到 2026-06-30，coverage 100%。
- 因果規則：日線收盤更新訊號與 stop；下一個日線區間只使用前一收盤已知 stop。跳空穿越 stop 以 1h open 成交，否則觸及時以 stop 成交。
- baseline：12 trades，net `-4.5%`，drawdown `17.5%`。
- 1h replay：13 trades，net `-26.7%`，drawdown `26.7%`，10 次 stop fill、0 次 gap fill。
- 差異：net `-22.2pp`，drawdown `+9.2pp`。結果與先前淘汰的 daily intrabar stop-first 一致。
- 結論：replay 工具保留作研究基礎，但「現有 stop 改成 1h 即時執行」未通過 promotion gate，不接 paper/live。下一輪若繼續出場研究，應測 stop 結構或啟動條件，而不是再次測更快執行。

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
python -m unittest discover tests
python -m compileall src tests
```

若環境的 `python` 不在 PATH，使用實際可用的 Python 執行檔，但測試內容不變。
