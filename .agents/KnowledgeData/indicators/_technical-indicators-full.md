# 技術指標知識庫

> 來源：TradingView Wiki、Investopedia、Murphy《Technical Analysis of the Financial Markets》、Pring《Technical Analysis Explained》
> 驗證狀態：✅ 廣泛驗證 | ⚠️ 部分驗證 | 🔬 進階/小眾

---

## 一、趨勢指標 (Trend Indicators)

### 1. 移動平均線 (Moving Averages)

#### SMA (Simple Moving Average)
```
SMA(n) = (P1 + P2 + ... + Pn) / n
```
- **常用週期**：20（短期）、50（中期）、200（長期）
- **用途**：判斷趨勢方向、支撐/阻力
- **黃金交叉**：SMA50 上穿 SMA200 → 看多信號
- **死亡交叉**：SMA50 下穿 SMA200 → 看空信號
- **驗證**：✅ 最基礎、最廣泛使用的指標
- **限制**：滯後性強，在盤整市場會產生大量假信號

#### EMA (Exponential Moving Average)
```
EMA(t) = Price(t) × k + EMA(t-1) × (1-k)
k = 2 / (n + 1)
```
- **常用週期**：9、12、21、26、50、200
- **特點**：對近期價格更敏感，滯後性小於 SMA
- **MACD 基礎**：MACD = EMA12 - EMA26
- **驗證**：✅ 廣泛使用，特別是在日內交易

#### 多均線系統
- **多頭排列**：短期 > 中期 > 長期（全部向上）
- **空頭排列**：短期 < 中期 < 長期（全部向下）
- **糾纏**：均線交叉 → 盤整期，避免交易

#### Hull Moving Average (HMA)
```
HMA = WMA(2×WMA(n/2) - WMA(n), √n)
```
- **特點**：幾乎零滯後，同時保持平滑
- **用途**：快速趨勢判斷
- **驗證**：⚠️ 小眾但有效，適合日內交易

---

### 2. MACD (Moving Average Convergence Divergence)

```
MACD Line = EMA12 - EMA26
Signal Line = EMA9 of MACD Line
Histogram = MACD Line - Signal Line
```

**信號類型：**
| 信號 | 條件 | 強度 |
|------|------|------|
| 看多交叉 | MACD 上穿 Signal | 中等 |
| 看空交叉 | MACD 下穿 Signal | 中等 |
| 看多背離 | 價格創新低但 MACD 未創新低 | 強 |
| 看空背離 | 價格創新高但 MACD 未創新高 | 強 |
| 零軸上方 | MACD > 0 | 趨勢偏多 |
| 零軸下方 | MACD < 0 | 趨勢偏空 |

**驗證**：✅ 最經典的動量指標之一
**限制**：在盤整市場效果差，需搭配其他指標

---

### 3. ADX (Average Directional Index)

```
+DI = 正向方向指標
-DI = 負向方向指標
ADX = 方向移動的平均值（0-100）
```

**解讀：**
| ADX 值 | 含義 |
|--------|------|
| 0-20 | 無趨勢/盤整 |
| 20-25 | 趨勢正在形成 |
| 25-50 | 強趨勢 |
| 50-75 | 非常強趨勢 |
| 75-100 | 極端趨勢（罕見） |

**交易策略：**
- ADX > 25 且 +DI > -DI → 只做多
- ADX > 25 且 -DI > +DI → 只做空
- ADX < 20 → 避免趨勢策略，改用區間策略

**驗證**：✅ Welles Wilder 原創，40+ 年驗證

---

### 4. Ichimoku Cloud (一目均衡表)

**五條線：**
| 線 | 計算 | 用途 |
|----|------|------|
| Tenkan-sen (轉換線) | (9期高+9期低)/2 | 短期趨勢 |
| Kijun-sen (基準線) | (26期高+26期低)/2 | 中期趨勢/支撐阻力 |
| Senkou Span A | (Tenkan+Kijun)/2，前移26期 | 雲的上沿 |
| Senkou Span B | (52期高+52期低)/2，前移26期 | 雲的下沿 |
| Chikou Span (延遲線) | 收盤價後移26期 | 確認信號 |

**交易規則：**
- 價格在雲上方 → 看多
- 價格在雲下方 → 看空
- 價格在雲內 → 盤整/不確定
- Tenkan 上穿 Kijun → 買入信號
- 雲的厚度 = 支撐/阻力強度

**驗證**：✅ 日本交易界經典，特別適合趨勢市場

