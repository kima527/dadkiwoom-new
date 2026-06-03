import sys
import os
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Paper trading")))

from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure

def main():
    client = KiwoomClient()
    code = "373220" # LG Energy Solution
    
    print("Fetching daily candles with retries...")
    daily_candles = None
    for attempt in range(5):
        try:
            daily_candles = client.get_daily_candles(code, last_n_days=90)
            if daily_candles:
                break
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
        time.sleep(2)
        
    if not daily_candles:
        print("Failed to fetch daily candles after retries.")
        return
        
    calculate_indicators_pure(
        daily_candles,
        use_compressed_peak=True
    )
    
    print("\n=== Last 20 Daily Candles for LG Energy Solution ===")
    print("Index | Date | Close | SMA5 | SMA20 | SMA60 | K | L | Whale")
    print("-" * 80)
    for idx, c in enumerate(daily_candles[-20:]):
        print(f"{idx} | {c['date']} | {c['close']:,.0f} | "
              f"{f'{c.get('sma5'):,.0f}' if c.get('sma5') is not None else 'None'} | "
              f"{f'{c.get('sma20'):,.0f}' if c.get('sma20') is not None else 'None'} | "
              f"{f'{c.get('sma60'):,.0f}' if c.get('sma60') is not None else 'None'} | "
              f"{f'{c.get('K'):,.0f}' if c.get('K') is not None else 'None'} | "
              f"{f'{c.get('L'):,.0f}' if c.get('L') is not None else 'None'} | "
              f"{f'{c.get('whale_line'):,.0f}' if c.get('whale_line') is not None else 'None'}")

if __name__ == "__main__":
    main()
