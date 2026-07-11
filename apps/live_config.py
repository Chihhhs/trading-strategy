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
STRATEGY_OVERRIDES = {
    # "name": "intraday_momentum",
    "coin_universe": ["BTC", "ETH", "BNB"],
    # "timeframe": "15m",
    # "leverage": 5,
    # "risk_per_trade": 0.08,
    "max_positions": 2,
    # "max_hold_days": 30,
    # "min_score": 3,
    # "tp_mult": 1.5,
    # "sl_mult": 1.0,
    # "entry_order_type": "ioc",
    "derivatives_crowding_exit_enabled": True,
    "derivatives_crowding_action": "reduce",
    "derivatives_crowding_reduce_fraction": 0.75,
    "microstructure_guard_enabled": True,
    "microstructure_guard_observe_only": True,
    "microstructure_max_spread_bps": 8.0,
    "microstructure_min_top_depth_usd": 1000.0,
    "microstructure_max_opposing_imbalance": 0.65,
    # "intraday_breakout_lookback": 12,
    # "intraday_max_hold_bars": 24,
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
    live_config_module.CIRCUIT.update(
        {key: value for key, value in CIRCUIT_OVERRIDES.items() if value is not None}
    )
