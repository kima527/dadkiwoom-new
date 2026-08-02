import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

sys.path.append(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\MovingAveragelineTraid\execution")
from strategy_wma_golden_cross import analyze_single, WMAGoldenCrossParams, wma

def run_backtest_15m(tickers):
    results_summary = []
    all_trades = []

    params = WMAGoldenCrossParams(
        wma_short=5,
        wma_long=20,
        support_tolerance=0.03, 
        support_lookback=7,     
        support_break_tolerance=0.01 
    )

    end_date = datetime.now()
    start_date_15m = end_date - timedelta(days=59) # max 60 days for 15m data in yfinance
    start_date_daily = end_date - timedelta(days=150) # enough for daily WMA50

    for symbol, name in tickers.items():
        print(f"[{name}] 데이터 다운로드 및 분석 중...")
        try:
            # 1. 일봉 데이터 조회 및 WMA50 계산
            df_daily = yf.download(symbol, start=start_date_daily.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), progress=False)
            if isinstance(df_daily.columns, pd.MultiIndex):
                df_daily.columns = df_daily.columns.droplevel(1)
            
            df_daily['WMA50_Daily'] = wma(df_daily['Close'], 50)
            df_daily['Date_Str'] = df_daily.index.strftime('%Y-%m-%d')
            daily_wma_map = dict(zip(df_daily['Date_Str'], df_daily['WMA50_Daily']))

            # 2. 15분봉 데이터 조회
            df = yf.download(symbol, start=start_date_15m.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), interval="15m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            
            if df.empty or len(df) < 50:
                print(f"[{name}] 15분봉 데이터 부족.")
                continue

            # 3. 15분봉 분석
            analyzed = analyze_single(df, params)
            
            # 일봉 WMA50 맵핑 (15분봉 날짜 기준)
            analyzed['Date_Str'] = analyzed.index.strftime('%Y-%m-%d')
            analyzed['WMA50_Daily'] = analyzed['Date_Str'].map(daily_wma_map)
            # 결측치는 ffill (전일 WMA50 사용)
            analyzed['WMA50_Daily'] = analyzed['WMA50_Daily'].ffill()

            holding = False
            entry_price = 0.0
            entry_date = None
            stop_loss = 0.0
            sell_target = 0.0
            
            trades = []
            
            for date, row in analyzed.iterrows():
                # --- 매도 로직 ---
                if holding:
                    # 1. 목표가 도달 (정배열 전고점)
                    if sell_target > 0 and row['Close'] >= sell_target:
                        exit_price = row['Close']
                        return_pct = (exit_price - entry_price) / entry_price * 100
                        trades.append({
                            'Stock': name,
                            'Entry Date': entry_date,
                            'Entry Price': entry_price,
                            'Exit Date': date,
                            'Exit Price': exit_price,
                            'Return (%)': return_pct,
                            'Reason': f'익절 (목표가 {sell_target:,.0f} 도달)'
                        })
                        holding = False
                        
                    # 2. 손절선 이탈
                    elif row['Close'] < stop_loss:
                        exit_price = row['Close']
                        return_pct = (exit_price - entry_price) / entry_price * 100
                        trades.append({
                            'Stock': name,
                            'Entry Date': entry_date,
                            'Entry Price': entry_price,
                            'Exit Date': date,
                            'Exit Price': exit_price,
                            'Return (%)': return_pct,
                            'Reason': '손절 (지지선 이탈)'
                        })
                        holding = False
                    
                    # 3. 트레일링 스탑 (수익 3% 이상일 때 20선 이탈)
                    elif (row['Close'] - entry_price) / entry_price > 0.03 and row['Close'] < row['WMA20']:
                        exit_price = row['Close']
                        return_pct = (exit_price - entry_price) / entry_price * 100
                        trades.append({
                            'Stock': name,
                            'Entry Date': entry_date,
                            'Entry Price': entry_price,
                            'Exit Date': date,
                            'Exit Price': exit_price,
                            'Return (%)': return_pct,
                            'Reason': '트레일링 익절 (WMA20 이탈)'
                        })
                        holding = False

                # --- 매수 로직 ---
                if not holding and row['Final_Entry']:
                    # 일봉 필터 확인 (현재가 > 일봉 WMA50)
                    if pd.notna(row['WMA50_Daily']) and row['Close'] > row['WMA50_Daily']:
                        holding = True
                        entry_price = row['Close']
                        entry_date = date
                        stop_loss = row['Signal_1'] * 0.98 if pd.notna(row['Signal_1']) else entry_price * 0.98
                        target = row['Sell_Target']
                        sell_target = target if pd.notna(target) and target > entry_price else entry_price * 1.10
                        
            # 미청산 포지션
            if holding:
                exit_price = analyzed.iloc[-1]['Close']
                return_pct = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'Stock': name,
                    'Entry Date': entry_date,
                    'Entry Price': entry_price,
                    'Exit Date': analyzed.index[-1],
                    'Exit Price': exit_price,
                    'Return (%)': return_pct,
                    'Reason': '보유중 (강제청산)'
                })
                
            all_trades.extend(trades)
            
            if trades:
                df_trades = pd.DataFrame(trades)
                win_rate = len(df_trades[df_trades['Return (%)'] > 0]) / len(trades) * 100
                avg_return = df_trades['Return (%)'].mean()
                total_return = (df_trades['Return (%)'] / 100 + 1).prod() - 1
                results_summary.append({
                    'Stock': name,
                    'Total Trades': len(trades),
                    'Win Rate (%)': round(win_rate, 2),
                    'Avg Return (%)': round(avg_return, 2),
                    'Cumulative Return (%)': round(total_return * 100, 2)
                })
                
        except Exception as e:
            print(f"[{name}] 분석 오류: {e}")

    print("\n\n" + "="*50)
    print("15분봉 백테스트 결과 요약 (최근 60일)")
    print("="*50)
    if results_summary:
        df_summary = pd.DataFrame(results_summary)
        print(df_summary.to_markdown(index=False))
    
    if all_trades:
        df_all_trades = pd.DataFrame(all_trades)
        print("\n최근 거래 내역:")
        print(df_all_trades.tail(15).to_markdown(index=False))

if __name__ == "__main__":
    tickers = {
        "005930.KS": "삼성전자",
        "000660.KS": "SK하이닉스",
        "035420.KS": "NAVER",
        "005380.KS": "현대차",
        "086520.KQ": "에코프로",
        "028300.KQ": "HLB",
        "042700.KS": "한미반도체",
        "001570.KS": "금양"
    }
    run_backtest_15m(tickers)
