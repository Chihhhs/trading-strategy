# Trading Strategy

以 Hyperliquid live / paper 交易與離線 backtest 為核心的交易策略專案。現在的主線重點是以 crypto trend 為核心、可持續執行、可排查、可接管實際持倉的策略執行流程。

目前 repo 提供三種主要使用模式：

- `backtest`：使用歷史資料做離線回測。
- `paper`：用 Binance 市場資料模擬多策略 paper trading。
- `live`：連接 Hyperliquid 帳戶執行實盤，並在每輪執行時同步交易所持倉與保護單狀態。

## Module 使用原則

- `apps/` 是入口與包裝層，仍然會 import `src/trading_strategy/` 內的 package，但不應承載可重用業務邏輯。
- 新的可重用邏輯請優先放在：
  - `trading_strategy.shared`
  - `trading_strategy.strategies`
  - `trading_strategy.positions`
- 共用 helper 位於 `trading_strategy.shared`、策略邏輯位於 `trading_strategy.strategies`、倉位 helper 位於 `trading_strategy.positions`；`core` 僅保留 legacy strategy 實作。

## 主要功能

- Hyperliquid live 實盤下單與持倉同步
- live 重啟後自動接管交易所既有持倉
- 啟動時檢查缺失的 TP/SL，必要時自動補掛
- 若仍有未受保護持倉，阻止新開倉
- JSONL 交易事件 log 與 API debug log，便於排查為何沒下單或下單被拒
- Binance 資料驅動的 paper trading 與離線 backtest

## 安裝

### 需求

- Python 3.11+
- [requirements.txt](/D:/code/trading-strategy/requirements.txt)

主要依賴：

- `backtesting`
- `hyperliquid-python-sdk`
- `python-dotenv`

### 安裝依賴

```bash
pip install -r requirements.txt
```

## 環境變數

可透過 `.env` 載入。範例可參考 [.env-template](/D:/code/trading-strategy/.env-template)。

必要或常用變數：

- `HL_ACCOUNT_ADDRESS`：Hyperliquid 帳戶地址
- `HL_PRIVATE_KEY`：Hyperliquid 私鑰，live mode 必填
- `HL_API_URL`：Hyperliquid API URL，預設 `https://api.hyperliquid.xyz`
- `MARKET_DATA_SOURCE`：`auto` / `hyperliquid` / `binance`
- `DEBUG_API`：設為 `1`、`true`、`yes`、`on` 時寫出 API debug log

## Canonical Entrypoints

### Live

```bash
python apps/runners/live_runner.py --live
python apps/runners/live_runner.py --live --loop
```

常用附加參數：

- `--report`：輸出目前 state 與部位資訊
- `--debug-account`：檢查 Hyperliquid 帳戶資料
- `--verify-orders`：驗證 state 中保存的 order 狀態
- `--reset`：重置 live state
- `--interval-minutes=5`：搭配 `--loop` 使用，調整輪詢間隔

### Paper

```bash
python apps/runners/paper_runner.py
python apps/runners/paper_runner.py --reset
```

### Backtest

```bash
python backtest/backtest_runner.py --coins BTC,ETH,SOL --strategy trend --max-days 240
python backtest/backtest_runner.py --coins BTC --strategy intraday_momentum --max-days 240
python backtest/backtest_runner.py --coins BTC,ETH --optimize --strategy-grid trend,intraday_momentum
```

參數摘要：

- `--coins`：逗號分隔標的，預設 `BTC,ETH,SOL,BNB`
- `--strategy`：`trend` / `intraday_momentum`
- `--max-days`：使用最近幾天歷史資料，預設 `240`
- `--initial-capital`：起始資金，預設 `1000`
- `--risk-pct`：每筆交易風險比例，預設 `0.05`
- `--max-positions`：回測同時最大持倉數，預設不限制；多幣 trend 建議設 `2`
- `--fee-bps`：每邊交易費用，單位 bps，預設 `0`
- `--slippage-bps`：每邊滑價估計，單位 bps，預設 `0`
- `--derivatives-data-path`：Funding / OI / Basis JSON；格式為 `coin -> bars`，欄位可包含 `funding_rate`、`open_interest`、`basis_pct`、`mark_price`、`index_price`
- `--enable-derivatives-filter`：讓 Funding / OI / Basis 只作為既有訊號的品質過濾器，不會自行產生交易
- `--disable-btc-filter`：停用 BTC 趨勢過濾
- `--show-trades`：輸出 trade 明細

