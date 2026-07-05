from .types import BacktestConfig


def build_backtesting_adapter(config: BacktestConfig):
    return {
        "runtime": "backtesting",
        "strategy": config.strategy,
        "supported": False,
        "message": "Adapter scaffold only; direct backtesting runtime is not implemented yet.",
    }
