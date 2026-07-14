# Short-Cycle Strategy Diagnosis

- Date: 2026-07-14
- Status: Research-only; current `intraday_momentum` rejected for paper/live promotion
- Primary timeframe: 15m
- Fixture: `data/historical_prices/binance_15m_90d_BTC_ETH_SOL_BNB.json`
- Universe: BTC, ETH, SOL, BNB
- Cost assumption: `fee_bps=4.5`, `slippage_bps=2` per side
- Canonical research entrypoint: `python backtest/backtest_runner.py --short-cycle-alpha-report ...`

## Decision Summary

目前短週期策略的主要問題不是單一的 turnover 過高，而是以下問題疊加：

1. 原始訊號在零成本下已接近零或為負期望。
2. 每回合約 13 bps 的 fee/slippage 明顯大於訊號 edge。
3. 出場後八根 bar 內重複進場具有顯著負期望。
4. score component 沒有單調預測力，volume confirmation 對 short side 尤其不利。
5. 策略具有明顯 direction、session 與 regime 依賴，但目前以靜態 24/7 規則交易。
6. 回測預設 close-fill exit 與 live trigger order 的 intrabar 行為不一致。
7. 研究報表與 promotion gate 仍有可觀測性和治理缺口。

因此：

- 凍結目前 `intraday_momentum`，只保留為 rejected wiring baseline。
- 不以調高風險、單純調 score、單一 cooldown 或相對 baseline 少虧作為 promotion 理由。
- 下一輪先修量測與 gate，再做單因素消融。
- breakout momentum 不再是預設首選；優先研究 regime/session-conditioned VWAP reversion 與更完整的 microstructure context。
- 未通過成本後 OOS gate 前，不進 paper；本研究不得改 live config。

## Scope And Method

本輪使用同一份 15m fixture，從七個角度診斷：

1. BTC baseline 的零成本與成本敏感度。
2. score、cooldown、hold、lookback、RR 與 ATR 候選。
3. first/middle/last 30-day 與 train60/test30 時間切分。
4. BTC、ETH、SOL、BNB 跨幣種比較。
5. close-fill 與 `intrabar_exit=stop_first` 執行語義比較。
6. signal score、direction、UTC session、weekday、exit reason、re-entry gap 的逐筆條件分析。
7. breakout continuation、volatility expansion、VWAP reversion 的 forward-return、random baseline 與 rolling split 報告。

注意：CLI 的 `max_days=8640` 目前實際代表 8,640 根 bars，不是 8,640 天。這是命名／資料契約問題，後續應修正或明確文件化。

## Baseline Findings

### BTC 15m, 90 Days

- Trades: `573`
- Win rate: `38.6%`
- Average hold: `3.3 bars`
- Exit counts: `TP=219`, `SL=344`, `TIME=10`
- Zero-cost portfolio result: `-40.1%`
- Current-cost net result: `-92.9%`
- Average gross return per trade: approximately `-0.0276%` (`-2.76 bps`)
- Round-trip fee/slippage assumption: `0.13%` (`13 bps`)
- Average net return per trade: approximately `-0.1576%`

名目 TP/SL 為 `1.2 ATR / 0.8 ATR`，但實際平均 gross winner/loss 約為 `+0.5273% / -0.3759%`。對應成本前損益兩平勝率約 `41.6%`，高於實際 `38.6%`；計入成本後所需勝率約 `56%`。所以成本不是唯一問題，但會把原本已偏負的期望快速放大。

成本開啟後的 portfolio-level `gross_pnl_pct` 會受動態 equity sizing 路徑影響，不適合直接與零成本 portfolio total 比較；判斷訊號品質時應優先看逐筆 gross return 與固定 notional 統計。

### Cross-Coin Zero-Cost Check

| Coin | Zero-cost portfolio result | Average gross return per trade |
|---|---:|---:|
| BTC | -40.1% | -0.0276% |
| ETH | -0.7% | +0.0069% |
| SOL | -31.5% | -0.0139% |
| BNB | -22.6% | -0.0108% |

ETH 接近持平，但沒有足以覆蓋成本的 edge；問題不是 BTC-only 的偶發異常。

## Candidate Checks

以下數字使用目前成本模型；gross total 仍會受 equity path 影響，只用於同設定下的方向比較。

| Candidate | Trades | Gross | Net | Decision |
|---|---:|---:|---:|---|
| baseline | 573 | -16.3% | -92.9% | Rejected |
| score 5 | 333 | -8.3% | -77.0% | Less turnover, still rejected |
| cooldown 8 | 324 | -8.9% | -78.6% | Less turnover, still rejected |
| cooldown 16 | 248 | +21.4% | -51.8% | Gross improves, net still rejected |
| score 5 + cooldown 8 | 203 | +5.1% | -50.4% | Still rejected |

