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
- live engine 的 paper mode 使用獨立 state dir，不再同步 Hyperliquid account
- 每輪執行會寫出 `run_started`、`account_snapshot`、`run_summary`
- entry / TP/SL / skip / reject 都有事件型 JSONL log
- 策略架構已重構為 `trading_strategy.strategies`
- backtest/live 已透過 strategy hook 對齊出場語義
- live K 線週期可由 `config.STRATEGY["timeframe"]` 控制
- microstructure guard 已接 live entry 前，但目前以 observe-only 為預設
- backtest 已支援 OI entry filter-only，用來測試 OI 是否能改善 trend entry 品質
- 第一版短週期策略 `intraday_momentum` 已接線，但資料驗證顯示不能部署

目前 canonical 入口：

- `python apps/runners/live_runner.py --live`
- `python apps/runners/live_runner.py --live --loop`
- `python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240`
- `python backtest/backtest_runner.py --coins BTC --strategy intraday_momentum --data-path data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json --max-days 8640`
- `python backtest/backtest_runner.py run --experiment experiments/trend_baseline.json`
- `python backtest/backtest_runner.py promote --experiment experiments/trend_paper_candidate.json`
- `python apps/runners/paper_runner.py --experiment experiments/trend_paper_candidate.json --approval-result /tmp/trend_promotion.json`

目前主要資料檔：

- `data/paper_strategies_live/live_state.json`
- `data/paper_strategies_live_paper/live_state.json`
- `data/paper_strategies_live/live_trading_records.jsonl`
- `data/paper_strategies_live/live_api_debug.log`
- `data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json`

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

### 2.6 策略架構重構

已完成：

- 新增 `trading_strategy.strategies` 作為策略 registry 與策略介面位置
- 新增 `BaseStrategy` / `StrategyContext` / `StrategySignal`
- `trend` 已搬到策略模組，舊 `core.*` import 保留為相容層
- backtest engine 會呼叫策略 hook：
  - `build_exit_policy()`
  - `initialize_position()`
  - `evaluate_open_position()`
  - `resolve_stop_target()`
- live entry / position update 也透過 active strategy 取得 signal 與 exit 行為

目的：

- 讓 backtest 與 live 不再各自硬寫 trend 出場邏輯
- 讓後續新增策略不需要修改 live 核心流程

### 2.7 短週期策略接線與資料驗證

已完成：

- 新增 `intraday_momentum`
- backtest CLI 支援 `--strategy intraday_momentum`
- optimizer 可用 `--strategy-grid trend,intraday_momentum`
- live `get_klines()` 支援 `config.STRATEGY["timeframe"]`
- 下載 Binance 15m 90d BTC/ETH/SOL/BNB K 線到：
  - `data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json`

驗證結果：

- `intraday_momentum`, BTC-only, 90d: `trades=573`, gross `pnl=-27.9%`, `drawdown=33.0%`
- 四幣同設定: `trades=2324`, gross `pnl=-59.1%`, `drawdown=77.5%`
- BTC-only turnover 約 `1866.7x` 起始資金，tier-0 taker fee drag 約 `84.0%`

結論：

- `intraday_momentum` 目前只能當 wiring baseline。
- 不應上 paper/live。
- 下一步應先做 cost/slippage model、turnover 限制、regime filter。

### 2.8 Position control、OI filter、microstructure guard

已完成：

- `derivatives_crowding_exit_enabled=True` 可用於 trend position control，live 設定採 `action=reduce`、`reduce_fraction=0.75`
- live `run_summary.strategy_snapshot` 會記錄 position control 與 microstructure guard 設定
- microstructure guard 使用 Hyperliquid L2 top book 計算 spread、top depth、book imbalance
- microstructure guard 預設 `observe-only`，只記錄 would-block，不強制阻擋 live entry
- live-engine paper mode 與 live mode state dir 分離，paper 不再同步 Hyperliquid account
- Binance OI history 覆蓋不足，改用 Bybit OI + Binance funding/basis fixture：
  - `data/derivatives/bybit_oi_binance_funding_basis_240d_BTC_ETH_BNB.json`
- OI entry filter-only 已接 backtest CLI：`--enable-oi-entry-filter`

驗證結果：

- live safety report 顯示目前 4 個 adopted positions 皆有 TP/SL 保護
- 隔離後 paper single-cycle 顯示 `balance=$1000`、`positions=0`、`balance_source=local_state`
- BTC/ETH/BNB 240d live-like trend baseline: `net_pnl=-23.9%`, `drawdown=46.0%`
- trend + position control: `net_pnl=-6.7%`, `drawdown=33.8%`
- trend + position control + OI entry filter-only: `net_pnl=+31.6%`, `drawdown=10.7%`, 但只有 5 trades，仍需更大樣本驗證

後續擴樣驗證：

