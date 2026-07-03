import argparse
import json
import os

from trading_strategy.core.risk import calc_position_size
from trading_strategy.core.signals import generate_fvg_signal, get_btc_direction_from_klines


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_PATH = os.path.join(PROJECT_ROOT, "data", "historical_prices", "1000d_50coins.json")
DEFAULT_COINS = ("BTC", "ETH", "SOL", "BNB")


def load_historical_data(path=DATA_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_backtest_for_coin(coin, data_map, strategy_type="both", max_days=None):
    coin_data = data_map.get(coin)
    btc_data = data_map.get("BTC", [])
    if not coin_data or len(coin_data) < 60:
        return None

    if max_days is not None:
        coin_data = coin_data[-max_days:]
        if btc_data:
            btc_data = btc_data[-max_days:]

    capital = 1000.0
    position = None
    trades = []
    peak_capital = capital
    max_drawdown = 0.0

    for i in range(50, len(coin_data)):
        window = coin_data[: i + 1]
        current = window[-1]["close"]

        if position is not None:
            should_close = False
            reason = ""
            if position["direction"] == "long":
                if current >= position["tp"]:
                    should_close, reason = True, "TP"
                elif current <= position["sl"]:
                    should_close, reason = True, "SL"
            else:
                if current <= position["tp"]:
                    should_close, reason = True, "TP"
                elif current >= position["sl"]:
                    should_close, reason = True, "SL"

            if should_close:
                if position["direction"] == "long":
                    pnl = (current - position["entry"]) * position["size"]
                else:
                    pnl = (position["entry"] - current) * position["size"]
                capital += pnl
                trades.append(
                    {
                        "coin": coin,
                        "direction": position["direction"],
                        "entry": position["entry"],
                        "exit": current,
                        "pnl": round(pnl, 4),
                        "reason": reason,
                        "score": position["score"],
                    }
                )
                position = None

        peak_capital = max(peak_capital, capital)
        if peak_capital > 0:
            drawdown = (peak_capital - capital) / peak_capital * 100
            max_drawdown = max(max_drawdown, drawdown)

        if position is not None:
            continue

        signal = generate_fvg_signal(window, strategy_type=strategy_type)
        if signal is None:
            continue

        if coin != "BTC" and btc_data and i < len(btc_data):
            btc_dir = get_btc_direction_from_klines(btc_data[: i + 1])
            if btc_dir == "bull" and signal["direction"] == "short":
                continue
            if btc_dir == "bear" and signal["direction"] == "long":
                continue

        size = calc_position_size(capital, current, signal["sl"], leverage=3, risk_pct=0.05)
        if size <= 0:
            continue

        position = {
            "direction": signal["direction"],
            "entry": current,
            "tp": signal["tp"],
            "sl": signal["sl"],
            "score": signal["score"],
            "size": size,
        }

    wins = sum(1 for trade in trades if trade["pnl"] > 0)
    total_pnl = capital - 1000.0
    return {
        "coin": coin,
        "trades": len(trades),
        "wins": wins,
        "win_rate": round((wins / len(trades) * 100) if trades else 0, 1),
        "ending_balance": round(capital, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / 1000.0 * 100, 1),
        "max_drawdown": round(max_drawdown, 1),
    }


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", default=",".join(DEFAULT_COINS))
    parser.add_argument("--strategy", choices=("fvg", "trend", "both"), default="both")
    parser.add_argument("--max-days", type=int, default=240)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    data_map = load_historical_data()
    coins = [coin.strip().upper() for coin in args.coins.split(",") if coin.strip()]

    results = []
    for coin in coins:
        result = run_backtest_for_coin(
            coin,
            data_map,
            strategy_type=args.strategy,
            max_days=args.max_days,
        )
        if result is not None:
            results.append(result)

    for result in results:
        print(
            f"{result['coin']}: trades={result['trades']}, win_rate={result['win_rate']:.1f}%, "
            f"pnl={result['total_pnl_pct']:+.1f}%, drawdown={result['max_drawdown']:.1f}%"
        )
    return results


__all__ = [
    "DATA_PATH",
    "DEFAULT_COINS",
    "build_parser",
    "load_historical_data",
    "main",
    "run_backtest_for_coin",
]
