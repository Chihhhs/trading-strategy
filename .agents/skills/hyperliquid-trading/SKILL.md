---
name: hyperliquid-trading
description: "Hyperliquid DEX 合約交易 — 即時數據、TP/SL 設定、市場結構分析、交易心態。支援 BTC 週期自適應策略和幣種相關性分散風險。"
---

# Hyperliquid DEX 合約交易

> 適用場景：在 Hyperliquid 上進行合約交易分析、設定 TP/SL、判斷市場結構
> 語言：zh-tw
> 風格：簡潔、結構化、誠實（說「不適合入場」比硬湊 setup 更重要）

---

## 核心規則

### 數據來源
- **即時價格**：只用 Hyperliquid `allMids` API（`curl -s "https://api.hyperliquid.xyz/info" -H "Content-Type: application/json" -d '{"type":"allMids"}'`）
- **歷史數據**：用 CoinGecko `market_chart`（計算 EMA、RSI、ATR、費波那契等）
- **重要**：`allMids` 回傳的價格是 **string 型別**，必須 `float()` 轉換才能比較
- **不要用 CoinGecko 當作即時價格**，它有延遲且 7d change 常回傳 None

### 分析風格
- 用 Hyperliquid 即時價格作為所有分析的錨點
- 說「不適合入場」比硬湊 setup 更重要
- 不重複分析，更新 ACCOUNT_SNAPSHOT.md 而非重寫
- 用戶是經驗豐富的交易者，直接給建議，不要過度解釋

---

## API 筆記

### 可用 Endpoint（15/44）
| Endpoint | 用途 |
|----------|------|
| `allMids` | 所有幣種即時價格（string，需 float 轉換） |
| `clearinghouseState` | Perp 持倉 + 保證金 |
| `spotClearinghouseState` | Spot 餘額 |
| `openOrders` | 所有掛單（spot + perp 混合，無法區分） |
| `userFills` | 交易歷史 |
| `meta` | 合約規格 |
| `metaAndAssetCtxs` | 合約規格 + 市場上下文 |
| `spotMeta` | Spot 合約規格 |
| `spotMetaAndAssetCtxs` | Spot 合約規格 + 市場上下文 |

### 重要發現
- `openOrders` 同時回傳 spot 和 perp 的掛單，無法用參數區分
- `sz=0` 的掛單代表已取消/完成，但仍會出現在列表中
- `side="A"` = 賣出，`side="B"` = 買入
- `limitPx` 是字串，需要 `float()` 轉換
- **清算價格**：用 API 提供的 `liquidationPx`，不要自己算
- **Rate limit**：連續呼叫需間隔 ≥ 0.3s
- **user 參數**：`metaAndAssetCtxs` 和 `allMids` 不需要 `user`，加上會 422
- 422 錯誤 = 參數格式錯誤或 rate limit，不是 endpoint 不存在

### 外部數據
- CoinGecko `market_chart?days=90` 計算 EMA/RSI/ATR/費波那契
- CoinGecko `simple/price?include_24hr_change=true` 取得 24h 變化
- alternative.me `fng` 恐懼貪婪指數
- Binance `premiumIndex` 資金費率

---

## TP/SL 方法論

### 核心原則
1. **SL 必須有技術依據**，不能隨便設
2. **初始 SL 要寬**（2-3x ATR），獲利後收緊（1.5-2x ATR）
3. **移動止損只上移不下移**（多頭）；只下移不上移（空頭）
4. **TP 從入場價往上算**，SL 從入場價往下算
5. **R:R 至少 1:2** 才值得入場

### SL 設定（6 種方法）
1. **ATR 止損**（推薦）：SL = 入場 ± N×ATR(14)，N=2.0
2. **波段高低點**：SL = 最近波段低點 - 緩衝
3. **EMA 止損**：SL = EMA50 下方
4. **費波那契**：SL = 61.8% 回撤位
5. **固定比例**：SL = 入場 × (1 - N%)
6. **結構止損**：SL = 前一個 HL/LH 下方/上方

### 移動止損（Trailing Stop）
1. **初始 SL 設寬**（3x ATR）
2. **獲利後啟動追蹤**：SL = 最高價 - 2x ATR（多頭）
3. **只上移不下移**
4. **TP1 平倉後 SL 移到入場價**（保本）

### 槓桿與 SL 匹配
| 槓桿 | 建議 SL 距離 |
|------|------------|
| 3x | 3-5% |
| 5x | 2-3% |
| 10x | 1-2% |
| 13x | 0.5-1%（不推薦） |

---

## 市場結構分析

### HH/HL/LH/LL
- HH = Higher High（更高高點）
- HL = Higher Low（更高低點）
- LH = Lower High（更低高點）
- LL = Lower Low（更低低點）

### Market Structure Shift（MSS）
- **MSS 看多**：下降趨勢中價格突破前高 → 回調不破前低（HL）→ 上升趨勢確認
- **MSS 看空**：上升趨勢中價格跌破前低 → 反彈不過前高（LH）→ 下降趨勢確認
- **確認需要**：有效突破（日線收盤站穩）+ 回測確認 + 成交量配合

### 費波那契回撤
- 上升趨勢：38.2% = 最佳做多入場，50% = 次佳
- 下降趨勢：38.2% = 最佳做空入場，50% = 次佳
- 61.8% = 可能趨勢反轉

### 盤整期策略
- 區間交易：支撐做多，阻力做空
- 突破交易：等突破區間後順勢入場
- MSS 等待：等結構轉換確認再入場（最安全）

---

## 交易心態

### 用戶偏好
- 想要簡潔結構化的分析
- 想要誠實的評估（「不適合入場」比硬湊 setup 好）
- 想要理解評分邏輯
- 不要重複分析，更新而非重寫
- 使用即時數據（Hyperliquid allMids）

### 常見陷阱（用戶糾正過的）
1. ❌ SL 隨便設 → ✅ 必須有技術依據（ATR/波段/EMA）
2. ❌ 初始 SL 太緊 → ✅ 初始要寬（3x ATR），獲利後收緊
3. ❌ 用 CoinGecko 當即時價格 → ✅ 用 Hyperliquid allMids
4. ❌ 忽略長期趨勢 → ✅ 先看大方向（90d/EMA200）
5. ❌ 在下跌趨勢中逆勢做多 → ✅ 等 MSS 確認
6. ❌ 頻繁交易 → ✅ 一週最多 3 筆
7. ❌ 加倉攤平 → ✅ 只在盈利時加倉

### 7 次翻倍計劃
- 目標：$69 → $5,832（7 次翻倍）
- 每筆需 +12.4%
- 只在 EMA20 附近入場，R:R ≥ 1:2
- 詳細計劃見 `~/.hermes/trading-knowledge/7X_GOAL.md`

---

## 支援檔案
- `references/hyperliquid-api-endpoints.md` — API endpoint 完整測試結果
- `references/tpsl-guide.md` — TP/SL 設定完整指南
- `references/market-structure-shift.md` — MSS 完整指南
- `references/long-term-vs-short-term.md` — 長期趨勢 vs 短期多空
