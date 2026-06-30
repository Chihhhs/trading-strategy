#!/usr/bin/env python3
"""
coin_scanner.py - 自動掃描符合雙策略條件的標的核心邏輯：
1. 掃描所有可交易幣種
2. 對每個幣跑「最近 60 天」的快速回測
3. 判斷該幣目前適合 FVG / Trend / 雙策略 / 跳過
4. 輸出「現在該用哪個策略」的建議清單

用法:
  from coin_scanner import CoinScanner
  scanner = CoinScanner()
  results = scanner.scan_all()
  # 返回: [{'coin': 'AVAX', 'strategy': 'trend', 'confidence': 0.8, 'reason': '...'}, ...]
"""
import json, urllib.request, statistics, time, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import atr, ema

# ══════════════════════════════════════════════════════════════
# 數據取得
# ══════════════════════════════════════════════════════════════

def get_klines(symbol, interval='1d', limit=200):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return [{'ts':d[0],'open':float(d[1]),'high':float(d[2]),'low':float(d[3]),'close':float(d[4]),'vol':float(d[5])} for d in data]
    except:
        return None

def get_all_binance_usdt_pairs():
    """取得所有 Binance USDT 永續合約對"""
    url = "https://api.binance.com/api/v3/exchangeInfo"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            symbols = []
            for s in data.get('symbols', []):
                if s.get('quoteAsset') == 'USDT' and s.get('status') == 'TRADING':
                    symbols.append(s['symbol'])
            return symbols
    except:
        return []

# ══════════════════════════════════════════════════════════════
# 工具函數
# ══════════════════════════════════════════════════════════════

def calc_rsi(closes, n=14):
    if len(closes) < n + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[-n:]) / n
    avg_l = sum(losses[-n:]) / n
    if avg_l == 0: return 100
    return 100 - 100 / (1 + avg_g / avg_l)

def get_ema_val(closes, period):
    if len(closes) < period: return closes[-1] if closes else 0
    result = ema(closes, period)
    if isinstance(result, list) and result:
        v = result[-1]
        return v if v is not None else closes[-1]
    if result is not None: return result
    return closes[-1] if closes else 0

def _fmt_price(price):
    """根據價格大小格式化"""
    if price is None: return "N/A"
    if price <= 0: return "$0"
    elif price < 0.000001:
        # 極小價格用科學記號
        return f"${price:.2e}"
    elif price < 0.00001:
        return f"${price:.8f}"
    elif price < 0.0001:
        return f"${price:.8f}"
    elif price < 0.01:
        return f"${price:.6f}"
    elif price < 1:
        return f"${price:.4f}"
    elif price < 100:
        return f"${price:.2f}"
    else:
        return f"${price:,.2f}"

def safe_atr_val(highs, lows, closes, period=14):
    if len(closes) < 2: return 1
    result = atr(highs, lows, closes, period)
    fallback = closes[-1] * 0.03
    if result is None: return fallback
    if isinstance(result, tuple):
        if result[0] and isinstance(result[0], list):
            for v in reversed(result[0]):
                if v is not None and isinstance(v, (int, float)): return v
        return fallback
    if isinstance(result, list):
        for v in reversed(result):
            if v is not None and isinstance(v, (int, float)): return v
        return fallback
    if isinstance(result, (int, float)): return result
    return fallback

# ══════════════════════════════════════════════════════════════
# 快速策略測試（用最近 N 天數據）
# ══════════════════════════════════════════════════════════════

