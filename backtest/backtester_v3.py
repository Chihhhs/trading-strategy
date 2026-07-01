#!/usr/bin/env python3
"""
backtester_v3.py - 交易策略回測框架 v3
新增：當天持有模式（intraday）
"""
import sys, os, json, time, math
sys.path.insert(0, os.path.dirname(__file__))
from indicators_v3 import *
from scoring_v4 import composite_score_v4, get_signal_summary

def get_binance_klines(symbol, interval="1d", limit=180):
    import urllib.request
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            result = []
            for d in data:
                result.append({
                    "ts": d[0], "open": float(d[1]), "high": float(d[2]),
                    "low": float(d[3]), "close": float(d[4]), "volume": float(d[5]),
                })
            return result
    except:
        return None

def get_coingecko_ohlcv(coin_id, days=180):
    import urllib.request
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc?vs_currency=usd&days={days}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            result = []
            for i, d in enumerate(data):
                # CoinGecko OHLCV: [timestamp, open, high, low, close]
                # 沒有 volume，用 high-low 差值作為代理成交量
                vol_proxy = float(d[2]) - float(d[3])  # high - low
                if vol_proxy <= 0:
                    vol_proxy = float(d[4]) * 0.01  # 用 close 的 1% 作為最小值
                result.append({
                    "ts": d[0], "open": float(d[1]), "high": float(d[2]),
                    "low": float(d[3]), "close": float(d[4]), "volume": vol_proxy,
                })
            return result
    except:
        return None

