from datetime import datetime, timedelta


def calc_position_size(balance, entry, sl, leverage, risk_pct):
    risk_amount = balance * risk_pct
    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return 0

    size = risk_amount / sl_distance
    notional = size * entry
    margin = notional / leverage
    max_margin = balance * 0.95
    if margin > max_margin:
        size = (max_margin * leverage) / entry
    return size


def check_circuit_breaker(state, circuit):
    today = datetime.now().strftime("%Y-%m-%d")
    today_pnl = sum(
        h.get("pnl", 0)
        for h in state.get("history", [])
        if h.get("exit_time", "").startswith(today)
    )
    if today_pnl < -state["balance"] * circuit["max_daily_loss_pct"] / 100:
        return False, "daily_loss"

    recent_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [
        h for h in state.get("history", []) if h.get("exit_time", "") >= recent_cutoff
    ]
    cons = sum(1 for h in reversed(recent) if h.get("pnl", 0) < 0)
    if cons >= circuit["max_consecutive_losses"]:
        return False, "consecutive_losses"

    return True, ""


def is_cooldown(state, coin, circuit):
    cutoff = datetime.now() - timedelta(hours=circuit["cooldown_hours"])
    for h in reversed(state.get("history", [])):
        if h.get("coin") != coin:
            continue
        try:
            if datetime.fromisoformat(h.get("exit_time", "")) > cutoff:
                return True
        except Exception:
            pass
        break
    return False
