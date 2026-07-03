import json
import urllib.request


WATCHLIST = [
    {"name": "BTC", "symbol": "BTCUSDT"},
    {"name": "ETH", "symbol": "ETHUSDT"},
    {"name": "SOL", "symbol": "SOLUSDT"},
    {"name": "BNB", "symbol": "BNBUSDT"},
    {"name": "AVAX", "symbol": "AVAXUSDT"},
    {"name": "XRP", "symbol": "XRPUSDT"},
    {"name": "NEAR", "symbol": "NEARUSDT"},
    {"name": "WLD", "symbol": "WLDUSDT"},
    {"name": "ZEC", "symbol": "ZECUSDT"},
]


def get_binance_klines(symbol, interval="1d", limit=90):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    return [
        {
            "ts": d[0],
            "open": float(d[1]),
            "high": float(d[2]),
            "low": float(d[3]),
            "close": float(d[4]),
            "volume": float(d[5]),
        }
        for d in data
    ]


def get_current_prices(watchlist=WATCHLIST):
    prices = {}
    for coin in watchlist:
        data = get_binance_klines(coin["symbol"], limit=5)
        if data:
            prices[coin["name"]] = data[-1]["close"]
    return prices
