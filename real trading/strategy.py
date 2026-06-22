import logging
from scanner import compute_sma
from indicator import calculate_tema, calculate_sma

logger = logging.getLogger(__name__)


# ============================================================
# 5분봉 기반 K, L, M, N 선 계산 함수
# ============================================================

def compute_all_lines_5m(candles):
    """
    5분봉 캔들 리스트를 받아 K, L, M, N 선의 현재 값을 모두 계산하여 반환합니다.
    
    Returns:
        dict: {
            'K': K선 값 (또는 None),
            'L': L선 값 (또는 None),
            'M': M선 값 (또는 None),
            'N': N선 값 (또는 None),
        }
    """
    n = len(candles)
    result = {'K': None, 'L': None, 'M': None, 'N': None}
    
    if n < 60:
        return result
    
    closes = [c['close'] for c in candles]
    
    # === SMA 계산 (K, L, N선용) ===
    sma5_list = calculate_sma(closes, 5)
    sma20_list = calculate_sma(closes, 20)
    sma60_list = calculate_sma(closes, 60)
    
    # === TEMA 계산 (M선용) ===
    tema5_list = calculate_tema(closes, 5)
    tema20_list = calculate_tema(closes, 20)
    
    # --- L선 계산 ---
    # L선 수식:
    # a=avg(c,5); b=avg(c,20); d=avg(c,60);
    # K_raw=valuewhen(1, a>b && b>d && a>d, C);
    # L=valuewhen(1, K_raw(2)<K_raw(1) && K_raw(1)>K_raw, K_raw(1))
    K_raw = [None] * n
    for i in range(n):
        a = sma5_list[i]
        b = sma20_list[i]
        d = sma60_list[i]
        if a is not None and b is not None and d is not None:
            if a > b and b > d and a > d:
                K_raw[i] = candles[i]['close']
            else:
                K_raw[i] = K_raw[i-1] if i > 0 else None
        else:
            K_raw[i] = K_raw[i-1] if i > 0 else None
    
    L_arr = [None] * n
    for i in range(2, n):
        k0 = K_raw[i]
        k1 = K_raw[i-1]
        k2 = K_raw[i-2]
        if k0 is not None and k1 is not None and k2 is not None:
            if k2 < k1 and k1 > k0:
                L_arr[i] = k1
            else:
                L_arr[i] = L_arr[i-1]
        else:
            L_arr[i] = L_arr[i-1] if i > 0 else None
    
    result['L'] = L_arr[-1]
    
    # --- K선 계산 ---
    # K선 수식:
    # a=avg(c,5); b=avg(c,20); d=avg(c,60);
    # K_raw=valuewhen(1, a>b && b>d && a>d, C);
    # M_val=valuewhen(1, K_raw(2)<K_raw(1) && K_raw(1)>K_raw, K_raw(1));   <- 이것이 L선
    # K=valuewhen(1, crossup(a, M_val), a)                                  <- SMA5가 L선을 상향돌파할 때의 SMA5 값
    K_line = [None] * n
    for i in range(1, n):
        a_curr = sma5_list[i]
        a_prev = sma5_list[i-1]
        l_curr = L_arr[i]
        l_prev = L_arr[i-1]
        
        if (a_curr is not None and a_prev is not None and 
            l_curr is not None and l_prev is not None):
            # CrossUp(a, L): 이전에 a <= L 이었다가 현재 a > L
            if a_prev <= l_prev and a_curr > l_curr:
                K_line[i] = a_curr
            else:
                K_line[i] = K_line[i-1]
        else:
            K_line[i] = K_line[i-1] if i > 0 else None
    
    result['K'] = K_line[-1]
    
    # --- M선 계산 ---
    # M선 수식 (TEMA 기반):
    # TEMA1=3*eavg(c,5)-3*eavg(eavg(c,5),5)+eavg(eavg(eavg(c,5),5),5);
    # TEMA2=3*eavg(c,20)-3*eavg(eavg(c,20),20)+eavg(eavg(eavg(c,20),20),20);
    # 조건=CrossUp(TEMA1, TEMA2);
    # M=ValueWhen(1, 조건, TEMA1)
    M_line = [None] * n
    for i in range(1, n):
        t1_curr = tema5_list[i]
        t1_prev = tema5_list[i-1]
        t2_curr = tema20_list[i]
        t2_prev = tema20_list[i-1]
        
        if (t1_curr is not None and t1_prev is not None and
            t2_curr is not None and t2_prev is not None):
            # CrossUp(TEMA1, TEMA2)
            if t1_prev <= t2_prev and t1_curr > t2_curr:
                M_line[i] = t1_curr
            else:
                M_line[i] = M_line[i-1]
        else:
            M_line[i] = M_line[i-1] if i > 0 else None
    
    result['M'] = M_line[-1]
    
    # --- N선 계산 ---
    # N선 수식 (SMA 기반):
    # M5=MA(C,5,단순); M20=MA(C,20,단순);
    # 조건=CrossUp(M5, M20);
    # N=ValueWhen(1, 조건, M5)
    N_line = [None] * n
    for i in range(1, n):
        s5_curr = sma5_list[i]
        s5_prev = sma5_list[i-1]
        s20_curr = sma20_list[i]
        s20_prev = sma20_list[i-1]
        
        if (s5_curr is not None and s5_prev is not None and
            s20_curr is not None and s20_prev is not None):
            # CrossUp(SMA5, SMA20)
            if s5_prev <= s20_prev and s5_curr > s20_curr:
                N_line[i] = s5_curr
            else:
                N_line[i] = N_line[i-1]
        else:
            N_line[i] = N_line[i-1] if i > 0 else None
    
    result['N'] = N_line[-1]
    
    return result