延長 hold、改 lookback、提高 RR、改 ATR stop 都沒有形成成本後正績效。簡單 throttle 能降低虧損，但不是已證明 alpha。

### Time Stability

- First 30 days: baseline gross/net `-12.2% / -60.0%`; cooldown 8 `-0.3% / -34.4%`; score 5 `-1.9% / -36.5%`。
- Middle 30 days: baseline `-9.8% / -60.8%`; cooldown 8 `-2.8% / -36.9%`; score 5 `-9.2% / -43.3%`。
- Last 30 days: baseline `-0.2% / -52.7%`; cooldown 8 `-18.2% / -48.2%`; score 5 `+3.8% / -32.0%`。

cooldown 的 gross 改善沒有跨窗口穩定；score 5 在最後 30 天較好，但仍無法覆蓋成本。這些結果只能產生研究假說，不能 promotion。

## Conditional Trade Diagnosis

以下為 BTC/ETH/SOL/BNB 合併、零成本逐筆 gross return：

### Score Calibration

- Score `-4`: `n=527`, mean `+0.0123%`, hit rate `39.3%`。
- Score `-5`: `n=663`, mean `-0.0526%`, hit rate `36.3%`。
- Score `+4`: `n=537`, mean `-0.0046%`, hit rate `40.4%`。
- Score `+5`: `n=597`, mean `+0.0066%`, hit rate `42.2%`。

較高絕對 score 並未單調改善結果。特別是 volume confirmation 讓 short 從 `-4` 進到 `-5` 時，結果反而惡化，因此不能再假設 volume 應無條件增加 breakout confidence。

### Direction

- Long: `n=1,134`, mean `+0.0013%`, hit rate `41.4%`。
- Short: `n=1,190`, mean `-0.0239%`, hit rate `37.6%`。

下一輪必須測 long-only，以及 long/short 分開的 score component 與 threshold；不能繼續共用完全對稱規則。

### Re-Entry Gap

- `<=8 bars`: `n=951`, mean `-0.0642%`, hit rate `36.1%`。
- `9-24 bars`: `n=890`, mean `+0.0385%`, hit rate `43.3%`。
- `>24 bars`: `n=479`, mean `-0.0024%`。

這是目前最強的結構性線索：立即再入場／訊號群聚具有負期望。下一輪應測 refractory period `4/8/12/16/24 bars`，但仍須以 frozen OOS 判斷，不能從同一窗口挑最佳值。

### UTC Session

- `00-04`: mean `+0.0105%`
- `04-08`: mean `-0.0123%`
- `08-12`: mean `-0.0572%`
- `12-16`: mean `+0.0504%`
- `16-20`: mean `-0.0561%`
- `20-24`: mean `-0.0683%`

session 差異很大，但目前只有單一 90-day fixture。`12-16 UTC` 只能作為待驗證假說，不得直接寫成 live filter。

## Backtest/Live Execution Gap

Backtest 預設未啟用 intrabar exit，觸及 TP/SL 時可能使用當根 close；live 則依賴交易所 trigger order。改用 `intrabar_exit=stop_first` 後：

- BTC trades 從 `573` 增加為 `656`。
- BTC average hold 從 `3.3` 降至 `1.3 bars`。
- BTC net 從 `-92.9%` 惡化為 `-95.2%`。
- ETH、SOL、BNB 也整體惡化。

這表示 live-like 執行不會拯救策略，反而暴露更多 intrabar churn。後續 promotion baseline 必須固定執行模型，不能用 close-fill 結果代替 live-like 結果。

## Alpha Discovery Result

固定使用 costs、rolling 30-day、train60/test30、50 次 random baseline 後：

- `intraday_breakout_continuation`: `3,120` events；1/3/6/12/24 bars 的成本後 forward return 全為負，且多數 random delta 為負。現有 breakout continuation 方向低於 random baseline。
- `intraday_volatility_expansion`: `7,686` events；各 horizon 淨報酬為負，高 volume expansion 在較長 horizon 更差。
- `intraday_vwap_reversion`: `17,570` events；全樣本各 horizon 仍為負，但最近 rolling/train-test window 的 12-bar 與 24-bar 結果轉正：
  - 12 bars: net `+0.0142%`, random delta `+0.0813%`, hit rate `51.45%`。
  - 24 bars: net `+0.0899%`, random delta `+0.1564%`, hit rate `51.07%`。

VWAP reversion 的早期窗口仍為負，因此 promotion gate 為 false。它只是下一輪優先研究方向，不是可交易策略。

## Research Infrastructure Defects

### Missing Risk-Normalized Excursion

`intraday_momentum.initialize_position()` 只保存 `entry_atr`，沒有保存 `initial_risk`，導致 trade history 的 `mfe_r`、`mae_r` 為空。下一輪必須補齊：

