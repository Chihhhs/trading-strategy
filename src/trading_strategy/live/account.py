import json

from . import config
from .io import api_post, debug_api_log

try:
    from eth_account import Account
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
except ImportError:
    Account = None
    Exchange = None
    Info = None


_HL_INFO_CLIENT = None
_HL_EXCHANGE_CLIENT = None
_HL_CLIENT_ERROR = None
_HL_PERP_META = None


def get_api_wallet_address():
    if not config.get_private_key() or Account is None:
        return None
    try:
        return Account.from_key(config.get_private_key()).address
    except Exception:
        return None


def get_hl_account_address():
    if config.get_account_address():
        return config.get_account_address()
    if config.get_private_key() and Account is not None:
        try:
            return Account.from_key(config.get_private_key()).address
        except Exception:
            return None
    return None


def is_probably_api_wallet_mode():
    return bool(config.get_private_key()) and not bool(config.get_account_address())


def get_hl_info_client():
    global _HL_INFO_CLIENT, _HL_CLIENT_ERROR
    if _HL_INFO_CLIENT is not None:
        return _HL_INFO_CLIENT
    if Info is None:
        _HL_CLIENT_ERROR = "未安裝 hyperliquid-python-sdk"
        return None
    try:
        _HL_INFO_CLIENT = Info(config.get_api_url(), skip_ws=True)
        return _HL_INFO_CLIENT
    except Exception as exc:
        _HL_CLIENT_ERROR = str(exc)
        return None


def get_hl_client_error():
    return _HL_CLIENT_ERROR


def get_hl_exchange_client():
    global _HL_EXCHANGE_CLIENT, _HL_CLIENT_ERROR
    if _HL_EXCHANGE_CLIENT is not None:
        return _HL_EXCHANGE_CLIENT
    if not config.get_private_key():
        _HL_CLIENT_ERROR = "未設定私鑰"
        return None
    if Account is None or Exchange is None:
        _HL_CLIENT_ERROR = "未安裝 hyperliquid-python-sdk"
        return None
    try:
        wallet = Account.from_key(config.get_private_key())
        _HL_EXCHANGE_CLIENT = Exchange(
            wallet,
            base_url=config.get_api_url(),
            account_address=config.get_account_address() or wallet.address,
        )
        return _HL_EXCHANGE_CLIENT
    except Exception as exc:
        _HL_CLIENT_ERROR = str(exc)
        return None


def get_hl_perp_meta():
    global _HL_PERP_META
    if _HL_PERP_META is not None:
        return _HL_PERP_META
    client = get_hl_info_client()
    if client is not None:
        try:
            _HL_PERP_META = client.meta()
            return _HL_PERP_META
        except Exception:
            pass
    data = api_post(f"{config.get_api_url()}/info", {"type": "meta"})
    if isinstance(data, dict):
        _HL_PERP_META = data
    return _HL_PERP_META


def get_hl_size_decimals(coin):
    meta = get_hl_perp_meta()
    if not isinstance(meta, dict):
        return None
    for item in meta.get("universe", []):
        if isinstance(item, dict) and item.get("name") == coin:
            value = item.get("szDecimals")
            return int(value) if value is not None else None
    return None


def get_hl_perp_user_state():
    address = get_hl_account_address()
    client = get_hl_info_client()
    if not address or client is None:
        return None
    try:
        return client.user_state(address)
    except Exception:
        return None


def get_hl_frontend_open_orders():
    address = get_hl_account_address()
    client = get_hl_info_client()
    if not address or client is None:
        return []
    try:
        result = client.frontend_open_orders(address)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def get_hl_balance():
    address = get_hl_account_address()
    if not address:
        debug_api_log("hl_balance_skipped", {"reason": "no_account_address"})
        return None
    client = get_hl_info_client()
    if client is None:
        return {
            "perp": api_post(f"{config.get_api_url()}/info", {"type": "clearinghouseState", "user": address}),
            "spot": api_post(f"{config.get_api_url()}/info", {"type": "spotClearinghouseState", "user": address}),
            "abstraction": api_post(f"{config.get_api_url()}/info", {"type": "userAbstraction", "user": address}),
            "dex_abstraction": api_post(f"{config.get_api_url()}/info", {"type": "userDexAbstraction", "user": address}),
        }
    try:
        return {
            "perp": client.user_state(address),
            "spot": client.spot_user_state(address),
            "abstraction": client.query_user_abstraction_state(address),
            "dex_abstraction": client.query_user_dex_abstraction_state(address),
        }
    except Exception as exc:
        debug_api_log("hl_balance_sdk_error", {"error": str(exc)})
        return api_post(f"{config.get_api_url()}/info", {"type": "clearinghouseState", "user": address})


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_hl_account_value(balance_info):
    if not isinstance(balance_info, dict):
        return None
    if any(key in balance_info for key in ("perp", "spot", "abstraction", "dex_abstraction")):
        return extract_hl_account_value(balance_info.get("perp"))
    candidates = [
        balance_info.get("accountValue"),
        (balance_info.get("marginSummary") or {}).get("accountValue"),
        (balance_info.get("crossMarginSummary") or {}).get("accountValue"),
        balance_info.get("withdrawable"),
        balance_info.get("equity"),
        balance_info.get("balance"),
    ]
    for candidate in candidates:
        numeric = _safe_float(candidate)
        if numeric is not None:
            return numeric
    return None


def sync_state_with_hl_balance(state):
    from .engine import sync_state_with_exchange_positions

    balance_info = get_hl_balance()
    account_value = extract_hl_account_value(balance_info)
    state["_hl_balance_info"] = balance_info
    state["_balance_source"] = "hyperliquid" if account_value is not None else "local_state"
    if account_value is not None:
        state["balance"] = account_value
    if is_probably_api_wallet_mode():
        state["_balance_warning"] = "請設定 HL_ACCOUNT_ADDRESS 指向主帳戶。"
    else:
        state.pop("_balance_warning", None)
    return sync_state_with_exchange_positions(
        state,
        (balance_info or {}).get("perp"),
        get_hl_frontend_open_orders(),
    )
