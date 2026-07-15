"""Read-only experiment result exports for research tooling."""

from pathlib import Path
import json


def build_research_export(result, trades):
    """Return normalized rows without recalculating PnL, costs, or drawdown."""
    metadata = result.to_dict()
    metadata.pop("config_diff", None)
    trade_rows = []
    for trade in trades:
        trade_rows.append(
            {
                "coin": trade.get("coin"),
                "direction": trade.get("direction"),
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "entry": trade.get("entry"),
                "exit": trade.get("exit_price", trade.get("exit")),
                "size": trade.get("size"),
                "pnl": trade.get("pnl"),
                "pnl_pct": trade.get("pnl_pct"),
                "cost": trade.get("cost"),
                "exit_reason": trade.get("exit_reason"),
                "hold_bars": trade.get("hold_bars"),
            }
        )
    return {"schema_version": 1, "result": metadata, "trades": trade_rows}


def write_research_export(path, result, trades):
    """Write an immutable-style JSON artifact; callers own path selection."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_research_export(result, trades)
    target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    return target
