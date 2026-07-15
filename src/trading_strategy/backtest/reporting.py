from .types import CoinResult


def _calc_max_drawdown(equity_curve):
    peak = 0.0
    max_drawdown = 0.0
    for balance in equity_curve:
        peak = max(peak, balance)
        if peak > 0:
            drawdown = (peak - balance) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)
    return round(max_drawdown, 1)


def calc_max_drawdown(equity_curve):
    return _calc_max_drawdown(equity_curve)


def calc_score(summary, *, drawdown_weight=0.5):
    return round(float(summary["total_pnl_pct"]) - float(summary["max_drawdown"]) * drawdown_weight, 2)


def _calc_avg_hold_bars(trades):
    hold_bars = [float(trade.get("hold_bars")) for trade in trades if trade.get("hold_bars") is not None]
    if not hold_bars:
        return 0.0
    return round(sum(hold_bars) / len(hold_bars), 1)


def _calc_direction_summary(trades):
    summary = {}
    for direction in ("long", "short"):
        subset = [trade for trade in trades if trade.get("direction") == direction]
        summary[direction] = {
            "trades": len(subset),
            "win_rate": round((sum(1 for trade in subset if float(trade.get("pnl") or 0.0) > 0) / len(subset) * 100) if subset else 0.0, 1),
            "pnl_pct": round(sum(float(trade.get("pnl_pct") or 0.0) for trade in subset), 1),
        }
    return summary


def _calc_market_context_summary(trades):
    groups = {}
    for trade in trades:
        context = trade.get("market_context_at_entry") or {}
        regime = context.get("regime") if isinstance(context, dict) else None
        if not regime:
            regime = "unclassified"
        groups.setdefault(regime, []).append(trade)
    summary = {}
    for regime, subset in sorted(groups.items()):
        pnl = [float(trade.get("pnl") or 0.0) for trade in subset]
        running = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in pnl:
            running += value
            peak = max(peak, running)
            max_drawdown = max(max_drawdown, peak - running)
        summary[regime] = {
            "trades": len(subset),
            "win_rate": round(sum(value > 0 for value in pnl) / len(subset) * 100, 1) if subset else 0.0,
            "net_pnl": round(sum(pnl), 2),
            "avg_hold_bars": _calc_avg_hold_bars(subset),
            "sequential_drawdown_contribution": round(max_drawdown, 2),
        }
    return summary


def build_coin_results(state, coins):
    initial_balance = float(state.get("initial_balance") or 0.0)
    results = []
    for coin in coins:
        trades = [trade for trade in state.get("history", []) if trade.get("coin") == coin]
        wins = sum(1 for trade in trades if float(trade.get("pnl") or 0.0) > 0)
        total_pnl = round(sum(float(trade.get("pnl") or 0.0) for trade in trades), 2)
        ending_balance = round(initial_balance + total_pnl, 2)
        win_rate = round((wins / len(trades) * 100) if trades else 0.0, 1)
        equity_curve = [initial_balance]
        running = initial_balance
        for trade in trades:
            running += float(trade.get("pnl") or 0.0)
            equity_curve.append(running)
        results.append(
            CoinResult(
                coin=coin,
                trades=len(trades),
                wins=wins,
                win_rate=win_rate,
                ending_balance=ending_balance,
                total_pnl=total_pnl,
                total_pnl_pct=round((total_pnl / initial_balance * 100) if initial_balance else 0.0, 1),
                max_drawdown=_calc_max_drawdown(equity_curve),
            )
        )
    return results


