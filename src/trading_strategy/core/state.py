import json
import os


def build_stats():
    return {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "total_pnl": 0.0,
        "max_win": 0.0,
        "max_loss": 0.0,
    }


def build_default_state(strategy, *, initial_balance=1000.0, strategy_name=None):
    state = {
        "balance": initial_balance,
        "positions": [],
        "history": [],
        "params": strategy,
        "stats": build_stats(),
        "_balance_source": "local_state",
    }
    if strategy_name is not None:
        state["strategy"] = strategy_name
    return state


def get_state_path(state_dir, name="live_state"):
    filename = name if name.endswith(".json") else f"{name}.json"
    return os.path.join(state_dir, filename)


def load_state(state_dir, strategy, *, name="live_state", initial_balance=1000.0):
    path = get_state_path(state_dir, name)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return build_default_state(
        strategy,
        initial_balance=initial_balance,
        strategy_name=None if name == "live_state" else name,
    )


def save_state(state_dir, state, io_lock=None, *, name="live_state"):
    path = get_state_path(state_dir, name)
    persistable = dict(state)
    persistable.pop("_hl_balance_info", None)
    persistable.pop("_balance_warning", None)
    persistable.pop("_data_cache", None)

    compact_positions = []
    for pos in persistable.get("positions", []):
        compact = dict(pos)
        order_meta = compact.get("order_meta")
        if isinstance(order_meta, dict):
            compact["order_meta"] = {
                "status": order_meta.get("status"),
                "resolved_price": order_meta.get("resolved_price"),
                "order_type": order_meta.get("order_type"),
                "size": order_meta.get("size"),
                "size_decimals": order_meta.get("size_decimals"),
                "order_summary": order_meta.get("order_summary"),
            }
        compact_positions.append(compact)
    persistable["positions"] = compact_positions

    tmp_path = path + ".tmp"
    if io_lock is None:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(persistable, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return

    with io_lock:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(persistable, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
