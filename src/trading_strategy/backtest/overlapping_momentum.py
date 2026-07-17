"""Experiment adapter surface for overlapping cross-sectional momentum."""

from dataclasses import replace
from datetime import datetime, timezone
import math
from statistics import mean, median, pstdev

from trading_strategy.paper_portfolio import PaperPortfolio, mark_portfolio, open_portfolio, rebalance_portfolio
from trading_strategy.strategies import build_execution_plan, overlapping_momentum_weights

from .independent_lab import Candidate, _aligned_closes, _aligned_funding, evaluate


def _canonical_start(timestamps, max_bars, rebalance_hour_utc):
    start_index = len(timestamps) - int(max_bars)
    while start_index < len(timestamps) - 1:
        signal_hour = datetime.fromtimestamp(timestamps[start_index - 1] / 1000, timezone.utc).hour
        if signal_hour == rebalance_hour_utc:
            return start_index
        start_index += 1
    raise ValueError("no canonical rebalance anchor in evaluation window")


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
        start_index = _canonical_start(timestamps, max_bars, self.rebalance_hour_utc)
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

    def run_fixed_unit_segment(
        self,
        data,
        *,
        start_index,
        end_index=None,
        initial_capital=1000.0,
        one_way_cost_bps=None,
        carry_bps_per_day=0.0,
        sz_decimals=None,
        min_notional=10.0,
    ):
        timestamps, closes = _aligned_closes(data)
        end_index = min(end_index or len(timestamps), len(timestamps))
        funding = _aligned_funding(timestamps, closes, self.funding_data)
        cost_bps = self.one_way_cost_bps if one_way_cost_bps is None else float(one_way_cost_bps)

        def prices_at(index):
            return {coin: values[index] for coin, values in closes.items()}

        def target_at(index):
            return overlapping_momentum_weights(
                closes,
                index=index,
                lookback_bars=self.candidate.lookback,
                top_n=self.candidate.top_n,
                overlap_cohorts=self.candidate.overlap_cohorts,
                cohort_spacing_bars=self.candidate.cohort_spacing,
            )

        initial_weights = target_at(start_index - 1)
        submitted_orders = 0
        skipped_small_orders = 0
        if sz_decimals is not None:
            plan = build_execution_plan(
                initial_weights,
                equity=initial_capital,
                prices=prices_at(start_index - 1),
                sz_decimals=sz_decimals,
                min_notional=min_notional,
            )
            submitted_orders += len(plan["orders"])
            skipped_small_orders += sum(row["reason"] == "below_minimum_notional" for row in plan["blockers"])
            initial_weights = {
                order["coin"]: order["target_size"] * prices_at(start_index - 1)[order["coin"]] / initial_capital
                for order in plan["orders"]
            }
        state = open_portfolio(
            timestamp=timestamps[start_index - 1],
            prices=prices_at(start_index - 1),
            target_weights=initial_weights,
            equity=initial_capital,
            one_way_cost_bps=cost_bps,
        )
        peak = state.equity
        max_drawdown = 0.0
        bar_returns = []
        stress_drag = 0.0
        for index in range(start_index, end_index):
            previous_equity = state.equity
            mark_portfolio(
                state,
                timestamp=timestamps[index],
                prices=prices_at(index),
                funding_rates={coin: values[index] for coin, values in funding.items()},
            )
            drag = (
                sum(abs(state.positions[coin] * state.prices[coin]) for coin in state.positions)
                * carry_bps_per_day
                / 6.0
                / 10_000.0
            )
            state.cash -= drag
            state.equity -= drag
            stress_drag += drag
            if (
                (index - start_index + 1) % self.candidate.rebalance_days == 0
                and index < end_index - 1
            ):
                target_weights = target_at(index)
                if sz_decimals is not None:
                    plan = build_execution_plan(
                        target_weights,
                        equity=state.equity,
                        prices=state.prices,
                        sz_decimals=sz_decimals,
                        min_notional=min_notional,
                        current_sizes=state.positions,
                    )
                    submitted_orders += len(plan["orders"])
                    skipped_small_orders += sum(
                        row["reason"] == "below_minimum_notional"
                        for row in plan["blockers"]
                    )
                    target_sizes = dict(state.positions)
                    target_sizes.update({order["coin"]: order["target_size"] for order in plan["orders"]})
                    target_weights = {
                        coin: target_sizes[coin] * state.prices[coin] / state.equity
                        for coin in target_sizes
                    }
                rebalance_portfolio(
                    state,
                    target_weights=target_weights,
                    one_way_cost_bps=cost_bps,
                )
            peak = max(peak, state.equity)
            max_drawdown = max(max_drawdown, (peak - state.equity) / peak * 100.0)
            bar_returns.append(state.equity / previous_equity - 1.0)
        volatility = pstdev(bar_returns) if len(bar_returns) > 1 else 0.0
        sharpe = mean(bar_returns) / volatility * math.sqrt(2190.0) if volatility else 0.0
        positive = [value for value in state.coin_pnl.values() if value > 0.0]
        return {
            "net_pnl_pct": (state.equity / initial_capital - 1.0) * 100.0,
            "max_drawdown_pct": max_drawdown,
            "sharpe": sharpe,
            "fees_paid": state.fees_paid,
            "funding_pnl": state.funding_pnl,
            "price_pnl": state.price_pnl,
            "stress_drag": stress_drag,
            "turnover": state.turnover_notional / initial_capital,
            "submitted_orders": submitted_orders,
            "skipped_small_orders": skipped_small_orders,
            "max_positive_contribution_share": max(positive) / sum(positive) if positive else 0.0,
            "coin_contributions": state.coin_pnl,
            "state": state.to_dict(),
        }

    def run_fixed_unit_replay(self, data, *, max_bars, initial_capital=1000.0):
        timestamps = _aligned_closes(data)[0]
        start_index = _canonical_start(timestamps, max_bars, self.rebalance_hour_utc)
        return self.run_fixed_unit_segment(
            data,
            start_index=start_index,
            end_index=len(timestamps),
            initial_capital=initial_capital,
        )

    def run_exchange_replay(self, data, *, max_bars, sz_decimals, initial_capital=1000.0, min_notional=10.0):
        timestamps = _aligned_closes(data)[0]
        start_index = _canonical_start(timestamps, max_bars, self.rebalance_hour_utc)
        return self.run_fixed_unit_segment(
            data,
            start_index=start_index,
            end_index=len(timestamps),
            initial_capital=initial_capital,
            sz_decimals=sz_decimals,
            min_notional=min_notional,
        )

    def advance_paper(
        self,
        data,
        *,
        sz_decimals,
        portfolio_state=None,
        initial_capital=1000.0,
        min_notional=10.0,
    ):
        timestamps, closes = _aligned_closes(data)
        if not self.funding_data:
            raise ValueError("paper execution requires funding data")
        incomplete = [
            coin
            for coin in closes
            if not self.funding_data.get(coin)
            or int(self.funding_data[coin][-1]["time"]) < timestamps[-1] - 3_600_000
        ]
        if incomplete:
            raise ValueError(f"incomplete funding through latest bar: {', '.join(sorted(incomplete))}")
        funding = _aligned_funding(timestamps, closes, self.funding_data)

        def prices_at(index):
            return {coin: values[index] for coin, values in closes.items()}

        def target_at(index):
            return overlapping_momentum_weights(
                closes,
                index=index,
                lookback_bars=self.candidate.lookback,
                top_n=self.candidate.top_n,
                overlap_cohorts=self.candidate.overlap_cohorts,
                cohort_spacing_bars=self.candidate.cohort_spacing,
            )

        submitted_orders = 0
        skipped_small_orders = 0
        if portfolio_state is None:
            signal_index = next(
                index
                for index in range(len(timestamps) - 1, -1, -1)
                if datetime.fromtimestamp(timestamps[index] / 1000, timezone.utc).hour == self.rebalance_hour_utc
            )
            prices = prices_at(signal_index)
            plan = build_execution_plan(
                target_at(signal_index),
                equity=initial_capital,
                prices=prices,
                sz_decimals=sz_decimals,
                min_notional=min_notional,
            )
            if any(row["reason"] == "missing_market_metadata" for row in plan["blockers"]):
                raise ValueError("paper initialization is missing market metadata")
            submitted_orders += len(plan["orders"])
            skipped_small_orders += len(plan["blockers"])
            rounded_weights = {
                order["coin"]: order["target_size"] * prices[order["coin"]] / initial_capital
                for order in plan["orders"]
            }
            state = open_portfolio(
                timestamp=timestamps[signal_index],
                prices=prices,
                target_weights=rounded_weights,
                equity=initial_capital,
                one_way_cost_bps=self.one_way_cost_bps,
            )
            next_index = signal_index + 1
            initialized = True
        else:
            state = PaperPortfolio(**portfolio_state)
            if state.last_time not in timestamps:
                raise ValueError("paper state timestamp is outside the retained fixture")
            next_index = timestamps.index(state.last_time) + 1
            initialized = False

        for index in range(next_index, len(timestamps)):
            mark_portfolio(
                state,
                timestamp=timestamps[index],
                prices=prices_at(index),
                funding_rates={coin: values[index] for coin, values in funding.items()},
            )
            if datetime.fromtimestamp(timestamps[index] / 1000, timezone.utc).hour != self.rebalance_hour_utc:
                continue
            plan = build_execution_plan(
                target_at(index),
                equity=state.equity,
                prices=state.prices,
                sz_decimals=sz_decimals,
                min_notional=min_notional,
                current_sizes=state.positions,
            )
            if any(row["reason"] == "missing_market_metadata" for row in plan["blockers"]):
                raise ValueError("paper rebalance is missing market metadata")
            submitted_orders += len(plan["orders"])
            skipped_small_orders += len(plan["blockers"])
            target_sizes = dict(state.positions)
            target_sizes.update({order["coin"]: order["target_size"] for order in plan["orders"]})
            rebalance_portfolio(
                state,
                target_weights={
                    coin: target_sizes[coin] * state.prices[coin] / state.equity
                    for coin in target_sizes
                },
                one_way_cost_bps=self.one_way_cost_bps,
            )
        return {
            "initialized": initialized,
            "bars_processed": len(timestamps) - next_index,
            "submitted_orders": submitted_orders,
            "skipped_small_orders": skipped_small_orders,
            "market_data_time": timestamps[-1],
            "portfolio": state.to_dict(),
        }

    def audit_fixed_unit(self, data, *, development_starts, fold_bars=720, holdout_bars=720):
        total = len(_aligned_closes(data)[0])
        development_end = total - holdout_bars

        def compact(row):
            return {key: value for key, value in row.items() if key not in {"state", "coin_contributions"}}

        def summarize(rows):
            positive = [row for row in rows if row["net_pnl_pct"] > 0.0]
            return {
                "scenarios": len(rows),
                "positive_scenarios": len(positive),
                "required_positive_scenarios": math.ceil(len(rows) * 0.75),
                "median_net_pnl_pct": median(row["net_pnl_pct"] for row in rows),
                "median_sharpe": median(row["sharpe"] for row in rows),
                "worst_drawdown_pct": max(row["max_drawdown_pct"] for row in rows),
                "worst_positive_contribution_share": max(
                    (row["max_positive_contribution_share"] for row in positive),
                    default=0.0,
                ),
            }

        folds = [
            self.run_fixed_unit_segment(data, start_index=start, end_index=start + fold_bars)
            for start in development_starts
        ]
        scenarios = [
            (start + shift, start + shift + fold_bars)
            for shift in range(self.candidate.rebalance_days)
            for start in development_starts
            if start + shift + fold_bars <= development_end
        ]
        normal = [self.run_fixed_unit_segment(data, start_index=start, end_index=end) for start, end in scenarios]
        stressed = [
            self.run_fixed_unit_segment(
                data,
                start_index=start,
                end_index=end,
                one_way_cost_bps=10.0,
                carry_bps_per_day=1.0,
            )
            for start, end in scenarios
        ]
        fold_summary = summarize(folds)
        normal_summary = summarize(normal)
        stressed_summary = summarize(stressed)
        fold_passed = (
            fold_summary["positive_scenarios"] >= fold_summary["required_positive_scenarios"]
            and fold_summary["median_sharpe"] > 0.5
            and fold_summary["worst_drawdown_pct"] <= 25.0
            and fold_summary["worst_positive_contribution_share"] <= 0.6
        )
        robustness_passed = all(
            row["positive_scenarios"] >= row["required_positive_scenarios"]
            and row["worst_drawdown_pct"] <= 25.0
            and row["worst_positive_contribution_share"] <= 0.6
            for row in (normal_summary, stressed_summary)
        )
        holdout = self.run_fixed_unit_replay(data, max_bars=holdout_bars)
        holdout_passed = (
            holdout["net_pnl_pct"] > 0.0
            and holdout["sharpe"] > 0.5
            and holdout["max_drawdown_pct"] <= 25.0
            and holdout["max_positive_contribution_share"] <= 0.6
        )
        return {
            "model": "fixed_units_daily_rebalance",
            "development_starts": list(development_starts),
            "folds": [compact(row) for row in folds],
            "fold_summary": fold_summary,
            "normal_robustness": normal_summary,
            "stressed_robustness": stressed_summary,
            "holdout": compact(holdout),
            "fold_passed": fold_passed,
            "robustness_passed": robustness_passed,
            "holdout_passed": holdout_passed,
            "passed": fold_passed and robustness_passed and holdout_passed,
        }


__all__ = ["OverlappingMomentumBacktester"]
