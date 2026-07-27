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
            
        # 2.2 추가 매수 검사 (물타기)
        if not state.added_on and state.first_buy_candle_time is not None:
            # df의 index가 time 문자열인 경우
            if state.first_buy_candle_time in df.index:
                buy_idx = df.index.get_loc(state.first_buy_candle_time)
                
                # 중복된 인덱스 방어 (get_loc이 slice를 반환할 수 있음)
                if isinstance(buy_idx, slice):
                    buy_idx = buy_idx.stop - 1
                elif isinstance(buy_idx, pd.Series):
                    buy_idx = buy_idx.to_numpy().nonzero()[0][-1]
                    
                # 매수 캔들 다음 캔들이 "완성" 되었는지 확인 (최소 2개 캔들 뒤에 있어야 완성된 것으로 간주)
                if buy_idx + 1 < len(df) - 1:
                    next_candle = df.iloc[buy_idx + 1]
                    # 음봉 확인 (종가 < 시가)
                    if next_candle['close'] < next_candle['open']:
                        target_price = next_candle['low'] + get_tick_size(int(next_candle['low']))
                        return {
                            "add_buy": True,
                            "add_buy_reason": "매수 후 다음 캔들 음봉 발생 (최저가+1호가 추가매수)",
                            "price": target_price
                        }
                    else:
                        # 양봉이면 추가매수 안 함
                        state.added_on = True
            else:
                # 매수 캔들이 1분봉 데이터에서 사라진 경우 (API가 오래된 캔들을 잘라냄)
                # 추가매수 기회를 소진 처리하여 무한 대기 방지
                state.added_on = True

    return {"buy": False, "sell": False, "add_buy": False}
