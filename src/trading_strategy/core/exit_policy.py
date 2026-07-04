"""Reusable exit-policy helpers for strategy variants."""


def _normalize_reason(value):
    return str(value or "").strip().upper()


def _is_trend_reason(reason):
    return _normalize_reason(reason).startswith("TREND_")


def build_exit_policy(*, signal=None, position=None):
    if isinstance(position, dict) and isinstance(position.get("exit_policy"), dict):
        return dict(position["exit_policy"])

    reason = ""
    if isinstance(signal, dict):
        reason = signal.get("reason", "")
    elif isinstance(position, dict):
        reason = position.get("sig") or position.get("signal_reason") or ""

    if _is_trend_reason(reason):
        return {
            "name": "trend_sl_only",
            "requires_tp": False,
            "requires_sl": True,
            "protection_event_prefix": "sl",
        }

    return {
        "name": "fixed_tpsl",
        "requires_tp": True,
        "requires_sl": True,
        "protection_event_prefix": "tpsl",
    }


__all__ = ["build_exit_policy"]
