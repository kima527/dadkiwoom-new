import os
import sys
import time
import pandas as pd
import numpy as np
import re

# real trading 디렉토리를 경로에 추가하여 64비트 REST API 모듈을 임포트합니다.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "real trading"))
try:
    from kiwoom_client import KiwoomRealClient
except ImportError:
    print("real trading/kiwoom_client.py 모듈을 찾을 수 없습니다.")
    sys.exit(1)

def check_condition_1(df):
    """
    조건1: 5가중, 20가중 CrossUp 지점의 H값을 구하고, 현재 종가가 그 값을 상향돌파(또는 그보다 큼)
    """
    close = df['close']
    high = df['high']

    def wma(series, period):
        weights = np.arange(1, period + 1)
        return series.rolling(period).apply(lambda prices: np.dot(prices, weights) / weights.sum(), raw=True)

    df['MM'] = wma(close, 5)
    df['MN'] = wma(close, 20)
    df['CrossUp'] = (df['MM'] > df['MN']) & (df['MM'].shift(1) <= df['MN'].shift(1))
    
    hh_values = []
    last_hh = np.nan
    for i in range(len(df)):
        if df['CrossUp'].iloc[i]:
            last_hh = high.iloc[i]
        hh_values.append(last_hh)
    df['HH'] = hh_values
    
    current_c = close.iloc[-1]
    current_hh = df['HH'].iloc[-1]
    
    return not np.isnan(current_hh) and current_c > current_hh

def check_condition_2(df):
    """
    조건2: 5, 20, 60 단순이평 정배열 상태의 종가(K)들 중 Peak값을 구하고 현재 종가가 Peak보다 큼
    """
    close = df['close']
    
    df['a'] = close.rolling(5).mean()
    df['b'] = close.rolling(20).mean()
    df['d'] = close.rolling(60).mean()
    
    df['is_aligned'] = (df['a'] > df['b']) & (df['b'] > df['d']) & (df['a'] > df['d'])
    
    k_values = []
    last_k = np.nan
    for i in range(len(df)):
        if df['is_aligned'].iloc[i]:
            last_k = close.iloc[i]
        k_values.append(last_k)
    df['K'] = k_values
    
    peak_val = np.nan
    if not df['K'].isna().all():
        peak_val = df['K'].max()
        
    current_c = close.iloc[-1]
    return not np.isnan(peak_val) and current_c > peak_val

def get_target_codes():
    desktop_path = os.path.join(os.path.expanduser("~"), "OneDrive", "바탕 화면")
    files = ["A.csv", "B.csv", "C.csv"]
    target_codes = set()
    
    for filename in files:
        filepath = os.path.join(desktop_path, filename)
        if os.path.exists(filepath):
            try:
                try:
                    df = pd.read_csv(filepath, header=None)
                    for col in df.columns:
                        for item in df[col].astype(str):
                            code = re.sub(r'[^0-9]', '', item)
                            if len(code) == 6:
                                target_codes.add(code)
                except:
                    with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
                        content = f.read()
                        codes = set(re.findall(r'\b[0-9]{6}\b', content))
                        target_codes.update(codes)
            except:
                pass
                
    return list(target_codes)

def main():
    print("==================================================")
    print("🚀 64-bit REST API 기반 주말 종목 검색기 시작")
    print("==================================================")
    
    client = KiwoomRealClient()
    if not client.test_connection():
        print("키움증권 REST API 연결(토큰 발급) 실패. 설정을 확인하세요.")
        return
        
    target_codes = get_target_codes()
    print(f"총 {len(target_codes)}개 종목을 바탕화면 파일에서 로드했습니다.")
    
    results = []
    for idx, code in enumerate(target_codes):
        print(f"[{idx+1}/{len(target_codes)}] 종목코드 {code} 검사 중...", end='\r')
        
        try:
            # 일봉 500일치 (약 100주) 가져와서 주봉으로 변환 (조건2의 60주 이평을 위해 충분한 일수 확보)
            daily_candles = client.get_daily_candles(code, 500)
            if not daily_candles:
                time.sleep(0.3)
                continue
                
            weekly_candles = client.get_weekly_candles_from_daily(daily_candles)
            if not weekly_candles or len(weekly_candles) < 60:
                time.sleep(0.3)
                continue
                
            df = pd.DataFrame(weekly_candles)
            
            cond1 = check_condition_1(df)
            cond2 = check_condition_2(df)
            
            if cond1 or cond2:
                name = client.get_stock_name(code) or code
                status_list = []
                if cond1: status_list.append("조건1")
                if cond2: status_list.append("조건2")
                status_str = " & ".join(status_list) + (" (동시만족)" if cond1 and cond2 else "")
                
                print(f"\n★ 타겟 발견 [{status_str}]: {name} ({code})")
                results.append({
                    "코드": code,
                    "종목명": name,
                    "조건1 만족여부": "O" if cond1 else "X",
                    "조건2 만족여부": "O" if cond2 else "X",
                    "동시만족여부": "O" if (cond1 and cond2) else "X"
                })
        except Exception as e:
            pass
            
        # REST API 과부하 방지 (초당 3회 이하 요청)
        time.sleep(0.3)
        
    print("\n\n검색 완료!")
    
    if results:
        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values(by="동시만족여부", ascending=False)
        
        # A.csv 형식과 동일하게 컬럼을 구성합니다.
        df_final = pd.DataFrame({
            "분": ["" for _ in range(len(df_results))],
            "신": ["" for _ in range(len(df_results))],
            "종목명": df_results["종목명"],
            "현재가": ["" for _ in range(len(df_results))],
            "등락률": ["" for _ in range(len(df_results))],
            "거래대금": ["" for _ in range(len(df_results))],
            "매수비율(%)": ["" for _ in range(len(df_results))],
            "전일비": ["" for _ in range(len(df_results))],
            "종목코드": ["'" + str(code) for code in df_results["코드"]]
        })
        
        desktop_path = os.path.join(os.path.expanduser("~"), "OneDrive", "바탕 화면")
        save_path = os.path.join(desktop_path, "weekend_search_results.csv")
        df_final.to_csv(save_path, index=False, sep=',', encoding="cp949")
        print(f"\n✅ 검색 결과가 바탕화면에 저장되었습니다: {save_path}")
    else:
        print("\n조건을 만족하는 종목이 없습니다.")

if __name__ == "__main__":
    main()
