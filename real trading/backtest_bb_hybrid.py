import asyncio
import pandas as pd
import numpy as np
from kiwoom_client import KiwoomClient

async def main():
    print("Initializing Kiwoom Client and fetching historical data...")
    client = KiwoomClient()
    
    # Fetch 15-minute candles for the last 60 days (gives a good sample size)
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
    
    # Calculate Indicators
    df['SMA5'] = df['Close'].rolling(window=5).mean()
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['SMA40'] = df['Close'].rolling(window=40).mean()
    df['SMA60'] = df['Close'].rolling(window=60).mean()
    
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['UpperBB'] = df['SMA20'] + (df['STD20'] * 2)
    df['LowerBB'] = df['SMA20'] - (df['STD20'] * 2)
    
    # Drop NaNs
    df = df.dropna().reset_index(drop=True)
    
    # Backtest variables
    initial_cash = 10_000_000
    
    def run_backtest(use_bb=False):
        cash = initial_cash
        holdings = 0
        buy_price = 0
        entry_reason = ""
        
        trades = []
        
        for i in range(2, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            pprev = df.iloc[i-2]
            
            # --- SELL LOGIC ---
            if holdings > 0:
                sell_signal = False
                sell_reason = ""
                
                # 1. Stop Loss (-2%)
                if curr['Close'] <= buy_price * 0.98:
                    sell_signal = True
                    sell_reason = "Stop Loss (-2%)"
                
                # 2. K-Peak Exit (Valid for SMA or BB entry)
                if not sell_signal:
                    is_bull = (curr['SMA5'] > curr['SMA20']) and (curr['SMA20'] > curr['SMA60'])
                    if is_bull:
                        if pprev['Close'] < prev['Close'] and prev['Close'] > curr['Close']:
                            sell_signal = True
                            sell_reason = "K-Peak Exit"
                            
                # 3. BB Upper Touch Exit (Only if BB was used)
                if use_bb and not sell_signal:
                    if curr['High'] >= curr['UpperBB']:
                        sell_signal = True
                        sell_reason = "BB Upper Touch"
                        
                if sell_signal:
                    sell_price = curr['Close']
                    revenue = holdings * sell_price
                    profit = revenue - (holdings * buy_price)
                    cash += revenue
                    trades.append({
                        'buy_time': buy_time,
                        'sell_time': curr['Time'],
                        'entry_reason': entry_reason,
                        'exit_reason': sell_reason,
                        'buy_price': buy_price,
                        'sell_price': sell_price,
                        'profit': profit,
                        'return_pct': (sell_price / buy_price - 1) * 100
                    })
                    holdings = 0
                    buy_price = 0
                    continue # Finished processing sell
            
            # --- BUY LOGIC ---
            if holdings == 0:
                buy_signal = False
                reason = ""
                
                # Condition 1: SMA 20 > 40 Golden Cross
                if prev['SMA20'] <= prev['SMA40'] and curr['SMA20'] > curr['SMA40']:
                    buy_signal = True
                    reason = "SMA Cross"
                
                # Condition 2: BB Lower Touch (Only if use_bb is True)
                if use_bb and not buy_signal:
                    # To avoid falling knives, buy when it touches lower BB and starts bouncing (Close > Open or similar)
                    # Simple approach: Close <= LowerBB
                    if curr['Close'] <= curr['LowerBB']:
                        buy_signal = True
                        reason = "BB Lower Touch"
                        
                if buy_signal:
                    buy_price = curr['Close']
                    holdings = int(cash // buy_price)
                    if holdings > 0:
                        cash -= holdings * buy_price
                        buy_time = curr['Time']
                        entry_reason = reason
                        
        # Close out any remaining position at the end
        if holdings > 0:
            sell_price = df.iloc[-1]['Close']
            revenue = holdings * sell_price
            profit = revenue - (holdings * buy_price)
            cash += revenue
            trades.append({
                        'buy_time': buy_time,
                        'sell_time': df.iloc[-1]['Time'],
                        'entry_reason': entry_reason,
                        'exit_reason': 'End of Period',
                        'buy_price': buy_price,
                        'sell_price': sell_price,
                        'profit': profit,
                        'return_pct': (sell_price / buy_price - 1) * 100
                    })
            
        final_return = ((cash - initial_cash) / initial_cash) * 100
        win_trades = [t for t in trades if t['profit'] > 0]
        win_rate = (len(win_trades) / len(trades) * 100) if trades else 0
        
        return {
            'final_cash': cash,
            'return_pct': final_return,
            'total_trades': len(trades),
            'win_rate': win_rate,
            'trades': trades
        }

    print("\n[1] Running Base Strategy (SMA 20/40 Cross Only)...")
    base_res = run_backtest(use_bb=False)
    print(f"Base Final Return: {base_res['return_pct']:.2f}% | Win Rate: {base_res['win_rate']:.2f}% | Trades: {base_res['total_trades']}")
    
    print("\n[2] Running Hybrid Strategy (SMA + BB Lower Touch)...")
    hybrid_res = run_backtest(use_bb=True)
    print(f"Hybrid Final Return: {hybrid_res['return_pct']:.2f}% | Win Rate: {hybrid_res['win_rate']:.2f}% | Trades: {hybrid_res['total_trades']}")
    
    print("\n--- Detailed Hybrid Trades ---")
    for t in hybrid_res['trades']:
        print(f"Buy: {t['buy_time']} [{t['entry_reason']}] @ {t['buy_price']:,.0f} -> Sell: {t['sell_time']} [{t['exit_reason']}] @ {t['sell_price']:,.0f} | Profit: {t['return_pct']:.2f}%")

if __name__ == "__main__":
    asyncio.run(main())
