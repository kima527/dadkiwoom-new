import logging
from indicator import calculate_sma

logger = logging.getLogger(__name__)

# 임계값 설정
MIN_ORDERBOOK_RATIO = 0.5 # 1분 거래대금이 매도 5호가 잔량금액의 0.5배 이상 (조정 가능)

def check_3m_buy_signal(dm) -> tuple:
    """
    3분봉 매수 신호 판별
    - 3분봉 SMA 3 > SMA 5 (골든크로스 또는 정배열 초기)
    """
    # 1. 3분봉 SMA 3 / 5 골든크로스 판별
    candles_3m = dm.get_completed_and_current_3m_candles()
    if len(candles_3m) < 6:
        return False, ""
        
    closes_3m = [c['close'] for c in candles_3m]
    sma3_list = calculate_sma(closes_3m, 3)
    sma5_list = calculate_sma(closes_3m, 5)
    
    curr_s3 = sma3_list[-1]
    curr_s5 = sma5_list[-1]
    prev_s3 = sma3_list[-2]
    prev_s5 = sma5_list[-2]
    
    if None in (curr_s3, curr_s5, prev_s3, prev_s5):
        return False, ""
        
    is_golden_cross = (prev_s3 <= prev_s5) and (curr_s3 > curr_s5)
    
    if not is_golden_cross:
        return False, ""
        
    msg = (f"🚀 [3분봉 매수 신호] {dm.name} | "
           f"SMA 3선이 5선을 돌파 (골든크로스)!")
           
    logger.info(msg)
    return True, msg

def check_3m_sell_signal(dm, buy_price: float) -> tuple:
    """
    3분봉 매도 신호 판별
    - 3분봉 SMA 20이 SMA 40을 데드크로스 할 때 청산
    """
    candles_3m = dm.get_completed_and_current_3m_candles()
    if len(candles_3m) < 42:
        return False, ""
        
    closes_3m = [c['close'] for c in candles_3m]
    sma20_list = calculate_sma(closes_3m, 20)
    sma40_list = calculate_sma(closes_3m, 40)
    
    curr_s20 = sma20_list[-1]
    curr_s40 = sma40_list[-1]
    prev_s20 = sma20_list[-2]
    prev_s40 = sma40_list[-2]
    
    if None in (curr_s20, curr_s40, prev_s20, prev_s40):
        return False, ""
        
    is_dead_cross = (prev_s20 >= prev_s40) and (curr_s20 < curr_s40)
    
    if is_dead_cross:
        current_price = dm.latest_price
        reason = f"3분봉 단기 추세 꺾임 (SMA 20/40 데드크로스) [현재가:{current_price:,.0f}]"
        return True, reason
        
    # 안전망: 매수가 대비 급락 (-3% 손절 라인, 예시)
    current_price = dm.latest_price
    if buy_price > 0 and current_price <= buy_price * 0.97:
        reason = f"긴급 안전망 발동 (진입가 대비 -3%) [현재가:{current_price:,.0f}, 평단가:{buy_price:,.0f}]"
        return True, reason
        
    return False, ""
