"""Experiment adapter surface for overlapping cross-sectional momentum."""

from dataclasses import replace
from datetime import datetime, timezone

from .independent_lab import Candidate, _aligned_closes, evaluate


class OverlappingMomentumBacktester:
    def __init__(self, *, fee_bps, slippage_bps, parameters, funding_data=None):
        self.one_way_cost_bps = float(fee_bps) + float(slippage_bps)
        self.funding_data = funding_data
        self.rebalance_hour_utc = int(parameters.rebalance_hour_utc)
        if self.rebalance_hour_utc not in range(0, 24, 4):
            raise ValueError("rebalance_hour_utc must match a 4h UTC candle")
        self.candidate = Candidate(
            name="cross-sectional-momentum",
            family="overlapping_momentum_long_short",
            lookback=int(parameters.lookback_bars),
            rebalance_days=int(parameters.rebalance_bars),
            top_n=int(parameters.top_n),
            overlap_cohorts=int(parameters.overlap_cohorts),
            cohort_spacing=int(parameters.cohort_spacing_bars),
        )

    def run(self, data, *, max_bars):
        timestamps = _aligned_closes(data)[0]
        total = len(timestamps)
        start_index = total - int(max_bars)
        while start_index < total - 1:
            signal_hour = datetime.fromtimestamp(timestamps[start_index - 1] / 1000, timezone.utc).hour
            if signal_hour == self.rebalance_hour_utc:
                break
            start_index += 1
        return evaluate(
            replace(self.candidate, carry_bps_per_day=0.0),
            data,
            start_index=start_index,
            end_index=total,
            one_way_cost_bps=self.one_way_cost_bps,
            periods_per_year=2190.0,
            bars_per_day=6.0,
            funding_data=self.funding_data,
        )


__all__ = ["OverlappingMomentumBacktester"]
