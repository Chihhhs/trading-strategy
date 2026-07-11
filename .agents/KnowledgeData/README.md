# 交易知識庫 v3.2
> 最後更新：2026-06-27
> 設計原則：README 只存索引，細節放子檔案，按需讀取節省 token

---

## 目錄結構

```
trading-knowledge/
├── README.md                    # 總索引（此檔案）
│
├── strategies/                  # 交易策略
│   ├── v2.0-improved-indicators.md  # v2.0 改良版策略指標（四層過濾）
│   ├── long-term-vs-short-term.md   # 長期趨勢 vs 短期多空
│   ├── market-structure-shift.md    # Market Structure Shift（MSS）
│   ├── consolidation-range-trading.md # 盤整期短線策略
│   ├── tpsl-guide.md               # TP/SL 設定完整指南 🆕
│   ├── trend-following/
│   │   └── macro-trend-strategy.md  # 大趨勢策略
│   ├── quantitative-factor-model.md # 量化因子模型
│   └── quantitative-factor-starter-guide.md # 量化因子入門
│
├── trade-history/               # 交易歷史
│   └── SUI/
│       ├── 2026-06-08_to_06-16_full_history.md  # SUI 完整交易歷史
│       └── sui-short-postmortem.md              # SUI 做空失利分析
│
├── indicators/                  # 技術指標
│   └── _technical-indicators-full.md
│
├── risk-management/             # 風險管理
│   ├── risk-management.md
│   └── liquidation-and-risk-sop.md  # 清算機制 + 風險管理 SOP 🆕
│
├── market-microstructure/       # 市場微觀結構
│   └── market-microstructure.md
│
├── psychology/                  # 交易心理學
│   └── trading-psychology.md
│
├── news-events/                 # 新聞事件與價格
│   └── news-and-price.md
│
├── macro-economics/             # 宏觀經濟
│   └── macro-and-crypto.md
│
├── sentiment-analysis/          # 情緒分析
│   └── sentiment-analysis.md
│
├── risk-events/                 # 風險事件管理
│   └── risk-event-management.md
│
├── value-investing/             # 價值投資（2026-06-27 新增）
│   ├── value-investing-framework.md  # 價值投資核心框架
│   ├── sector-analysis.md           # 加密產業分析
│   ├── memory-ai-investing.md       # AI 記憶體/美股投資
│   └── opportunity-scan.md          # 投資機會掃描
│
└── scripts/                     # 可重用腳本
    ├── hyperliquid-api-endpoints.md  # Hyperliquid API 筆記
    └── market_scan.txt               # 最新市場掃描
```

---

## 快速索引（按使用情境）

### 我要找某個指標的用法
→ `indicators/_technical-indicators-full.md` 或用 `search_files` 搜尋

### 我要找某個策略
→ `strategies/v2.0-improved-indicators.md`（最新版）

### 我要看長期趨勢 vs 短期多空
→ `strategies/long-term-vs-short-term.md`

### 我要看 Market Structure Shift
→ `strategies/market-structure-shift.md`

### 我要看盤整期怎麼做短線
→ `strategies/consolidation-range-trading.md`

### 我要設定 TP/SL
→ `strategies/tpsl-guide.md`（6 種 SL 方法 + 5 種 TP 方法 + 5 種策略組合）

### 我要分析市場情緒
→ `sentiment-analysis/sentiment-analysis.md`

### 我要看宏觀經濟影響
→ `macro-economics/macro-and-crypto.md`

### 我要做價值投資分析
→ `value-investing/value-investing-framework.md`

### 我要看產業分析
→ `value-investing/sector-analysis.md`

### 我要找投資機會
→ `value-investing/opportunity-scan.md`

### 我要看 AI/記憶體投資
→ `value-investing/memory-ai-investing.md`

### 我要更新帳戶倉位
→ `ACCOUNT_SNAPSHOT.md`（不要寫入 memory）

### 我要看交易歷史
→ `trade-history/SUI/`

---

## 策略演進

| 版本 | 日期 | 主要改良 |
|------|------|---------|
| v1.0 | 2026-06 | EMA + RSI + MACD 傳統指標 |
| v2.0 | 2026-06-16 | 四層過濾：BTC相關 + 市場結構 + 價格位置 + 確認信號 |
| v2.1 | 2026-06-16 | 加入費波那契回撤 + Market Structure Shift |
| v3.0 | 2026-06 | 統一框架完成，5層過濾 + 4階段出場 |
| v3.2 | 2026-06-27 | 新增價值投資知識庫 |

---

## 專業級評分系統 v4

> 位置：`~/.hermes/scripts/trading_lib/scoring_v4.py`
> 指標：`~/.hermes/scripts/trading_lib/indicators_v3.py`

24 項評分因素：
- 核心層 12 項：趨勢、RSI、MACD、成交量、支撐阻力、K線形態、背離、Liquidity Sweep、Order Flow Delta、Order Flow Imbalance、Anchored VWAP、Volume Profile
- 增強層 6 項：恐懼貪婪、資金費率、交易所淨流、波動率狀態、美元指數、BTC 主導度
- v2.0 新增 6 項：BTC 相關性、市場結構、價格位置、成交量確認、RSI 確認、資金費率確認
- v2.1 新增：費波那契位置評分

信號：STRONG_BUY / BUY / LEAN_LONG / NEUTRAL / LEAN_SHORT / SELL / STRONG_SELL

---

## 免責聲明

所有資料僅供學習參考，不構成投資建議。交易有風險，請謹慎評估。
