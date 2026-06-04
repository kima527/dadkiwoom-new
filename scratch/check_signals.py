import sys
import os
import openpyxl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Paper trading")))

import config
from kiwoom_client import KiwoomClient

def calculate_indicators_with_historical_k(candles, use_compressed_peak=True, tema_period1=5, tema_period2=20):
    from indicator import (
        calculate_sma, calculate_wma, calculate_ema, calculate_tema, calculate_bollinger_bands
    )
    
    n = len(candles)
    if n == 0:
        return candles

    closes = [c['close'] for c in candles]
    
    sma5 = calculate_sma(closes, 5)
    sma20 = calculate_sma(closes, 20)
    sma60 = calculate_sma(closes, 60)
    for i in range(n):
        candles[i]['sma5'] = sma5[i]
        candles[i]['sma20'] = sma20[i]
        candles[i]['sma60'] = sma60[i]

    last_K = None
    for i in range(n):
        c = candles[i]
        s5 = c['sma5']
        s20 = c['sma20']
        s60 = c['sma60']
        if s5 is not None and s20 is not None and s60 is not None:
            if s5 > s20 and s20 > s60:
                last_K = c['close']
        c['K_static'] = last_K # Store statically for L-line and reference

    last_L = None
    if use_compressed_peak:
        compressed_K = []
        for i in range(n):
            k_val = candles[i]['K_static']
            if k_val is not None:
                if not compressed_K or compressed_K[-1][1] != k_val:
                    compressed_K.append((i, k_val))
        peaks = {}
        for idx in range(2, len(compressed_K)):
            k_2 = compressed_K[idx-2][1]
            k_1 = compressed_K[idx-1][1]
            k_0 = compressed_K[idx][1]
            if k_2 < k_1 and k_1 > k_0:
                confirm_idx = compressed_K[idx][0]
                peaks[confirm_idx] = k_1
        current_L = None
        for i in range(n):
            if i in peaks:
                current_L = peaks[i]
            candles[i]['L'] = current_L
    else:
        for i in range(n):
            if i >= 2:
                k_2 = candles[i-2]['K_static']
                k_1 = candles[i-1]['K_static']
                k_0 = candles[i]['K_static']
                if k_2 is not None and k_1 is not None and k_0 is not None:
                    if k_2 < k_1 and k_1 > k_0:
                        last_L = k_1
            candles[i]['L'] = last_L

    wma5 = calculate_wma(closes, 5)
    wma20 = calculate_wma(closes, 20)
    ema40 = calculate_ema(closes, 40)
    tema3 = calculate_tema(closes, 3)
    bb5_upper, bb5_mid, bb5_lower = calculate_bollinger_bands(closes, 5, 2.0)
    bb20_upper, bb20_mid, bb20_lower = calculate_bollinger_bands(closes, 20, 2.0)
    
    for i in range(n):
        candles[i]['wma5'] = wma5[i]
        candles[i]['wma20'] = wma20[i]
        candles[i]['ema40'] = ema40[i]
        candles[i]['tema3'] = tema3[i]
        candles[i]['bb5_upper'] = bb5_upper[i]
        candles[i]['bb5_mid'] = bb5_mid[i]
        candles[i]['bb5_lower'] = bb5_lower[i]
        candles[i]['bb20_upper'] = bb20_upper[i]
        candles[i]['bb20_mid'] = bb20_mid[i]
        candles[i]['bb20_lower'] = bb20_lower[i]

    virtual_holding = False
    has_seen_new_alignment_since_buy = False
    monitoring_sell = False
    has_crossed_bb5_upper = False
    waiting_for_bb_rebuy = False
    trade_K = None

    for i in range(n):
        c = candles[i]
        c_prev = candles[i-1] if i > 0 else None

        c['signal_buy'] = False
        c['signal_sell_cond1'] = False
        c['signal_sell_cond2'] = False
        c['signal_sell'] = False
        c['sell_reason'] = None
        c['buy_condition_type'] = "N/A"
        c['signal_buy_bb_rebound'] = False

        c['signal_buy_prep'] = False
        c['signal_buy_prep_tema'] = False
        c['signal_buy_tema'] = False
        c['signal_buy_ema40'] = False
        c['signal_buy_sma20_rebound'] = False
        c['signal_sell_second_line'] = False
        c['second_line_val'] = None

        # Time window extraction for synchronization
        try:
            t_part = c["time"].split(" ")[1]
            h = int(t_part.split(":")[0])
            is_buy_window = (h == 9)
        except Exception:
            is_buy_window = True

        is_buy_signal = False
        if c['tema3'] is not None and c['sma60'] is not None:
            if c['tema3'] > c['sma60']:
                is_buy_signal = True

        is_sell_dead_signal = False
        if (c['tema3'] is not None and c['sma60'] is not None
                and c_prev is not None
                and c_prev.get('tema3') is not None
                and c_prev.get('sma60') is not None):
            if c_prev['tema3'] >= c_prev['sma60'] and c['tema3'] < c['sma60']:
                is_sell_dead_signal = True

        # Check 15m SMA 5 & SMA 60 Dead Cross (Macro Exit)
        is_15m_sma_dead = False
        if (c['sma5'] is not None and c['sma60'] is not None
                and c_prev is not None
                and c_prev.get('sma5') is not None
                and c_prev.get('sma60') is not None):
            if c_prev['sma5'] >= c_prev['sma60'] and c['sma5'] < c['sma60']:
                is_15m_sma_dead = True

        if not virtual_holding:
            if waiting_for_bb_rebuy:
                # Check for rebuy cross (SMA5 Golden Cross SMA60)
                is_rebuy_cross = False
                if (c['sma5'] is not None and c['sma60'] is not None
                        and c_prev is not None
                        and c_prev.get('sma5') is not None
                        and c_prev.get('sma60') is not None):
                    if c_prev['sma5'] < c_prev['sma60'] and c['sma5'] >= c['sma60']:
                        is_rebuy_cross = True

                if is_rebuy_cross:
                    virtual_holding = True
                    has_seen_new_alignment_since_buy = False
                    monitoring_sell = False
                    has_crossed_bb5_upper = False
                    waiting_for_bb_rebuy = False
                    # Use historical K-line at rebuy if valid
                    trade_K = c['K_static'] if (c.get('K_static') is not None and c['K_static'] < c['close']) else None
                    c['signal_buy_bb_rebound'] = True
                    c['buy_condition_type'] = "SMA5 GoldCross"
            else:
                if is_buy_signal and is_buy_window:
                    virtual_holding = True
                    has_seen_new_alignment_since_buy = False
                    monitoring_sell = False
                    has_crossed_bb5_upper = False
                    waiting_for_bb_rebuy = False
                    # Use historical K-line at buy if valid
                    trade_K = c['K_static'] if (c.get('K_static') is not None and c['K_static'] < c['close']) else None
                    c['signal_buy'] = True
                    c['buy_condition_type'] = "TEMA 3 > SMA 60"
        else:
            s5 = c.get('sma5')
            s20 = c.get('sma20')
            s60 = c.get('sma60')
            if s5 is not None and s20 is not None and s60 is not None:
                if s5 > s20 and s20 > s60:
                    has_seen_new_alignment_since_buy = True
                    trade_K = c['close']

            if c['bb20_upper'] is not None and c['high'] >= c['bb20_upper']:
                monitoring_sell = True

            if monitoring_sell and c['bb5_upper'] is not None and c['high'] >= c['bb5_upper']:
                has_crossed_bb5_upper = True

            is_bb_sell = False
            if has_crossed_bb5_upper and c_prev is not None:
                if c['close'] < c_prev['close']:
                    is_bb_sell = True



            # Check Sell Conditions
            is_sell_cond2 = False
            # Condition 2 (Stop Loss): L선 이하 1% 하락 시 손절 매도
            if c['L'] is not None:
                if c['close'] < c['L'] * 0.99:
                    is_sell_cond2 = True

            if is_15m_sma_dead:
                c['signal_sell'] = True
                c['sell_reason'] = "15m SMA5-60 Dead Cross"
                virtual_holding = False
                waiting_for_bb_rebuy = False
            elif is_bb_sell:
                c['signal_sell'] = True
                c['sell_reason'] = "BB5 Upper Reversal"
                virtual_holding = False
                waiting_for_bb_rebuy = True
            elif is_sell_cond2:
                c['signal_sell_cond2'] = True
                c['signal_sell'] = True
                c['sell_reason'] = "L-line 1% Stop Loss"
                virtual_holding = False
                waiting_for_bb_rebuy = False
            elif is_sell_dead_signal:
                c['signal_sell_cond1'] = True
                c['signal_sell'] = True
                c['sell_reason'] = "TEMA 3 Dead Cross"
                virtual_holding = False
                waiting_for_bb_rebuy = False

        c['K'] = trade_K
        c['signal_buy_dynamic'] = c['signal_buy']
        
        # Macro indicators and filters
        c['sma5_gt_sma60'] = (c['sma5'] > c['sma60']) if (c['sma5'] is not None and c['sma60'] is not None) else False
        c['signal_sell_sma5_sma60_dead'] = is_15m_sma_dead

        # Daily Close Reset logic removed to allow overnight holding.

    return candles