def build_portfolio_summary(state, equity_curve, peak_balance=None):
    initial_balance = float(state.get("initial_balance") or 0.0)
    ending_balance = round(float(state.get("balance") or 0.0), 2)
    total_pnl = round(ending_balance - initial_balance, 2)
    total_cost = round(sum(float(trade.get("cost") or 0.0) for trade in state.get("history", [])), 2)
    gross_pnl = round(total_pnl + total_cost, 2)
    wins = int(state.get("stats", {}).get("wins") or 0)
    total_trades = int(state.get("stats", {}).get("total_trades") or 0)
    summary = {
        "trades": total_trades,
        "wins": wins,
        "win_rate": round((wins / total_trades * 100) if total_trades else 0.0, 1),
        "starting_balance": round(initial_balance, 2),
        "ending_balance": ending_balance,
        "total_pnl": total_pnl,
        "total_pnl_pct": round((total_pnl / initial_balance * 100) if initial_balance else 0.0, 1),
        "gross_pnl": gross_pnl,
        "gross_pnl_pct": round((gross_pnl / initial_balance * 100) if initial_balance else 0.0, 1),
        "total_cost": total_cost,
        "total_cost_pct": round((total_cost / initial_balance * 100) if initial_balance else 0.0, 1),
        "max_drawdown": _calc_max_drawdown(equity_curve),
        "peak_balance": round(float(peak_balance or max(equity_curve or [initial_balance])), 2),
        "avg_hold_bars": _calc_avg_hold_bars(state.get("history", [])),
        "exit_reason_counts": {
            reason: sum(1 for trade in state.get("history", []) if trade.get("exit_reason") == reason)
            for reason in sorted({trade.get("exit_reason") for trade in state.get("history", []) if trade.get("exit_reason")})
        },
        "direction_summary": _calc_direction_summary(state.get("history", [])),
        "market_context_entry_summary": _calc_market_context_summary(state.get("history", [])),
    }
    diagnostics = dict(state.get("_diagnostics") or {})
    summary["missing_data_coins"] = list(diagnostics.get("missing_data_coins") or [])
    summary["diagnostics"] = diagnostics
    summary["score"] = calc_score(summary)
    return summary


def format_result_lines(result, *, show_trades=False):
    lines = []
    if result.portfolio.get("total_cost"):
        lines.append(
            "Portfolio: trades={trades}, win_rate={win_rate:.1f}%, net_pnl={total_pnl_pct:+.1f}%, gross_pnl={gross_pnl_pct:+.1f}%, cost={total_cost_pct:.1f}%, drawdown={max_drawdown:.1f}%, avg_hold_bars={avg_hold_bars:.1f}, score={score:+.2f}".format(
                **result.portfolio
            )
        )
    else:
        lines.append(
            "Portfolio: trades={trades}, win_rate={win_rate:.1f}%, pnl={total_pnl_pct:+.1f}%, drawdown={max_drawdown:.1f}%, avg_hold_bars={avg_hold_bars:.1f}, score={score:+.2f}".format(
                **result.portfolio
            )
        )
    lines.append(f"Exit reasons: {result.portfolio.get('exit_reason_counts', {})}")
    lines.append(f"Direction summary: {result.portfolio.get('direction_summary', {})}")
    context_summary = result.portfolio.get("market_context_entry_summary") or {}
    if context_summary:
        lines.append(f"Market context entries: {context_summary}")
    missing_data_coins = result.portfolio.get("missing_data_coins") or []
    if missing_data_coins:
        lines.append(f"Missing data coins: {', '.join(missing_data_coins)}")
    diagnostics = result.portfolio.get("diagnostics") or {}
    relevant = {
        key: diagnostics.get(key)
        for key in (
            "btc_filtered_signals",
            "price_position_filtered_signals",
            "dead_cat_filtered_signals",
            "pullback_filtered_signals",
            "trend_rsi_filtered_signals",
            "trend_atr_filtered_signals",
            "trend_price_position_filtered_signals",
            "trend_overextension_filtered_signals",
            "derivatives_funding_filtered_signals",
            "derivatives_basis_filtered_signals",
            "derivatives_oi_filtered_signals",
            "derivatives_missing_context_signals",
            "oi_entry_filter_confirmed_signals",
            "oi_entry_filter_unconfirmed_signals",
            "oi_entry_filter_missing_context_signals",
            "oi_entry_filter_late_crowded_blocks",
            "derivatives_crowding_exit_signals",
            "derivatives_crowding_exit_long_signals",
            "derivatives_crowding_exit_short_signals",
            "derivatives_crowding_reduce_signals",
            "derivatives_crowding_reduce_long_signals",
            "derivatives_crowding_reduce_short_signals",
            "trend_alpha_btc_regime_boosts",
            "trend_alpha_funding_basis_boosts",
            "trend_alpha_oi_boosts",
            "trend_alpha_crowded_blocks",
            "trend_alpha_missing_derivatives_bars",
            "trend_alpha_unconfirmed_blocks",
            "market_context_blocked_signals",
            "market_context_breakout_confirmed",
            "momentum_decay_deadlines_set",
            "momentum_decay_time_limit_exits",
        )
        if diagnostics.get(key)
    }
    if relevant:
        lines.append(f"Diagnostics: {relevant}")
    for coin_result in result.coin_results:
        lines.append(
            f"{coin_result.coin}: trades={coin_result.trades}, win_rate={coin_result.win_rate:.1f}%, "
            f"pnl={coin_result.total_pnl_pct:+.1f}%, drawdown={coin_result.max_drawdown:.1f}%"
        )
    if show_trades:
        for trade in result.trades:
            lines.append(
                f"TRADE {trade.get('coin')} {trade.get('direction')} "
                f"entry={trade.get('entry')} exit={trade.get('exit')} pnl={trade.get('pnl')} "
                f"reason={trade.get('exit_reason')}"
            )
    return lines