def run_backtest(data, coin_name, initial_capital=1000, leverage=3, fee_pct=0.08,
                 tp_mult=2.0, sl_mult=1.5, holding_period=7, risk_per_trade=0.05,
                 intraday_mode=False, verbose=False, macro_score=None,
                 slippage_pct=0.05, funding_rate_daily=0.01,
                 max_drawdown_pct=20, max_consecutive_losses=3):
    """
    回測引擎 v3.2
    
    參數:
    - intraday_mode: True = 當天開倉當天平倉（用收盤價），False = 原有邏輯
    - macro_score: 宏觀評分（-20 到 +20），None 表示不使用
    - slippage_pct: 滑價百分比（預設 0.05%）
    - funding_rate_daily: 每日資金費率成本（預設 0.01%）
    - max_drawdown_pct: 最大回撤限制（預設 20%，超過則停止交易）
    - max_consecutive_losses: 最大連續虧損次數（預設 3 次，超過則停止）
    """
    n = len(data)
    if n < 35:
        return {"error": "數據不足"}
    
    capital = initial_capital
    position = None
    trades = []
    equity_curve = [initial_capital]
    wins = 0
    losses = 0
    peak_capital = initial_capital
    max_drawdown = 0
    consecutive_losses = 0
    stopped = False  # 是否因回撤/連續虧損而停止
    stop_reason = ""
    
    for i in range(30, n):
        # 檢查回撤限制
        if peak_capital > 0:
            current_dd = (peak_capital - capital) / peak_capital * 100
            if current_dd > max_drawdown:
                max_drawdown = current_dd
            if max_drawdown > max_drawdown_pct:
                stopped = True
                stop_reason = f"回撤限制觸發 ({max_drawdown:.1f}% > {max_drawdown_pct}%)"
                break
        
        # 檢查連續虧損限制
        if consecutive_losses >= max_consecutive_losses:
            stopped = True
            stop_reason = f"連續虧損限制觸發 ({consecutive_losses}次)"
            break
        
        closes = [d["close"] for d in data[:i+1]]
        highs = [d["high"] for d in data[:i+1]]
        lows = [d["low"] for d in data[:i+1]]
        vols = [d["volume"] for d in data[:i+1]]
        opens = [d["open"] for d in data[:i+1]]
        
        current_price = closes[-1]
        current_open = opens[-1]
        
        # ATR
        atr_vals = atr(highs, lows, closes, 14)
        atr_valid = [v for v in atr_vals[-20:] if v is not None] if atr_vals else []
        atr_val = atr_valid[-1] if atr_valid else current_price * 0.03
        
        # 評分
        score_result = composite_score_v4(
            closes=closes, highs=highs, lows=lows, vols=vols, opens=opens,
            fear_greed=50, btc_7d_change=None, macro_score=macro_score
        )
        signal = score_result["signal"]
        score = score_result["score"]
        
        # ──────────────────────────────────────────────────
        # 檢查現有倉位
        # ──────────────────────────────────────────────────
        if position is not None:
            entry = position["entry"]
            side = position["side"]
            sl = position["sl"]
            tp = position["tp"]
            notional = position["notional"]
            days_held = i - position["entry_day"]
            
            close_position = False
            close_price = current_price
            close_reason = ""
            
            if intraday_mode:
                # 當天持有模式：收盤時強制平倉
                close_position = True
                close_price = current_price
                close_reason = "INTRADAY"
            else:
                # 原有邏輯：檢查 SL/TP
                if side == "long":
                    if lows[-1] <= sl:
                        close_position = True; close_price = sl; close_reason = "SL"
                    elif highs[-1] >= tp:
                        close_position = True; close_price = tp; close_reason = "TP"
                else:
                    if highs[-1] >= sl:
                        close_position = True; close_price = sl; close_reason = "SL"
                    elif lows[-1] <= tp:
                        close_position = True; close_price = tp; close_reason = "TP"
                
                # 時間止損
                if not close_position and days_held >= holding_period:
                    close_position = True; close_reason = "TIME"
                
                # 信號反轉
                if not close_position:
                    if side == "long" and signal in ("SELL", "STRONG_SELL"):
                        close_position = True; close_reason = "REV"
                    elif side == "short" and signal in ("BUY", "STRONG_BUY"):
                        close_position = True; close_reason = "REV"
            
            if close_position:
                if side == "long":
                    price_pct = (close_price / entry - 1)
                else:
                    price_pct = (entry / close_price - 1)
                
                pnl_amount = notional * price_pct * leverage
                
                # 手續費（進場 + 出場）
                fee_cost = notional * fee_pct / 100 * leverage * 2
                
                # 滑價成本（根據 ATR 動態計算）
                slippage_cost = notional * slippage_pct / 100 * leverage
                
                # 資金費率成本（持有天數 * 每日費率）
                funding_cost = notional * funding_rate_daily / 100 * leverage * days_held
                
                total_costs = fee_cost + slippage_cost + funding_cost
                pnl_amount -= total_costs
                capital += pnl_amount
                if capital < 0: capital = 0
                
                trades.append({
                    "side": side, "entry": entry, "exit": close_price,
                    "entry_day": position["entry_day"], "exit_day": i,
                    "pnl_pct": round(price_pct * leverage * 100, 2),
                    "pnl_amount": round(pnl_amount, 2),
                    "costs": round(total_costs, 2),
                    "reason": close_reason, "days_held": days_held,
                    "score": position["score"],
                })
                
                if pnl_amount > 0:
                    wins += 1
                    consecutive_losses = 0  # 重置連續虧損
                else:
                    losses += 1
                    consecutive_losses += 1
                
                if verbose:
                    emoji = "✅" if pnl_amount > 0 else "❌"
                    print(f"  {emoji} {side.upper()} 平倉 @ ${close_price:.4f} | PnL: ${pnl_amount:+.2f} | {close_reason}")
                position = None
        
        # ──────────────────────────────────────────────────
        # 開新倉
        # ──────────────────────────────────────────────────
        if position is None and capital > 10:
            should_open = False
            side = None
            
            if intraday_mode:
                # 當天持有模式：只用 STRONG 信號
                if signal == "STRONG_BUY":
                    should_open = True; side = "long"
                elif signal == "STRONG_SELL":
                    should_open = True; side = "short"
            else:
                if signal in ("STRONG_BUY", "BUY"):
                    should_open = True; side = "long"
                elif signal in ("STRONG_SELL", "SELL"):
                    should_open = True; side = "short"
            
            if should_open:
                risk_amount = capital * risk_per_trade
                sl_distance = atr_val * sl_mult
                if sl_distance <= 0: sl_distance = current_price * 0.05
                
                sl_pct = sl_distance / current_price
                notional = risk_amount / sl_pct / leverage if sl_pct > 0 else 0
                max_notional = capital * 0.8
                if notional > max_notional: notional = max_notional
                if notional < 1: notional = 0
                
                if notional > 0:
                    entry = current_price
                    if side == "long":
                        sl = entry - sl_distance
                        tp = entry + atr_val * tp_mult
                    else:
                        sl = entry + sl_distance
                        tp = entry - atr_val * tp_mult
                    
                    position = {
                        "side": side, "entry": entry, "sl": sl, "tp": tp,
                        "notional": notional, "entry_day": i, "score": score,
                    }
        
        # 權益曲線
        if position is not None:
            if position["side"] == "long":
                unrealized = (current_price / position["entry"] - 1) * leverage * position["notional"]
            else:
                unrealized = (position["entry"] / current_price - 1) * leverage * position["notional"]
            equity_curve.append(capital + unrealized)
        else:
            equity_curve.append(capital)
        
        if equity_curve[-1] > peak_capital: peak_capital = equity_curve[-1]
        if peak_capital > 0:
            dd = (peak_capital - equity_curve[-1]) / peak_capital * 100
            if dd > max_drawdown: max_drawdown = dd
    
    # 統計
    total_trades = wins + losses
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    win_pnl = sum(t["pnl_amount"] for t in trades if t["pnl_amount"] > 0)
    loss_pnl = abs(sum(t["pnl_amount"] for t in trades if t["pnl_amount"] < 0))
    profit_factor = win_pnl / loss_pnl if loss_pnl > 0 else (float("inf") if win_pnl > 0 else 0)
    avg_win = win_pnl / wins if wins > 0 else 0
    avg_loss = loss_pnl / losses if losses > 0 else 0
    
    returns = []
    for j in range(1, len(equity_curve)):
        if equity_curve[j-1] > 0:
            r = (equity_curve[j] - equity_curve[j-1]) / equity_curve[j-1]
            returns.append(r)
    if returns:
        avg_r = sum(returns) / len(returns)
        std_r = (sum((r - avg_r)**2 for r in returns) / len(returns))**0.5
        sharpe = (avg_r / std_r * math.sqrt(365)) if std_r > 0 else 0
    else:
        sharpe = 0
    
    final_capital = equity_curve[-1] if equity_curve else initial_capital
    total_return = (final_capital / initial_capital - 1) * 100
    
    return {
        "coin": coin_name, "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2), "total_return": round(total_return, 2),
        "total_trades": total_trades, "wins": wins, "losses": losses,
        "win_rate": round(win_rate, 1), "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(max_drawdown, 2), "sharpe": round(sharpe, 2),
        "total_costs": round(sum(t.get("costs", 0) for t in trades), 2),
        "stopped": stopped,
        "stop_reason": stop_reason,
        "trades": trades, "equity_curve": equity_curve,
    }

