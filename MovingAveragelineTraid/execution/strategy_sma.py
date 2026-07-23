import pandas as pd
import ta

def calculate_sma_signals(df: pd.DataFrame) -> dict:
    """
    Calculate SMAs and return trading signals based on Two-Track Strategy:
    1. Opening Price Breakout (시가 돌파 매매)
    2. 3-20-60 Dip Buy (3-20 돌파 후 60 도달 전 눌림목 매매)
    """
    if len(df) < 60:
        return {"buy": False, "breakout_buy": False, "dip_buy": False, "sell": False, "sma20": 0.0}

    # Calculate SMAs
    df['sma3'] = ta.trend.sma_indicator(df['close'], window=3)
    df['sma5'] = ta.trend.sma_indicator(df['close'], window=5)
    df['sma20'] = ta.trend.sma_indicator(df['close'], window=20)
    df['sma60'] = ta.trend.sma_indicator(df['close'], window=60)

    latest = df.iloc[-1]
    prev1 = df.iloc[-2]
    
    sma3 = latest['sma3']
    sma5 = latest['sma5']
    sma20 = latest['sma20']
    sma60 = latest['sma60']
    
    today_open = df.iloc[0]['open']
    
    # --------------------------------------------------
    # 1. Breakout Buy: 시가 재돌파 매매 (거래량 폭발)
    # --------------------------------------------------
    prev_vol = prev1['volume']
    current_vol = latest['volume']
    vol_exploded = current_vol > (prev_vol * 3.0)
    
    # 직전 봉은 시가 아래(또는 같음), 현재 봉은 시가를 강하게 돌파
    is_breakout = (prev1['close'] <= today_open) and (latest['close'] > today_open)
    breakout_buy = bool(is_breakout and vol_exploded)
    
    # --------------------------------------------------
    # 2. Dip Buy: 3-20-60 눌림목 매매
    # --------------------------------------------------
    # 조건 1: 3이평선이 20이평선 위에 위치
    in_zone = (sma3 > sma20)
    
    # 조건 2: 반등 확인 (3이평선을 위로 돌파/회복)
    bouncing = latest['close'] > sma3 and prev1['close'] <= prev1['sma3']
    
    dip_buy = bool(in_zone and bouncing)
    
    # --------------------------------------------------
    # 3. Sell Signal: 데드크로스 또는 20이평선 이탈
    # --------------------------------------------------
    sell_signal = (sma3 < sma5) or (latest['close'] < sma20)
    
    # Backward compatibility for 'buy' signal (Trigger if either is true, but bot should check specifics)
    general_buy = breakout_buy or dip_buy
    
    return {
        "buy": general_buy,
        "breakout_buy": breakout_buy,
        "dip_buy": dip_buy,
        "sell": sell_signal,
        "sma20": sma20
    }
