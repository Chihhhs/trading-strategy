"""
binance_api.py - Binance API 封裝
位置: ~/.hermes/scripts/trading_lib/
"""
import json, urllib.request, urllib.error


def get_klines(symbol, interval="4h", limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return [{"t": k[0], "o": float(k[1]), "h": float(k[2]),
                 "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in data]
    except:
        return []


def get_funding_rate(symbol="BTCUSDT"):
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return float(json.loads(resp.read())["lastFundingRate"]) * 100
    except:
        return 0


def get_fear_greed_index():
    try:
        req = urllib.request.Request("https://api.alternative.me/fng/?limit=1")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return int(json.loads(resp.read())["data"][0]["value"])
    except:
        return 50


def get_dxy():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?interval=1d&range=1mo"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())["chart"]["result"][0]["indicators"]["quote"]["close"][-1]
    except:
        return 103


def get_btc_dominance():
    try:
        req = urllib.request.Request("https://api.coingecko.com/api/v3/global")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())["data"]["market_cap_percentage"]["btc"]
    except:
        return 50
