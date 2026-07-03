# backtesting.py Usage Notes

更新日期：2026-07-02

## 目的

這份文件記錄 `backtest/framework_backtesting_py.py` 在本專案中的定位，避免之後把它誤用成與原始多幣主回測完全等價的替代品。

## 結論

`backtesting.py` 在這個專案裡是有意義的，但最適合拿來做：

- 單幣快速測試
- 參數掃描
- walk-forward 驗證
- 用第二套回測框架交叉檢查策略穩健性

不適合直接拿來取代原本的主回測 `backtest/fvg_backtest_1000d.py`。

## 為什麼不能直接取代原版主回測

原版高 PnL 回測的優勢，不只來自訊號本身，還來自組合層：

- 多幣池輪動
- 同一資金池下的多倉位配置
- `max_positions` 控制
- BTC 方向過濾
- 槓桿與 `risk_per_trade` 倉位 sizing
- 每 3 天一次的進場節奏

`backtesting.py` 天生較適合單資產或簡化研究流。雖然我們已經在 framework 版補上部分接近原版的規則，但它仍然比較適合作為研究工具，而不是唯一基準。

## 建議使用方式

### 1. 原版主回測：正式比較用

使用：

```bash
python backtest/fvg_backtest_1000d.py
```

用途：

- 比較策略組合
- 檢查多幣池配置效果
- 作為是否調整 live 參數的主要依據

### 2. backtesting.py：研究沙盒用

使用：

```bash
python backtest/framework_backtesting_py.py --coin BTC
python backtest/framework_backtesting_py.py --batch --coins BTC,ETH,BNB,ADA,ATOM
python backtest/framework_backtesting_py.py --coin BTC --grid-min-scores 3,4 --grid-tp-mults 1.5,2.0 --grid-sl-mults 1.0,1.5
python backtest/framework_backtesting_py.py --coin BTC --walk-forward --train-bars 700 --test-bars 150
python backtest/framework_backtesting_py.py --portfolio --coins BTC,ETH,BNB,ADA,ATOM --cash 1000 --leverage 5 --risk-per-trade 0.08 --min-score 3 --tp-mult 1.5 --sl-mult 1.0 --max-hold-bars 30 --entry-every-bars 3 --max-positions 3
```

用途：

- 快速找單幣參數方向
- 看不同幣種對同一套規則的反應
- 檢查 out-of-sample 表現
- 驗證原版好結果是否過度依賴特定實作細節

## 下次改進時的建議流程

1. 先用 `framework_backtesting_py.py` 做小規模實驗。
2. 只要發現有潛力的參數組合，再回到 `fvg_backtest_1000d.py` 做正式多幣驗證。
3. 只有在原版主回測也改善時，才考慮寫入 `src/trading_strategy/live.py`。

## 這次已知觀察

- 單幣 `BTC` 在 framework 版上不一定重現原版高績效。
- 一旦補回多幣組合層，結果會比單幣版本更接近原始歷史回測。
- framework 版目前最有價值的用途，仍是研究與比較，不是直接替代主引擎。

## 後續可做

- 把 framework 版輸出整理成 CSV / Markdown 報告
- 增加更完整的多幣組合分析
- 在 framework 版加入更多與 live 一致的保護機制
- 做固定流程的「先 grid search，後 walk-forward，最後主回測驗證」
