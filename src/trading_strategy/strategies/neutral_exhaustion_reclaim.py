"""State-only neutral-zone downside exhaustion reclaim strategy."""

from .base import BaseStrategy, StrategyContext, StrategySignal
from .trend_pullback_reclaim import _atr, _value


class NeutralExhaustionReclaimStrategy(BaseStrategy):
    name = "neutral_exhaustion_reclaim"

    def _state(self, context):
        window = list(context.window or [])
        lookback = int(_value(context.config, "pullback_lookback", 12))
        trend_lookback = int(_value(context.config, "trend_lookback", 42))
        if len(window) <= max(lookback, trend_lookback):
            return None
        closes = [float(bar["close"]) for bar in window]
        current = closes[-1]
        previous = closes[-2]
        trend = current / closes[-trend_lookback - 1] - 1.0
        short_return = current / closes[-lookback - 1] - 1.0
        return {
            "current": current,
            "previous": previous,
            "trend": trend,
            "short_return": short_return,
            "entry_drawdown": float(_value(context.config, "entry_drawdown", 0.02)),
            "maximum_abs_trend": float(_value(context.config, "maximum_abs_trend", 0.10)),
            "exit_recovery": float(_value(context.config, "exit_recovery", 0.01)),
            "funding_rate": float((window[-1].get("funding_rate") or window[-1].get("funding") or 0.0)),
            "maximum_entry_funding_payment": float(
                _value(context.config, "maximum_entry_funding_payment", 0.0000125)
            ),
            "atr": _atr(window, int(_value(context.config, "atr_period", 14))),
        }

    def generate_signal(self, context: StrategyContext):
        state = self._state(context)
        if state is None or abs(state["trend"]) > state["maximum_abs_trend"]:
            return None
        if state["short_return"] > -state["entry_drawdown"] or state["current"] <= state["previous"]:
            return None
        if state["funding_rate"] > state["maximum_entry_funding_payment"]:
            return None
        atr_value = state["atr"] or state["current"] * 0.01
        return StrategySignal(
            direction="long",
            tp=None,
            sl=state["current"] - atr_value * float(_value(context.config, "stop_atr_multiple", 3.0)),
            score=1.0,
            reason="NEUTRAL_EXHAUSTION_RECLAIM",
            raw=state,
        )

    def build_exit_policy(self, *, signal=None, position=None):
        return {
            "name": "state_exit_with_protective_sl",
            "requires_tp": False,
            "requires_sl": True,
            "protection_event_prefix": "state_exit",
        }

    def evaluate_open_position(self, position, context: StrategyContext):
        state = self._state(context)
        if state is None:
            return {"exit_reason": None}
        if abs(state["trend"]) > state["maximum_abs_trend"]:
            return {"exit_reason": "NEUTRAL_REGIME_EXIT"}
        if state["short_return"] >= state["exit_recovery"]:
            return {"exit_reason": "PULLBACK_RECOVERED"}
        return {"exit_reason": None}


__all__ = ["NeutralExhaustionReclaimStrategy"]
