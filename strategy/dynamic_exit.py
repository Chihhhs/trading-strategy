#!/usr/bin/env python3
"""
dynamic_exit.py - 動態出場引擎（最終版）

核心邏輯：
1. 根據波動率百分位數自適應調整 TP/SL 倍數
2. 只有趨勢市況（ADX > 25）用追蹤止損，其他都用固定 TP/SL
3. 波動率百分位數基於該幣種歷史波動率分佈（不需要過濾）

波動率自適應：
- 低波動（< 30%）：TP=1.5R, SL=1.0x ATR
- 正常（30-70%）：TP=2.0R, SL=1.5x ATR
- 高波動（> 70%）：TP=3.0R, SL=2.0x ATR
- 趨勢 + ADX > 25：追蹤止損，不設 TP

出場條件：
- 固定 TP/SL：TP 或 SL 觸發
- 趨勢追蹤：ATR 追蹤止損 / 結構破壞 / ADX 轉弱
- 通用：最小持倉 3 天，最大 7 天
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from indicators_v3 import atr, adx
from scoring_v6 import classify_market, market_structure


class DynamicExitCalculator:
    """動態出場計算器"""
    
    def __init__(self, config=None):
        if config is None:
            config = {}
        self.config = config
        self.atr_period = config.get('atr_period', 14)
        self.trailing_mult = config.get('trailing_mult', 2.0)
        self.min_hold_days = config.get('min_hold_days', 3)
        self.max_hold_days = config.get('max_hold_days', 7)
    
    def get_vol_percentile(self, highs, lows, closes, lookback=90):
        """
        計算當前波動率百分位數
        
        返回: (percentile, atr_pct, atr_val)
        """
        current = closes[-1]
        atr_vals = atr(highs, lows, closes, self.atr_period)
        atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else current * 0.03
        atr_pct = atr_val / current * 100
        
        historical = []
        for i in range(max(0, len(closes) - lookback), len(closes)):
            if i < self.atr_period:
                continue
            a = atr(highs[:i+1], lows[:i+1], closes[:i+1], self.atr_period)
            if a and a[-1] is not None:
                historical.append(a[-1] / closes[i] * 100)
        
        if not historical:
            return 50, atr_pct, atr_val
        
        below = sum(1 for x in historical if x < atr_pct)
        equal = sum(1 for x in historical if x == atr_pct)
        pct = (below + 0.5 * equal) / len(historical) * 100
        return pct, atr_pct, atr_val
    
    def calc_exit(self, entry_price, atr_val, side, regime, vol_percentile, highs=None, lows=None, closes=None):
        """
        計算 TP/SL
        
        根據波動率百分位數 + 市況 + ADX 決定策略
        """
        # 根據波動率百分位數決定 SL 倍數
        if vol_percentile < 30:
            sl_mult, tp_mult = 1.0, 1.5  # 低波動
        elif vol_percentile < 70:
            sl_mult, tp_mult = 1.5, 2.0  # 正常
        else:
            sl_mult, tp_mult = 2.0, 3.0  # 高波動
        
        sl_distance = atr_val * sl_mult
        
        if regime in ('trending_up', 'trending_down'):
            # 趨勢：需要 ADX > 25 才用追蹤止損
            use_trend = False
            if highs is not None and lows is not None and closes is not None:
                adx_vals, _, _ = adx(highs, lows, closes, 14)
                if adx_vals and len(adx_vals) > 0 and adx_vals[-1] is not None and adx_vals[-1] > 25:
                    use_trend = True
            
            if use_trend:
                tp_distance = atr_val * 5.0
                strategy = 'trend_following'
            else:
                tp_distance = sl_distance * (tp_mult / sl_mult)
                strategy = 'fixed'
        else:
            tp_distance = sl_distance * (tp_mult / sl_mult)
            strategy = 'fixed'
        
        if side == 'long':
            tp = entry_price + tp_distance
            sl = entry_price - sl_distance
        else:
            tp = entry_price - tp_distance
            sl = entry_price + sl_distance
        
        return {
            'tp_price': round(tp, 6),
            'sl_price': round(sl, 6),
            'strategy': strategy,
            'tp_pct': round(tp_distance / entry_price * 100, 2),
            'sl_pct': round(sl_distance / entry_price * 100, 2),
        }
    
    def check_exit(self, position, current_price, highs, lows, closes):
        """
        檢查是否應該出場
        
        返回: {should_exit, reason, pnl_pct}
        """
        side = position['side']
        entry = position['entry_price']
        tp = position['tp_price']
        sl = position['sl_price']
        strategy = position['strategy']
        days = position.get('days_held', 0)
        
        # 最小持倉
        if days < self.min_hold_days:
            return {'should_exit': False, 'reason': f'最小持倉({days}/{self.min_hold_days})',
                    'pnl_pct': self._pnl(side, entry, current_price)}
        
        # SL 檢查（任何市況）
        if side == 'long' and current_price <= sl:
            return {'should_exit': True, 'reason': 'SL 觸發', 'pnl_pct': self._pnl(side, entry, current_price)}
        if side == 'short' and current_price >= sl:
            return {'should_exit': True, 'reason': 'SL 觸發', 'pnl_pct': self._pnl(side, entry, current_price)}
        
        if strategy == 'trend_following':
            # 趨勢模式：先檢查時間止損，再檢查追蹤止損
            if days >= self.max_hold_days:
                return {'should_exit': True, 'reason': f'最大持倉({days}天)',
                        'pnl_pct': self._pnl(side, entry, current_price)}
            return self._check_trend_exit(position, current_price, highs, lows, closes)
        else:
            # 固定 TP/SL
            if side == 'long' and current_price >= tp:
                return {'should_exit': True, 'reason': 'TP 觸發', 'pnl_pct': self._pnl(side, entry, current_price)}
            if side == 'short' and current_price <= tp:
                return {'should_exit': True, 'reason': 'TP 觸發', 'pnl_pct': self._pnl(side, entry, current_price)}
        
        # 最大持倉（固定 TP/SL 模式）
        if days >= self.max_hold_days:
            return {'should_exit': True, 'reason': f'最大持倉({days}天)',
                    'pnl_pct': self._pnl(side, entry, current_price)}
        
        return {'should_exit': False, 'reason': '持倉中',
                'pnl_pct': self._pnl(side, entry, current_price)}
    
    def _check_trend_exit(self, position, current_price, highs, lows, closes):
        """趨勢追蹤出場"""
        side = position['side']
        entry = position['entry_price']
        
        atr_vals = atr(highs, lows, closes, self.atr_period)
        atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else entry * 0.03
        
        # ATR 追蹤止損
        if side == 'long':
            highest = max(position.get('highest_price', entry), current_price)
            position['highest_price'] = highest
            trailing_sl = highest - atr_val * self.trailing_mult
            if trailing_sl > position['sl_price']:
                position['sl_price'] = round(trailing_sl, 6)
            if current_price < position['sl_price']:
                return {'should_exit': True, 'reason': f'追蹤止損(高點{highest:.2f})',
                        'pnl_pct': self._pnl(side, entry, current_price)}
        else:
            lowest = min(position.get('lowest_price', entry), current_price)
            position['lowest_price'] = lowest
            trailing_sl = lowest + atr_val * self.trailing_mult
            if trailing_sl < position['sl_price']:
                position['sl_price'] = round(trailing_sl, 6)
            if current_price > position['sl_price']:
                return {'should_exit': True, 'reason': f'追蹤止損(低點{lowest:.2f})',
                        'pnl_pct': self._pnl(side, entry, current_price)}
        
        # 結構破壞
        if len(closes) >= 30:
            struct, _ = market_structure(highs, lows, closes, 30)
            if side == 'long' and struct == 'BEARISH':
                return {'should_exit': True, 'reason': '結構轉空', 'pnl_pct': self._pnl(side, entry, current_price)}
            if side == 'short' and struct == 'BULLISH':
                return {'should_exit': True, 'reason': '結構轉多', 'pnl_pct': self._pnl(side, entry, current_price)}
        
        # ADX 轉弱
        if len(closes) >= 28:
            adx_vals, _, _ = adx(highs, lows, closes, 14)
            if adx_vals and adx_vals[-1] is not None:
                adx_current = adx_vals[-1]
                adx_entry = position.get('adx_at_entry', 25)
                if adx_entry > 25 and adx_entry - adx_current > 10:
                    return {'should_exit': True, 'reason': f'ADX轉弱({adx_entry:.0f}→{adx_current:.0f})',
                            'pnl_pct': self._pnl(side, entry, current_price)}
        
        return {'should_exit': False, 'reason': '趨勢持倉中',
                'pnl_pct': self._pnl(side, entry, current_price)}
    
    @staticmethod
    def _pnl(side, entry, current):
        if side == 'long':
            return round((current / entry - 1) * 100, 2)
        return round((entry / current - 1) * 100, 2)


class DynamicExitMonitor:
    """動態出場監控器"""
    
    def __init__(self, exit_calculator=None):
        self.calc = exit_calculator or DynamicExitCalculator()
        self.positions = {}
    
    def open_position(self, coin, side, entry_price, regime, atr_val, vol_percentile=50, highs=None, lows=None, closes=None):
        """開倉"""
        exit_plan = self.calc.calc_exit(entry_price, atr_val, side, regime, vol_percentile, highs, lows, closes)
        
        self.positions[coin] = {
            'side': side,
            'entry_price': entry_price,
            'tp_price': exit_plan['tp_price'],
            'sl_price': exit_plan['sl_price'],
            'strategy': exit_plan['strategy'],
            'regime': regime,
            'entry_day': 0,
            'days_held': 0,
            'highest_price': entry_price,
            'lowest_price': entry_price,
            'adx_at_entry': 25,
        }
        
        return exit_plan
    
    def update_position(self, coin, current_price, highs, lows, closes, adx_val=None):
        """更新持倉"""
        if coin not in self.positions:
            return None
        
        pos = self.positions[coin]
        pos['days_held'] += 1
        
        if adx_val:
            pos['adx_at_entry'] = adx_val
        
        result = self.calc.check_exit(pos, current_price, highs, lows, closes)
        
        if result['should_exit']:
            del self.positions[coin]
        
        return result
    
    def get_position_summary(self, coin):
        """獲取持倉摘要"""
        if coin not in self.positions:
            return None
        pos = self.positions[coin]
        return {
            'coin': coin,
            'side': pos['side'],
            'entry_price': pos['entry_price'],
            'tp_price': pos['tp_price'],
            'sl_price': pos['sl_price'],
            'strategy': pos['strategy'],
            'regime': pos['regime'],
            'days_held': pos['days_held'],
        }


if __name__ == '__main__':
    from backtester_v3 import get_binance_klines
    
    calc = DynamicExitCalculator()
    
    print('=' * 70)
    print('動態出場引擎測試')
    print('=' * 70)
    
    for coin in ['BTC', 'ETH', 'SOL', 'BNB', 'AVAX', 'XRP', 'NEAR', 'WLD', 'ZEC']:
        data = get_binance_klines(coin + 'USDT', limit=180)
        if not data:
            continue
        
        closes = [d['close'] for d in data]
        highs = [d['high'] for d in data]
        lows = [d['low'] for d in data]
        vols = [d['volume'] for d in data]
        
        vol_pct, atr_pct, atr_val = calc.get_vol_percentile(highs, lows, closes)
        regime = classify_market(closes, highs, lows, vols)['regime']
        
        exit_plan = calc.calc_exit(closes[-1], atr_val, 'short', regime, vol_pct, highs, lows, closes)
        
        print(f'{coin}: ATR%={atr_pct:.2f}%, 波動百分位={vol_pct:.0f}%, 市況={regime}')
        print(f'  做空: SL={exit_plan["sl_pct"]:+.1f}% TP={exit_plan["tp_pct"]:+.1f}% 策略={exit_plan["strategy"]}')
