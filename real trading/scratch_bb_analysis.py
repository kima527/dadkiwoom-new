import asyncio
import pandas as pd
import numpy as np
from kiwoom_client import KiwoomClient

async def main():
    client = KiwoomClient()
    # Fetch enough 15-minute candles to cover July 7 to July 9
    candles = await asyncio.to_thread(client.get_15min_candles, '005930', 20)
    if not candles:
        print("No data fetched.")
        return
        
    df = pd.DataFrame({'Time': [c['time'] for c in candles], 'Close': [c['close'] for c in candles], 'High': [c['high'] for c in candles], 'Low': [c['low'] for c in candles]})
    
    # Calculate SMA 20/40
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA40'] = df['Close'].rolling(window=40).mean()
    
    # Calculate Bollinger Bands (20, 2)
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['Upper'] = df['SMA20'] + (df['STD20'] * 2)
    df['Lower'] = df['SMA20'] - (df['STD20'] * 2)
    
    # Filter for dates July 7 to July 9
    # Format of 'Time' is 'YYYY-MM-DD HH:MM:00'
    mask = (df['Time'] >= '2026-07-07 00:00:00') & (df['Time'] <= '2026-07-09 23:59:59')
    target_df = df[mask].copy()
    
    if target_df.empty:
        print("No data found for July 7 to 9.")
        return
        
    print("--- Data from July 7 to July 9 (15m) ---")
    for idx, row in target_df.iterrows():
        # Check SMA cross
        prev_sma20 = df['SMA20'].iloc[idx-1]
        prev_sma40 = df['SMA40'].iloc[idx-1]
        sma_signal = ""
        if prev_sma20 <= prev_sma40 and row['SMA20'] > row['SMA40']:
            sma_signal = " [SMA Golden Cross BUY]"
        elif prev_sma20 >= prev_sma40 and row['SMA20'] < row['SMA40']:
            sma_signal = " [SMA Dead Cross SELL]"
            
        # Check BB lower touch
        bb_signal = ""
        if row['Low'] <= row['Lower']:
            bb_signal = " [BB Lower Touch BUY]"
        if row['High'] >= row['Upper']:
            bb_signal += " [BB Upper Touch SELL]"
            
        print(f"{row['Time']} | Close: {row['Close']:,.0f} | Low: {row['Low']:,.0f} | LowerBB: {row['Lower']:,.0f} | SMA20: {row['SMA20']:,.0f} | SMA40: {row['SMA40']:,.0f} {sma_signal}{bb_signal}")
    
    print("\n--- Summary ---")
    print("Max Price:", target_df['High'].max())
    print("Min Price:", target_df['Low'].min())

asyncio.run(main())
