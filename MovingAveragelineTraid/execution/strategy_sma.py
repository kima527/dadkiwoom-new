import pandas as pd
import ta

def calculate_sma_signals(df: pd.DataFrame) -> dict:
    """
    Calculate SMAs and return trading signals based on 15m SMA Strategy.
    df must have a 'close' column.
    """
    if len(df) < 20:
        return {"buy": False, "sell": False, "sma20": 0.0}

    # Calculate SMAs
    df['sma3'] = ta.trend.sma_indicator(df['close'], window=3)
    df['sma5'] = ta.trend.sma_indicator(df['close'], window=5)
    df['sma20'] = ta.trend.sma_indicator(df['close'], window=20)

    # Get the latest values
    latest = df.iloc[-1]
    
    sma3 = latest['sma3']
    sma5 = latest['sma5']
    sma20 = latest['sma20']
    
    # 1. Buy Signal: SMA 3 > SMA 5 > SMA 20 (Perfect short-term order)
    buy_signal = (sma3 > sma5) and (sma5 > sma20)
    
    # 2. Sell Signal: Dead Cross or Trend Break
    # Dead Cross: SMA 3 < SMA 5
    # Trend Break: Close < SMA 20
    sell_signal = (sma3 < sma5) or (latest['close'] < sma20)
    
    return {
        "buy": buy_signal,
        "sell": sell_signal,
        "sma20": sma20
    }