- BTC/ETH/BNB 240d OI lookback 3/5 穩定為正；lookback 10 轉弱但仍為正
- BTC/ETH/BNB 提高 OI min change 到 `0.5%` / `1.0%` 後，240d 表現更好，但交易數降到 4
- BTC/ETH/BNB 近 120d / 180d 不穩：寬鬆 OI filter 只觸發 1 筆且虧損，嚴格門檻則沒有交易
- 擴展到 BTC/ETH/BNB/XRP/DOGE/ADA/LINK/LTC 後，position control 單獨為 `net_pnl=+11.5%`、`drawdown=24.7%`
- 同一 8 幣 universe 加 OI filter-only 後，`min_change=0.5%` 為 `net_pnl=-4.8%`、`drawdown=41.9%`
- `min_change=1.0%` 小幅轉正但 score 仍負；`min_change=2.0%` 明顯轉差

結論：

- OI entry filter-only 尚未達 live promotion 標準。
- 目前可 live 的 alpha-derived component 仍只有 funding/basis position control。
- OI filter 可進 paper-only / research monitor，等待更多樣本與更長 OOS 驗證。

### 2.9 Robustness gate 與 adaptive trail 候選

已完成：

- 新增 `--trend-evaluation-report`，用固定窗口 `120/180/240` 與多組 universe 比較 frozen baseline 和單一 candidate。
- 評估報告輸出成本後 net PnL、drawdown、score 差異、幣種貢獻、價格相關性，以及依 `ATR_TRAIL` / `FAILURE` / `SL` 等 exit reason 分組的 PnL、持有 bar、MFE、MAE。
- 新增可選 adaptive ATR trail：入場 ADX 高於門檻時使用較寬 trail，否則使用較緊 trail。預設關閉，不改既有 live 行為。
- paper mode 可在訊號出現時記錄 Binance funding/basis + Bybit current OI；live mode 硬性跳過這個 monitor。
- microstructure snapshot report 可比較 would-block 與 allowed 事件的後續方向報酬；沒有 L2 replay 資料時不得宣稱 guard 有 alpha。

首次實測：

- 以 BTC/ETH/BNB/XRP/DOGE/ADA/LINK/LTC、240d Bybit OI + Binance funding/basis、`fee=4.5bps`、`slippage=2bps` 測試 adaptive ATR trail。
- 九組固定比較中只有兩組達到每組五筆 trades 的最低樣本；雖然兩組皆不劣於 baseline，仍未達至少三組合格樣本的 gate，結果為 `passes_majority_gate=False`。
- 因此 adaptive ATR trail 保留為 research-only，不進 paper/live。
- paper live-engine 單輪已確認 `derivatives_monitor_enabled=True`、`priced_ratio=1.0`，但當下沒有訊號，故 `derivatives_context_observed=0`；OI event 欄位與 live hard gate 由 unit tests 驗證。
- paper 研究現在會在每個 trend signal 記錄 funding/basis/Bybit OI 與 Hyperliquid L2（包含 allowed 與 would-block），並持久化等待 1/3/6 根後的方向化 forward return。觀測佇列只在 paper mode 啟用，預設 30 個去重訊號為最小樣本；尚未達門檻前不得改為 entry filter 或 live 強制 guard。

Promotion gate：

- candidate 必須在至少三個具備足夠交易樣本的固定比較中，以每組至少五筆 trades 為下限，並在多數比較同時不劣於 baseline 的 net PnL 與 max drawdown。
- 只有通過 gate 的單一候選，才允許進 paper；不直接接 live。

### 2.10 Experiment spec 與 promotion workflow

已完成：

- strategy registry 增加 typed `StrategyDefinition`、capabilities、default timeframe 與 minimum bars。
- JSON manifest 嚴格轉成 `ExperimentSpec`，以 fingerprint 確保可重現。
- backtest adapter 輸出成本後 `ExperimentResult`，包含 turnover 與幣種貢獻。
- promotion gate 只比較樣本足夠的相同窗口/幣池，net PnL 與 drawdown 同時不劣於 baseline 才算通過。
- experiment paper runner 必須取得 `approved_for_paper` decision，並使用相同 strategy hooks 與 typed parameters。
- live 保持隔離，不消費研究 manifest。
- intraday experiment 使用 90-bar rolling strategy context，避免長窗口回測重複計算完整歷史。
- manifest loader 嚴格拒絕錯誤容器/boolean、非有限成本與非正窗口；paper state 以 fingerprint 隔離，避免 stale spec 或 legacy state 碰撞。

實測：

- trend paper candidate 六組比較中僅一組達到每組五筆交易，低於三組門檻，promotion 正確回傳 `rejected`。
- intraday rejected baseline 在 2,880–8,640 bars、BTC/四幣比較中，成本後 PnL 約 `-52.7%` 至 `-99.8%`，turnover 約 `807.8x` 至 `1968.9x`，仍不可進 paper/live。