範例：用接近 Hyperliquid tier-0 taker 的 4.5 bps 費用估算 trend：

```bash
python backtest/backtest_runner.py --coins BTC --strategy trend --max-days 240 --risk-pct 0.03 --leverage 2 --enable-atr-trailing --enable-failure-exit --fee-bps 4.5
```

多幣 trend 研究時，避免直接把每個幣都用同一個高 `risk-pct` 疊上去；先用較低單幣風險與持倉上限：

```bash
python backtest/backtest_runner.py --coins BTC,BNB,ETH --strategy trend --max-days 1000 --risk-pct 0.015 --max-positions 2 --enable-atr-trailing --enable-failure-exit --fee-bps 4.5
```

衍生資料 research report：

```bash
python backtest/backtest_runner.py --coins BTC,ETH --max-days 240 --research-report --derivatives-data-path data/derivatives/example.json
```

### Strategy Selection

- `trend`：主線日線 / 較低頻趨勢策略。使用 `trend_sl_only` 出場語義，live 預設只要求 SL，並透過策略 hook 管理動態 stop / failure exit。
- `intraday_momentum`：第一版短週期動能 / 波動突破策略。策略本身是 candle-based，可用在 5m / 15m / 1h K 線；目前預設 historical data 仍是日線，所以要做真正 intraday 回測時需要提供 intraday candle JSON。
- live 若要切短週期，請在 [apps/live_config.py](apps/live_config.py) 覆寫：

```python
STRATEGY_OVERRIDES = {
    "name": "intraday_momentum",
    "timeframe": "15m",
    "max_positions": 2,
    "risk_per_trade": 0.03,
}
```

## 專案結構

```text
apps/
  runners/
    live_runner.py         # live 執行入口
    paper_runner.py        # paper 執行入口
backtest/
  backtest_runner.py       # 離線回測入口
src/
  trading_strategy/
    shared/                # 共用 risk / state / trade history helper
    strategies/            # strategy registry / interface / trend strategy
    positions/             # position snapshot / lifecycle / trend stop helper
    backtest/              # 回測 package（data / engine / portfolio / reporting / cli）
    paper.py               # paper trading 主邏輯
    hyperliquid.py         # Hyperliquid 市場價格與 tick helper
    core/                  # retained legacy_unified strategy helper only
    live/
      config.py            # live 模式設定、狀態路徑、策略參數
      cli.py               # live 主流程與 CLI
      account.py           # 帳戶、資金、交易所狀態同步
      engine/              # 進出場、接管、保護、run summary
      orders.py            # entry / TP / SL / close 下單邏輯
      market.py            # 幣池與市場資料來源
      io.py                # state / log 讀寫
data/
  paper_strategies_live/   # live state 與 log
  paper_strategies/        # paper state
  historical_prices/       # backtest 歷史資料
tests/
  test_live.py             # live 流程相關測試
```

## Apps 與 Import 入口

- `apps/runners/live_runner.py` 透過 `apps/_live_bootstrap.py` 啟動 `trading_strategy.live.main`
- `apps/runners/paper_runner.py` 直接 import `trading_strategy.paper.main`
- `apps/live_config.py` 用來覆寫 `trading_strategy.live.config`

這表示 `apps` import 還在，而且是刻意保留的，但它們只應該當 entrypoint / wrapper，不是新 module 的落點。

## Live 模式的重要行為

目前 live 流程在每次 `run_once()` 會依序做這些事：

1. 載入本地 state。
2. 同步 Hyperliquid 帳戶資金、持倉與 open orders。
3. 檢查 `perp` 可交易資金。
4. 若交易所上有本地未知持倉，接管為本地部位。
5. 檢查每個持倉是否缺少 reduce-only TP/SL，必要時自動補掛。
6. 若仍存在未受保護持倉，跳過新開倉。
7. 否則才進入掃描、訊號判定與新下單。

### Live 前置條件

- 必須提供 `HL_PRIVATE_KEY`
- 必須提供 `HL_ACCOUNT_ADDRESS`
- Hyperliquid `perp` 帳戶必須有可交易資金
- 只有 `spot` 餘額、不含 `perp` 可交易資金時，live 會拒絕開倉

### 目前的保護機制

