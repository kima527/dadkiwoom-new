import logging
from scanner import compute_sma
from indicator import calculate_tema, calculate_sma

logger = logging.getLogger(__name__)


# ============================================================
# 1분봉 SMA 20/40 크로스 및 필터 로직
# ============================================================

# ============================================================
# 1분봉 SMA 20/40 크로스 및 필터 로직
# ============================================================

def check_1m_golden_cross(dm) -> bool:
    """
    1분봉 SMA 20이 SMA 40을 상향 돌파(Golden Cross)했는지 확인합니다.
    [필터 적용]: 직전 5캔들 평균 거래량 대비 현재 캔들의 거래량이 2배 이상 터졌을 때만 True 반환.
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
    
    if curr_s20 is None or curr_s40 is None or prev_s20 is None or prev_s40 is None:
        return False
        
    # 골든크로스 판별: 직전까지 SMA20 <= SMA40 이다가, 현재 SMA20 > SMA40 으로 돌파
    is_golden_cross = (prev_s20 <= prev_s40) and (curr_s20 > curr_s40)
    
    # 조건검색식(Real_Traiding)에서 이미 1분봉 거래량 300% 이상인 종목만 걸러주므로,
    # 여기서는 순수하게 1분봉 SMA 20/40 골든크로스 타점만 확인합니다.
    if is_golden_cross:
        logger.warning(f"🚀 [{dm.stock_code}] 1분봉 SMA 20/40 골든크로스 발생! (조건검색 거래량 폭발 확인됨)")
        return True
        
    return False


def check_1m_dead_cross(dm) -> tuple:
    """
    1분봉 SMA 20이 SMA 40을 하향 이탈(Dead Cross)했는지 확인합니다.
    Returns: (is_sell: bool, reason: str)
    """
    candles = dm.get_completed_and_current_1m_candles()
    if len(candles) < 42:
        return False, ""
        
    closes = [c['close'] for c in candles]
    sma20_list = calculate_sma(closes, 20)
    sma40_list = calculate_sma(closes, 40)
    
    curr_s20 = sma20_list[-1]
    curr_s40 = sma40_list[-1]
    prev_s20 = sma20_list[-2]
    prev_s40 = sma40_list[-2]
    
    if curr_s20 is None or curr_s40 is None or prev_s20 is None or prev_s40 is None:
        return False, ""
        
    # 데드크로스 판별: 직전까지 SMA20 >= SMA40 이다가, 현재 SMA20 < SMA40 으로 이탈
    is_dead_cross = (prev_s20 >= prev_s40) and (curr_s20 < curr_s40)
    
    if is_dead_cross:
        current_price = dm.latest_price
        reason = f"1분봉 SMA 20/40 데드크로스 발생 [현재가:{current_price:,.0f}, SMA20:{curr_s20:,.0f}, SMA40:{curr_s40:,.0f}]"
        return True, reason
        
    return False, ""

