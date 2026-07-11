# 量化因子入門指南

> 適合新手的 3 個核心因子 + 實作範例

---

## 核心概念

**量化因子 = 影響資產報酬的可量化指標**

```
報酬 = β₁×因子₁ + β₂×因子₂ + ... + α
```

---

## 新手的 3 個核心因子

### 1. 動量因子（最重要，30% 權重）

**邏輯：** 過去表現好的資產，未來繼續表現好

```python
# 計算方式
動量 = (當前價格 / 90天前價格 - 1) × 100

# 應用
if 動量 > 20%:  買入（強勢）
if 動量 < -20%: 賣出（弱勢）

# 加密市場範例
# 過去 90 天漲幅 > 20% 的幣種 → 買入
# 過去 90 天跌幅 > 20% 的幣種 → 賣出
```

**為什麼有效：**
- 趨勢延續效應
- 投資者追逐績效
- 機構資金流入強勢資產

### 2. 價值因子（20% 權重）

**邏輯：** 被低估的資產，長期會回歸合理價值

```python
# 計算方式（加密市場）
MVRV = 市值 / 已實現市值
MVRV_Z = (MVRV - 歷史平均MVRV) / 歷史標準差

# 應用
if MVRV_Z < 0:  買入（低估）
if MVRV_Z > 7:  賣出（高估）

# 簡易版（不用鏈上數據）
NVT = 市值 / 日交易量
if NVT < 20:  買入（低估）
if NVT > 100: 賣出（高估）
```

**為什麼有效：**
- 均值回歸效應
- 價值投資長期有效
- 避免追高殺低

### 3. 情緒因子（15% 權重）

**邏輯：** 情緒極端時，反向操作

```python
# 計算方式
# 方法 A：恐懼貪婪指數
fng = get_fear_greed_index()

# 方法 B：資金費率（加密特有）
funding_rate = get_funding_rate()

# 應用
if fng < 20:  買入（極度恐懼）
if fng > 80:  賣出（極度貪婪）

if funding_rate > 0.1%:  考慮做空（多頭過於樂觀）
if funding_rate < -0.1%: 考慮做空（空頭過於悲觀）
```

**為什麼有效：**
- 散戶通常在極端情緒時做錯決策
- 機構反向操作
- 市場情緒週期性波動

---

## 多因子組合範例

```python
def score_coin(coin_data):
    score = 0
    
    # 動量因子（30%）
    momentum = (coin_data['price'] / coin_data['price_90d'] - 1) * 100
    if momentum > 30:    score += 30
    elif momentum > 10:  score += 15
    elif momentum < -20: score -= 10
    
    # 價值因子（20%）
    nvt = coin_data['market_cap'] / coin_data['volume_24h']
    if nvt < 30:    score += 20
    elif nvt < 50:  score += 10
    elif nvt > 100: score -= 10
    
    # 情緒因子（15%）
    fng = coin_data['fear_greed']
    if fng < 20:    score += 15
    elif fng < 40:  score += 5
    elif fng > 80:  score -= 15
    
    return score

# 使用
coins = ['BTC', 'ETH', 'SOL', 'AAVE', 'HYPE']
for coin in coins:
    score = score_coin(get_coin_data(coin))
    print(f"{coin}: {score}/100")
```

---

## 實際操作步驟

### 步驟 1：收集數據（免費）

| 數據 | 來源 |
|------|------|
| K 線價格 | Binance API / CCXT |
| 市值/交易量 | CoinGecko API |
| 恐懼貪婪指數 | alternative.me API |
| 資金費率 | Binance API |
| 鏈上數據 | Glassnode（付費）/ Dune Analytics |

### 步驟 2：計算因子

```python
# 每週執行一次
for coin in watchlist:
    # 動量
    momentum = (price_now / price_90d_ago - 1) * 100
    
    # 價值
    nvt = market_cap / volume_24h
    
    # 情緒
    fng = get_fear_greed()
    
    # 綜合評分
    score = momentum * 0.3 + nvt_score * 0.2 + fng_score * 0.15
```

### 步驟 3：排序並選擇

```
1. 所有幣種計算評分
2. 按評分排序
3. 買入前 20%（評分最高）
4. 賣出後 20%（評分最低）
5. 每月再平衡
```

---

## 進階因子（學完基礎後）

| 因子 | 說明 | 難度 |
|------|------|------|
| 波動率 | 低波動資產風險調整後報酬更好 | 中 |
| 流動性 | 流動性改善的幣種有超額報酬 | 中 |
| 質量 | 基本面好的幣種長期表現更好 | 高 |
| 鏈上 | 交易所流出、持有者行為 | 高 |

---

## 常見陷阱

```
❌ 過度擬合：用太多參數去配合歷史數據
❌ 忽略成本：手續費、滑衝擊成本
❌ 數據窺視：用未來數據回測
❌ 幸存者偏差：只看現在存在的幣種
✅ 解決：保持簡單、定期驗證、控制風險
```

---

## 推薦工具

| 工具 | 用途 | 費用 |
|------|------|------|
| CCXT | 串接交易所 API | 免費 |
| CoinGecko API | 價格/市值數據 | 免費 |
| Glassnode | 鏈上數據 | 付費 |
| TradingView | 回測/視覺化 | 免費/付費 |
| Python + Pandas | 數據分析 | 免費 |
