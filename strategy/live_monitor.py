#!/usr/bin/env python3
"""
live_monitor.py - 實盤監控系統
整合 scoring_v6 + dynamic_exit

功能：
1. 定時拉取 Binance 即時數據
2. 對所有幣種評分並生成信號
3. 根據波動率自適應計算 TP/SL
4. 信號變化時發送通知到 Telegram

使用方法：
  python3 live_monitor.py --interval 300  # 每 5 分鐘更新
  python3 live_monitor.py --once          # 只跑一次
"""
import sys, os, json, time, math, subprocess
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__))

from indicators_v3 import atr, adx
from scoring_v6 import composite_score_v6, get_signal_summary, _signal_history, classify_market
from dynamic_exit import DynamicExitCalculator, DynamicExitMonitor

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════

WATCHLIST = [
    {'name': 'BTC', 'symbol': 'BTCUSDT'},
    {'name': 'ETH', 'symbol': 'ETHUSDT'},
    {'name': 'SOL', 'symbol': 'SOLUSDT'},
    {'name': 'BNB', 'symbol': 'BNBUSDT'},
    {'name': 'AVAX', 'symbol': 'AVAXUSDT'},
    {'name': 'XRP', 'symbol': 'XRPUSDT'},
    {'name': 'NEAR', 'symbol': 'NEARUSDT'},
    {'name': 'WLD', 'symbol': 'WLDUSDT'},
    {'name': 'ZEC', 'symbol': 'ZECUSDT'},
]

# 信號歷史（持久化）
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SIGNAL_LOG = os.path.join(PROJECT_ROOT, 'data', 'signal_log.json')


# ══════════════════════════════════════════════════════════════
# 數據獲取
# ══════════════════════════════════════════════════════════════

def get_binance_klines(symbol, interval='1d', limit=90):
    import urllib.request
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return [{
                'ts': d[0], 'open': float(d[1]), 'high': float(d[2]),
                'low': float(d[3]), 'close': float(d[4]), 'volume': float(d[5]),
            } for d in data]
    except Exception as e:
        print(f'  ⚠️ {symbol} 數據獲取失敗: {e}')
        return None


# ══════════════════════════════════════════════════════════════
# 信號記錄
# ══════════════════════════════════════════════════════════════

def load_signal_log():
    if os.path.exists(SIGNAL_LOG):
        with open(SIGNAL_LOG, 'r') as f:
            return json.load(f)
    return {}

def save_signal_log(log):
    os.makedirs(os.path.dirname(SIGNAL_LOG), exist_ok=True)
    with open(SIGNAL_LOG, 'w') as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

def load_history_log():
    HISTORY_LOG = SIGNAL_LOG.replace('.json', '_history.json')
    if os.path.exists(HISTORY_LOG):
        with open(HISTORY_LOG, 'r') as f:
            return json.load(f)
    return []

def save_history_log(history):
    HISTORY_LOG = SIGNAL_LOG.replace('.json', '_history.json')
    os.makedirs(os.path.dirname(HISTORY_LOG), exist_ok=True)
    with open(HISTORY_LOG, 'w') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
# 分析引擎
# ══════════════════════════════════════════════════════════════

calc = DynamicExitCalculator()
monitor = DynamicExitMonitor()

def analyze_coin(coin_config):
    """分析單個幣種"""
    name = coin_config['name']
    symbol = coin_config['symbol']
    
    data = get_binance_klines(symbol, limit=90)
    if not data or len(data) < 60:
        return None
    
    closes = [d['close'] for d in data]
    highs = [d['high'] for d in data]
    lows = [d['low'] for d in data]
    vols = [d['volume'] for d in data]
    opens = [d['open'] for d in data]
    
    current_price = closes[-1]
    
    # 評分
    r = composite_score_v6(closes, highs, lows, vols, opens,
                           fear_greed=50, funding_rate=0.01,
                           coin_name=name, use_confirmation=True, min_consecutive=2)
    
    # 波動率百分位數
    vol_pct, atr_pct, atr_val = calc.get_vol_percentile(highs, lows, closes)
    
    # 出場計算（根據信號方向決定 side）
    regime = r['details'].get('market_regime', 'ranging')
    signal_side = 'long' if 'BUY' in r['signal'] else ('short' if 'SELL' in r['signal'] else 'long')
    exit_plan = calc.calc_exit(current_price, atr_val, signal_side, regime, vol_pct, highs, lows, closes)
    
    return {
        'name': name,
        'symbol': symbol,
        'price': current_price,
        'signal': r['signal'],
        'score': r['score'],
        'confidence': r['confidence'],
        'regime': regime,
        'vol_pct': vol_pct,
        'atr_pct': atr_pct,
        'tp_price': exit_plan['tp_price'],
        'sl_price': exit_plan['sl_price'],
        'strategy': exit_plan['strategy'],
        'tp_pct': exit_plan['tp_pct'],
        'sl_pct': exit_plan['sl_pct'],
        'summary': get_signal_summary(r),
    }


