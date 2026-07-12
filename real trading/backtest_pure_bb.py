import asyncio
import pandas as pd
import numpy as np
from kiwoom_client import KiwoomClient

async def main():
    print("Initializing Kiwoom Client and fetching historical data...")
    client = KiwoomClient()
    
    # Fetch 15-minute candles for the last 60 days
    candles = await asyncio.to_thread(client.get_15min_candles, '005930', 60)
    if not candles:
        print("No data fetched.")
        return
        
    df = pd.DataFrame({
        'Time': [c['time'] for c in candles],
        'Close': [c['close'] for c in candles],
        'High': [c['high'] for c in candles],
        'Low': [c['low'] for c in candles]
    })
    
    # Calculate Bollinger Bands
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['UpperBB'] = df['SMA20'] + (df['STD20'] * 2)
    df['LowerBB'] = df['SMA20'] - (df['STD20'] * 2)
    
    # Drop NaNs
    df = df.dropna().reset_index(drop=True)
    
    # Backtest variables
    initial_cash = 10_000_000
    cash = initial_cash
    holdings = 0
    buy_price = 0
    trades = []
    
    max_drawdown = 0
    peak_cash = initial_cash
    
    for i in range(2, len(df)):
        curr = df.iloc[i]
        
        # Calculate Drawdown if holding
        if holdings > 0:
            current_value = cash + (holdings * curr['Close'])
            if current_value > peak_cash:
                peak_cash = current_value
            dd = (peak_cash - current_value) / peak_cash * 100
            if dd > max_drawdown:
                max_drawdown = dd
                
        # --- SELL LOGIC ---
        if holdings > 0:
            # ONLY Sell at Upper Band Touch (기본 원칙)
            if curr['High'] >= curr['UpperBB']:
                sell_price = curr['Close']
                revenue = holdings * sell_price
                profit = revenue - (holdings * buy_price)
                cash += revenue
                trades.append({
                    'buy_time': buy_time,
                    'sell_time': curr['Time'],
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit': profit,
                    'return_pct': (sell_price / buy_price - 1) * 100
                })
                holdings = 0
                buy_price = 0
                continue
        
        # --- BUY LOGIC ---
        if holdings == 0:
            # Buy at Lower Band Touch (기본 원칙)
            if curr['Low'] <= curr['LowerBB']:
                buy_price = curr['Close']
                holdings = int(cash // buy_price)
                if holdings > 0:
                    cash -= holdings * buy_price
                    buy_time = curr['Time']

    # Close out any remaining position at the end
    if holdings > 0:
        sell_price = df.iloc[-1]['Close']
        revenue = holdings * sell_price
        profit = revenue - (holdings * buy_price)
        cash += revenue
        trades.append({
                    'buy_time': buy_time,
                    'sell_time': df.iloc[-1]['Time'] + " (End)",
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'profit': profit,
                    'return_pct': (sell_price / buy_price - 1) * 100
                })
        
    final_return = ((cash - initial_cash) / initial_cash) * 100
    
    print("\n--- Pure Bollinger Band Strategy (No Stop Loss) ---")
    print(f"Final Return: {final_return:.2f}%")
    print(f"Max Drawdown (최대 손실폭): -{max_drawdown:.2f}%")
    print(f"Total Trades: {len(trades)}")
    
    for t in trades:
        print(f"Buy: {t['buy_time']} @ {t['buy_price']:,.0f} -> Sell: {t['sell_time']} @ {t['sell_price']:,.0f} | Profit: {t['return_pct']:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
