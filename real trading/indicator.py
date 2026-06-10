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

def calculate_bollinger_bands(prices, period, num_std=2.0):
    """Calculates Bollinger Bands upper, mid, lower bands."""
    import math
    upper_band = []
    lower_band = []
    mid_band = []
    
    sma = calculate_sma(prices, period)
    
    for i in range(len(prices)):
        if i >= period - 1:
            window = prices[i - period + 1 : i + 1]
            mean = sma[i]
            if mean is None:
                mid_band.append(None)
                upper_band.append(None)
                lower_band.append(None)
                continue
            variance = sum((x - mean) ** 2 for x in window) / float(period)
            std_dev = math.sqrt(variance)
            mid_band.append(mean)
            upper_band.append(mean + num_std * std_dev)
            lower_band.append(mean - num_std * std_dev)
        else:
            mid_band.append(None)
            upper_band.append(None)
            lower_band.append(None)
            
    return upper_band, mid_band, lower_band

def calculate_indicators_pure(candles, use_compressed_peak=True, tema_period1=5, tema_period2=20):
    """
    Calculates technical indicators for a list of candle dictionaries in-place.
    Each candle should have 'close' (float).
    
    Adds fields:
      - sma5, sma20, sma60
      - K, L
      - wma5, wma20
      - ema40
      - signal_buy_prep, signal_buy, signal_sell
      - signal_sell_l_break  : L선 하향 이탈 (상승 후 L선 안으로 진입)
      - signal_buy_ema40     : EMA40 접셨 (저가 ≤ EMA40 ≤ 고가)
      - tema1, tema2, tema_gate_line, disparity_pct
      - signal_buy_prep_tema, signal_buy_tema
      - sugeub, signal_sugeub_spike, signal_perfect_breakout
    """
    n = len(candles)
    if n == 0:
        return candles

    closes = [c['close'] for c in candles]
    
    # 1. SMAs & TEMA
    sma5 = calculate_sma(closes, 5)
    sma20 = calculate_sma(closes, 20)
    sma40 = calculate_sma(closes, 40)
    tema60 = calculate_tema(closes, 60)
    tema20 = calculate_tema(closes, 20)
    
    for i in range(n):
        candles[i]['sma5'] = sma5[i]
        candles[i]['sma20'] = sma20[i]
        candles[i]['sma40'] = sma40[i]
        candles[i]['tema60'] = tema60[i]
        candles[i]['tema20'] = tema20[i]

    # 2. Perfect Alignment & K-line
    last_K = None
    for i in range(n):
        c = candles[i]
        s5 = c['sma5']
        s20 = c['sma20']
        t60 = c['tema60']
        
        if s5 is not None and s20 is not None and t60 is not None:
            if s5 > s20 and s20 > t60:
                last_K = c['close']
        c['K'] = last_K
        c['K_static'] = last_K

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

    # 3-b. Whale Line (세력선): valuewhen(1, crossup(sma5, L), sma5)
    last_whale = None
    for i in range(n):
        c = candles[i]
        c_prev = candles[i-1] if i > 0 else None
        if i > 0 and c['sma5'] is not None and c['L'] is not None and c_prev['sma5'] is not None and c_prev['L'] is not None:
            if c_prev['sma5'] < c_prev['L'] and c['sma5'] >= c['L']:
                last_whale = c['sma5']
        c['whale_line'] = last_whale

    # 4. WMAs
    wma5 = calculate_wma(closes, 5)
    wma20 = calculate_wma(closes, 20)
    
    for i in range(n):
        candles[i]['wma5'] = wma5[i]
        candles[i]['wma20'] = wma20[i]

    # 4-b. EMA40 (지수이동평균 40스 접선)
    ema40 = calculate_ema(closes, 40)
    for i in range(n):
        candles[i]['ema40'] = ema40[i]

    # 4-c. TEMA 3 (삼중지수이동평균 3)
    tema3 = calculate_tema(closes, 3)
    for i in range(n):
        candles[i]['tema3'] = tema3[i]

    # 4-d. Bollinger Bands (5 and 20 periods)
    bb5_upper, bb5_mid, bb5_lower = calculate_bollinger_bands(closes, 5, 2.0)
    bb20_upper, bb20_mid, bb20_lower = calculate_bollinger_bands(closes, 20, 2.0)
    for i in range(n):
        candles[i]['bb5_upper'] = bb5_upper[i]
        candles[i]['bb5_mid'] = bb5_mid[i]
        candles[i]['bb5_lower'] = bb5_lower[i]
        candles[i]['bb20_upper'] = bb20_upper[i]
        candles[i]['bb20_mid'] = bb20_mid[i]
        candles[i]['bb20_lower'] = bb20_lower[i]

    # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
    # ── 4-e. TEMA Gate Line (calculated early to be used as stop loss) ──
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
                gate_line_val = tema1[i]

        candles[i]['tema_gate_line'] = gate_line_val

    # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
    # ── 5. Signals and Custom State Machine (TEMA 3 & SMA 60 Golden/Dead Cross + BB 5/20 Upper Sell & Lower Rebuy) ──
    virtual_holding = False
    has_seen_new_alignment_since_buy = False
    monitoring_sell = False
    has_crossed_bb5_upper = False
    waiting_for_bb_rebuy = False
    trade_K = None

    for i in range(n):
        c = candles[i]
        c_prev = candles[i-1] if i > 0 else None

        # Time window extraction for synchronization (08:00~12:00 only for first buy)
        try:
            t_part = c["time"].split(" ")[1]
            h = int(t_part.split(":")[0])
            is_buy_window = (8 <= h < 12)
        except Exception:
            is_buy_window = True

        # Initialize new signal fields
        c['signal_buy'] = False
        c['signal_sell_cond1'] = False
        c['signal_sell_cond2'] = False
        c['signal_sell'] = False
        c['sell_reason'] = None
        c['buy_condition_type'] = "N/A"
        c['signal_buy_bb_rebound'] = False

        # Preserve prep/rebound fields for backward compatibility to prevent Flask errors
        c['signal_buy_prep'] = False
        c['signal_buy_prep_tema'] = False
        c['signal_buy_tema'] = False
        c['signal_buy_ema40'] = False
        c['signal_buy_sma20_rebound'] = False
        c['signal_sell_second_line'] = False
        c['second_line_val'] = None

        # 1. Buy Signal (TEMA 3 > TEMA 60 and TEMA 60 Slope >= +0.05%)
        is_buy_signal = False
        if (c['tema3'] is not None and c['tema60'] is not None 
            and c_prev is not None and c_prev.get('tema60') is not None and c_prev['tema60'] != 0):
            slope = ((c['tema60'] - c_prev['tema60']) / c_prev['tema60']) * 100
            if c['tema3'] > c['tema60'] and slope >= 0.05:
                is_buy_signal = True

        # 2. Sell Signal Condition 1 (TEMA 3 & TEMA 60 Dead Cross State)
        is_sell_dead_signal = False
        if c['tema3'] is not None and c['tema60'] is not None:
            if c['tema3'] < c['tema60']:
                is_sell_dead_signal = True

        # Check 15m SMA 5 & TEMA 60 Dead Cross State (Macro Exit)
        is_15m_sma_dead = False
        if c['sma5'] is not None and c['tema60'] is not None:
            if c['sma5'] < c['tema60']:
                is_15m_sma_dead = True

        # 3. Custom Virtual Trade Tracker / State Machine
        if not virtual_holding:
            if waiting_for_bb_rebuy:
                # Check for rebuy cross (SMA5 Golden Cross TEMA60)
                is_rebuy_cross = False
                if (c['sma5'] is not None and c['tema60'] is not None
                        and c_prev is not None
                        and c_prev.get('sma5') is not None
                        and c_prev.get('tema60') is not None):
                    if c_prev['sma5'] < c_prev['tema60'] and c['sma5'] >= c['tema60']:
                        is_rebuy_cross = True

                if is_rebuy_cross:
                    virtual_holding = True
                    has_seen_new_alignment_since_buy = False
                    monitoring_sell = False
                    has_crossed_bb5_upper = False
                    waiting_for_bb_rebuy = False
                    trade_K = c['K_static'] if (c.get('K_static') is not None and c['K_static'] < c['close']) else None
                    c['signal_buy_bb_rebound'] = True
                    c['signal_buy_sma20_rebound'] = True  # For backward compatibility
                    c['buy_condition_type'] = "SMA5 GoldCross"
            else:
                if is_buy_signal and is_buy_window:
                    virtual_holding = True
                    has_seen_new_alignment_since_buy = False
                    monitoring_sell = False
                    has_crossed_bb5_upper = False
                    waiting_for_bb_rebuy = False
                    trade_K = c['K_static'] if (c.get('K_static') is not None and c['K_static'] < c['close']) else None
                    c['signal_buy'] = True
                    c['buy_condition_type'] = "TEMA 3 > SMA 60"
        # [FIX] Always evaluate sell conditions regardless of virtual_holding state
        # so that real holdings can be sold even if the simulation missed the buy.
        
        # Check for perfect alignment (K line generated/updated for current trade)
        s5 = c.get('sma5')
        s20 = c.get('sma20')
        t60 = c.get('tema60')
        if s5 is not None and s20 is not None and t60 is not None:
            if s5 > s20 and s20 > t60:
                has_seen_new_alignment_since_buy = True
                trade_K = c['close']

        # Bollinger Band sell conditions
        # 1) 20상한선을 돌파하면 매도관찰 진입
        if c['bb20_upper'] is not None and c['high'] >= c['bb20_upper']:
            monitoring_sell = True

        # 2) 매도관찰 상태에서 5볼린저 상한선까지 추가 돌파 (상태 기록용으로 유지)
        if monitoring_sell and c['bb5_upper'] is not None and c['high'] >= c['bb5_upper']:
            has_crossed_bb5_upper = True

        # 3) 20상한선 돌파로 매도관찰 진입 후, 5상한선과 20상한선 사이에 있거나 5상한선 위에 있어도 하락하게 되면 매도
        is_bb_sell = False
        if monitoring_sell and c_prev is not None:
            if c['close'] < c_prev['close']:
                is_bb_sell = True

        # Check Sell Conditions
        is_sell_cond2 = False
        # Condition 2 (Stop Loss): 관문선 이하 1% 하락 시 손절 매도
        if c.get('tema_gate_line') is not None:
            if c['close'] < c['tema_gate_line'] * 0.99:
                is_sell_cond2 = True

        if is_15m_sma_dead:
            c['signal_sell'] = True
            c['sell_reason'] = "15m SMA5-60 Dead Cross"
            virtual_holding = False
            waiting_for_bb_rebuy = False
            monitoring_sell = False
        elif is_bb_sell:
            c['signal_sell'] = True
            c['sell_reason'] = "BB5 Upper Reversal"
            virtual_holding = False  # Reset virtual trade state
            waiting_for_bb_rebuy = True
            monitoring_sell = False
        elif is_sell_cond2:
            c['signal_sell_cond2'] = True
            c['signal_sell'] = True
            c['sell_reason'] = "Gate-line 1% Stop Loss"
            virtual_holding = False  # Reset virtual trade state
            waiting_for_bb_rebuy = False
            monitoring_sell = False
        elif is_sell_dead_signal:
            c['signal_sell_cond1'] = True
            c['signal_sell'] = True
            c['sell_reason'] = "TEMA 3 Dead Cross"
            virtual_holding = False  # Reset virtual trade state
            waiting_for_bb_rebuy = False
            monitoring_sell = False

        # Overwrite candle K-line with trade-specific K-line for orders & display
        c['K'] = trade_K
        # Map to dynamic buy signal for main.py integration
        c['signal_buy_dynamic'] = c['signal_buy']
        
        # Macro indicators and filters
        c['sma5_gt_tema60'] = (c['sma5'] > c['tema60']) if (c['sma5'] is not None and c['tema60'] is not None) else False
        c['tema3_gt_tema60'] = is_buy_signal
        c['signal_sell_sma5_tema60_dead'] = is_15m_sma_dead
        c['signal_sell_tema3_tema60_dead'] = is_sell_dead_signal

        # Daily Close Reset logic removed to allow overnight holding.

    # 6. Disparity calculation (TEMA Gate Line was already calculated before)
    for i in range(n):
        gate_line_val = candles[i].get('tema_gate_line')
        # Disparity
        if gate_line_val is not None and gate_line_val > 0:
            candles[i]['disparity_pct'] = abs(candles[i]['close'] - gate_line_val) / gate_line_val * 100.0
        else:
            candles[i]['disparity_pct'] = None

    # 10. 기준선(L) & 세력선(whale_line) 동시 상향 돌파 시그널 (빨간 다이아몬드 지점)
    for i in range(n):
        c = candles[i]
        close_val = float(c['close'])
        is_perfect_breakout = False
        c_prev = candles[i-1] if i > 0 else None
        
        if (c.get('L') is not None and c.get('whale_line') is not None and 
            c_prev is not None and c_prev.get('L') is not None and c_prev.get('whale_line') is not None):
            
            above_lines = (close_val > c['L']) and (close_val > c['whale_line'])
            was_below = (c_prev['close'] <= c_prev['L']) or (c_prev['close'] <= c_prev['whale_line'])
            
            if above_lines and was_below:
                is_perfect_breakout = True
    return candles