- `initial_risk`
- `mfe_r`, `mae_r`, `best_close_r`
- entry score components，而不是只保存合計 score
- re-entry gap、UTC session、direction
- ATR/range、EMA gap、momentum、volume ratio
- 若資料可得：spread、depth、order-flow imbalance、maker/taker 與實際 fill context

### Relative-Only Promotion Gate

目前 turnover report 只要求 candidate net PnL、drawdown、turnover 相對 baseline 不劣。當 baseline 極差時，深度負績效也可能通過相對 gate。

短週期 candidate 必須同時通過絕對條件，不能只比 baseline 少虧。

### No-Op Candidates

- BTC-only 報告中的 BTC filter 不提供實際跨市場差異。
- `intraday_max_range_pct=2.0` 在目前 fixture 沒有過濾交易。

報表必須記錄每個 candidate 的 filtered-event count 和 parameters fingerprint；沒有改變事件集合的 candidate 應標示為 `no_op`，不能列為獨立證據。

## Next Execution Plan

### Phase 0: Measurement Integrity

1. 補齊 `initial_risk`、MFE/MAE R、entry component、re-entry/session context。
2. 將 `max_days` 修正為 bars 語義，或新增明確的 `max_bars`。
3. 固定 close-fill 與 live-like intrabar 兩種 execution profile，promotion 只採 live-like profile。
4. Promotion gate 增加 absolute profitability、event count、concentration 和 no-op 檢查。

### Phase 1: Frozen Baselines

固定比較：

- BTC-only、BTC/ETH/BNB、BTC/ETH/SOL/BNB。
- first/middle/last 30-day、rolling 30-day、train60/test30。
- zero-cost 與 `4.5 + 2 bps` per-side cost。
- close-fill 與 intrabar stop-first。
- 相同 universe、fixture、random baseline 與 minimum event count。

### Phase 2: One-Factor Ablation

每次只改一項：

1. Refractory period: `0/4/8/12/16/24 bars`。
2. Long-only、short-only、多空不對稱 threshold。
3. Volume confirmation on/off。
4. Breakout、EMA、momentum、volume component 個別移除。
5. Session buckets；先凍結規則，再跑 OOS。

### Phase 3: Alternative Alpha

1. VWAP reversion 12/24 bars，加入 regime/session conditioning。
2. 若有可重播資料，加入 L2 spread/depth/order-flow imbalance。
3. 對 FOMC、jump、liquidation-cascade 等 event-time regime 做 exclude/observe 分析。
4. Breakout momentum 保留 rejected control，不再作為主候選。

### Phase 4: Promotion Boundary

建議 paper research gate：

- Aggregate OOS net PnL after costs `> 0`。
- 至少 `200` 個 OOS events，且每個被引用的 split 達最低樣本。
- Random-baseline delta `> 0`。
- Turnover 相對 baseline 至少下降 `30%`。
- Max drawdown 不劣於 baseline，並設定絕對上限。
- 單一 coin 或 UTC session 不得貢獻超過 `50%` 的正 PnL。
- 至少三個固定比較可評估，且多數同時通過 net PnL 與 drawdown gate。

通過只代表可進 bounded paper observation；live 仍需要真實 fill、slippage、L2 adverse-selection 資料與獨立人工審查。

## External Research Context

外部研究只用來建立可檢驗假說，不代替本 repo 的 OOS 證據：

- Crypto intraday momentum 與 reversal 會隨 jumps、FOMC、liquidity 等狀態切換：[Intraday Return Predictability in the Cryptocurrency Markets](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4080253)。
- 納入現實交易與風險假設後，許多 crypto momentum portfolio 的結果會顯著弱化：[Momentum in the Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565)。
- 短期價格變動與 order-flow imbalance、市場深度的關係通常比單純成交量更直接：[The Price Impact of Order Book Events](https://arxiv.org/abs/1011.6402)。
- Bitcoin jumps 與 order-flow imbalance、aggressive trading、spread 變化相關：[High-Frequency Jump Analysis of Bitcoin Market](https://arxiv.org/abs/1704.08175)。
- FOMC statement 後 crypto volatility 與 trading activity 會明顯改變，支持 event-time regime 的研究必要性：[Scheduled FOMC Statements and Cryptocurrency Trading Activity](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6299551)。

## Skill Health Note

- `.agents/skills/repo-superpowers-workflow` 的 spec → plan → execute → verify 流程仍適用。
- `.agents/skills/crypto-strategy-backtest` 含舊外部路徑、編碼問題、過時費率／績效敘述；本輪僅借用研究流程，沒有把其中的績效數字當證據。
- 後續應另開文件維護任務，更新 skill 的 canonical commands、成本預設、資料 fixture 與 promotion gate，避免舊內容污染決策。

## Final Status

- Current `intraday_momentum`: `rejected_research_baseline`
- Breakout continuation: `deprioritized`
- Volatility expansion: `deprioritized`
- VWAP reversion: `research_candidate_only`
- Live config impact: none
- Paper promotion: not approved