---

### 5. SuperTrend

```
Upper Band = (High + Low) / 2 + ATR(n) × Multiplier
Lower Band = (High + Low) / 2 - ATR(n) × Multiplier
```

- **常用參數**：ATR週期=10，乘數=3
- **多頭**：價格在 Upper Band 上方
- **空頭**：價格在 Lower Band 下方
- **驗證**：✅ 簡潔有效，廣泛用於自動化交易

---

## 二、動量指標 (Momentum Indicators)

### 6. RSI (Relative Strength Index)

```
RSI = 100 - 100/(1 + RS)
RS = 平均上漲幅度 / 平均下跌幅度（通常14期）
```

**標準解讀：**
| RSI 值 | 含義 |
|--------|------|
| > 70 | 超買（可能回調） |
| < 30 | 超賣（可能反彈） |
| 40-60 | 中性區 |
| 50 以上 | 多頭動能較強 |

**進階用法：**
- **RSI 背離**：價格創新高但 RSI 未創新高 → 趨勢衰竭
- **RSI 50 線**：RSI > 50 且回升 → 多頭確認
- **RSI 區間轉移**：牛市時 RSI 在 40-80 波動；熊市時在 20-60 波動
- ** Wilder 原始規則**：RSI > 80 才是真正的超買（非 70）

**驗證**：✅ 最經典的動量指標，40+ 年驗證

---

### 7. Stochastic Oscillator (KD 指標)

```
%K = (當前收盤 - 最近n期最低) / (最近n期最高 - 最近n期最低) × 100
%D = %K 的 m 期移動平均
```

**常用參數**：14, 3, 3（%K週期, %K平滑, %D週期）

**解讀：**
| 條件 | 信號 |
|------|------|
| %K > 80 | 超買 |
| %K < 20 | 超賣 |
| %K 上穿 %D（在超賣區） | 買入 |
| %K 下穿 %D（在超買區） | 賣出 |
| 背離 | 趨勢衰竭 |

**驗證**：✅ George Lane 原創，廣泛使用

---

### 8. CCI (Commodity Channel Index)

```
CCI = (典型價格 - SMA(典型價格)) / (0.015 × 平均偏差)
典型價格 = (High + Low + Close) / 3
```

**解讀：**
- CCI > +100 → 超買
- CCI < -100 → 超賣
- CCI 從 -100 下方回升 → 買入信號
- CCI 從 +100 上方回落 → 賣出信號

**驗證**：✅ Donald Lambert 原創，適合商品和加密貨幣

---

### 9. Williams %R

```
%R = (n期最高 - 當前收盤) / (n期最高 - n期最低) × (-100)
```

- 與 Stochastic 類似但刻度相反
- %R > -20 → 超買
- %R < -80 → 超賣

**驗證**：✅ Larry Williams 原創

---

### 10. ROC (Rate of Change)

```
ROC = (當前價格 - n期前價格) / n期前價格 × 100
```

- ROC > 0 → 價格在上漲
- ROC < 0 → 價格在下跌
- ROC 背離 → 趨勢衰竭信號

---

## 三、波動率指標 (Volatility Indicators)

### 11. Bollinger Bands (布林通道)

```
中軌 = SMA(20)
上軌 = SMA(20) + 2 × σ(20)
下軌 = SMA(20) - 2 × σ(20)
```

**交易策略：**
| 策略 | 條件 |
|------|------|
| 均值回歸 | 價格觸及上軌 → 做空；觸及下軌 → 做多 |
| 趨勢追蹤 | 價格沿上軌運行 → 強多頭 |
| 擠壓 (Squeeze) | 通道變窄 → 即將大幅波動 |
| W底 | 第二個底部在上軌上方 → 看多 |
| M頭 | 第二個頭部在下軌下方 → 看空 |

**%B 指標**：
```
%B = (價格 - 下軌) / (上軌 - 下軌)
```
- %B > 1 → 價格超出上軌
- %B < 0 → 價格超出下軌
- %B = 0.5 → 價格在中軌

**驗證**：✅ John Bollinger 原創，最經典的波動率指標

---

### 12. ATR (Average True Range)

```
TR = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
ATR = SMA(TR, n) 或 Wilder 平滑
```

**常用週期**：14

**用途：**
1. **止損設置**：止損 = 入場價 ± 2×ATR
2. **倉位計算**：倉位 = 風險金額 / (2×ATR)
3. **波動率判斷**：ATR 上升 = 波動加大
4. **突破確認**：價格突破 + ATR 上升 = 有效突破

