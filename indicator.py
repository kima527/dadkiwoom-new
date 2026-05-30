def calculate_sma(prices, period):
    """Calculates SMA. Returns a list of values of same length as prices."""
    sma = []
    for i in range(len(prices)):
        if i >= period - 1:
            window = prices[i - period + 1 : i + 1]
            sma.append(sum(window) / float(period))
        else:
            sma.append(None)
    return sma

def calculate_wma(prices, period):
    """Calculates Linear Weighted Moving Average."""
    wma = []
    denom = sum(range(1, period + 1))
    for i in range(len(prices)):
        if i >= period - 1:
            val = sum((j + 1) * prices[i - period + 1 + j] for j in range(period))
            wma.append(val / float(denom))
        else:
            wma.append(None)
    return wma

def calculate_indicators_pure(candles, use_compressed_peak=True):
    """
    Calculates technical indicators for a list of candle dictionaries in-place.
    Each candle should have 'close' (float).
    
    Adds fields:
      - sma5, sma20, sma60
      - K
      - L
      - wma5, wma20
      - signal_buy_prep, signal_buy, signal_sell
    """
    n = len(candles)
    if n == 0:
        return candles

    closes = [c['close'] for c in candles]
    
    # 1. SMAs
    sma5 = calculate_sma(closes, 5)
    sma20 = calculate_sma(closes, 20)
    sma60 = calculate_sma(closes, 60)
    
    for i in range(n):
        candles[i]['sma5'] = sma5[i]
        candles[i]['sma20'] = sma20[i]
        candles[i]['sma60'] = sma60[i]

    # 2. Perfect Alignment & K-line
    last_K = None
    for i in range(n):
        c = candles[i]
        s5 = c['sma5']
        s20 = c['sma20']
        s60 = c['sma60']
        
        if s5 is not None and s20 is not None and s60 is not None:
            if s5 > s20 and s20 > s60:
                last_K = c['close']
        c['K'] = last_K

    # 3. L-line (valuewhen of K peaks)
    last_L = None
    if use_compressed_peak:
        # Option B: Compressed Sequence Peak
        # Find points where K changes
        compressed_K = [] # list of (timeline_index, K_value)
        for i in range(n):
            k_val = candles[i]['K']
            if k_val is not None:
                if not compressed_K or compressed_K[-1][1] != k_val:
                    compressed_K.append((i, k_val))
        
        # Find peaks in compressed_K
        peaks = {} # timeline_index -> peak_value
        for idx in range(2, len(compressed_K)):
            k_2 = compressed_K[idx-2][1]
            k_1 = compressed_K[idx-1][1]
            k_0 = compressed_K[idx][1]
            
            if k_2 < k_1 and k_1 > k_0:
                # Peak value is k_1, confirmed at the index of k_0
                confirm_idx = compressed_K[idx][0]
                peaks[confirm_idx] = k_1
                
        current_L = None
        for i in range(n):
            if i in peaks:
                current_L = peaks[i]
            candles[i]['L'] = current_L
    else:
        # Option A: Literal Evaluation
        for i in range(n):
            if i >= 2:
                k_2 = candles[i-2]['K']
                k_1 = candles[i-1]['K']
                k_0 = candles[i]['K']
                
                if k_2 is not None and k_1 is not None and k_0 is not None:
                    if k_2 < k_1 and k_1 > k_0:
                        last_L = k_1
            candles[i]['L'] = last_L

    # 4. WMAs
    wma5 = calculate_wma(closes, 5)
    wma20 = calculate_wma(closes, 20)
    
    for i in range(n):
        candles[i]['wma5'] = wma5[i]
        candles[i]['wma20'] = wma20[i]

    # 5. Signals
    for i in range(n):
        c = candles[i]
        c_prev = candles[i-1] if i > 0 else None
        
        # Buy Prep: Close is within 1% under L (L * 0.99 <= Close < L)
        if c['L'] is not None:
            c['signal_buy_prep'] = (c['close'] >= c['L'] * 0.99) and (c['close'] < c['L'])
        else:
            c['signal_buy_prep'] = False
            
        # Buy: Close passes L (Close >= L) and previous Close was below previous L
        if c['L'] is not None and c_prev is not None and c_prev['L'] is not None:
            c['signal_buy'] = (c['close'] >= c['L']) and (c_prev['close'] < c_prev['L'])
        else:
            c['signal_buy'] = False
            
        # Sell: WMA 5 crosses below WMA 20
        if c['wma5'] is not None and c['wma20'] is not None and c_prev is not None and c_prev['wma5'] is not None and c_prev['wma20'] is not None:
            c['signal_sell'] = (c['wma5'] < c['wma20']) and (c_prev['wma5'] >= c_prev['wma20'])
        else:
            c['signal_sell'] = False
            
    return candles

if __name__ == "__main__":
    print("Testing pure Python technical indicator logic...")
    # We need at least 80 bars to test SMA 60 properly.
    # 0 to 59: flat at 100.0
    prices = [100.0] * 60
    
    # 60 to 75: rising prices (102 to 132) -> perfect alignment
    for i in range(16):
        prices.append(102.0 + i * 2.0)
        
    # 76: peak at 138.0 -> still aligned
    prices.append(138.0)
    
    # 77 to 85: dropping prices (125, 120, 115...) -> alignment breaks, K becomes flat
    for p in [128.0, 125.0, 120.0, 118.0, 115.0, 115.0, 115.0]:
        prices.append(p)
        
    # 86 to 90: rise again to form a second peak
    for i in range(5):
        prices.append(120.0 + i * 3.0) # 120, 123, 126, 129, 132
    prices.append(135.0) # peak 2
    prices.append(125.0) # drop again
    
    mock_candles = [{'close': p} for p in prices]
    res = calculate_indicators_pure(mock_candles, use_compressed_peak=True)
    
    print("\nSample Results (Tail where indicators are active):")
    fmt = "{:<5} | {:<7} | {:<7} | {:<7} | {:<7} | {:<7} | {:<5} | {:<5} | {:<5}"
    print(fmt.format("Index", "Close", "SMA5", "SMA60", "K", "L", "B_Prep", "Buy", "Sell"))
    print("-" * 75)
    for idx, c in enumerate(res[65:]):
        real_idx = 65 + idx
        print(fmt.format(
            real_idx,
            c['close'],
            round(c['sma5'], 2) if c['sma5'] else "None",
            round(c['sma60'], 2) if c['sma60'] else "None",
            round(c['K'], 2) if c['K'] else "None",
            round(c['L'], 2) if c['L'] else "None",
            str(c['signal_buy_prep']),
            str(c['signal_buy']),
            str(c['signal_sell'])
        ))

