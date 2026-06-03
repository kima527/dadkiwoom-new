import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Paper trading")))

from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure

def inspect_stock(code, name, target_date):
    client = KiwoomClient()
    print(f"\n--- Daily Candles for {name} ({code}) ---")
    daily_candles = client.get_daily_candles(code, last_n_days=90)
    if not daily_candles:
        print(f"Failed to fetch daily candles for {code}.")
        return
        
    calculate_indicators_pure(
        daily_candles,
        use_compressed_peak=True
    )
    
    # Print the last 15 days
    for c in daily_candles[-15:]:
        prefix = ">> " if c['date'] == target_date else "   "
        print(f"{prefix}Date: {c['date']} | Close: {c['close']:,.0f} | L: {f'{c.get('L'):,.0f}' if c.get('L') is not None else 'None'} | Whale: {f'{c.get('whale_line'):,.0f}' if c.get('whale_line') is not None else 'None'}")

def main():
    inspect_stock("018260", "Samsung SDS", "2026-05-26")
    inspect_stock("012330", "Hyundai Mobis", "2026-05-28")

if __name__ == "__main__":
    main()
