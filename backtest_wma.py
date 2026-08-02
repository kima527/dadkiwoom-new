import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 현재 폴더 경로를 sys.path에 추가하여 strategy_wma_golden_cross 모듈 임포트
sys.path.append(os.path.join(os.path.dirname(__file__), "MovingAveragelineTraid", "execution"))
try:
    from strategy_wma_golden_cross import analyze_single, WMAGoldenCrossParams, wma
except ImportError:
    # 경로가 다를 경우를 대비한 절대경로
    sys.path.append(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\MovingAveragelineTraid\execution")
    from strategy_wma_golden_cross import analyze_single, WMAGoldenCrossParams, wma

def run_backtest(tickers, start_date, end_date):
    results_summary = []
    all_trades = []

    params = WMAGoldenCrossParams(
        wma_short=5,
        wma_long=20,
        support_tolerance=0.03, # 실전 백테스트를 위해 허용 오차 약간 완화
        support_lookback=7,     # 최근 7일(약 1주일) 이내 지지 확인
        support_break_tolerance=0.01 
    )

    for symbol, name in tickers.items():
        print(f"[{name}] 데이터 다운로드 및 분석 중...")
        try:
            df = yf.download(symbol, start=start_date, end=end_date, progress=False)
            
            if df.empty or len(df) < 50:
                print(f"[{name}] 데이터 부족으로 건너뜀.")
                continue
                
            # yfinance는 MultiIndex 컬럼을 반환할 수 있으므로 단일 레벨로 평탄화
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            
            # 전략 로직 적용
            analyzed = analyze_single(df, params)
            analyzed['WMA50'] = wma(analyzed['Close'], 50)
            
            # 백테스트 변수 초기화
            holding = False
            entry_price = 0.0
            entry_date = None
            stop_loss = 0.0
            
            trades = []
            
            for date, row in analyzed.iterrows():
                # --- 매도 로직 ---
                if holding:
                    # 1. 손절: 종가가 손절선(지지선의 98%)을 하향 이탈
                    if row['Close'] < stop_loss:
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
                    
                    # 2. 익절/추세 종료: 종가가 단기선(WMA5) 또는 장기선(WMA20)을 하향 이탈 (수익 확보)
                    # 여기서는 충분한 수익(5% 이상)이 났을 때 WMA5 이탈 시 매도하는 트레일링 로직 적용
                    elif (row['Close'] - entry_price) / entry_price > 0.05 and row['Close'] < row['WMA5']:
                        exit_price = row['Close']
                        return_pct = (exit_price - entry_price) / entry_price * 100
                        trades.append({
                            'Stock': name,
                            'Entry Date': entry_date,
                            'Entry Price': entry_price,
                            'Exit Date': date,
                            'Exit Price': exit_price,
                            'Return (%)': return_pct,
                            'Reason': '익절 (단기추세 이탈)'
                        })
                        holding = False
                    
                    # 3. 장기 추세 이탈: WMA20 이탈
                    elif row['Close'] < row['WMA20']:
                        exit_price = row['Close']
                        return_pct = (exit_price - entry_price) / entry_price * 100
                        trades.append({
                            'Stock': name,
                            'Entry Date': entry_date,
                            'Entry Price': entry_price,
                            'Exit Date': date,
                            'Exit Price': exit_price,
                            'Return (%)': return_pct,
                            'Reason': '청산 (WMA20 이탈)'
                        })
                        holding = False

                # --- 매수 로직 ---
                # 주의: 이미 보유 중이 아닐 때만 진입 (WMA50 위에 있을 때만)
                if not holding and row['Final_Entry'] and row['Close'] > row['WMA50']:
                    holding = True
                    entry_price = row['Close']
                    entry_date = date
                    stop_loss = row['Signal_1'] * 0.98 # 지지선에서 -2% 추가 하락 시 손절
                    
            # 종료일 기준 미청산 포지션 강제 청산 (결과 집계용)
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
            
            # 종목별 통계
            if trades:
                df_trades = pd.DataFrame(trades)
                win_trades = df_trades[df_trades['Return (%)'] > 0]
                win_rate = len(win_trades) / len(trades) * 100
                avg_return = df_trades['Return (%)'].mean()
                total_return = (df_trades['Return (%)'] / 100 + 1).prod() - 1
                
                results_summary.append({
                    'Stock': name,
                    'Total Trades': len(trades),
                    'Win Rate (%)': round(win_rate, 2),
                    'Avg Return (%)': round(avg_return, 2),
                    'Cumulative Return (%)': round(total_return * 100, 2)
                })
            else:
                results_summary.append({
                    'Stock': name,
                    'Total Trades': 0,
                    'Win Rate (%)': 0.0,
                    'Avg Return (%)': 0.0,
                    'Cumulative Return (%)': 0.0
                })
                
        except Exception as e:
            print(f"[{name}] 분석 오류: {e}")

    # 최종 결과 출력 포맷팅
    print("\n\n" + "="*50)
    print("백테스트 결과 요약 (2023.01.01 ~ 현재)")
    print("="*50)
    df_summary = pd.DataFrame(results_summary)
    print(df_summary.to_markdown(index=False))
    
    print("\n\n" + "="*50)
    print("전체 거래 내역 요약")
    print("="*50)
    if all_trades:
        df_all_trades = pd.DataFrame(all_trades)
        total_win = len(df_all_trades[df_all_trades['Return (%)'] > 0])
        total_loss = len(df_all_trades[df_all_trades['Return (%)'] <= 0])
        total_win_rate = total_win / len(df_all_trades) * 100
        total_avg_return = df_all_trades['Return (%)'].mean()
        
        print(f"총 거래 횟수: {len(df_all_trades)}")
        print(f"총 승률: {total_win_rate:.2f}% ({total_win}승 {total_loss}패)")
        print(f"평균 수익률: {total_avg_return:.2f}%")
        
        print("\n최근 10건의 거래 내역:")
        print(df_all_trades.tail(10).to_markdown(index=False))
        
        # 아티팩트에 기록하기 위해 json 형식으로 저장
        df_summary.to_json("backtest_summary.json", orient="records")
        df_all_trades.to_json("backtest_trades.json", orient="records")
    else:
        print("발생한 거래가 없습니다.")


if __name__ == "__main__":
    # 코스피/코스닥 주요 종목 믹스 (대형주 + 변동성/테마주)
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
    
    start_date = "2023-01-01"
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    run_backtest(tickers, start_date, end_date)
