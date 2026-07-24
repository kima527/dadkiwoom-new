import pandas as pd
import ta
import math

def get_tick_size(price: int) -> int:
    """한국 거래소 기준 호가 단위(Tick Size) 계산"""
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

class TradeState:
    def __init__(self, initial_high: int, stop_loss: int):
        self.initial_high = initial_high
        self.stop_loss = stop_loss
        self.has_traded_today = False
        self.price_dropped_below_high = False
        self.is_holding = False

def calculate_sma_breakout_signals(df: pd.DataFrame, state: TradeState) -> dict:
    """
    df: 1분봉 데이터 (마지막 행이 현재 캔들)
    state: 해당 종목의 현재 상태 객체
    반환: {'buy': bool, 'sell': bool, 'sell_reason': str, 'buy_reason': str, 'price': float}
    """
    if len(df) < 10:
        return {"buy": False, "sell": False}
        
    df = df.copy()
    # 3-10 이평선 계산
    df['sma3'] = ta.trend.sma_indicator(df['close'], window=3)
    df['sma10'] = ta.trend.sma_indicator(df['close'], window=10)
    
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    
    sma3 = latest['sma3']
    sma10 = latest['sma10']
    
    prev_sma3 = prev['sma3'] if prev is not None else 0
    prev_sma10 = prev['sma10'] if prev is not None else 0
    
    # NaN 방어: 이평선 데이터가 아직 충분히 쌓이지 않았으면 신호 없음 반환
    if pd.isna(sma3) or pd.isna(sma10) or pd.isna(prev_sma3) or pd.isna(prev_sma10):
        return {"buy": False, "sell": False}
    
    # 골든/데드크로스 여부 (현재 캔들 기준)
    is_golden_cross = (prev_sma3 <= prev_sma10) and (sma3 > sma10)
    is_dead_cross = (prev_sma3 >= prev_sma10) and (sma3 < sma10)
    
    # 2호가 기준 가격 계산
    tick_size = get_tick_size(state.initial_high)
    two_ticks_below = state.initial_high - (tick_size * 2)
    
    high_price = latest['high']
    low_price = latest['low']
    close_price = latest['close']
    open_price = latest['open']
    
    # 포지션을 안 가지고 있는 경우 (매수 검사)
    if not state.is_holding:
        # 최초 매수
        if not state.has_traded_today:
            # 고가가 초기 고점을 뚫었는가
            if high_price > state.initial_high:
                exec_price = open_price if open_price > state.initial_high else state.initial_high + tick_size
                return {
                    "buy": True,
                    "buy_reason": "초기 고점 돌파 (최초)",
                    "price": exec_price
                }
        # 재매수 로직
        else:
            # 고점 밑으로 내려온 적이 있는지 플래그 업데이트
            if low_price < state.initial_high:
                state.price_dropped_below_high = True
                
            if state.price_dropped_below_high:
                # 조건: 가격이 고점 근처(2호가 이내)이거나 돌파했고, 동시에 3-10 골든크로스가 발생
                approached = (high_price >= two_ticks_below)
                if approached and is_golden_cross:
                    return {
                        "buy": True, 
                        "buy_reason": "골든크로스 + 재돌파/근접 재매수",
                        # 1분봉상 골든크로스 확인 후 종가 부근 체결 가정
                        "price": close_price 
                    }
                    
    # 포지션을 보유 중인 경우 (매도 검사)
    else:
        # 1. 강제 손절 (최고점봉의 최저점 이탈)
        if low_price < state.stop_loss:
            exec_price = open_price if open_price < state.stop_loss else state.stop_loss - get_tick_size(state.stop_loss)
            return {
                "sell": True,
                "sell_reason": f"강제 손절 (손절선 {state.stop_loss} 이탈)",
                "price": exec_price
            }
            
        # 2. 3-10 데드크로스 매도
        if is_dead_cross:
            return {
                "sell": True,
                "sell_reason": "3-10 데드크로스",
                "price": close_price
            }
            
    return {"buy": False, "sell": False}
