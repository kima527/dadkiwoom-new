import asyncio
import pandas as pd
from kiwoom_client import KiwoomClient
from data_manager import RealtimeDataManager

async def main():
    client = KiwoomClient()
    dm = RealtimeDataManager(client, "005930")
    print("Fetching data...")
    # Seed data
    await dm.seed_initial_data(days=3)
    
    # Give it a second to fetch
    await asyncio.sleep(2)
    
    candles = dm.get_completed_and_current_15m_candles()
    if len(candles) == 0:
        print("No candles fetched.")
        return
        
    closes = [c['close'] for c in candles]
    current_price = dm.latest_price
    print(f"Total candles: {len(candles)}")
    print(f"Current Price: {current_price}")
    
    df = pd.DataFrame({'Close': closes})
    df['SMA5'] = df['Close'].rolling(window=5).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA40'] = df['Close'].rolling(window=40).mean()
    df['SMA60'] = df['Close'].rolling(window=60).mean()
    
    print("\n--- Recent 3 Candles (15m) ---")
    print(df.tail(3)[['Close', 'SMA5', 'SMA20', 'SMA40', 'SMA60']])
    
    sma20 = df['SMA20'].iloc[-1]
    sma40 = df['SMA40'].iloc[-1]
    
    print("\n--- Strategy State ---")
    if sma20 > sma40:
        print("상태: 골든크로스 / 상승 추세 (SMA20 > SMA40)")
    else:
        print("상태: 역배열 대기 (SMA20 <= SMA40)")

if __name__ == "__main__":
    asyncio.run(main())
