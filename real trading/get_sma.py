import sys
import time
from kiwoom_client import KiwoomClient
from indicator import calculate_sma

def main():
    client = KiwoomClient()
    if not client.test_connection():
        print("API 연결 실패.")
        return
        
    target_code = "005930"
    print("5분봉 데이터 조회 중...")
    candles = client.get_5min_candles(target_code, last_n_days=3)
    
    if not candles or len(candles) < 24:
        print(f"데이터 부족: {len(candles) if candles else 0}개")
        return
        
    closes = [c['close'] for c in candles]
    
    sma3 = calculate_sma(closes, 3)
    sma24 = calculate_sma(closes, 24)
    
    curr_sma3 = sma3[-1]
    curr_sma24 = sma24[-1]
    
    print(f"현재 가격: {closes[-1]:.0f}원")
    print(f"현재 3이평선 (5분봉): {curr_sma3:.2f}")
    print(f"현재 24이평선 (5분봉): {curr_sma24:.2f}")

if __name__ == "__main__":
    main()
