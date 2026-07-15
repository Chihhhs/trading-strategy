"""Pure, observe-only entry-decision records for the live runtime."""

from dataclasses import asdict, dataclass, field

from trading_strategy.market_context import MarketContextDetector, entry_decision
from trading_strategy.strategies.base import signal_value


@dataclass(frozen=True)
class Decision:
    allowed: bool
    action: str
    reason_codes: tuple[str, ...] = ()
    signal_context: dict = field(default_factory=dict)
    btc_regime: str | None = None
    market_context: dict | None = None
    safety_blockers: tuple[str, ...] = ()

    def to_dict(self):
        return asdict(self)


def observe_market_context(coin, window, signal, strategy_config):
    """Classify completed bars only; callers must not use this to gate entries."""
    if not window:
        return None
    context = MarketContextDetector(strategy_config).observe(coin, window)
    hypothetical = entry_decision(signal_value(signal, "direction"), context)
    payload = context.to_dict()
    payload["hypothetical_allowed"] = hypothetical["allowed"]
    payload["hypothetical_reason"] = hypothetical["reason"]
    return payload


def build_decision(*, allowed, action, reason_codes=(), signal=None, btc_regime=None, market_context=None):
    reasons = tuple(str(reason) for reason in reason_codes if reason)
    signal_context = {
        "direction": signal_value(signal, "direction"),
        "score": signal_value(signal, "score"),
        "reason": signal_value(signal, "reason"),
    }
    return Decision(
        allowed=bool(allowed),
        action=str(action),
        reason_codes=reasons,
        signal_context=signal_context,
        btc_regime=btc_regime,
        market_context=market_context,
        safety_blockers=reasons if not allowed else (),
    )
