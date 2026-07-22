import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

def compute_sma(candles: list, period: int, key: str = 'close') -> list:
    """간단한 단순이동평균(SMA) 계산 함수"""
    smas = []
    for i in range(len(candles)):
        if i < period - 1:
            smas.append(None)
        else:
            window = candles[i - period + 1 : i + 1]
            avg = sum(c[key] for c in window) / period
            smas.append(avg)
    return smas

def scan_golden_cross_stocks(client, target_codes: list) -> Dict[str, float]:
    """
    39개 타겟 종목에 대해 최근 1~3일 전에 일봉 SMA5가 SMA40을 상향 돌파(골든크로스)했는지 검사합니다.
    단순히 SMA5 > SMA40인 상태가 아니라, 이전 날엔 작거나 같다가 당일에 커진 '교차' 지점만 찾습니다.
    조건 만족 시, 골든크로스 발생 당일의 '종가(Close)'를 기준가(Reference Price)로 반환합니다.
    
    Returns:
        Dict[str, float]: { "종목코드": 기준가 }
    """
    logger.info("일봉 스캐닝을 시작합니다. (조건: 1~3일 전 SMA5가 SMA40을 완벽하게 상향 돌파)")
    screened_stocks = {}

    from datetime import datetime
    today_str = datetime.now().strftime("%Y%m%d")

    for code in target_codes:
        daily_candles = client.get_daily_candles(code, last_n_days=60)
        
        if not daily_candles or len(daily_candles) < 45:
            continue
            
        # 전날 장마감 기준을 맞추기 위해, 가장 최신 캔들이 오늘 날짜(장중 미완성 캔들)라면 제외
        if daily_candles[-1]['date'] == today_str:
            daily_candles.pop()
            
        if not daily_candles:
            continue
            
        sma3 = compute_sma(daily_candles, 3)
        sma20 = compute_sma(daily_candles, 20)
        sma40 = compute_sma(daily_candles, 40)
        
        gc_found = False
        reference_price = 0.0
        
        # i는 -1 (당일/최신), -2 (1일전), -3 (2일전), -4 (3일전)
        for i in [-1, -2, -3, -4]:
            if len(sma3) < abs(i) + 1:
                break
                
            s3_curr = sma3[i]
            s3_prev = sma3[i-1]
            s20_curr = sma20[i]
            s20_prev = sma20[i-1]
            s40_curr = sma40[i]
            s40_prev = sma40[i-1]
            
            if s3_curr is None or s3_prev is None or s20_curr is None or s20_prev is None or s40_curr is None or s40_prev is None:
                continue
                
            # 추가 조건: 일봉에서 SMA20 > SMA40 (전반적인 우상향 추세 유지)
            if s20_curr <= s40_curr:
                continue
                
            # 완벽한 상향 돌파 (이전에는 작거나 같았고, 지금은 커짐)
            is_40_gc = (s3_curr > s40_curr and s3_prev <= s40_prev)
            is_20_gc = (s3_curr > s20_curr and s3_prev <= s20_prev)
            
            if is_40_gc or is_20_gc:
                gc_found = True
                reference_price = daily_candles[i]['close']
                days_ago = abs(i) - 1 # -1 -> 0일전, -2 -> 1일전, -3 -> 2일전
                gc_type = "SMA 3/40" if is_40_gc else "SMA 3/20"
                logger.info(f"[{code}] 조건 충족! {days_ago}일 전 {gc_type} 골든크로스 발생. 기준가(종가): {reference_price}")
                break
        
        if gc_found:
            screened_stocks[code] = reference_price

    logger.info(f"스캐닝 완료: 총 {len(target_codes)}개 중 {len(screened_stocks)}개 종목이 관심 종목으로 편입되었습니다.")
    return screened_stocks