**驗證**：✅ Welles Wilder 原創，風險管理必備

---

### 13. Keltner Channel

```
中軌 = EMA(20)
上軌 = EMA(20) + 2 × ATR(10)
下軌 = EMA(20) - 2 × ATR(10)
```

- 與布林通道類似但使用 ATR 而非標準差
- 更平滑，假信號更少
- **驗證**：✅ Chester Keltner 原創

---

### 14. Donchian Channel (唐奇安通道)

```
上軌 = n期最高
下軌 = n期最低
中軌 = (上軌 + 下軌) / 2
```

- **海龜交易法則**的核心指標
- 價格突破上軌 → 買入
- 價格突破下軌 → 賣出
- **驗證**：✅ 海龜交易法則實證有效

---

## 四、成交量指標 (Volume Indicators)

### 15. OBV (On-Balance Volume)

```
如果 Close > Close(-1): OBV = OBV(-1) + Volume
如果 Close < Close(-1): OBV = OBV(-1) - Volume
如果 Close = Close(-1): OBV = OBV(-1)
```

- OBV 上升 + 價格上升 → 確認多頭
- OBV 下降 + 價格上升 → 背離（趨勢衰弱）
- **驗證**：✅ Joseph Granville 原創

---

### 16. VWAP (Volume Weighted Average Price)

```
VWAP = Σ(價格 × 成交量) / Σ(成交量)
```

- **機構交易基準**：價格 > VWAP → 多頭；價格 < VWAP → 空頭
- **日內交易核心指標**
- 價格回到 VWAP → 買入機會（多頭市場）
- **驗證**：✅ 機構投資者廣泛使用

---

### 17. Volume Profile

- 顯示在每個價格水平的成交量
- **POC (Point of Control)**：成交量最大的價格
- **Value Area**：70% 成交量所在的價格範圍
- **HVN (High Volume Node)**：高成交量節點 = 支撐/阻力
- **LVN (Low Volume Node)**：低成交量節點 = 價格快速通過
- **驗證**：✅ J. Peter Steidlmayer 原創，CME 官方推廣

---

### 18. Money Flow Index (MFI)

```
MFI = 100 - 100/(1 + 正資金流/負資金流)
```

- RSI 的成交量加權版本
- MFI > 80 → 超買
- MFI < 20 → 超賣
- **驗證**：✅ 結合價格和成交量，比 RSI 更全面

---

## 五、複合/進階指標

### 19. Supertrend + EMA 組合

```
趨勢判斷：Supertrend 方向 + EMA200 方向一致
入場：價格回調至 EMA20 + Supertrend 確認
止損：Supertrend 另一側
```

---

### 20. RSI + Bollinger Bands 組合

```
RSI < 30 + 價格觸及布林下軌 → 強烈買入
RSI > 70 + 價格觸及布林上軌 → 強烈賣出
```

---

### 21. MACD + RSI 組合

```
MACD 看趨勢方向
RSI 看入場時機
MACD 看多 + RSI 從超賣區回升 → 最佳買入
```

---

### 22. ATR + ADX 組合

```
ADX > 25 → 有趨勢 → 使用 ATR 追蹤止損
ADX < 20 → 無趨勢 → 不使用趨勢策略
```

---

## 六、指標使用原則

### 指標分類搭配（建議不超過 3-4 個）

| 類別 | 推薦指標 | 作用 |
|------|---------|------|
| 趨勢 | EMA/MA, ADX, Ichimoku | 判斷方向 |
| 動量 | RSI, MACD | 確認強度 |
| 波動率 | Bollinger, ATR | 設置止損/TP |
| 成交量 | OBV, VWAP | 確認參與度 |

### 常見錯誤

1. **指標過多**：5+ 個指標會互相矛盾，導致無法決策
2. **參數最佳化**：過度擬合歷史數據，實盤效果差
3. **忽略趨勢**：在強趨勢中使用逆勢指標（如 RSI 超買做空）
4. **單一信號交易**：需要至少 2-3 個指標確認
5. **不同時間框架矛盾**：日線看多但小時線看空 → 等待一致

### 多時間框架分析 (MTF)

```
1. 大週期（日線/週線）：判斷主要趨勢方向
2. 中週期（4H/1H）：尋找入場區域
3. 小週期（15m/5m）：精確入場時機
```

**規則**：只在大週期方向上交易。日線看多 → 只在 1H 找買入機會。