def calculate_indicators_1min(candles):
    """
    Calculates technical indicators for 1-minute candles.
    Calculates TEMA 20 and SMA 40.
    """
    from indicator import calculate_tema, calculate_sma
    n = len(candles)
    if n == 0:
        return candles
        
    closes = [c['close'] for c in candles]
    
    tema20 = calculate_tema(closes, 20)
    sma40 = calculate_sma(closes, 40)
    
    for i in range(n):
        candles[i]['tema20'] = tema20[i]
        candles[i]['sma40'] = sma40[i]
        
    return candles

def run_simulation(candles, fee_tax_pct=0.20):
    trades = []
    is_holding = False
    buy_price = 0.0
    buy_time = None
    buy_index = -1
    sold_qty = 0
    
    n = len(candles)
    for i in range(n - 1):
        current = candles[i]
        nxt = candles[i + 1]
        
        try:
            t_part = current["time"].split(" ")[1]
            h, m = map(int, t_part.split(":")[:2])
            is_buy_window = (h == 9)
            is_rebuy_window = (h >= 10 and (h < 15 or (h == 15 and m < 20)))
        except Exception:
            is_buy_window = True
            is_rebuy_window = True
            
        if not is_holding:
            if is_buy_window and current.get("signal_buy_dynamic"):
                is_holding = True
                buy_price = nxt["open"]
                buy_time = nxt["time"]
                buy_index = i + 1
                sold_qty = 0
            elif is_rebuy_window and current.get("signal_buy_bb_rebound") and sold_qty > 0:
                is_holding = True
                buy_price = nxt["open"]
                buy_time = nxt["time"]
                buy_index = i + 1
                sold_qty = 0
        else:
            if current.get("signal_sell"):
                sell_price = nxt["open"]
                sell_time = nxt["time"]
                
                gross_return = ((sell_price - buy_price) / buy_price) * 100.0
                net_return = gross_return - fee_tax_pct
                holding_bars = (i + 1) - buy_index
                
                sell_reason = current.get("sell_reason", "전략 매도")
                
                trades.append({
                    "buy_time": buy_time,
                    "buy_price": buy_price,
                    "sell_time": sell_time,
                    "sell_price": sell_price,
                    "return_pct": round(net_return, 2),
                    "holding_bars": holding_bars,
                    "is_completed": True,
                    "reason": sell_reason
                })
                is_holding = False
                
                if sell_reason == "BB5 Upper Reversal":
                    sold_qty = 1.0
                else:
                    sold_qty = 0.0
                
    if is_holding:
        last_candle = candles[-1]
        sell_price = last_candle["close"]
        sell_time = last_candle["time"] + " (미청산 평가)"
        
        gross_return = ((sell_price - buy_price) / buy_price) * 100.0
        net_return = gross_return - fee_tax_pct
        holding_bars = (n - 1) - buy_index
        
        trades.append({
            "buy_time": buy_time,
            "buy_price": buy_price,
            "sell_time": sell_time,
            "sell_price": sell_price,
            "return_pct": round(net_return, 2),
            "holding_bars": holding_bars,
            "is_completed": False,
            "reason": "미청산 평가"
        })
        
    return trades

