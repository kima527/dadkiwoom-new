import logging
from scanner import compute_sma

logger = logging.getLogger(__name__)

def get_daily_kl_lines(daily_candles):
    """
    일봉 기준 K선, L선을 계산합니다.
    - 골든크로스(SMA3 > SMA40) 구간에서의 최고 종가를 하나의 '피크(Peak)'로 정의.
    - K선: 가장 최근에 형성된 피크 (현재 골든크로스 진행 중이면 현재 피크, 아니면 직전 피크)
    - L선: K선 이전의 피크
    """
    n = len(daily_candles)
    if n < 40:
        return None, None
        
    sma3 = compute_sma(daily_candles, 3)
    sma40 = compute_sma(daily_candles, 40)
    
    peaks = []
    in_gc = False
    current_peak = 0
    
    for idx in range(n):
        s3 = sma3[idx]
        s40 = sma40[idx]
        
        if s3 is None or s40 is None:
            continue
            
        if s3 > s40:
            if not in_gc:
                # 골든크로스 진입
                in_gc = True
                current_peak = daily_candles[idx]['close']
            else:
                # 골든크로스 유지 중 고점 갱신
                current_close = daily_candles[idx]['close']
                if current_close > current_peak:
                    current_peak = current_close
        else:
            if in_gc:
                # 데드크로스 발생 (골든크로스 종료) -> 피크 확정
                in_gc = False
                peaks.append(current_peak)
                current_peak = 0
                
    # 만약 현재 골든크로스가 진행 중이라면, 지금까지의 고점도 피크 목록에 임시로 포함
    if in_gc and current_peak > 0:
        peaks.append(current_peak)
        
    k_line = None
    l_line = None
    
    if len(peaks) >= 1:
        k_line = peaks[-1]
    if len(peaks) >= 2:
        l_line = peaks[-2]
        
    return k_line, l_line

def check_buy_signal(dm) -> bool:
    """
    매수 조건 검사
    1. 전일 고가 돌파 (Yesterday's High Breakout)
    """
    current_price = dm.latest_price
    
    daily_candles = list(dm.candles_daily)
    if len(daily_candles) < 42:
        return False
        
    # [NEW] 일봉 K선, L선 동시 돌파 (Breakout) 검사
    k_line, l_line = get_daily_kl_lines(daily_candles)
    if k_line is not None and l_line is not None:
        target_price = max(k_line, l_line)
        yesterday_close = daily_candles[-2]['close'] if len(daily_candles) >= 2 else 0
        
        # 어제는 저항선(목표가) 이하에서 끝났는데, 오늘 뚫고 올라갔다면 진정한 "돌파 매수"
        if yesterday_close <= target_price and current_price > target_price:
            logger.warning(f"🚀 [{dm.stock_code}] 일봉 K/L선 동시 돌파 감지! (어제종가: {yesterday_close} -> 현재가: {current_price} > 저항: {target_price})")
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