Promotion 邊界固定為 `research -> cost-adjusted backtest -> majority gate -> paper observation -> explicit live review`。目前尚未處理 live config 與 experiment spec 的統一，這是刻意保留的安全邊界，不應在沒有獨立設計與驗證時自動擴張。

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

### 3.4 短週期策略目前主要問題是成本與 turnover

15m 資料驗證顯示：

- 交易次數太高
- gross PnL 已經偏弱
- 扣 maker/taker fee 後不可接受

這代表短週期策略下一步不是直接調高風險或上 live，而是先降低 turnover 並加入成本模型。

## 4. Next Improvements Worth Prioritizing

以下是下一輪最值得做的改善項目，依優先度排序。

### P1. 成本 / 滑價 / turnover 模型

現況：

- backtest 目前沒有內建 maker/taker fee、spread、slippage
- 15m 策略的 turnover 足以讓費用主導結果

建議：

- 在 backtest summary 補 `turnover`
- 增加 maker/taker fee、spread、slippage 參數
- summary 同時輸出 gross 與 net PnL
- optimizer 排序應以 net score 為主

原因：

- 沒有成本模型時，短週期策略的回測幾乎不可用

### P1. 短週期策略 turnover 限制與 regime filter

現況：

- `intraday_momentum` 已接線，但 overtrade
- 90d BTC-only 573 筆，四幣 2324 筆

建議：

- 增加最小 bar 間隔 / cooldown
- 增加 BTC 高階 regime filter
- 增加 ATR percentile / volatility regime filter
- 增加成交量與趨勢品質門檻
- 先用 BTC-only 15m 資料驗證，再擴展到四幣

原因：

- 第一版策略證明 wiring 可用，但不是有效 alpha

### P1. 日線 trend 出場快速迭代

現況：

- live baseline 維持 `trend + funding/basis position control`；不因研究候選改動 live 預設。
- 240d 成本後出場診斷以 `SL` 為主，ATR trail 只在少數長趨勢捕捉到收益。
- `breakout_failure` 的既有測試已被淘汰；不得以單一窗口的局部改善重新推進，且不新增專用 CLI 或 live/paper 設定。
- closed trade 現在會記錄 `initial_risk`、`mfe_r`、`mae_r` 與僅依已收盤 K 線計算的 `best_close_r`；robustness report 依 exit reason 聚合 R-multiple，作為下一輪出場假說的必要證據。
- dynamic stop 在收盤達 `1R` 時確實會移至 breakeven；日線 backtest 以 close fill 模擬 stop 後的跳空，不能把 bar high/low 的 MFE 直接視為可成交保本。
- `intrabar_exit=stop_first` 與關閉 ATR trail 都未通過 frozen robustness gate：前者在 BTC/ETH/BNB 240d `net -22.2%`、drawdown `+9.2%`；後者只在 PnL 局部改善但回撤惡化。兩者均淘汰。

下一步：

- 以 `best_close_r` 而不是 intrabar MFE，從更長歷史與更細粒度資料重新定位單一候選；每次只比較一種出場變體。
- 固定成本、`120/180/240d`、BTC-only、BTC/ETH/BNB、擴展幣池；需至少 3 個合格比較，且多數比較同時不劣於 baseline 的 net PnL 與 max drawdown，才可進 paper。
- 不重新測試已淘汰的 adaptive ATR trail、`breakout_failure`、`intrabar_exit=stop_first` 或 ATR trail disabled；在新的資料診斷提出可驗證假說前，不新增出場規則。

### 主要研究線：短週期 alpha research（15m）

- 15m 是後續主要研究時間框架；新策略不受既有 trend 或 `intraday_momentum` 限制，但與日線 trend 的訊號、持倉與 live config 完全分離。
- 現有 `intraday_momentum` 是已被成本與 turnover 否決的負面 baseline，不能以單純調參方式直接 promotion。
- `--short-cycle-alpha-report` 是短週期研究主入口，先檢查 feature bucket、regime split、成本後 forward return、walk-forward split 與 randomized baseline。
- 短週期 promotion gate 只判斷 signal 是否值得 deeper research；即使通過也不能直接接 paper/live strategy。
- 先補齊可重播的 15m OHLCV、funding/OI、交易成本與可觀測 L2 context；資料不足時只輸出 missing-data diagnostics，不以日線 derivatives 代理短週期結果。
- 依序研究 breakout、mean reversion、volatility expansion、Funding/Basis crowding、OI expansion 與 order-flow/L2 context 的 feature-to-forward-return 關係；先證實成本後 edge，才建立策略規則。
- 每個候選固定比較 BTC-only、BTC/ETH/BNB 與擴展幣池，採用 walk-forward、randomized baseline、費用與滑價；未通過多數窗口的 net PnL、drawdown 與樣本門檻，不進 paper/live。
- 短週期 research 成果只可先進 bounded paper observation；累積足夠真實成交、滑價與 L2 adverse-selection 資料後，才可提案加入 live，預設關閉。

