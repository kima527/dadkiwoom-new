import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Paper trading")))

import config
from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure

def main():
    client = KiwoomClient()
    code = "018260" # Samsung SDS
    
    print("Fetching 15-minute candles...")
    candles = client.get_15min_candles(code, last_n_days=14)
    if not candles:
        print("Failed to fetch candles.")
        return
        
    calculate_indicators_pure(
        candles,
        use_compressed_peak=True
    )
    
    # Filter only for 2026-05-27
    target_date = "2026-05-27"
    day_candles = [c for c in candles if c['date'] == target_date]
    
    print(f"\n=== 15-Minute Candles for {target_date} ===")
    print(f"{'Time':<20} | {'Close':<8} | {'L':<8} | {'Whale':<8} | {'Sugeub Spike':<12} | {'Perfect Break':<12}")
    print("-" * 80)
    for c in day_candles:
        time_str = c['time']
        close_val = c['close']
        L_val = f"{c.get('L'):.1f}" if c.get('L') is not None else "None"
        whale_val = f"{c.get('whale_line'):.1f}" if c.get('whale_line') is not None else "None"
        spike_str = str(c.get('signal_sugeub_spike', False))
        break_str = str(c.get('signal_perfect_breakout', False))
        print(f"{time_str:<20} | {close_val:<8} | {L_val:<8} | {whale_val:<8} | {spike_str:<12} | {break_str:<12}")

if __name__ == "__main__":
    main()