def format_comparison_lines(results_by_strategy):
    ordered = list(results_by_strategy.items())
    lines = [f"Comparison: {', '.join(name for name, _ in ordered)}"]
    for name, result in ordered:
        summary = result.portfolio
        lines.append(
            f"{name}: trades={summary['trades']}, win_rate={summary['win_rate']:.1f}%, "
            f"pnl={summary['total_pnl_pct']:+.1f}%, drawdown={summary['max_drawdown']:.1f}%, "
            f"avg_hold_bars={summary.get('avg_hold_bars', 0.0):.1f}, score={summary.get('score', 0.0):+.2f}"
        )
        lines.append(f"{name} exits: {summary.get('exit_reason_counts', {})}")
        if summary.get("missing_data_coins"):
            lines.append(f"{name} missing_data: {', '.join(summary['missing_data_coins'])}")
        diagnostics = summary.get("diagnostics") or {}
        compare_diag = {
            key: diagnostics.get(key)
            for key in (
                "btc_filtered_signals",
                "price_position_filtered_signals",
                "dead_cat_filtered_signals",
                "pullback_filtered_signals",
                "trend_rsi_filtered_signals",
                "trend_atr_filtered_signals",
                "trend_price_position_filtered_signals",
                "trend_overextension_filtered_signals",
                "derivatives_funding_filtered_signals",
                "derivatives_basis_filtered_signals",
                "derivatives_oi_filtered_signals",
                "derivatives_missing_context_signals",
                "oi_entry_filter_confirmed_signals",
                "oi_entry_filter_unconfirmed_signals",
                "oi_entry_filter_missing_context_signals",
                "oi_entry_filter_late_crowded_blocks",
                "derivatives_crowding_exit_signals",
                "derivatives_crowding_exit_long_signals",
                "derivatives_crowding_exit_short_signals",
                "derivatives_crowding_reduce_signals",
                "derivatives_crowding_reduce_long_signals",
                "derivatives_crowding_reduce_short_signals",
                "trend_alpha_btc_regime_boosts",
                "trend_alpha_funding_basis_boosts",
                "trend_alpha_oi_boosts",
                "trend_alpha_crowded_blocks",
                "trend_alpha_missing_derivatives_bars",
                "trend_alpha_unconfirmed_blocks",
                "market_context_blocked_signals",
                "market_context_breakout_confirmed",
                "momentum_decay_deadlines_set",
                "momentum_decay_time_limit_exits",
            )
            if diagnostics.get(key)
        }
        if compare_diag:
            lines.append(f"{name} diagnostics: {compare_diag}")
    return lines


def format_optimization_lines(rows, *, top_n=10):
    lines = []
    for index, row in enumerate(rows[:top_n], start=1):
        lines.append(
            f"{index}. strategy={row['strategy']} leverage={row['leverage']:.1f} "
            f"risk={row['risk_pct']:.2f} btc_filter={'on' if row['btc_filter_enabled'] else 'off'} "
            f"atr_trailing={'on' if row.get('atr_trailing_enabled') else 'off'} "
            f"trades={row['trades']} atr_trail_exits={row.get('atr_trail_exits', 0)} win_rate={row['win_rate']:.1f}% "
            f"avg_hold_bars={row.get('avg_hold_bars', 0.0):.1f} "
            f"pnl={row['total_pnl_pct']:+.1f}% cost={row.get('total_cost_pct', 0.0):.1f}% drawdown={row['max_drawdown']:.1f}% "
            f"score={row['score']:+.2f}"
        )
    return lines
