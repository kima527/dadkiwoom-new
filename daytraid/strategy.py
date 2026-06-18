import logging
from scanner import compute_sma

logger = logging.getLogger(__name__)

def check_buy_signal(dm) -> bool:
    """
    매수 조건 검사
    1. 전일 고가 돌파 (Yesterday's High Breakout)
    """
    current_price = dm.latest_price
    
    daily_candles = list(dm.candles_daily)
    if len(daily_candles) < 42:
        return False
        
    # [NEW] 5일 이평선 하락 추세 검사 (매수 금지)
    sma3 = compute_sma(daily_candles, 3)
    sma5 = compute_sma(daily_candles, 5)
    sma20 = compute_sma(daily_candles, 20)
    sma40 = compute_sma(daily_candles, 40)
    
    # 5일 이평선 하락 추세 검사 (매수 금지)
    if len(sma5) >= 2:
        curr_sma5 = sma5[-1]
        prev_sma5 = sma5[-2]
        if curr_sma5 is not None and prev_sma5 is not None:
            if curr_sma5 < prev_sma5:
                return False

    # A: 최근 0~3일(당일 포함) 일봉 SMA3이 SMA40 골든크로스
    cond_a_valid = False
    for j in [0, 1, 2, 3]:
        idx_curr = -(j + 1)
        idx_prev = -(j + 2)
        if abs(idx_prev) <= len(sma3):
            s3_c = sma3[idx_curr]
            s40_c = sma40[idx_curr]
            s3_p = sma3[idx_prev]
            s40_p = sma40[idx_prev]
            if s3_c is not None and s40_c is not None and s3_p is not None and s40_p is not None:
                if s3_p <= s40_p and s3_c > s40_c:
                    cond_a_valid = True
                    break

    # B: 당일 일봉 SMA3이 SMA20 골든크로스
    cond_b_valid = False
    if len(sma3) >= 2:
        s3_today = sma3[-1]
        s20_today = sma20[-1]
        s3_yest = sma3[-2]
        s20_yest = sma20[-2]
        if s3_today is not None and s20_today is not None and s3_yest is not None and s20_yest is not None:
            if s3_yest <= s20_yest and s3_today > s20_today:
                cond_b_valid = True
                
    # A 또는 B 중 하나라도 발생해야 함 (OR 조건)
    if not (cond_a_valid or cond_b_valid):
        return False
        
    # 오늘 날짜를 제외한 가장 최근 일봉(즉, 전일 일봉)의 고가 찾기
    from datetime import datetime
    now_date = datetime.now().strftime("%Y%m%d")
    yesterday_high = None
    
    for c in reversed(daily_candles):
        c_date = str(c['date']).replace("-", "")
        if c_date != now_date:
            yesterday_high = c['high']
            break
            
    if yesterday_high is None:
        yesterday_high = daily_candles[-2]['high'] # Fallback
        
    # 현재가가 전일 고가를 돌파했는지 확인
    # "전일 고가"라는 중요한 저항선을 뚫어내는 엄청난 매수세에 올라타는 돌파 매매
    if current_price > yesterday_high:
        logger.warning(f"🚀 [{dm.stock_code}] 전일 고가 돌파 감지! (현재가: {current_price} > 전일고가: {yesterday_high})")
        return True
        
    return False

def check_sell_signal(dm) -> bool:
    """
    매도 조건 검사 (15분봉 실시간 데드크로스)
    1. 15분봉 기준 SMA3이 SMA40을 실시간으로 하향 돌파(데드크로스)
    """
    candles = dm.get_completed_and_current_15m_candles()
    if len(candles) < 40:
        return False
        
    sma3 = compute_sma(candles, 3)
    sma40 = compute_sma(candles, 40)
    
    curr_sma3 = sma3[-1]
    curr_sma40 = sma40[-1]
    
    prev_sma3 = sma3[-2]
    prev_sma40 = sma40[-2]
    
    if curr_sma3 is None or curr_sma40 is None or prev_sma3 is None or prev_sma40 is None:
        return False
        
    # 실시간 데드크로스 판단
    if prev_sma3 >= prev_sma40 and curr_sma3 < curr_sma40:
        logger.warning(f"📉 [{dm.stock_code}] 15분봉 실시간 데드크로스 발생! (SMA3: {curr_sma3:.2f} < SMA40: {curr_sma40:.2f})")
        return True
        
    # 새로운 로직: L선 매도 조건
    current_l = get_current_l_line(candles)
    if current_l is not None and dm.latest_price < current_l:
        logger.warning(f"📉 [{dm.stock_code}] 15분봉 L선 하회(돌파 실패) 발생! (현재가: {dm.latest_price} < L선: {current_l})")
        return True
        
    return False

def get_current_l_line(candles_15m):
    """
    15분봉 기준 L선을 계산하여 현재 L선 값을 반환
    """
    n = len(candles_15m)
    if n < 40:
        return None
        
    sma3 = compute_sma(candles_15m, 3)
    sma40 = compute_sma(candles_15m, 40)
    
    k_line = [None] * n
    last_k = None
    for idx in range(n):
        s3 = sma3[idx]
        s40 = sma40[idx]
        if s3 is not None and s40 is not None:
            if s3 > s40:
                current_close = candles_15m[idx]['close']
                if last_k is None or current_close > last_k:
                    last_k = current_close
        k_line[idx] = last_k
        
    compressed_k = []
    for idx in range(n):
        k_val = k_line[idx]
        if k_val is not None:
            if not compressed_k or compressed_k[-1][1] != k_val:
                compressed_k.append((idx, k_val))
                
    peaks = {}
    for idx in range(2, len(compressed_k)):
        k_2 = compressed_k[idx-2][1]
        k_1 = compressed_k[idx-1][1]
        k_0 = compressed_k[idx][1]
        if k_2 < k_1 and k_1 > k_0:
            confirm_idx = compressed_k[idx][0]
            peaks[confirm_idx] = k_1
            
    current_l = None
    for idx in range(n):
        if idx in peaks:
            current_l = peaks[idx]
            
    return current_l
