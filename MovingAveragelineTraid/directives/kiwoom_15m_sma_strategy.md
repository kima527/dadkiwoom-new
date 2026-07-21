# Kiwoom 15m SMA Strategy Directive

## Overview
This strategy uses 15-minute candles and Simple Moving Averages (SMA) to capture short-term explosive momentum in target stocks.

## Buy Logic (Entry)
1. **Trend & Signal Filter**:
   - The stock must satisfy **SMA 3 > SMA 5 > SMA 20** on the 15-minute timeframe.
   - This "Perfect short-term order" represents explosive momentum.

2. **Priority Filtering**:
   - If multiple stocks generate a signal simultaneously, calculate a priority score:
     `Priority Score = Theme Weight (from watchlist.json) * Momentum Score`
   - Momentum Score is derived from the recent trade speed/acceleration (e.g., how quickly trades are hitting the ask price).

3. **3-Second Observation & Safety Zone Limit Order (Rate Limit Solution)**:
   - When the top priority stock is identified, the bot must wait exactly **3 seconds**.
   - After 3 seconds, fetch the recent tick data (1 API call).
   - Calculate a "Safety Zone" (the expected lowest point of the current fluctuation, typically the SMA 20 line or recent tick low).
   - Calculate buy quantity: `(Available Cash * 0.95) // Safety Zone Price`.
   - Place a **Limit Order (지정가 매수)** at the Safety Zone price.

## Sell Logic (Exit)
1. **Take Profit (Dead Cross)**:
   - Sell when SMA 3 crosses below SMA 5.
2. **Trend Break**:
   - Sell if the price closes below SMA 20.
3. **Stop Loss**:
   - Sell immediately if the price drops by -3% from the entry average price.
