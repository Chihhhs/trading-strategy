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
        _HL_CLIENT_ERROR = "missing hyperliquid-python-sdk"
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
        _HL_CLIENT_ERROR = "missing HL_PRIVATE_KEY"
        return None
    if Account is None or Exchange is None:
        _HL_CLIENT_ERROR = "missing hyperliquid-python-sdk"
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
        result = {
            "perp": client.user_state(address),
            "spot": client.spot_user_state(address),
            "abstraction": client.query_user_abstraction_state(address),
            "dex_abstraction": client.query_user_dex_abstraction_state(address),
        }
        debug_api_log(
            "hl_balance_sdk",
            {
                "request_user": address,
                "response_keys": sorted(result.keys()),
                "account_values": extract_hl_account_values(result),
                "client_error": _HL_CLIENT_ERROR,
                "raw_response": result,
            },
        )
        return result
    except Exception as exc:
        debug_api_log("hl_balance_sdk_error", {"error": str(exc)})
        return api_post(f"{config.get_api_url()}/info", {"type": "clearinghouseState", "user": address})


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_hl_perp_account_value(balance_info):
    if not isinstance(balance_info, dict):
        return None
    perp_info = balance_info.get("perp") if any(
        key in balance_info for key in ("perp", "spot", "abstraction", "dex_abstraction")
    ) else balance_info
    if not isinstance(perp_info, dict):
        return None
    candidates = [
        perp_info.get("accountValue"),
        (perp_info.get("marginSummary") or {}).get("accountValue"),
        (perp_info.get("crossMarginSummary") or {}).get("accountValue"),
        perp_info.get("withdrawable"),
        perp_info.get("equity"),
        perp_info.get("balance"),
    ]
    for candidate in candidates:
        numeric = _safe_float(candidate)
        if numeric is not None:
            return numeric
    return None


def extract_hl_spot_account_value(balance_info):
    if not isinstance(balance_info, dict):
        return None
    spot_info = balance_info.get("spot") if any(
        key in balance_info for key in ("perp", "spot", "abstraction", "dex_abstraction")
    ) else None
    if not isinstance(spot_info, dict):
        return None
    token_rows = spot_info.get("tokenToAvailableAfterMaintenance") or []
    for row in token_rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            numeric = _safe_float(row[1])
            if numeric is not None:
                return numeric
    for item in spot_info.get("balances", []):
        if not isinstance(item, dict):
            continue
        if item.get("coin") not in ("USDC", "USDT", "USDT0"):
            continue
        numeric = _safe_float(item.get("total"))
        if numeric is not None:
            return numeric
    return None


def extract_hl_account_values(balance_info):
    perp_value = extract_hl_perp_account_value(balance_info)
    spot_value = extract_hl_spot_account_value(balance_info)
    effective_balance = perp_value if perp_value is not None else spot_value
    if perp_value is not None:
        balance_source = "hyperliquid_perp"
    elif spot_value is not None:
        balance_source = "hyperliquid_spot"
    else:
        balance_source = "local_state"
    return {
        "perp_account_value": perp_value,
        "spot_account_value": spot_value,
        "effective_balance": effective_balance,
        "balance_source": balance_source,
    }


def extract_hl_account_value(balance_info):
    return extract_hl_account_values(balance_info)["effective_balance"]


def sync_state_with_hl_balance(state):
    from .engine.reconcile import sync_state_with_exchange_positions

    balance_info = get_hl_balance()
    account_values = extract_hl_account_values(balance_info)
    account_value = account_values["effective_balance"]
    state["_hl_balance_info"] = balance_info
    state["_balance_source"] = account_values["balance_source"]
    state["_perp_account_value"] = account_values["perp_account_value"]
    state["_spot_account_value"] = account_values["spot_account_value"]
    if account_value is not None:
        state["balance"] = account_value
    if is_probably_api_wallet_mode():
        state["_balance_warning"] = "Set HL_ACCOUNT_ADDRESS to the tradable main account."
    elif account_values["perp_account_value"] is not None and account_values["perp_account_value"] <= 0:
        state["_balance_warning"] = "Hyperliquid perp tradable balance is 0. Fund perp margin first."
    else:
        state.pop("_balance_warning", None)
    return sync_state_with_exchange_positions(
        state,
        (balance_info or {}).get("perp"),
        get_hl_frontend_open_orders(),
    )
