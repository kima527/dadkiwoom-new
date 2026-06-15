import sys
sys.path.append(r'c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading')
from kiwoom_client import KiwoomRealClient
from indicator import calculate_indicators_pure

def check():
    c = KiwoomRealClient()
    candles = calculate_indicators_pure(c.get_15min_candles('066570', 30))
    for x in candles:
        if 241000 <= x['close'] <= 242000:
            print(f"Date: {x['date']}, Close: {x['close']}, SMA5: {x.get('sma5')}, SMA20: {x.get('sma20')}, TEMA60: {x.get('tema60')}, K: {x.get('K')}")

if __name__ == "__main__":
    check()