def quick_fvg_test(data):
    """
    快速測試 FVG 策略在最近數據的表現
    返回: (win_rate, total_pnl, trade_count)
    """
    if len(data) < 30: return 0, 0, 0
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d['vol'] for d in data]
    
    trades = []
    position = None
    
    for i in range(20, len(closes) - 3):
        c = closes[i]
        h20 = max(highs[i-20:i])
        l20 = min(lows[i-20:i])
        r = h20 - l20
        if r == 0: continue
        fib = (h20 - c) / r * 100
        
        fb = fe = False
        for j in range(max(i-3, 2), i+1):
            if highs[j-2] < highs[j] and highs[j-2] <= c <= highs[j]: fb = True
            if lows[j-2] > lows[j] and lows[j] <= c <= lows[j-2]: fe = True
        
        av2 = statistics.mean(vols[max(0,i-20):i])
        av5 = statistics.mean(vols[max(0,i-50):i]) if i >= 50 else av2
        vr = av2 / av5 if av5 > 0 else 1
        
        s = 0
        if 33 <= fib <= 43: s += 3
        elif 47 <= fib <= 53: s += 2
        if fib < 15: s -= 3
        if fib > 85: s -= 2
        if fb: s += 3
        if fe: s -= 3
        if vr > 1.3: s = int(s * 1.15)
        elif vr < 0.7: s = int(s * 0.85)
        
        signal = "NEUTRAL"
        if s >= 5: signal = "BUY"
        elif s <= -5: signal = "SELL"
        
        if position:
            days = i - position['entry_idx']
            if position['side'] == 'long':
                pnl = (c - position['entry']) / position['entry'] * 300
            else:
                pnl = (position['entry'] - c) / position['entry'] * 300
            
            xr = None
            if position['side'] == 'long':
                if c < position['sl']: xr = 'SL'
                elif c >= position['tp']: xr = 'TP'
                elif signal == 'SELL' and days >= 2: xr = 'REV'
            else:
                if c > position['sl']: xr = 'SL'
                elif c <= position['tp']: xr = 'TP'
                elif signal == 'BUY' and days >= 2: xr = 'REV'
            if days >= 14 and not xr: xr = 'TIME'
            
            if xr:
                trades.append({'pnl': pnl})
                position = None
        
        if position is None and signal in ['BUY', 'SELL']:
            if signal == 'BUY':
                sl = l20
                tp = c + (c - l20) * 1.5
                position = {'side':'long','entry':c,'sl':sl,'tp':tp,'entry_idx':i}
            else:
                sl = h20
                tp = c - (h20 - c) * 1.5
                position = {'side':'short','entry':c,'sl':sl,'tp':tp,'entry_idx':i}
    
    if not trades: return 0, 0, 0
    wins = len([t for t in trades if t['pnl'] > 0])
    total = sum(t['pnl'] for t in trades)
    return wins / len(trades) * 100, total, len(trades)


def quick_trend_test(data):
    """
    快速測試 Trend 策略在最近數據的表現
    返回: (win_rate, total_pnl, trade_count)
    """
    if len(data) < 30: return 0, 0, 0
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    
    trades = []
    position = None
    
    for i in range(20, len(closes) - 3):
        c = closes[i]
        e20 = get_ema_val(closes[:i+1], 20)
        e50 = get_ema_val(closes[:i+1], 50)
        if e20 is None or e50 is None: continue
        rsi = calc_rsi(closes[:i+1])
        av = safe_atr_val(highs[:i+1], lows[:i+1], closes[:i+1])
        
        if position:
            days = i - position['entry_idx']
            if position['side'] == 'long':
                pnl = (c - position['entry']) / position['entry'] * 300
                position['highest'] = max(position.get('highest', position['entry']), c)
                trail = position['highest'] - 2.0 * av
                xr = None
                if c < position['sl']: xr = 'SL'
                elif c < trail and pnl > 5: xr = 'TRAIL'
                elif e20 < e50 and days > 3: xr = 'REV'
                if days >= 30 and not xr: xr = 'TIME'
                if xr:
                    trades.append({'pnl': pnl})
                    position = None
            else:
                pnl = (position['entry'] - c) / position['entry'] * 300
                position['lowest'] = min(position.get('lowest', position['entry']), c)
                trail = position['lowest'] + 2.0 * av
                xr = None
                if c > position['sl']: xr = 'SL'
                elif c > trail and pnl > 5: xr = 'TRAIL'
                elif e20 > e50 and days > 3: xr = 'REV'
                if days >= 30 and not xr: xr = 'TIME'
                if xr:
                    trades.append({'pnl': pnl})
                    position = None
        
        if position is None:
            if e20 > e50 * 1.02 and 50 < rsi <= 70:
                sl = c - 1.5 * av
                tp = c + 2.0 * av
                position = {'side':'long','entry':c,'sl':sl,'tp':tp,'entry_idx':i,'highest':c}
            elif e20 < e50 * 0.98 and 30 <= rsi < 50:
                sl = c + 1.5 * av
                tp = c - 2.0 * av
                position = {'side':'short','entry':c,'sl':sl,'tp':tp,'entry_idx':i,'lowest':c}
    
    if not trades: return 0, 0, 0
    wins = len([t for t in trades if t['pnl'] > 0])
    total = sum(t['pnl'] for t in trades)
    return wins / len(trades) * 100, total, len(trades)


# ══════════════════════════════════════════════════════════════
# 尋幣掃描器
# ══════════════════════════════════════════════════════════════

