# Hyperliquid API Endpoint 筆記

> 測試日期：2026-06-16
> 錢包：0x288A2637fcf6f9f793AcC5beAc7107efa6530681

## 可用 Endpoint（15/44）

| Endpoint | 用途 | 回傳 |
|----------|------|------|
| `allMids` | 所有幣種即時價格 | dict（**價格是 string，需 float() 轉換**） |
| `clearinghouseState` | Perp 持倉 + 保證金 | dict |
| `spotClearinghouseState` | Spot 餘額 | dict |
| `openOrders` | 所有掛單（spot + perp 混合） | list |
| `userFills` | 交易歷史 | list |
| `meta` | 合約規格 | dict |
| `metaAndAssetCtxs` | 合約規格 + 市場上下文 | list[2] |
| `spotMeta` | Spot 合約規格 | dict |
| `spotMetaAndAssetCtxs` | Spot 合約規格 + 市場上下文 | list[2] |
| `twapHistory` | TWAP 歷史 | list |
| `referral` | 推薦資訊 | dict |
| `userVaultEquities` | 金庫權益 | list |
| `delegations` | 委託 | list |
| `validatorSummaries` | 驗證者摘要 | list |
| `userRateLimit` | 速率限制 | dict |

## 不可用 Endpoint（29/44）

`userState`, `account`, `marginSummary`, `orders`, `spotOrders`, `perpOrders`, `spotOpenOrders`, `perpOpenOrders`, `fills`, `userFillsByTime`, `spotFills`, `perpFills`, `assetCtxs`, `l2Book`, `candles`, `funding`, `openInterest`, `subAccounts`, `agents`, `authorizations`, `apiKeys`, `twapOrders`, `maxMarketOrderSz`, `maxLimitOrderSz`, `vaultDetails`, `leadingVault`, `vaultSummary`, `vaultEquities`, `spotDeploy`

全部返回 422 Unprocessable Entity。

## 關鍵發現

### allMids 價格是 string
```python
# 錯誤
if isinstance(p, (int, float)):  # string 永遠返回 False

# 正確
try:
    price = float(mids.get('BTC', 0))
except (ValueError, TypeError):
    continue
```

### openOrders 混合 spot + perp
- 無法用參數區分
- 需要用 `clearinghouseState` / `spotClearinghouseState` 判斷持倉在哪
- 用戶的 OCO 模式：entry + SL 用 reduceOnly 反向單

### 外部數據
- CoinGecko `market_chart?days=90` 計算 EMA/RSI/ATR/費波那契
- CoinGecko `simple/price?include_24hr_change=true` 取得 24h 變化
- alternative.me `fng` 恐懼貪婪指數
- Binance `premiumIndex` 資金費率
