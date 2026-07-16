import logging
from scanner import compute_sma
from indicator import calculate_tema, calculate_sma

logger = logging.getLogger(__name__)

# ============================================================
# 1분봉 조건검색 연계 초단기 스캘핑 매수/매도 로직
# ============================================================

def check_1m_golden_cross(dm) -> bool:
    """
    [수정된 로직: 옵션 1 하이브리드 - 1분봉 SMA 20/40 골든크로스 타점 진입]
    HTS 검색식(강력한 돌파)에 포착된 종목을 즉시 사지 않고 감시합니다.
    주가가 눌림목을 거친 뒤, 1분봉상 SMA 20선이 SMA 40선을 상향 돌파(골든크로스)하는 
    바로 그 찰나의 타점에만 즉시 시장가 진입합니다.
    """
    candles = dm.get_completed_and_current_1m_candles()
    if len(candles) < 42:
        return False
        
    closes = [c['close'] for c in candles]
    sma20_list = calculate_sma(closes, 20)
    sma40_list = calculate_sma(closes, 40)
    
    curr_s20 = sma20_list[-1]
    curr_s40 = sma40_list[-1]
    prev_s20 = sma20_list[-2]
    prev_s40 = sma40_list[-2]
    
    current_price = dm.latest_price
    
    if curr_s20 is None or curr_s40 is None or prev_s20 is None or prev_s40 is None or current_price <= 0:
        return False
        
    # SMA 20이 SMA 40을 방금 막 상향 돌파했는지 확인 (골든크로스)
    is_golden_cross = (prev_s20 <= prev_s40) and (curr_s20 > curr_s40)
    
    if is_golden_cross:
        logger.warning(f"🚀 [{dm.stock_code}] 1분봉 SMA 20/40 골든크로스 타점 포착! 즉시 매수! (현재가: {current_price:,.0f})")
        return True
        
    return False


def check_1m_dead_cross(dm) -> tuple:
    """
    [수정된 로직: 초단기 익절/손절]
    스캘핑 진입 후 1분봉 단기 추세선(SMA 5/10) 데드크로스 발생 시 빠르게 청산합니다.
    """
    candles = dm.get_completed_and_current_1m_candles()
    if len(candles) < 12:
        return False, ""
        
    closes = [c['close'] for c in candles]
    sma5_list = calculate_sma(closes, 5)
    sma10_list = calculate_sma(closes, 10)
    
    curr_s5 = sma5_list[-1]
    curr_s10 = sma10_list[-1]
    prev_s5 = sma5_list[-2]
    prev_s10 = sma10_list[-2]
    
    if curr_s5 is None or curr_s10 is None or prev_s5 is None or prev_s10 is None:
        return False, ""
        
    # 데드크로스 판별: SMA 5 가 SMA 10 을 하향 이탈
    is_dead_cross = (prev_s5 >= prev_s10) and (curr_s5 < curr_s10)
    
    if is_dead_cross:
        current_price = dm.latest_price
        reason = f"1분봉 초단기 추세 꺾임 (SMA 5/10 데드크로스) [현재가:{current_price:,.0f}, SMA5:{curr_s5:,.0f}]"
        return True, reason
        
    # 추가 청산 가드: 주가가 SMA 10선을 확연히 깨고 내려갈 때 (0.5% 이탈)
    current_price = dm.latest_price
    if current_price < curr_s10 * 0.995:
        reason = f"주가 SMA 10선 강하게 이탈 (추세 붕괴) [현재가:{current_price:,.0f}, SMA10:{curr_s10:,.0f}]"
        return True, reason

    return False, ""