- 啟動時會以交易所持倉為權威來源同步本地 state
- 若本地沒有 TP/SL，會檢查交易所 open orders
- 若 TP/SL 缺失，會嘗試自動補掛 reduce-only trigger orders
- 若補掛失敗，`run_summary.unprotected_positions_count` 會大於 `0`
- 只要還有未受保護持倉，系統會阻止新開倉

## 重要資料檔案

### Live state 與 log

位於 [data/paper_strategies_live](/D:/code/trading-strategy/data/paper_strategies_live)：

- [live_state.json](/D:/code/trading-strategy/data/paper_strategies_live/live_state.json)
  - 本地保存的 live 持倉、策略快照與保護單資訊
- [live_trading_records.jsonl](/D:/code/trading-strategy/data/paper_strategies_live/live_trading_records.jsonl)
  - 每輪執行的事件 log，排查第一入口
- [live_api_debug.log](/D:/code/trading-strategy/data/paper_strategies_live/live_api_debug.log)
  - 更底層的 API debug 記錄
- [coin_list.json](/D:/code/trading-strategy/data/paper_strategies_live/coin_list.json)
  - live 可掃描幣池快取

### Paper state

位於 [data/paper_strategies](/D:/code/trading-strategy/data/paper_strategies)。

### Backtest 資料

預設歷史資料檔：

- [data/historical_prices/1000d_50coins.json](/D:/code/trading-strategy/data/historical_prices/1000d_50coins.json)

## 排查建議

### 1. 沒有下單

先看 [live_trading_records.jsonl](/D:/code/trading-strategy/data/paper_strategies_live/live_trading_records.jsonl)：

- `entry_skipped`
- `entry_order_rejected`
- `run_summary`

重點欄位：

- `reason`
- `message`
- `entry_rejected_reasons`
- `top_blockers`
- `missing_price_count`
- `unprotected_positions_count`

### 2. 有持倉但沒有 TP/SL

先看：

- `tpsl_missing_detected`
- `tpsl_repair_attempted`
- `tpsl_repair_failed`
- `tpsl_repaired`

再對照 [live_state.json](/D:/code/trading-strategy/data/paper_strategies_live/live_state.json) 中：

- `tp_order`
- `sl_order`
- `protection_status`
- `position_source`

### 3. 帳戶有錢但 live 不開倉

檢查 `account_snapshot` 與 state 中的：

- `_perp_account_value`
- `_spot_account_value`
- `_balance_warning`

若 `perp` 為 `0`，即使 `spot` 有餘額也不會開倉。

## 目前已知高風險區域

- Hyperliquid tick size 與 trigger order 價格正規化
- reduce-only TP/SL trigger orders 是否真的存在於交易所
- `live_state.json.params` 與 runtime `config.STRATEGY` 可能漂移
- 幣池、價格來源與交易所可交易 universe 的一致性

## 相關文檔

- [docs/backtest_results.md](/D:/code/trading-strategy/docs/backtest_results.md)
- [docs/backtesting_py_usage_notes.md](/D:/code/trading-strategy/docs/backtesting_py_usage_notes.md)
- [docs/restruct.md](/D:/code/trading-strategy/docs/restruct.md)
- [.agents/project_detail.md](/D:/code/trading-strategy/.agents/project_detail.md)
- [.agents/current_progress.md](/D:/code/trading-strategy/.agents/current_progress.md)

## Daily Live Reconciliation

- `run_once()` now supports exchange-first daily recovery.
- On each startup the live flow rebuilds local context from exchange positions and open orders.
- `live_state.json` now persists `managed_orders` so adopted open orders can be tracked across runs.
- Orphan exchange open orders are auto-canceled and logged.
- `trend_sl_only` replaces SL with a strict sequence: cancel old SL first, then place the new SL.

## License

MIT

## Research Manual

- [docs/research_manual/00_decision_framework.md](docs/research_manual/00_decision_framework.md)
- [docs/research_manual/01_quant_research_map.md](docs/research_manual/01_quant_research_map.md)
- [docs/research_manual/02_current_strategy_review.md](docs/research_manual/02_current_strategy_review.md)
- [docs/research_manual/03_research_backlog.md](docs/research_manual/03_research_backlog.md)
- [docs/research_manual/04_intraday_strategy_candidates.md](docs/research_manual/04_intraday_strategy_candidates.md)
- [docs/exit_rules.md](docs/exit_rules.md)