### P2. Trend entry 與多幣 portfolio

- entry：Funding/Basis/OI 僅作研究、paper monitor 或 filter 候選，不單獨產生 entry；等待足夠 OOS 樣本。
- portfolio：固定 BTC-only 為核心對照，只有跨窗口正貢獻且不顯著提高回撤的幣種才可加入最多兩倉 universe。

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

## 8. Trend Exit Replay Result (2026-07-13)

已完成日線訊號、1h 僅重播出場的 240 天研究工具與固定 fixture。BTC/ETH/BNB 的 1h coverage 為 100%，回測保留 `fee=4.5bps`、`slippage=2bps`、position control 與 ATR trail。

結果：

- daily close-fill baseline：12 trades，net `-4.5%`，max drawdown `17.5%`
- causal 1h replay：13 trades，net `-26.7%`，max drawdown `26.7%`
- delta：net `-22.2pp`，drawdown `+9.2pp`
- 1h replay 共 10 次 stop fill、0 次 gap fill，沒有 coverage 缺口

決策：

- 不將 1h stop replay 接入 paper/live。
- 不再重測「同一 stop 只改成更快成交」；它與已淘汰的 daily intrabar stop-first 指向相同負面結果。
- replay engine 與固定資料保留，供下一個單一候選做公平 A/B。
- 下一個合理候選必須改變 stop 結構或啟動條件，並先定義經濟理由與 frozen parameters；不得同時改入場。

## 9. Close-confirmed Stop Result (2026-07-13)

已完成 strict stop sweep 診斷與單根 1h close-confirmed frozen candidate。規則保留 gap open 即時退出，非 gap 則等 1h close 穿越 stop 並以 close 成交。

主要結果：

- Daily baseline：12 trades，net `-4.5%`，drawdown `17.5%`
- Strict 1h：13 trades，net `-26.7%`，drawdown `26.7%`
- Close-confirmed 1h：12 trades，net `-24.5%`，drawdown `24.5%`
- Confirmed 相對 baseline：net `-20.0pp`，drawdown `+7.0pp`
- Frozen gate：6 comparisons 中只有 1 組達最低交易樣本，且該組未改善；`required_240d_multi_pass=False`、`passes_majority_gate=False`

Stop sweep 證據：

- 10/10 strict stop events 具完整 72h 後續資料
- 分類：6 reclaimed、3 false sweep、1 unclear、0 valid stop
- 平均方向化結果：6h `+0.066R`、12h `-0.012R`、24h `+0.093R`、72h `+0.326R`
- Long 24h 平均 `-0.228R`，short `+0.415R`；效果集中於特定方向，缺乏共用規則所需的穩定性

決策：

- close-confirmed stop 淘汰，不進 paper observe-only 或 live。
- 不測 2-bar confirmation，不以同一資料繼續調 threshold。
- live 保持既有 Trend + funding/basis position control 與交易所硬 SL。
- 下一個出場研究必須提出不同的結構性假說；不能只是延後相同 stop 的成交。

## 10. Canonical Live-like Baseline (2026-07-13)

研究基準已校正：

- Canonical baseline 為 daily Trend decisions + causal 1h hard-SL execution。
- Daily close-fill 降級為 counterfactual，不再用於 promotion。
- Replay 報告使用 hourly mark-to-market net-liquidation equity 計算 drawdown。
- Trade reporting 以 position lifecycle 為單位，partial reduction 另列 execution records，不再灌大交易筆數與 win rate。
- 所有 entry/exit/stop events 使用市場 timestamp，不再退回系統執行時間。

240d 結果：

- BTC/ETH/BNB：10 positions，net `-26.7%`，hourly MTM DD `26.72%`
- BTC-only：2 positions，net `-3.6%`，hourly MTM DD `9.29%`
- ETH/BNB：8 positions，net `-23.8%`，hourly MTM DD `23.81%`
- Initial stop：8 positions，合計約 `-263.8`
- Breakeven stop：2 positions，合計約 `-3.4`
- Canonical gate：`eligible=1/6`、`positive=0`、`passes_live_like_baseline_gate=False`

研究決策：

- 現有 Trend 沒有通過 live-like baseline，不得再把 daily BTC winner 當作 live edge。
- 停止 stop stage、ATR、confirmation 與 failure-exit 調參。
- 下一主線應改善 entry/regime/universe，且每個 candidate 必須相對 strict hard-SL + MTM baseline 比較。
- BTC 可保留為核心研究標的，但目前樣本只有兩筆，不足以上 live 證據。
- ETH/BNB 持續負貢獻，未有新的 entry alpha 證據前不應擴大 live 配置。
