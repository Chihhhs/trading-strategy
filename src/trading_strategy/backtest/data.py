import json
import os


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
DATA_PATH = os.path.join(PROJECT_ROOT, "data", "historical_prices", "1000d_50coins.json")
DEFAULT_COINS = ("BTC", "ETH", "SOL", "BNB")


def load_historical_data(path=DATA_PATH, *, max_days=None):
    with open(path, "r", encoding="utf-8") as handle:
        data_map = json.load(handle)
    return normalize_data_map(data_map, max_days=max_days)


def normalize_data_map(data_map, *, max_days=None):
    normalized = {}
    for coin, bars in (data_map or {}).items():
        if not isinstance(bars, list):
            continue
        usable = bars[-max_days:] if max_days is not None else list(bars)
        normalized[str(coin).upper()] = usable
    return normalized


def get_coin_series(data_map, coin, *, max_days=None):
    bars = list((data_map or {}).get(str(coin).upper(), []))
    if max_days is not None:
        bars = bars[-max_days:]
    return bars
