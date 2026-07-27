import pandas as pd
import ta
import math
from datetime import datetime, time as dtime

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
    def __init__(self):
        self.is_holding = False
        self.trade_ended = False
        
        self.first_buy_candle_time = None
        self.added_on = False
        self.first_qty = 0

def calculate_sma_breakout_signals(df: pd.DataFrame, state: TradeState, hold_buy_price: float = 0.0) -> dict:
    """
    df: 1분봉 데이터 (마지막 행이 현재 캔들)
    state: 해당 종목의 현재 상태 객체
    hold_buy_price: 보유 시 매입단가
    """
    if state.trade_ended or df.empty:
        return {"buy": False, "sell": False, "add_buy": False}
        
    df = df.copy()
    # 5, 20 이평선 계산
    df['sma5'] = ta.trend.sma_indicator(df['close'], window=5)
    df['sma20'] = ta.trend.sma_indicator(df['close'], window=20)
    
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    
    close_price = latest['close']
    
    # 1. 포지션을 안 가지고 있는 경우 (조건검색 포착 즉시 매수)
    if not state.is_holding:
        return {
            "buy": True,
            "buy_reason": "조건검색 즉시 매수",
            "price": close_price
        }
                    
    # 2. 포지션을 보유 중인 경우
    else:
        prev_close = prev['close'] if prev is not None else latest['open']
        
        # 2.0 이전 캔들 종가 대비 -1.5% 급락 손절 검사
        if close_price <= prev_close * 0.985:
            return {
                "sell": True,
                "sell_reason": "전 캔들 종가 대비 -1.5% 급락 손절",
                "price": close_price
            }
            
        # 2.1 강제 손절 검사: 매입단가 대비 -3%
        is_stop_loss = False
        if hold_buy_price > 0 and close_price <= hold_buy_price * 0.97:
            is_stop_loss = True
            
        if is_stop_loss:
            return {
                "sell": True,
                "sell_reason": "고정 손절 (-3%)",
                "price": close_price
            }
            
        # 2.2 매도 검사: 5-20 데드크로스
        is_dead_cross = False
        if prev is not None and not pd.isna(latest['sma5']) and not pd.isna(latest['sma20']) and not pd.isna(prev['sma5']) and not pd.isna(prev['sma20']):
            if prev['sma5'] >= prev['sma20'] and latest['sma5'] < latest['sma20']:
                is_dead_cross = True
                
        if is_dead_cross:
            return {
                "sell": True,
                "sell_reason": "5-20 이평선 데드크로스",
                "price": close_price
            }
            
    return {"buy": False, "sell": False, "add_buy": False}

    return {"buy": False, "sell": False, "add_buy": False}
