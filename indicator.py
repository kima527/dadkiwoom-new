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

def calculate_ema(prices, period):
    """
    Calculates Exponential Moving Average (지수이동평균).
    Handles None values in input for chained EMA calculations (e.g., EMA of EMA).
    First valid EMA value is seeded with SMA of the first 'period' non-None values.
    """
    n = len(prices)
    ema = [None] * n
    k = 2.0 / (period + 1)

    # Find the first index where we have 'period' consecutive non-None values
    seed_start = None
    for i in range(n - period + 1):
        window = prices[i:i + period]
        if all(v is not None for v in window):
            seed_start = i
            break

    if seed_start is None:
        return ema  # Not enough data

    # Seed EMA with SMA of the first valid window
    seed_end = seed_start + period - 1
    ema[seed_end] = sum(prices[seed_start:seed_end + 1]) / float(period)

    # Calculate remaining EMA values
    for i in range(seed_end + 1, n):
        if prices[i] is not None and ema[i - 1] is not None:
            ema[i] = prices[i] * k + ema[i - 1] * (1 - k)

    return ema

def calculate_tema(prices, period):
    """
    Calculates Triple Exponential Moving Average (TEMA / 삼중지수이동평균).
    TEMA = 3*EMA1 - 3*EMA2 + EMA3
    where EMA1 = EMA(close, period), EMA2 = EMA(EMA1, period), EMA3 = EMA(EMA2, period)
    """
    ema1 = calculate_ema(prices, period)
    ema2 = calculate_ema(ema1, period)
    ema3 = calculate_ema(ema2, period)

    tema = []
    for i in range(len(prices)):
        if ema1[i] is not None and ema2[i] is not None and ema3[i] is not None:
            tema.append(3.0 * ema1[i] - 3.0 * ema2[i] + ema3[i])
        else:
            tema.append(None)
    return tema

