import os
import sys
import time
import logging
from datetime import datetime
from collections import defaultdict

from kiwoom_client import KiwoomClient
from strategy import convert_to_chart_list
from indicator import calculate_indicators_pure
from strategy import evaluate_trend_buy, evaluate_rebuy, evaluate_inflection_sell, check_highspeed_liquidation
import config

logging.basicConfig(level=logging.WARNING)

def run_backtest():
    client = KiwoomClient()
    if not client.test_connection():
        print("API Connection failed.")
        return
        
    stocks = config.HARDCODED_TARGET_STOCKS
    today_date = datetime.now().strftime("%Y%m%d")
    
    results = []
    
    for code in stocks:
        try:
            print(f"Fetching data for {code}...")
            raw_15m = client.get_15min_candles(code, last_n_days=5)
            raw_5m = client.get_5min_candles(code, last_n_days=2)
            raw_3m = client.get_3min_candles(code, last_n_days=2)
            
            if not raw_15m or not raw_5m or not raw_3m:
                continue
                
            c_15m = convert_to_chart_list(raw_15m)
            c_5m = convert_to_chart_list(raw_5m)
            c_3m = convert_to_chart_list(raw_3m)
            
            c_15m.reverse()
            c_5m.reverse()
            c_3m.reverse()
            
            c_15m = calculate_indicators_pure(c_15m)
            c_5m = calculate_indicators_pure(c_5m)
            c_3m = calculate_indicators_pure(c_3m)
            
            today_3m = [c for c in c_3m if c['time'].startswith(today_date)]
            if not today_3m:
                continue
                
            first_3m_high = today_3m[0]['high']
            buy_price = 0
            
            for curr_3m in today_3m:
                t = curr_3m['time']
                
                # Check afternoon trap (main.py line 1170)
                hour = int(t[8:10])
                minute = int(t[10:12])
                is_afternoon_trap = hour > 13 or (hour == 13 and minute >= 30)
                
                curr_15m = next((c for c in reversed(c_15m) if c['time'] <= t), None)
                curr_5m = next((c for c in reversed(c_5m) if c['time'] <= t), None)
                
                if not curr_15m or not curr_5m:
                    continue
                    
                if buy_price == 0:
                    if is_afternoon_trap:
                        continue # Skip buy if afternoon
                        
                    is_trend, t_reason = evaluate_trend_buy(curr_15m, [curr_3m], first_3m_high)
                    is_rebuy, r_reason = evaluate_rebuy(curr_15m, [curr_3m], code, [], today_date)
                    
                    if is_trend or is_rebuy:
                        buy_price = curr_3m['close']
                        reason = t_reason if is_trend else r_reason
                        results.append(f"[{t[8:10]}:{t[10:12]}] BUY {code} @ {buy_price:,} (이유: {reason})")
                
                else:
                    fast_sell, fs_reason = check_highspeed_liquidation([curr_5m], curr_3m['close'])
                    
                    profit = (curr_3m['close'] - buy_price) / buy_price * 100
                    if profit >= 3.0:
                        fast_sell = True
                        fs_reason = "익절 (3% 도달)"
                    elif profit <= -1.0:
                        fast_sell = True
                        fs_reason = "손절 (-1% 도달)"
                        
                    if fast_sell:
                        results.append(f"[{t[8:10]}:{t[10:12]}] SELL {code} @ {curr_3m['close']:,} (이유: {fs_reason}) 수익률: {profit:.2f}%")
                        buy_price = 0
                        continue
                        
                    is_sell, s_reason = evaluate_inflection_sell([curr_15m], [curr_5m])
                    if is_sell:
                        results.append(f"[{t[8:10]}:{t[10:12]}] SELL {code} @ {curr_3m['close']:,} (이유: {s_reason}) 수익률: {profit:.2f}%")
                        buy_price = 0
                        
        except Exception as e:
            print(f"Exception for {code}: {e}")
            
    print("\n\n====== 오늘(당일) 백테스트 결과 ======")
    if not results:
        print("조건에 부합하여 매매된 종목이 없습니다.")
    else:
        for r in results:
            print(r)

if __name__ == '__main__':
    run_backtest()
