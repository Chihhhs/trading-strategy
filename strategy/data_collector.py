#!/usr/bin/env python3
"""
data_collector.py - 收集即時市場價格，存為歷史數據供回測使用
位置: strategy/

功能：
1. 定期收集所有 WATCHLIST 幣種的即時價格
2. 存為 JSON 格式的歷史數據
3. 可作為 parameter_sweep.py 的回測數據源

使用方法：
  python3 data_collector.py              # 收集一次
  python3 data_collector.py --loop       # 每 4 小時收集一次
  python3 data_collector.py --show       # 顯示已收集的數據狀態
"""
import sys, os, json, time
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__))

from live_monitor import WATCHLIST, get_binance_klines

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data', 'historical_prices')
os.makedirs(DATA_DIR, exist_ok=True)

def collect_once():
    """收集一次所有幣種的即時價格"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    date_tag = datetime.now().strftime('%Y%m%d')
    
    prices = {}
    for coin in WATCHLIST:
        try:
            data = get_binance_klines(coin['symbol'], limit=5)
            if data and len(data) > 0:
                latest = data[-1]
                prices[coin['name']] = {
                    'symbol': coin['symbol'],
                    'price': latest['close'],
                    'high': latest['high'],
                    'low': latest['low'],
                    'open': latest['open'],
                    'volume': latest['volume'],
                    'timestamp': timestamp,
                }
        except Exception as e:
            print(f"  ⚠️ {coin['name']} 失敗: {e}")
    
    # 按日期存檔
    filename = f"prices_{date_tag}.json"
    filepath = os.path.join(DATA_DIR, filename)
    
    # 如果檔案已存在，合併數據
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            existing = json.load(f)
        existing['data'].append({'time': timestamp, 'prices': prices})
    else:
        existing = {
            'date': date_tag,
            'created': timestamp,
            'coins': [c['name'] for c in WATCHLIST],
            'data': [{'time': timestamp, 'prices': prices}],
        }
    
    with open(filepath, 'w') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    print(f"✅ {timestamp} | 收集 {len(prices)} 個幣種 | 存至 {filename}")
    return prices

def show_status():
    """顯示已收集的數據狀態"""
    files = sorted([f for f in os.listdir(DATA_DIR) if f.startswith('prices_') and f.endswith('.json')])
    
    if not files:
        print("❌ 尚無數據")
        return
    
    print(f"📊 已收集 {len(files)} 天的數據:")
    print(f"{'日期':<12} {'記錄數':>6} {'幣種數':>6} {'最新時間'}")
    print(f"{'─' * 12} {'─' * 6} {'─' * 6} {'─' * 20}")
    
    for f in files:
        filepath = os.path.join(DATA_DIR, f)
        try:
            with open(filepath, 'r') as fh:
                data = json.load(fh)
            date = data.get('date', f.replace('prices_', '').replace('.json', ''))
            records = len(data.get('data', []))
            coins = len(data.get('coins', []))
            latest = data['data'][-1]['time'] if data.get('data') else '-'
            print(f"{date:<12} {records:>6} {coins:>6} {latest}")
        except:
            print(f"{f:<12} (讀取失敗)")
    
    # 顯示最新價格
    latest_file = os.path.join(DATA_DIR, files[-1])
    with open(latest_file, 'r') as f:
        data = json.load(f)
    if data.get('data'):
        print(f"\n📈 最新價格 ({data['data'][-1]['time']}):")
        prices = data['data'][-1]['prices']
        for coin, info in sorted(prices.items()):
            print(f"  {coin:<8} ${info['price']:>12,.2f} | Vol: {info['volume']:>15,.0f}")

def loop_collect(interval_hours=4):
    """持續收集"""
    print(f"🔄 開始收集（每 {interval_hours} 小時），按 Ctrl+C 停止")
    while True:
        try:
            collect_once()
            print(f"  下次收集: {interval_hours} 小時後")
            time.sleep(interval_hours * 3600)
        except KeyboardInterrupt:
            print("\n⏹️ 停止收集")
            break

if __name__ == '__main__':
    args = sys.argv[1:]
    
    if '--show' in args:
        show_status()
    elif '--loop' in args:
        interval = 4
        for i, a in enumerate(args):
            if a == '--interval' and i + 1 < len(args):
                interval = int(args[i + 1])
        loop_collect(interval)
    else:
        collect_once()