def calculate_indicators_pure(candles, use_compressed_peak=True, tema_period1=5, tema_period2=20):
    """
    Calculates technical indicators for a list of candle dictionaries in-place.
    Each candle should have 'close' (float).
    
    Adds fields:
      - sma5, sma20, sma60
      - K, L
      - wma5, wma20
      - signal_buy_prep, signal_buy, signal_sell
      - tema1, tema2, tema_gate_line, disparity_pct
      - signal_buy_prep_tema, signal_buy_tema
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

    # 5. Signals & State Tracking (K/L, Whale line, Surge, Sell, Rebuy)
    last_whale = None
    is_surged = False
    recent_sell = False
    neg_count = 0
    
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

        # Whale Line (세력선): valuewhen(1, crossup(sma5, L), sma5)
        if i > 0 and c['sma5'] is not None and c['L'] is not None and c_prev['sma5'] is not None and c_prev['L'] is not None:
            if c_prev['sma5'] < c_prev['L'] and c['sma5'] >= c['L']:
                last_whale = c['sma5']
                is_surged = False  # Reset surge state when whale line updates
        c['whale_line'] = last_whale

        # Check for Surge (관문선과 세력선폭의 2배이상 상승)
        if c['K'] is not None and c['whale_line'] is not None:
            width = abs(c['K'] - c['whale_line'])
            target_price = c['K'] + (width * 2)
            if c['high'] >= target_price:
                is_surged = True
        
        c['is_surged'] = is_surged

        # Sell Condition 1: Surge & Drop below L (기준선 안으로 캔들이 들어올때)
        signal_sell_1 = False
        if is_surged and c['L'] is not None and c_prev is not None and c_prev['L'] is not None:
            # Drop below L (crossdown L)
            if c_prev['close'] >= c_prev['L'] and c['close'] < c['L']:
                signal_sell_1 = True
                is_surged = False  # Reset after sell

        # Sell Condition 2: 5 SMA dead crosses 20 SMA
        signal_sell_2 = False
        if c['sma5'] is not None and c['sma20'] is not None and c_prev is not None and c_prev['sma5'] is not None and c_prev['sma20'] is not None:
            if c['sma5'] < c['sma20'] and c_prev['sma5'] >= c_prev['sma20']:
                signal_sell_2 = True
                
        c['signal_sell_market_1'] = signal_sell_1
        c['signal_sell_market_2'] = signal_sell_2
        
        # Legacy sell signal mapping
        c['signal_sell'] = signal_sell_1 or signal_sell_2

        # Rebuy Condition: After sell, 1st or 2nd negative candle where SMA 5 turns upward
        signal_rebuy = False
        if signal_sell_1 or signal_sell_2:
            recent_sell = True
            neg_count = 0
        elif recent_sell:
            # Check if it's a negative candle (음봉)
            # Assuming we only have 'close' in mock, but real API gives 'open'. If 'open' is missing, fallback to c_prev['close'] > c['close']
            open_price = c.get('open', c_prev['close'] if c_prev else c['close'])
            if c['close'] < open_price:
                neg_count += 1
                if i > 0 and c['sma5'] is not None and c_prev['sma5'] is not None:
                    if c['sma5'] > c_prev['sma5']:
                        signal_rebuy = True
                        recent_sell = False  # Reset after rebuy
                if neg_count >= 2:
                    recent_sell = False  # Stop tracking after 2nd negative candle
                    
        c['signal_rebuy'] = signal_rebuy

    # 6. TEMA Gate Line (테마급등관문선)
    # TEMA1 = TEMA(close, 기간1), TEMA2 = TEMA(close, 기간2)
    # 조건 = CrossUp(TEMA1, TEMA2)
    # 관문선 = ValueWhen(1, 조건, TEMA1)
    tema1 = calculate_tema(closes, tema_period1)
    tema2 = calculate_tema(closes, tema_period2)

    gate_line_val = None
    for i in range(n):
        candles[i]['tema1'] = tema1[i]
        candles[i]['tema2'] = tema2[i]

        # CrossUp: TEMA1이 TEMA2를 상향돌파하는 순간
        if (i > 0
                and tema1[i] is not None and tema2[i] is not None
                and tema1[i-1] is not None and tema2[i-1] is not None):
            if tema1[i-1] < tema2[i-1] and tema1[i] >= tema2[i]:
                gate_line_val = tema1[i]  # ValueWhen(1, 조건, TEMA1)

        candles[i]['tema_gate_line'] = gate_line_val

        # Disparity: 현재가와 관문선의 이격도 (%)
        if gate_line_val is not None and gate_line_val > 0:
            candles[i]['disparity_pct'] = abs(candles[i]['close'] - gate_line_val) / gate_line_val * 100.0
        else:
            candles[i]['disparity_pct'] = None

    # 7. TEMA Gate Line Signals (관문선 기반 매매 시그널)
    for i in range(n):
        c = candles[i]
        c_prev = candles[i-1] if i > 0 else None

        # Buy Prep (TEMA): 현재가가 관문선 1% 이내 밑에 도달
        if c['tema_gate_line'] is not None:
            c['signal_buy_prep_tema'] = (
                c['close'] >= c['tema_gate_line'] * 0.99
                and c['close'] < c['tema_gate_line']
            )
        else:
            c['signal_buy_prep_tema'] = False

        # Buy (TEMA): 현재가가 관문선을 상향돌파
        if (c['tema_gate_line'] is not None
                and c_prev is not None
                and c_prev.get('tema_gate_line') is not None):
            c['signal_buy_tema'] = (
                c['close'] >= c['tema_gate_line']
                and c_prev['close'] < c_prev['tema_gate_line']
            )
        else:
            c['signal_buy_tema'] = False

    # 8. Dynamic Buy Signal (상승장 vs 하락장 반등 매수 전략 구분)
    # 상승중(sma5 > sma20)일 때는 L선 상향돌파(signal_buy)를 매수 신호로 함
    # 하락 후 반등중(sma5 <= sma20)일 때는 TEMA 관문선 돌파(signal_buy_tema)를 매수 신호로 함
    for i in range(n):
        c = candles[i]
        s5 = c.get('sma5')
        s20 = c.get('sma20')
        
        if s5 is not None and s20 is not None:
            if s5 > s20:
                c['signal_buy_dynamic'] = c.get('signal_buy', False)
                c['buy_condition_type'] = "L-line (Uptrend)"
            else:
                c['signal_buy_dynamic'] = c.get('signal_buy_tema', False)
                c['buy_condition_type'] = "TEMA Gate (Rebound)"
        else:
            c['signal_buy_dynamic'] = False
            c['buy_condition_type'] = "N/A"
            
    return candles

if __name__ == "__main__":
    print("Testing pure Python technical indicator logic...")
    print("TEMA Period1=5, Period2=20")
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
    res = calculate_indicators_pure(mock_candles, use_compressed_peak=True, tema_period1=5, tema_period2=20)
    
    print("\nSample Results (Tail where indicators are active):")
    fmt = "{:<5} | {:<7} | {:<7} | {:<7} | {:<7} | {:<7} | {:<10} | {:<8} | {:<5} | {:<5} | {:<5}"
    print(fmt.format("Index", "Close", "SMA5", "SMA60", "K", "L", "TEMA_Gate", "Disp%", "B_Prep", "Buy", "Sell"))
    print("-" * 105)
    for idx, c in enumerate(res[55:]):
        real_idx = 55 + idx
        print(fmt.format(
            real_idx,
            c['close'],
            round(c['sma5'], 2) if c['sma5'] else "None",
            round(c['sma60'], 2) if c['sma60'] else "None",
            round(c['K'], 2) if c['K'] else "None",
            round(c['L'], 2) if c['L'] else "None",
            round(c['tema_gate_line'], 2) if c.get('tema_gate_line') else "None",
            round(c['disparity_pct'], 2) if c.get('disparity_pct') is not None else "None",
            str(c['signal_buy_prep']),
            str(c['signal_buy']),
            str(c['signal_sell'])
        ))