def calculate_obv(candles):
    """Calculates On Balance Volume (OBV)."""
    n = len(candles)
    obv = []
    current_obv = 0
    for i in range(n):
        if i == 0:
            obv.append(0)
            continue
        c_prev = candles[i-1]['close']
        c_curr = candles[i]['close']
        v = candles[i].get('volume', 0)
        
        if c_curr > c_prev:
            current_obv += v
        elif c_curr < c_prev:
            current_obv -= v
            
        obv.append(current_obv)
    return obv

def calculate_indicators_1min(candles):
    """
    Calculates technical indicators for 1-minute candles (used as a leading indicator).
    Calculates TEMA 3, TEMA 60, OBV.
    """
    n = len(candles)
    if n == 0:
        return candles
        
    closes = [c['close'] for c in candles]
    tema3 = calculate_tema(closes, 3)
    tema60 = calculate_tema(closes, 60)
    obv = calculate_obv(candles)
    
    for i in range(n):
        candles[i]['tema3'] = tema3[i]
        candles[i]['tema60'] = tema60[i]
        candles[i]['obv'] = obv[i]
        
    return candles

def calculate_indicators_3min(candles):
    """
    Calculates technical indicators for 3-minute candles.
    Calculates TEMA 20, SMA 40, SMA 20, OBV, and 3-candle average volume.
    """
    n = len(candles)
    if n == 0:
        return candles
        
    closes = [c['close'] for c in candles]
    
    tema20 = calculate_tema(closes, 20)
    sma20 = calculate_sma(closes, 20)
    sma40 = calculate_sma(closes, 40)
    sma3 = calculate_sma(closes, 3)
    sma60 = calculate_sma(closes, 60)
    tema3 = calculate_tema(closes, 3)
    bb20_upper, bb20_mid, bb20_lower = calculate_bollinger_bands(closes, 20, 2.0)
    obv = calculate_obv(candles)
    
    for i in range(n):
        candles[i]['tema20'] = tema20[i]
        candles[i]['sma20'] = sma20[i]
        candles[i]['sma40'] = sma40[i]
        candles[i]['sma3'] = sma3[i]
        candles[i]['sma60'] = sma60[i]
        candles[i]['tema3'] = tema3[i]
        candles[i]['bb20_upper'] = bb20_upper[i]
        candles[i]['obv'] = obv[i]
        
        # Calculate 3-candle average volume (excluding current candle)
        if i >= 3:
            avg_v = (candles[i-1].get('volume', 0) + candles[i-2].get('volume', 0) + candles[i-3].get('volume', 0)) / 3.0
            candles[i]['vol_avg_3'] = avg_v
        else:
            candles[i]['vol_avg_3'] = 0
            
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
    
    mock_candles = [{
        'close': p,
        'open': p * 0.99,
        'high': p * 1.02,
        'low': p * 0.98,
        'volume': 10000000 if idx % 5 == 0 else 100000
    } for idx, p in enumerate(prices)]
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


