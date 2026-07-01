# FVG Strategy — Hyperliquid 趨勢交易策略

> 基於 FVG（Fair Value Gap）+ 趨勢跟隨的雙策略系統，支援回測與實盤執行。

## 分支結構

```
main          ← 目前主要開發分支（回測 + paper + live 實盤修改）
└── live      ← 保留分支（舊的實盤整合線）
```

| 分支 | 用途 |
|------|------|
| `main` | 目前主線，包含策略邏輯、回測、資料路徑調整、Hyperliquid 實盤修改 |
| `live` | 保留舊實盤分支歷史；只有在需要回看舊整合方式、比對差異，或做隔離中的實盤實驗時才使用 |

目前建議預設都在 `main` 上開發與執行。`live` 不是完全沒用，但已不再是日常主線。

## 目錄結構

```
fvg-strategy/
├── README.md              # 本文件
├── .gitignore
├── strategy/              # 策略邏輯
│   ├── fvg_live_strategy.py    # 最終策略（含全保護機制）
│   ├── fvg_paper_trader.py     # Paper trading 版本
│   ├── dual_strategy.py        # 趨勢 + FVG 雙策略
│   ├── coin_scanner.py         # 多幣種掃描 + 評分
│   ├── fvg_live_ready.py       # 實盤就緒版本
│   ├── binance_api.py          # Binance 價格數據
│   └── data_collector.py       # 數據收集工具
├── backtest/              # 回測框架
│   ├── fvg_backtest_1000d.py   # 1000天回測（主）
│   ├── fvg_backtest_60d.py     # 60天快速回測
│   ├── fvg_enhanced_backtest.py
│   ├── fvg_risk_comparison.py  # 風控對比
│   ├── fvg_multi_coin.py       # 多幣種回測
│   ├── fvg_protection.py       # 保護機制對比
│   ├── final_backtest_v4.py
│   └── backtest_v6.py
├── results/               # 回測結果
│   └── backtest_reports/
├── data/                  # 歷史數據
│   └── 1000d_50coins.json      # 50幣 x 1000天
└── docs/                  # 分析文件
    └── backtest_results.md
```

## 快速開始

### 環境需求

```bash
python3.11+
# 無外部依賴（stdlib only: urllib, json, statistics）
```

### 跑回測

```bash
# 1000天完整回測
python3 backtest/fvg_backtest_1000d.py

# 60天快速回測
python3 backtest/fvg_backtest_60d.py

# 風控對比
python3 backtest/fvg_risk_comparison.py
```

### 實盤（main 分支）

```bash
python3 strategy/fvg_live_strategy.py --live
```

## 策略參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| 槓桿 | 5x | 可調 3x-10x |
| 風險 | 8% | 每筆最大虧損 |
| TP | 2R | 止盈 = 2x 風險 |
| SL | 1.5R | 止損 = 1.5x 風險 |
| 趨勢門檻 | ADX > 25 | 趨勢強度過濾 |
| 評分 | ≥4 | 多因子綜合評分 |

## 回測結果

見 [docs/backtest_results.md](docs/backtest_results.md)

### 摘要

| 版本 | PnL | PF | Max DD | Sharpe | 交易數 |
|------|-----|-----|--------|--------|--------|
| 基礎 5x 8% | +259% | 1.16 | 78% | — | 185 |
| 全保護 5x 8% | +797% | 1.45 | 73% | 2.21 | 185 |
| 趨勢優化 5x 10% | +1427% | — | — | — | 184 |

## 風控機制

- ✅ 趨勢反轉檢測（EMA20/EMA50 交叉自動平倉）
- ✅ Break-even Stop（獲利達 1R 移 SL）
- ✅ Dynamic Position Size（波動自適應）
- ✅ Daily Risk Limit（單日虧 5% 停機）
- ✅ BTC 方向過濾（不逆勢）
- ✅ 熔斷（連虧 5 次 → 停 24h）
- ✅ 持倉超時（30 天平倉）

## License

MIT