def main():
    client = KiwoomClient()
    watchlist = [{"code": "064400", "name": "LG씨엔에스"}]
    days_to_fetch = 14
    all_results = {}
    
    print("Fetching data and running simulations for LG CNS...")
    for stock in watchlist:
        code = stock["code"]
        name = stock["name"]
        candles = client.get_15min_candles(code, last_n_days=days_to_fetch)
        if not candles or len(candles) < 60:
            continue
            
        calculate_indicators_with_historical_k(candles, use_compressed_peak=True)
        
        unique_dates = sorted(list(set(c["date"] for c in candles)))
        last_5_dates = unique_dates[-5:]
        
        trades = run_simulation(candles)
        
        filtered_trades = []
        for t in trades:
            sell_date = t["sell_time"].split(" ")[0]
            buy_date = t["buy_time"].split(" ")[0]
            
            if t["is_completed"]:
                if sell_date in last_5_dates:
                    filtered_trades.append(t)
            else:
                if buy_date in last_5_dates:
                    filtered_trades.append(t)
                    
        all_results[code] = {
            "name": name,
            "trades": filtered_trades
        }

    # Summary
    print("\n================ DIAGNOSTIC BACKTEST RESULTS ================")
    for code, data in all_results.items():
        name = data["name"]
        trades = data["trades"]
        print(f"[{name} ({code})] 거래 {len(trades)}회")
        for idx, t in enumerate(trades, 1):
             print(f"  {idx}. 매수: {t['buy_time']} ({t['buy_price']:,.0f}원) -> 매도: {t['sell_time']} ({t['sell_price']:,.0f}원) | 수익률: {t['return_pct']:+.2f}% | 사유: {t['reason']}")

if __name__ == "__main__":
    main()