# ══════════════════════════════════════════════════════════════
# 報告生成
# ══════════════════════════════════════════════════════════════

def format_report(results):
    """格式化報告"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [f'📊 **市場監控報告** | {now}', '']
    
    # 按信號強度排序
    buy_signals = [r for r in results if 'BUY' in r['signal']]
    sell_signals = [r for r in results if 'SELL' in r['signal']]
    neutral = [r for r in results if r['signal'] == 'NEUTRAL']
    
    if buy_signals:
        lines.append('🟢 **做多信號:**')
        for r in sorted(buy_signals, key=lambda x: -x['score']):
            lines.append(f"  **{r['name']}** ${r['price']:,.2f}")
            lines.append(f"    信號: {r['signal']} | 分數: {r['score']:.1f} | 信心度: {r['confidence']}%")
            lines.append(f"    市況: {r['regime']} | 波動百分位: {r['vol_pct']:.0f}%")
            lines.append(f"    TP: ${r['tp_price']:,.2f} ({r['tp_pct']:+.1f}%) | SL: ${r['sl_price']:,.2f} ({r['sl_pct']:+.1f}%)")
            lines.append(f"    策略: {r['strategy']}")
            lines.append('')
    
    if sell_signals:
        lines.append('🔴 **做空信號:**')
        for r in sorted(sell_signals, key=lambda x: x['score']):
            lines.append(f"  **{r['name']}** ${r['price']:,.2f}")
            lines.append(f"    信號: {r['signal']} | 分數: {r['score']:.1f} | 信心度: {r['confidence']}%")
            lines.append(f"    市況: {r['regime']} | 波動百分位: {r['vol_pct']:.0f}%")
            lines.append(f"    TP: ${r['tp_price']:,.2f} ({r['tp_pct']:+.1f}%) | SL: ${r['sl_price']:,.2f} ({r['sl_pct']:+.1f}%)")
            lines.append(f"    策略: {r['strategy']}")
            lines.append('')
    
    if neutral:
        lines.append('⚪ **中性:**')
        for r in neutral:
            lines.append(f"  {r['name']}: {r['signal']} (分數: {r['score']:.1f})")
    
    return '\n'.join(lines)


# ══════════════════════════════════════════════════════════════
# 主循環
# ══════════════════════════════════════════════════════════════

def run_once():
    """跑一次分析"""
    print(f'\n{"="*60}')
    print(f'📊 市場分析 | {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'{"="*60}')
    
    results = []
    prev_log = load_signal_log()
    history = load_history_log()
    
    for coin in WATCHLIST:
        print(f'  分析 {coin["name"]}...')
        r = analyze_coin(coin)
        if r:
            results.append(r)
            
            # 檢查信號變化
            prev = prev_log.get(coin['name'], {})
            if prev.get('signal') != r['signal']:
                change_msg = f"🔔 信號變化: {coin['name']} {prev.get('signal', 'N/A')} → {r['signal']} @ ${r['price']:,.2f} (分數: {r['score']:.1f})"
                print(f'    {change_msg}')
                # 發送到 Telegram
                try:
                    import subprocess
                    subprocess.run(
                        [sys.executable, os.path.join(os.path.dirname(__file__), 'send_telegram.py'), change_msg],
                        timeout=15, capture_output=True
                    )
                except Exception:
                    pass
                # 記錄到歷史
                history.append({
                    'time': datetime.now().isoformat(),
                    'coin': coin['name'],
                    'prev_signal': prev.get('signal', 'N/A'),
                    'new_signal': r['signal'],
                    'price': r['price'],
                    'score': r['score'],
                })
            
            # 更新記錄
            prev_log[coin['name']] = {
                'signal': r['signal'],
                'score': r['score'],
                'price': r['price'],
                'time': datetime.now().isoformat(),
            }
    
    save_signal_log(prev_log)
    save_history_log(history)
    
    # 生成報告
    report = format_report(results)
    print('\n' + report)
    
    return results


def run_loop(interval=300):
    """持續監控"""
    print(f'🚀 啟動實盤監控（每 {interval} 秒更新）')
    print(f'   監控幣種: {", ".join(c["name"] for c in WATCHLIST)}')
    print(f'   出場策略: 波動率自適應 TP/SL + 趨勢追蹤止損')
    print()
    
    while True:
        try:
            run_once()
            print(f'\n⏳ 下次更新: {interval} 秒後...')
            time.sleep(interval)
        except KeyboardInterrupt:
            print('\n\n👋 監控結束')
            break
        except Exception as e:
            print(f'\n⚠️ 錯誤: {e}')
            time.sleep(60)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='實盤監控系統')
    parser.add_argument('--interval', type=int, default=300, help='更新間隔（秒）')
    parser.add_argument('--once', action='store_true', help='只跑一次')
    args = parser.parse_args()
    
    if args.once:
        run_once()
    else:
        run_loop(args.interval)