def determine_entry_zone(lines, entry_price):
    """
    매수 시점의 가격이 어느 구간(Zone)에 위치하는지 판단합니다.
    
    Returns:
        str: 'UPPER' (K/L선 부근 돌파 구간) 또는 'LOWER' (M/N선 부근 눌림목 구간)
    """
    K = lines.get('K')
    L = lines.get('L')
    M = lines.get('M')
    N = lines.get('N')
    
    # K선 또는 L선 위에서 매수한 경우 -> 돌파 구간 (UPPER)
    if K is not None and entry_price >= K:
        return 'UPPER'
    if L is not None and entry_price >= L:
        return 'UPPER'
    
    # 그 외 (M/N선 부근 또는 아래) -> 눌림목 구간 (LOWER)
    return 'LOWER'


# ============================================================
# 매도 신호 판단 (진입 위치별 이원화 로직)
# ============================================================

def check_sell_signal_by_lines(dm, entry_zone=None, lines=None):
    """
    5분봉 K, L, M, N선 기반의 지능형 매도 신호를 판단합니다.
    
    Args:
        dm: RealtimeDataManager (5분봉 데이터 보유)
        entry_zone: 'UPPER' (돌파 구간 진입) 또는 'LOWER' (눌림목 구간 진입)
        lines: (선택) 이미 계산된 K, L, M, N선 딕셔너리
    
    Returns:
        tuple: (is_sell: bool, reason: str)
    """
    if lines is None:
        candles = dm.get_completed_and_current_5m_candles()
        if len(candles) < 60:
            return False, ""
        
        lines = compute_all_lines_5m(candles)
    current_price = dm.latest_price
    
    if current_price <= 0:
        return False, ""
    
    K = lines.get('K')
    L = lines.get('L')
    M = lines.get('M')
    N = lines.get('N')
    
    if entry_zone == 'UPPER':
        # === Case A: 돌파 구간에서 매수 -> K선이 절대 방어선 ===
        if K is not None and current_price < K:
            return True, f"K선 하향 이탈 (돌파 실패) [현재가:{current_price:,.0f} < K선:{K:,.0f}]"
    
    elif entry_zone == 'LOWER':
        # === Case B: 눌림목 구간에서 매수 -> M선, N선 순차 방어 ===
        # 1차 방어: M선 이탈
        if M is not None and current_price < M:
            return True, f"M선 하향 이탈 (1차 방어선 붕괴) [현재가:{current_price:,.0f} < M선:{M:,.0f}]"
        # 2차 마지노선: N선 이탈
        if N is not None and current_price < N:
            return True, f"N선 하향 이탈 (마지노선 붕괴) [현재가:{current_price:,.0f} < N선:{N:,.0f}]"
    
    else:
        # entry_zone을 알 수 없는 경우 (기존 보유 종목 등) -> 보수적으로 M선 기준 적용
        if M is not None and current_price < M:
            return True, f"M선 하향 이탈 (기본 방어) [현재가:{current_price:,.0f} < M선:{M:,.0f}]"
        if N is not None and current_price < N:
            return True, f"N선 하향 이탈 (마지노선) [현재가:{current_price:,.0f} < N선:{N:,.0f}]"
    
    return False, ""


def check_entry_filter_by_lines(dm):
    """
    매수 진입 전 M선/N선 위에 있는지 확인하는 안전 필터.
    
    Returns:
        bool: True면 매수 가능, False면 매수 차단
    """
    candles = dm.get_completed_and_current_5m_candles()
    if len(candles) < 60:
        # 데이터 부족 시 필터를 통과시킴 (기존 조건검색 신호를 존중)
        return True
    
    lines = compute_all_lines_5m(candles)
    current_price = dm.latest_price
    
    if current_price <= 0:
        return False
    
    N = lines['N']
    
    # N선(마지노선)이 형성되어 있고, 현재가가 N선 아래면 매수 차단
    if N is not None and current_price < N:
        logger.info(f"[{dm.stock_code}] 매수 필터 차단: 현재가({current_price:,.0f}) < N선({N:,.0f})")
        return False
    
    return True


# ============================================================
# 기존 호환 함수 (기존 코드에서 호출되는 함수 유지)
# ============================================================


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