def print_report(result, title=""):
    if "error" in result:
        print(f"  ❌ {result['error']}"); return
    print(f"\n{'='*60}")
    print(f"📊 {result['coin']} {title}")
    print(f"{'='*60}")
    print(f"  初始: ${result['initial_capital']:,.2f} → 最終: ${result['final_capital']:,.2f}")
    print(f"  總回報: {result['total_return']:+.2f}% | 交易: {result['total_trades']} | 勝率: {result['win_rate']:.1f}%")
    print(f"  盈虧比: {result['profit_factor']:.2f} | 最大回撤: {result['max_drawdown']:.2f}% | 夏普: {result['sharpe']:.2f}")
    print(f"  總成本: ${result.get('total_costs', 0):,.2f} (手續費+滑價+資金費率)")
    
    if result.get("stopped"):
        print(f"  ⚠️ 提前停止: {result.get('stop_reason', '')}")
    
    if result["trades"]:
        reasons = {}
        for t in result["trades"]:
            r = t["reason"]
            reasons[r] = reasons.get(r, 0) + 1
        print(f"  平倉原因: {reasons}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--coins", nargs="+", default=["SOL","UNI","HYPE","BTC","ETH","DOGE","ADA"])
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--capital", type=float, default=1000)
    parser.add_argument("--leverage", type=int, default=3)
    parser.add_argument("--tp", type=float, default=2.0)
    parser.add_argument("--sl", type=float, default=1.5)
    parser.add_argument("--hold", type=int, default=7)
    parser.add_argument("--risk", type=float, default=0.05)
    parser.add_argument("--intraday", action="store_true", help="當天持有模式")
    parser.add_argument("--compare", action="store_true", help="對比兩種模式")
    args = parser.parse_args()
    
    # 獲取數據
    binance_pairs = {c: c + "USDT" for c in args.coins}
    coingecko_fallback = {"HYPE": "hyperliquid"}
    
    all_data = {}
    print(f"⏳ 獲取數據...")
    for coin in args.coins:
        pair = binance_pairs.get(coin)
        data = get_binance_klines(pair, limit=args.days) if pair else None
        if not data and coin in coingecko_fallback:
            time.sleep(2)
            data = get_coingecko_ohlcv(coingecko_fallback[coin], args.days)
        if data and len(data) >= 30:
            all_data[coin] = data
            print(f"  ✓ {coin}: {len(data)} 天")
        else:
            print(f"  ✗ {coin}: 無數據")
        time.sleep(0.3)
    
    # 回測
    if args.compare:
        # 對比模式
        print(f"\n{'═'*70}")
        print(f"📊 對比：正常模式 vs 當天持有模式")
        print(f"{'═'*70}")
        
        print(f"\n{'─'*70}")
        print(f"【正常模式】TP={args.tp}x ATR | SL={args.sl}x ATR | 持有={args.hold}天")
        print(f"{'─'*70}")
        normal_results = {}
        for coin in args.coins:
            if coin not in all_data: continue
            r = run_backtest(all_data[coin], coin, initial_capital=args.capital,
                           leverage=args.leverage, tp_mult=args.tp, sl_mult=args.sl,
                           holding_period=args.hold, risk_per_trade=args.risk)
            normal_results[coin] = r
            print_report(r, "正常模式")
        
        print(f"\n{'─'*70}")
        print(f"【當天持有模式】收盤平倉 | 只用 STRONG 信號")
        print(f"{'─'*70}")
        intraday_results = {}
        for coin in args.coins:
            if coin not in all_data: continue
            r = run_backtest(all_data[coin], coin, initial_capital=args.capital,
                           leverage=args.leverage, tp_mult=args.tp, sl_mult=args.sl,
                           holding_period=1, risk_per_trade=args.risk, intraday_mode=True)
            intraday_results[coin] = r
            print_report(r, "當天持有")
        
        # 對比表格
        print(f"\n{'═'*80}")
        print(f"📊 對比總結")
        print(f"{'═'*80}")
        print(f"{'幣種':<6} | {'正常模式':^30} | {'當天持有模式':^30}")
        print(f"{'':6} | {'回報%':>8} {'交易':>5} {'勝率':>7} {'回撤':>7} | {'回報%':>8} {'交易':>5} {'勝率':>7} {'回撤':>7}")
        print(f"{'─'*80}")
        
        for coin in args.coins:
            if coin in normal_results and coin in intraday_results:
                nr = normal_results[coin]
                ir = intraday_results[coin]
                if "error" not in nr and "error" not in ir:
                    print(f"{coin:<6} | {nr['total_return']:>+7.1f}% {nr['total_trades']:>4} {nr['win_rate']:>6.1f}% {nr['max_drawdown']:>6.1f}% | {ir['total_return']:>+7.1f}% {ir['total_trades']:>4} {ir['win_rate']:>6.1f}% {ir['max_drawdown']:>6.1f}%")
    else:
        # 單一模式
        mode = "當天持有" if args.intraday else "正常"
        print(f"\n{'═'*70}")
        print(f"📊 {mode}模式回測")
        print(f"{'═'*70}")
        
        results = {}
        for coin in args.coins:
            if coin not in all_data: continue
            r = run_backtest(all_data[coin], coin, initial_capital=args.capital,
                           leverage=args.leverage, tp_mult=args.tp, sl_mult=args.sl,
                           holding_period=args.hold, risk_per_trade=args.risk,
                           intraday_mode=args.intraday)
            results[coin] = r
            print_report(r)
        
        # 總結
        print(f"\n{'═'*70}")
        print(f"📊 {mode}模式總結")
        print(f"{'═'*70}")
        print(f"{'幣種':<6} {'回報%':>8} {'交易':>5} {'勝率':>7} {'盈虧比':>7} {'回撤%':>8} {'夏普':>7} {'最終$':>10}")
        print(f"{'─'*70}")
        total_ret = 0; cnt = 0
        for coin, r in results.items():
            if "error" not in r:
                total_ret += r["total_return"]; cnt += 1
                print(f"{coin:<6} {r['total_return']:>+7.1f}% {r['total_trades']:>4} {r['win_rate']:>6.1f}% {r['profit_factor']:>6.2f} {r['max_drawdown']:>7.1f}% {r['sharpe']:>6.2f} ${r['final_capital']:>8.2f}")
        if cnt > 0:
            print(f"{'─'*70}")
            print(f"{'平均':<6} {total_ret/cnt:>+7.1f}%")
