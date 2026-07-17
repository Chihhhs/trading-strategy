#!/usr/bin/env python3
"""App-side live strategy overrides.

Edit this file when you want to tweak live config from `apps/`
without touching the canonical implementation in `src/`.
"""

# Environment overrides applied before running the live entrypoint.
# Use strings for env values. Set to None to skip.
ENV_OVERRIDES = {
    "MARKET_DATA_SOURCE": "auto",
    "DEBUG_API": "0",
    # "HL_API_URL": "https://api.hyperliquid.xyz",
}

# Strategy overrides merged into trading_strategy.live.config.STRATEGY
LIVE_UNIVERSE = (
    # Historical Hyperliquid-active members retained from the former 50-coin reference.
    "BTC", "ETH", "BNB", "NEO", "LTC", "ADA", "XRP", "IOTA", "XLM", "TRX",
    "ETC", "LINK", "FET", "ZEC", "DASH", "ATOM", "ALGO", "DOGE", "HBAR", "STX",
    # Fixed 2026-07-16 market-cap leaders that are active Hyperliquid perps.
    "SOL", "HYPE", "XMR", "CC", "BCH", "SUI", "AVAX", "NEAR", "UNI", "TAO",
    "PAXG", "WLFI", "ASTER", "ONDO", "AAVE", "SKY", "DOT", "WLD"
)

STRATEGY_OVERRIDES = {
    # "name": "intraday_momentum",
    "coin_universe": list(LIVE_UNIVERSE),
    # "timeframe": "15m",
    # "leverage": 5,
    # "risk_per_trade": 0.08,
    # "max_hold_days": 30,
    # "min_score": 3,
    # "tp_mult": 1.5,
    # "sl_mult": 1.0,
    # "entry_order_type": "ioc",
    "derivatives_crowding_exit_enabled": True,
    "derivatives_crowding_action": "reduce",
    "derivatives_crowding_reduce_fraction": 0.75,
    "derivatives_monitor_enabled": True,
    # Paper-only research: capture full entry context until 30 trend signals accrue.
    "signal_observation_enabled": True,
    "signal_observation_min_samples": 30,
    "signal_observation_horizons": (1, 3, 6),
    "microstructure_guard_enabled": True,
    "microstructure_guard_observe_only": True,
    "microstructure_max_spread_bps": 8.0,
    "microstructure_min_top_depth_usd": 1000.0,
    "microstructure_max_opposing_imbalance": 0.65,
    # "intraday_breakout_lookback": 12,
    # "intraday_max_hold_bars": 24,
}

MODE_STRATEGY_OVERRIDES = {
    "paper": {"max_positions": 10, "coin_universe": None, "paper_execution_enabled": False},
    "live": {"max_positions": 2, "coin_universe": list(LIVE_UNIVERSE)},
}

PAPER_PROFILE_STRATEGY_OVERRIDES = {
    "collector": {"coin_universe": None, "paper_execution_enabled": False},
    "observer": {"coin_universe": None, "paper_execution_enabled": False},
    "execution": {
        "coin_universe": list(LIVE_UNIVERSE),
        "max_positions": 2,
        "paper_execution_enabled": True,
    },
}

# Circuit-breaker overrides merged into trading_strategy.live.config.CIRCUIT
CIRCUIT_OVERRIDES = {
    # "max_daily_loss_pct": 15.0,
    # "max_consecutive_losses": 5,
    # "cooldown_hours": 24,
}


def apply_overrides(live_config_module):
    for key, value in ENV_OVERRIDES.items():
        if value is None:
            continue
        import os

        os.environ[key] = str(value)

    live_config_module.STRATEGY.update(
        {key: value for key, value in STRATEGY_OVERRIDES.items() if value is not None}
    )
    live_config_module.MODE_STRATEGY_OVERRIDES.update(MODE_STRATEGY_OVERRIDES)
    live_config_module.PAPER_PROFILE_STRATEGY_OVERRIDES.update(PAPER_PROFILE_STRATEGY_OVERRIDES)
    live_config_module.set_mode(live_config_module.MODE)
    live_config_module.CIRCUIT.update(
        {key: value for key, value in CIRCUIT_OVERRIDES.items() if value is not None}
    )
