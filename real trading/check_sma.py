import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from kiwoom_client import KiwoomClient
from data_manager import RealtimeDataManager
from indicator import calculate_sma

async def main():
    client = KiwoomClient()
    if not client.test_connection():
        print("Failed to connect to Kiwoom API")
        return
    
    print("Fetching 5-minute candles...")
    past_5m = client.get_5min_candles("005930", 10)
    
    dm = RealtimeDataManager("005930", "삼성전자", 0.0)
    dm.seed_initial_data([], past_5m, [], [])
    
    candles = dm.get_completed_and_current_5m_candles()
    if len(candles) < 60:
        print("Not enough candles")
        return
        
    closes = [c['close'] for c in candles]
    sma3_list = calculate_sma(closes, 3)
    sma60_list = calculate_sma(closes, 60)
    
    curr_sma3 = sma3_list[-1]
    curr_sma60 = sma60_list[-1]
    
    print(f"Current price: {dm.latest_price}")
    print(f"SMA 3: {curr_sma3:.2f}")
    print(f"SMA 60: {curr_sma60:.2f}")
    
    # Also print previous ones just in case
    print(f"Prev SMA 3: {sma3_list[-2]:.2f}")
    print(f"Prev SMA 60: {sma60_list[-2]:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
