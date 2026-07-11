# Hyperliquid API 完整筆記

> 更新：2026-06-18
> 錢包：0x288A2637fcf6f9f793AcC5beAc7107efa6530681

---

## 可用 Endpoint

### 帳戶/持倉

| Endpoint | 用途 | 需要 user | 回傳 |
|----------|------|----------|------|
| `clearinghouseState` | Perp 持倉 + 保證金 + 清算價 | ✅ | dict |
| `spotClearinghouseState` | Spot 餘額 | ✅ | dict |
| `webData2` | 完整帳戶（含 openOrders） | ✅ | dict |

### 掛單

| Endpoint | 用途 | 需要 user | 回傳 |
|----------|------|----------|------|
| `openOrders` | 所有掛單（spot + perp 混合） | ✅ | list |

### 交易歷史

| Endpoint | 用途 | 需要 user | 回傳 |
|----------|------|----------|------|
| `userFills` | 所有成交記錄 | ✅ | list |

### 市場

| Endpoint | 用途 | 需要 user | 回傳 |
|----------|------|----------|------|
| `allMids` | 所有幣種最新價格 | ❌ | dict |
| `meta` | 合約規格 | ❌ | dict |
| `metaAndAssetCtxs` | 合約規格 + 市場上下文 | ❌ | list[2] |

### 其他

| Endpoint | 用途 | 需要 user | 回傳 |
|----------|------|----------|------|
| `userRateLimit` | 速率限制 | ✅ | dict |
| `referral` | 推薦資訊 | ✅ | dict |

---

## 關鍵發現

### 1. Rate Limit

```
Hyperliquid API 有 rate limit
- 連續呼叫間隔需 ≥ 0.3 秒
- 否則回傳 HTTP 422
- 建議每次呼叫後 sleep(0.3)
```

### 2. openOrders 欄位

```json
{
  "coin": "SOL",        // 幣種
  "side": "A",          // A=賣出(Sell), B=買入(Buy)
  "limitPx": "62.82",   // 限價價格（字串）
  "sz": "0.0",          // 剩餘數量（0=已取消/完成）
  "oid": 472530876936,  // 訂單 ID
  "timestamp": 1781758739500,  // 時間戳（毫秒）
  "origSz": "0.0",      // 原始數量
  "reduceOnly": true    // 是否只減倉（SL/TP）
}
```

**重要：**
- `sz=0` 不代表訂單不存在，而是已取消或已成交
- `side="A"` = Ask = 賣出（Long 的 SL 是賣出）
- `side="B"` = Bid = 買入
- `limitPx` 是字串，需要 float() 轉換

### 3. clearinghouseState 持倉欄位

```json
{
  "coin": "SOL",
  "szi": "2.66",           // 數量（正=多頭, 負=空頭）
  "leverage": {"type": "cross", "value": 10},
  "entryPx": "72.3007",    // 入場價
  "positionValue": "190.90",  // 名目價值
  "unrealizedPnl": "-1.42",   // 未實現盈虧
  "returnOnEquity": "-0.09",  // 保證金報酬率
  "liquidationPx": "52.28",   // ⭐ 清算價格（API 直接提供，精確值）
  "marginUsed": "19.09",      // 已用保證金
  "maxLeverage": 20,          // 最大槓桿
  "cumFunding": {
    "allTime": "-0.028195",     // 累計資金費率（全部）
    "sinceOpen": "-0.028195",   // 累計資金費率（開倉以來）
    "sinceChange": "-0.027441"  // 累計資金費率（上次調整以來）
  }
}
```

**重要：**
- `liquidationPx` 是 API 直接提供的精確清算價格，不要自己計算
- `szi` 正負號代表方向（正=Long, 負=Short）
- `returnOnEquity` 是保證金報酬率，不是帳戶報酬率

### 4. 清算價格

```
API 直接提供 liquidationPx，不需要自己計算

你的持倉清算價（2026-06-18）:
  SOL:  $52.28  (距當前 27.1%)
  UNI:  $0.46   (距當前 85.4%)
  HYPE: $52.96  (距當前 25.7%)

清算條件：
  Long:  價格 ≤ liquidationPx → 清算
  Short: 價格 ≥ liquidationPx → 清算
```

### 5. 保證金計算

```
accountValue = 帳戶總價值（含未實現盈虧）
totalMarginUsed = 所有持倉保證金總和
withdrawable = 可提款金額 = accountValue - totalMarginUsed
marginPct = totalMarginUsed / accountValue × 100

風險等級：
  > 80%: 🔴 高風險
  60-80%: 🟠 中風險
  40-60%: 🟡 注意
  < 40%: 🟢 安全
```

### 6. 資金費率

```
cumFunding.sinceOpen = 開倉以來的累計資金費率
  > 0: 你付錢給空頭（多頭擁擠）
  < 0: 空頭付錢給你（空頭擁擠）

你的持倉（2026-06-18）:
  SOL:  -0.028195 (空頭付給你)
  UNI:  +0.009570 (你付給空頭)
  HYPE: +0.055129 (你付給空頭)
```

---

## API 使用範例

```python
import urllib.request
import json
import time

API_URL = "https://api.hyperliquid.xyz/info"
PUBKEY = "0x288A...0681"

def query(req_type, need_user=True, extra=None):
    payload = {"type": req_type}
    if need_user:
        payload["user"] = PUBKEY
    if extra:
        payload.update(extra)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(API_URL, data=body,
          headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        time.sleep(0.3)  # rate limit 保護
        return json.loads(resp.read())

# 查持倉（含清算價）
chs = query("clearinghouseState")
for p in chs["assetPositions"]:
    ap = p["position"]
    print(f'{ap["coin"]}: liq={ap["liquidationPx"]} pnl={ap["unrealizedPnl"]}')

# 查價格
mids = query("allMids", need_user=False)
print(f'SOL: ${mids["SOL"]}')

# 查掛單
orders = query("openOrders")
for o in orders:
    status = "有效" if float(o["sz"]) > 0 else "已取消"
    print(f'{o["coin"]} {o["side"]} ${o["limitPx"]} × {o["sz"]} [{status}]')
```

---

## 已知問題

| 問題 | 說明 |
|------|------|
| Rate limit | 連續呼叫需間隔 ≥ 0.3s，否則 422 |
| openOrders 無法區分 spot/perp | 需要配合 clearinghouseState 判斷 |
| sz=0 的掛單 | 不代表不存在，是已取消/完成，但仍會出現在 openOrders 中 |
| limitPx 是字串 | 需要 float() 轉換 |

---

*存放：~/.hermes/trading-knowledge/scripts/hyperliquid-api-endpoints.md*
*最後更新：2026-06-18*
