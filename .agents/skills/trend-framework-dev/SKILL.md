---
name: trend-framework-dev
description: 趨勢交易框架開發流程 — 從回測到實盤的完整 SOP。包含市場狀態判斷、入場/出場邏輯、幣種篩選標準。
triggers:
  - "趨勢框架"
  - "trend framework"
  - "unified framework"
  - "開發交易策略"
  - "回測框架"
---

# 趨勢交易框架開發

## 框架概述

統一趨勢框架（`unified_framework.py`），同時處理大波段（1-3月）和短線（1-14天），自動判斷用哪種。

核心邏輯：
1. 多時間框架分析（20天短線 + 60天波段）
2. 根據市場狀態自動選擇波段/短線
3. 統一出場邏輯（試探倉 → 保本 → 利潤鎖 → 追蹤止損）

## 關鍵參數

### 市場狀態判斷
- 波段（60天）：EMA排列 × 3 + 動量 + 成交量確認
- 短線（20天）：動量 + 波動率 + 成交量 + 價格突破
- 閾值：long_score ≥ 5 才確認趨勢（從 4 提高到 5）
- 價格位置過濾：>75% 不做多，<25% 不做空
- 60天涨幅限制：>120% 不做多

### 入場條件
- EMA20 > EMA50（多頭）+ RSI 45-70 + ATR < 8%
- 試探倉 SL：1.5x-3x ATR（自適應）
- TP：3x risk

### 出場邏輯（4階段）
1. 固定 SL → 虧損出場
2. 盈利 > 5% → SL 移到 break-even
3. 盈利 > 20% → SL 移到 entry + 5%
4. 追蹤止損 2.5x ATR + 趨勢結束確認

## 幣種篩選標準

### 適合趨勢策略的幣種
| 指標 | 好 | 差 |
|------|-----|-----|
| 趨勢天數/60天 | >50% | <30% |
| 60天涨幅 | >15% | <5% |
| 最大回撤 | <70% | >85% |
| 與BTC相關性 | 正相關 >0.5 | 負相關或 0 |

### 目前測試結果（1000天回測）
| 幣種 | PnL | WR | 狀態 |
|------|-----|-----|------|
| ZEC | +3177% | 25% | 🏆 |
| DOGE | +676% | 30% | 🔥 |
| SHIB | +530% | 44% | 🔥 |
| BCH | +306% | 56% | 🔥 |
| BTC | +238% | 47% | ✅ |
| OP | +191% | 33% | ✅ |
| SOL | +170% | 33% | ✅ |
| NEAR | +135% | 20% | ✅ |
| WLD | +348% | 67% | ✅ |
| LDO | +23% | 38% | ⚠️ |
| ETH | -19% | 39% | ⚠️ |
| AVAX | -112% | 27% | ❌ |
| AAVE | -232% | 23% | ❌ 震盪型 |
| LINK | -283% | 14% | ❌ 震盪型 |
| UNI | -21% | 24% | ❌ 震盪型 |
| FIL | -116% | 35% | ❌ 震盪型 |
| TIA | -156% | 25% | ❌ 震盪型 |
| INJ | -46% | 40% | ❌ 震盪型 |

### 不適合趨勢策略的幣種
- AAVE：0/60 天趨勢，完全震盪，最大回撤 86%
- LINK：趨勢反覆，SL 頻繁被掃
- UNI/FIL/TIA/INJ：震盪型，無持續趨勢

### 特殊案例
- HYPER：與 BTC 負相關 -0.96，可作為對沖（小倉位）

## 開發流程 SOP

### 1. 新增幣種測試
```bash
cd ~/.hermes/scripts/trading_lib
python3 -c "
from backtester_v3 import get_binance_klines
from unified_framework import UnifiedFramework
data = get_binance_klines('SYMBOL', limit=1000)
uf = UnifiedFramework(leverage=3)
trades, stats = uf.backtest(data, 'NAME')
# 分析結果...
"
```

### 2. 調整參數
- 改 `unified_framework.py` 中的 PARAMS / REGIME
- 改 `LONG_TERM` 或 `SHORT_TERM` 參數
- 改 `analyze_market_regime()` 中的打分邏輯

### 3. 驗證標準
- 回測 1000 天
- 賺錢條件：PnL > 0 且 WR > 30%
- 虧損容忍：單幣最大 -50%（超過就排除）

## 相關文件
- `unified_framework.py` — 核心框架
- `coin_scanner.py` — 每日掃描（用統一框架）
- `pure_trend.py` — 純趨勢版本（實驗中）
- `backtester_v3.py` — 數據取得
- `indicators_v3.py` — 指標計算

## Cron Jobs
- `daily-coin-scanner`：每天 09:00 UTC 掃描，結果送到 Telegram
- `hourly-check.py`：每小時信號檢查