class CoinScanner:
    """
    自動掃描符合策略條件的標的
    
    評分邏輯：
    - 用最近 60 天數據跑 FVG 和 Trend 策略
    - 看哪個策略的「平均 PnL / 交易」較高
    - 同時看勝率（穩定性）
    - 最終給出建議：fvg / trend / both / skip
    """
    
    def __init__(self, lookback=60, min_trades=3):
        self.lookback = lookback
        self.min_trades = min_trades  # 最低交易次數（避免樣本太小）
    
    def analyze_coin(self, data, coin_name):
        """
        分析單個幣，返回策略建議（使用統一框架）
        """
        if len(data) < 200:
            return None
        
        # 使用統一框架回測
        from unified_framework import UnifiedFramework
        uf = UnifiedFramework(leverage=3)
        trades, stats = uf.backtest(data, coin_name)
        
        if not trades or len(trades) < self.min_trades:
            return None
        
        # 計算績效指標
        closes = [d['close'] for d in data]
        current = closes[-1]
        wins = [t for t in trades if t['pnl'] > 0]
        total_pnl = sum(t['pnl'] for t in trades)
        wr = len(wins) / len(trades) * 100
        avg_pnl = total_pnl / len(trades)
        
        # 只算最近 lookback 天的交易（用 days 推算）
        # trades 是依時間順序的，後面的交易 entry_idx 較大
        # 用 days 無法精確推算，改用比例估算
        recent_n = max(1, len(trades) // 10)  # 大約最近 10% 的交易
        recent_trades = trades[-recent_n:] if recent_n > 0 else []
        recent_pnl = sum(t['pnl'] for t in recent_trades) if recent_n > 0 else 0
        recent_wr = len([t for t in recent_trades if t['pnl'] > 0]) / recent_n * 100 if recent_n >= 1 else 0
        
        # 決策邏輯（寬鬆篩選：只要回測賺的就顯示）
        if total_pnl > 0 and avg_pnl > 0:
            strategy = 'unified'
            confidence = min(0.9, max(0.3, wr / 100))
        elif total_pnl > -20 and wr >= 30:
            strategy = 'unified'
            confidence = 0.3
        else:
            strategy = 'skip'
            confidence = 0
        
        # 目前市場狀態
        from unified_framework import analyze_market_regime, safe_atr, get_ema
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        vols = [d.get('vol', d.get('volume', 0)) for d in data]
        regime = analyze_market_regime(closes, highs, lows, vols, len(closes) - 1)
        
        atr_val = safe_atr(highs, lows, closes, 14)
        e20 = get_ema(closes, 20)
        e50 = get_ema(closes, 50)
        from unified_framework import calc_rsi
        rsi = calc_rsi(closes)
        
        # 目前入場信號
        from unified_framework import find_entry_signal
        signal = find_entry_signal(data, len(data) - 1, regime, closes, highs, lows, vols)
        
        # 建議入場價/TP/SL
        if signal:
            entry_price = signal['entry']
            sl_price = signal['sl']
            tp_price = signal['tp']
            recommended_side = '做多' if signal['side'] == 'long' else '做空'
        else:
            entry_price = current
            sl_price = current * 0.95
            tp_price = current * 1.08
            recommended_side = '觀望'
        
        sl_pct = abs(entry_price - sl_price) / entry_price * 100
        tp_pct = abs(tp_price - entry_price) / entry_price * 100
        
        return {
            'coin': coin_name,
            'strategy': strategy,
            'confidence': round(confidence, 2),
            'current_price': current,
            'total_pnl': round(total_pnl, 1),
            'avg_pnl': round(avg_pnl, 1),
            'wr': round(wr, 1),
            'trade_count': len(trades),
            'recent_wr': round(recent_wr, 1),
            'recent_pnl': round(recent_pnl, 1),
            'recent_n': recent_n,
            'regime': regime.get('reason', ''),
            'direction': regime.get('direction', 'neutral'),
            'strength': regime.get('strength', 0),
            'rsi': round(rsi, 1),
            'atr_pct': round(atr_val / current * 100, 2),
            'recommended_side': recommended_side,
            'entry_price': entry_price,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'tp_pct': round(tp_pct, 1),
            'sl_pct': round(sl_pct, 1),
            'signal_reason': signal.get('reason', '') if signal else '無信號',
        }
    
    def scan_all(self, top_n=20, specific_coins=None):
        """
        掃描所有幣，返回符合條件的標的
        
        specific_coins: 指定幣種列表，例如 ['BTCUSDT', 'ETHUSDT']
        如果為 None，則掃描所有 Binance USDT 交易對
        """
        if specific_coins:
            targets = specific_coins
        else:
            print("📡 取得 Binance 所有 USDT 交易對...")
            targets = get_all_binance_usdt_pairs()
            if not targets:
                print("❌ 無法取得交易對列表，使用預設列表")
                targets = ['BTCUSDT','ETHUSDT','SOLUSDT','AVAXUSDT','WLDUSDT',
                           'ZECUSDT','LINKUSDT','DOGEUSDT','BNBUSDT','XRPUSDT',
                           'ADAUSDT','DOTUSDT','ATOMUSDT','UNIUSDT','AAVEUSDT',
                           'NEARUSDT','APTUSDT','SUIUSDT','ARBUSDT','OPUSDT',
                           'INJUSDT','TONUSDT','PEPEUSDT','SHIBUSDT','LDOUSDT']
        
        print(f"🔍 掃描 {len(targets)} 個幣種（最近 {self.lookback} 天數據）...")
        
        results = []
        errors = 0
        
        for idx, sym in enumerate(targets):
            data = get_klines(sym, '1d', 1000)
            if not data or len(data) < 200:
                errors += 1
                continue
            
            name = sym.replace('USDT', '')
            result = self.analyze_coin(data, name)
            if result and result['strategy'] != 'skip':
                results.append(result)
            
            if (idx + 1) % 20 == 0:
                print(f"  進度: {idx+1}/{len(targets)} | 找到 {len(results)} 個標的")
                time.sleep(0.3)  # 避免 rate limit
        
        # 排序：先看 confidence，再看平均 PnL
        results.sort(key=lambda x: (x['confidence'], max(x.get('fvg_avg', 0), x.get('trend_avg', 0))), reverse=True)
        
        print(f"✅ 掃描完成: {len(results)} 個符合標的（{errors} 個數據不足）")
        return results[:top_n]
    
    def format_report(self, results):
        """格式化報告（使用統一框架結果）"""
        if not results:
            return "沒有找到符合條件的標的"
        
        lines = []
        lines.append("📊 統一框架尋幣掃描報告")
        lines.append(f"分析窗口: 最近 {self.lookback} 天 | 最低交易次數: {self.min_trades}")
        lines.append("")
        
        for idx, r in enumerate(results[:8], 1):
            price = r['current_price']
            # 根據價格大小決定小數位數
            if price < 0.001:
                pfmt = f"${price:.8f}"
            elif price < 1:
                pfmt = f"${price:.6f}"
            elif price < 100:
                pfmt = f"${price:.4f}"
            else:
                pfmt = f"${price:,.2f}"
            
            # 方向圖示
            dir_icon = {'up': '📈', 'down': '📉', 'neutral': '⏸️'}.get(r.get('direction', 'neutral'), '⏸️')
            
            lines.append(f"#{idx} {r['coin']} | 現價 {pfmt} | {dir_icon} {r.get('recommended_side', '觀望')}")
            lines.append(f"   信心度: {r['confidence']:.0%} | 強度: {r.get('strength', 0)}/10 | RSI: {r.get('rsi', 'N/A')} | ATR: {r.get('atr_pct', 'N/A')}%")
            lines.append(f"   回測: WR {r['wr']:.0f}% | PnL {r['total_pnl']:+.0f}% | {r['trade_count']}筆 | 均{r['avg_pnl']:+.1f}%/筆")
            
            if r.get('recent_n', 0) > 0:
                lines.append(f"   近{self.lookback}天: WR {r.get('recent_wr', 0):.0f}% | PnL {r.get('recent_pnl'):+.0f}% | {r['recent_n']}筆")
            
            # 入場建議
            entry = _fmt_price(r.get('entry_price', 0))
            tp = _fmt_price(r.get('tp_price', 0))
            sl = _fmt_price(r.get('sl_price', 0))
            lines.append(f"   🎯 入場 {entry} → TP {tp} (+{r.get('tp_pct', 0):.1f}%) | SL {sl} (-{r.get('sl_pct', 0):.1f}%)")
            
            if r.get('signal_reason'):
                lines.append(f"   💡 {r['signal_reason']}")
            if r.get('regime'):
                lines.append(f"   📋 {r['regime']}")
            
            lines.append("")
        
        # 統計
        total_coins = len(results)
        long_coins = len([r for r in results if r.get('recommended_side') == '做多'])
        short_coins = len([r for r in results if r.get('recommended_side') == '做空'])
        lines.append(f"📈 市場狀態: 做多 {long_coins} | 做空 {short_coins} | 觀望 {total_coins - long_coins - short_coins}")
        
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    scanner = CoinScanner(lookback=60, min_trades=3)
    
    # 掃描指定幣（快速）或全部幣（較慢）
    import sys
    if '--full' in sys.argv:
        results = scanner.scan_all(top_n=20)
    else:
        # 預設：掃描主流 + 熱門幣（移除 LINK：不適合統一框架）
        specific = [
            'BTCUSDT','ETHUSDT','SOLUSDT','AVAXUSDT','WLDUSDT',
            'ZECUSDT','DOGEUSDT','BNBUSDT','XRPUSDT',
            'ADAUSDT','DOTUSDT','ATOMUSDT','UNIUSDT','AAVEUSDT',
            'NEARUSDT','APTUSDT','SUIUSDT','ARBUSDT','OPUSDT',
            'INJUSDT','TONUSDT','PEPEUSDT','SHIBUSDT','LDOUSDT',
            'FILUSDT','BCHUSDT','ICPUSDT','RENDERUSDT','TIAUSDT',
        ]
        results = scanner.scan_all(top_n=20, specific_coins=specific)
    
    report = scanner.format_report(results)
    print(report)