def check_short_term_sugeub(candles, timeframe_minutes):
    """
    Checks if the latest candle in 1-min or 5-min intervals represents a volume (sugeub) spike.
    timeframe_minutes must be either 1 or 5.
    
    Conditions:
      1. Bullish candle (close > open)
      2. Current volume >= 2.0x the average volume of the previous 2 candles.
    """
    if not candles or len(candles) < 3:
        return False
        
    latest = candles[-1]
    h = float(latest.get('high', latest['close']))
    l = float(latest.get('low', latest['close']))
    o = float(latest.get('open', latest['close']))
    c = float(latest['close'])
    v = float(latest.get('volume', 0))
    
    # 1. Bullish candle check
    if c <= o:
        return False
        
    # 2. Volume spike check (>= 2.0x average of last 2 candles)
    prev_vol_1 = float(candles[-2].get('volume', 0))
    prev_vol_2 = float(candles[-3].get('volume', 0))
    avg_prev_vol = (prev_vol_1 + prev_vol_2) / 2.0
    
    if avg_prev_vol <= 0 or v < (avg_prev_vol * 2.0):
        return False
        
    return True


def parse_tick_execution_data(res):
    """
    Parses REST API daily_stock_price_request_ka10003 response.
    Returns:
      (volume_power: float, block_buy_count: int)
      
    - volume_power (체결강도): Latest tick's 'cntr_str' value. Default 100.0.
    - block_buy_count (1억 이상 매수 건수): Counter of items in 'cntr_infr'
      where abs(price) * abs(qty) >= 100,000,000 and qty > 0 (marked with '+').
    """
    if not res:
        return 100.0, 0
        
    items = res.get("cntr_infr", [])
    if not items:
        return 100.0, 0
        
    # 1. Parse Volume Power (체결강도) from the latest tick
    latest_item = items[0]
    volume_power = 100.0
    try:
        vp_str = latest_item.get("cntr_str", "100.0").strip()
        volume_power = float(vp_str)
    except (ValueError, TypeError, AttributeError):
        pass
        
    # 2. Count block buy trades (>= 100M KRW and buy direction '+')
    block_buy_count = 0
    for item in items:
        try:
            raw_qty = item.get("cntr_trde_qty", "0").strip()
            # If the quantity starts with '+', it is a buy trade.
            if not raw_qty.startswith("+"):
                continue
                
            qty = abs(int(raw_qty))
            price = abs(int(item.get("cur_prc", "0")))
            
            value = price * qty
            if value >= 50000000: # 50 Million KRW
                block_buy_count += 1
        except (ValueError, TypeError):
            continue
            
    return volume_power, block_buy_count


def get_tick_size(price: float) -> int:
    """KRX 주식 가격대별 호가 단위 반환 (2023년 개정 기준)"""
    if price < 2000:
        return 1
    elif price < 5000:
        return 5
    elif price < 20000:
        return 10
    elif price < 50000:
        return 50
    elif price < 200000:
        return 100
    elif price < 500000:
        return 500
    else:
        return 1000

def adjust_price_by_ticks(price: float, ticks: int) -> int:
    """호가 경계선을 안전하게 넘나들며 지정된 호가(ticks)만큼 가격을 가감"""
    current_price = int(price)
    for _ in range(abs(ticks)):
        if ticks > 0:
            tick_size = get_tick_size(current_price)
            current_price += tick_size
        else:
            temp_price = current_price - 1
            tick_size = get_tick_size(temp_price)
            current_price -= tick_size
    return current_price




