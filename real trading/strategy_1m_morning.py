import logging
from datetime import datetime, time
from indicator import calculate_sma

logger = logging.getLogger(__name__)

def is_morning_session() -> bool:
    """오전 09:00 ~ 10:00 사이인지 판별합니다."""
    current_time = datetime.now().time()
    start_time = time(9, 0)
    end_time = time(10, 0)
    return start_time <= current_time <= end_time

def check_1m_buy_signal(dm) -> tuple:
    """
    1분봉 오전장 매수 신호 판별
    - 오전장(09:00~10:00) 이어야 함
    - 정배열 (SMA3 > SMA5 > SMA20)
    - 눌림목: 현재가가 3이평선 대비 +1.0% 이하, 5이평선 위에 위치
    """
    if not is_morning_session():
        return False, ""
        
    candles_1m = dm.get_completed_and_current_1m_candles()
    if len(candles_1m) < 20:
        return False, ""
        
    closes_1m = [c['close'] for c in candles_1m]
    sma3_list = calculate_sma(closes_1m, 3)
    sma5_list = calculate_sma(closes_1m, 5)
    sma20_list = calculate_sma(closes_1m, 20)
    
    curr_s3 = sma3_list[-1]
    curr_s5 = sma5_list[-1]
    curr_s20 = sma20_list[-1]
    
    if None in (curr_s3, curr_s5, curr_s20):
        return False, ""
        
    is_perfect_order = (curr_s3 > curr_s5) and (curr_s5 > curr_s20)
    
    latest_close = dm.latest_price
    is_pullback = (latest_close <= curr_s3 * 1.01) and (latest_close >= curr_s5 * 0.99)
    
    if is_perfect_order and is_pullback:
        msg = (f"🚀 [1분봉 눌림목 매수] {dm.name} | "
               f"SMA3/5/20 정배열 구간에서 3분선 지지 확인!")
        logger.info(msg)
        return True, msg
        
    return False, ""

def check_1m_sell_signal(dm, buy_price: float) -> tuple:
    """
    1분봉 매도 신호 판별
    - 기계적 손절 (-1.5%)
    - 이평선 이원화 데드크로스 (추세 성숙도에 따라 SMA20 또는 SMA60 데드크로스)
    """
    candles_1m = dm.get_completed_and_current_1m_candles()
    if len(candles_1m) < 60:
        return False, ""
        
    closes_1m = [c['close'] for c in candles_1m]
    sma3_list = calculate_sma(closes_1m, 3)
    sma20_list = calculate_sma(closes_1m, 20)
    sma40_list = calculate_sma(closes_1m, 40)
    sma60_list = calculate_sma(closes_1m, 60)
    
    curr_s3 = sma3_list[-1]
    curr_s20 = sma20_list[-1]
    curr_s40 = sma40_list[-1]
    curr_s60 = sma60_list[-1]
    
    if None in (curr_s3, curr_s20, curr_s40, curr_s60):
        return False, ""
        
    current_price = dm.latest_price
    
    # 1. 기계적 손절 (-1.5%)
    if buy_price > 0 and current_price <= buy_price * 0.985:
        reason = f"🚨 긴급 기계적 손절 발동 (-1.5%) [현재가:{current_price:,.0f}, 평단가:{buy_price:,.0f}]"
        return True, reason
        
    # 2. 이평선 데드크로스 이원화
    if curr_s40 > curr_s60:
        # 추세 성숙/재진입 시: 3이평선이 60이평선 데드크로스할 때까지 홀딩
        if curr_s3 < curr_s60:
            reason = f"📉 1분봉 장기 추세 이탈 (SMA 3/60 데드크로스) [현재가:{current_price:,.0f}]"
            return True, reason
    else:
        # 초기 진입 시: 3이평선이 20이평선 데드크로스 시 컷
        if curr_s3 < curr_s20:
            reason = f"📉 1분봉 단기 추세 이탈 (SMA 3/20 데드크로스) [현재가:{current_price:,.0f}]"
            return True, reason
            
    return False, ""
