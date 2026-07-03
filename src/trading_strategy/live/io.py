import json
import threading
import urllib.request
from datetime import datetime

from trading_strategy.core.state import load_state as load_state_file
from trading_strategy.core.state import save_state as save_state_file

from . import config


_IO_LOCK = threading.RLock()


def api_get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def api_post(url, data):
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def hl_info_post(data):
    return api_post(f"{config.get_api_url()}/info", data)


def debug_api_log(event, payload):
    if not config.is_debug_api():
        return
    record = {"ts": datetime.now().isoformat(), "event": event, "payload": payload}
    try:
        with open(config.API_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def append_trade_record(record):
    try:
        with _IO_LOCK:
            with open(config.TRADE_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_state():
    return load_state_file(config.STATE_DIR, config.STRATEGY)


def save_state(state):
    save_state_file(config.STATE_DIR, state, _IO_LOCK)
