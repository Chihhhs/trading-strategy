import os
from datetime import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
LIVE_STATE_DIR = os.path.join(PROJECT_ROOT, "data", "paper_strategies_live")
PAPER_STATE_DIR = os.path.join(PROJECT_ROOT, "data", "paper_strategies_live_paper")
STATE_DIR = LIVE_STATE_DIR
HL_API_LOG_DIR = os.path.join(PROJECT_ROOT, "data", "hl_api")
TRADE_HISTORY_DIR = os.path.join(PROJECT_ROOT, "data", "trade_history")
BINANCE_API = "https://api.binance.com"
BINANCE_FUTURES_API = "https://fapi.binance.com"
BYBIT_API = "https://api.bybit.com"

MODE = "paper"

STRATEGY = {
    "name": "trend",
    "coin_universe": None,
    "timeframe": "1d",
    "leverage": 5,
    "risk_per_trade": 0.08,
    "max_positions": 3,
    "max_hold_days": 30,
    "min_score": 3,
    "tp_mult": 1.5,
    "sl_mult": 1.0,
    "entry_order_type": "ioc",
    "atr_trailing_enabled": False,
    "atr_activation_r": 1.5,
    "atr_trailing_mult": 2.0,
    "adaptive_atr_trailing_enabled": False,
    "adaptive_atr_strong_adx": 35.0,
    "adaptive_atr_strong_mult": 3.0,
    "adaptive_atr_weak_mult": 1.5,
    "failure_exit_enabled": False,
    "failure_exit_bars": 3,
    "failure_exit_mode": "breakout_failure",
    "trend_entry_filter_enabled": True,
    "trend_rsi_min_long": 45.0,
    "trend_rsi_max_long": 75.0,
    "trend_rsi_min_short": 30.0,
    "trend_rsi_max_short": 55.0,
    "trend_max_atr_pct": 8.0,
    "trend_price_position_lookback": 60,
    "trend_long_max_price_position": 0.85,
    "trend_short_min_price_position": 0.25,
    "trend_max_roc_60_long": 120.0,
    "trend_min_roc_60_short": -120.0,
    "derivatives_crowding_exit_enabled": False,
    "derivatives_crowding_action": "reduce",
    "derivatives_crowding_reduce_fraction": 0.75,
    "derivatives_crowding_funding_z_lookback": 30,
    "derivatives_crowding_funding_z_threshold": 0.75,
    "derivatives_crowding_basis_abs_threshold_pct": 0.03,
    "derivatives_monitor_enabled": False,
    "signal_observation_enabled": False,
    "signal_observation_min_samples": 30,
    "signal_observation_horizons": (1, 3, 6),
    "microstructure_guard_enabled": False,
    "microstructure_guard_observe_only": False,
    "microstructure_max_spread_bps": 8.0,
    "microstructure_min_top_depth_usd": 1000.0,
    "microstructure_max_opposing_imbalance": 0.65,
    "intraday_breakout_lookback": 12,
    "intraday_fast_ema": 8,
    "intraday_slow_ema": 21,
    "intraday_max_hold_bars": 24,
    "intraday_momentum_threshold_pct": 0.2,
    "intraday_volume_ratio": 1.2,
}

CIRCUIT = {
    "max_daily_loss_pct": 15.0,
    "max_consecutive_losses": 5,
    "cooldown_hours": 24,
}

os.makedirs(LIVE_STATE_DIR, exist_ok=True)
os.makedirs(PAPER_STATE_DIR, exist_ok=True)
os.makedirs(HL_API_LOG_DIR, exist_ok=True)
os.makedirs(TRADE_HISTORY_DIR, exist_ok=True)


def get_env(name, default=""):
    return os.environ.get(name, default)


def _date_stamp(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%d")


def get_api_log_path(now=None):
    return os.path.join(HL_API_LOG_DIR, f"{_date_stamp(now)}.log")


def get_trade_log_path(now=None):
    return os.path.join(TRADE_HISTORY_DIR, f"{_date_stamp(now)}.jsonl")


def get_private_key():
    return get_env("HL_PRIVATE_KEY", "")


def get_account_address():
    return get_env("HL_ACCOUNT_ADDRESS", "") or get_env("HL_WALLET_ADDRESS", "")


def get_api_url():
    return get_env("HL_API_URL", "https://api.hyperliquid.xyz")


def get_market_data_source():
    source = get_env("MARKET_DATA_SOURCE", "auto").lower()
    if source in ("binance", "hyperliquid"):
        return source
    return "hyperliquid" if MODE == "live" else "binance"


def is_debug_api():
    return get_env("DEBUG_API", "").lower() in ("1", "true", "yes", "on")


def get_state_dir():
    return LIVE_STATE_DIR if MODE == "live" else PAPER_STATE_DIR


def set_mode(mode):
    global MODE
    MODE = mode
