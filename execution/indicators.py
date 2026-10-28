import pandas as pd
import numpy as np
from datetime import datetime
from typing import Tuple, Optional

def calculate_tema(series: pd.Series, period: int) -> pd.Series:
    """
    영웅문(키움 HTS) TEMA(Triple Exponential Moving Average) 계산
    TEMA = 3*eavg(c, 기간) - 3*eavg(eavg(c, 기간), 기간) + eavg(eavg(eavg(c, 기간), 기간), 기간)
    """
    if len(series) < period:
        return pd.Series(np.nan, index=series.index)
        
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    tema = 3.0 * ema1 - 3.0 * ema2 + ema3
    return tema

def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """단순 이동평균 (SMA)"""
    return series.rolling(window=period).mean()

def calculate_theme_gate_line(df: pd.DataFrame, p1: int = 5, p2: int = 20) -> pd.DataFrame:
    """
    수식 1: 테마급등관문선 (기간1=5, 기간2=20)
    TEMA1 = 3*eavg(c,기간1)-3*eavg(eavg(c,기간1),기간1)+eavg(eavg(eavg(c,기간1),기간1),기간1);
    TEMA2 = 3*eavg(c,기간2)-3*eavg(eavg(c,기간2),기간2)+eavg(eavg(eavg(c,기간2),기간2),기간2);
    조건 = CrossUp(TEMA1, TEMA2);
    ValueWhen(1, 조건, TEMA1)
    """
    df = df.copy()
    tema1 = calculate_tema(df['close'], p1)
    tema2 = calculate_tema(df['close'], p2)
    
    df['tema_fast'] = tema1
    df['tema_slow'] = tema2
    
    # 골든크로스 판별 (CrossUp)
    cross_up = (tema1.shift(1) <= tema2.shift(1)) & (tema1 > tema2)
    df['gate_cross_up'] = cross_up
    
    # ValueWhen(1, 조건, TEMA1)
    gate_values = np.where(cross_up, tema1, np.nan)
    df['theme_gate'] = pd.Series(gate_values, index=df.index).ffill()
    
    return df

def calculate_theme_gate_high(df: pd.DataFrame, p1: int = 5, p2: int = 20) -> pd.DataFrame:
    """
    수식 2: 급등관문고가선 (종류=테마이동평균)
    MM = MA(C,기간1,종류);
    MN = MA(C,기간2,종류);
    조건 = CrossUp(MM,MN);
    HH = ValueWhen(1, 조건, H);
    """
    df = df.copy()
    if 'tema_fast' not in df.columns or 'tema_slow' not in df.columns:
        df['tema_fast'] = calculate_tema(df['close'], p1)
        df['tema_slow'] = calculate_tema(df['close'], p2)
        
    cross_up = (df['tema_fast'].shift(1) <= df['tema_slow'].shift(1)) & (df['tema_fast'] > df['tema_slow'])
    df['gate_cross_up'] = cross_up
    
    # HH = ValueWhen(1, 조건, H)
    hh_values = np.where(cross_up, df['high'], np.nan)
    df['theme_gate_high'] = pd.Series(hh_values, index=df.index).ffill()
    
    return df

def calculate_theme_gijun_line(df: pd.DataFrame, p_fast: int = 5, p_mid: int = 20, p_slow: int = 60) -> pd.DataFrame:
    """
    수식 3: 테마기준선 (테마급등관문선 조건적용)
    a=avg(c,5); b=avg(c,20); d=avg(c,60);
    K=valuewhen(1, a>b && b>d && a>d, C);
    valuewhen(1, K(2)<K(1) && K(1)>K, K(1))
    """
    df = df.copy()
    a = calculate_sma(df['close'], p_fast)
    b = calculate_sma(df['close'], p_mid)
    d = calculate_sma(df['close'], p_slow)
    
    df['sma5'] = a
    df['sma20'] = b
    df['sma60'] = d
    
    # 5 > 20 > 60 완전 정배열
    jeongbae = (a > b) & (b > d) & (a > d)
    k_vals = np.where(jeongbae, df['close'], np.nan)
    df['K'] = pd.Series(k_vals, index=df.index).ffill()
    
    # K의 피크(변곡점): K(2) < K(1) && K(1) > K
    k_prev1 = df['K'].shift(1)
    k_prev2 = df['K'].shift(2)
    is_peak = (k_prev2 < k_prev1) & (k_prev1 > df['K'])
    df['is_gijun_peak'] = is_peak
    
    # valuewhen(1, 피크, K(1))
    gijun_vals = np.where(is_peak, k_prev1, np.nan)
    df['theme_gijun'] = pd.Series(gijun_vals, index=df.index).ffill()
    
    return df

def detect_gate_inflection(df: pd.DataFrame) -> pd.DataFrame:
    """
    하락변곡을 하던 테마급등관문선이 상승변곡을 시작할 때 감지:
    
    1) 골든크로스 발생 시마다 테마급등관문선의 고유 레벨(Level) 기록
    2) 직전 골든크로스 레벨 시퀀스 추적:
       - 이전 2번의 골든크로스: G[k-2] > G[k-1] (하락 추세)
       - 이번 골든크로스: G[k] > G[k-1] (상승 변곡 / 저점 상승 U턴)
    3) 보조 지표: TEMA1(5) 자체의 U턴 변곡 (하락 후 상승 전환)
    """
    df = df.copy()
    
    # 골든크로스 시점의 gate 값들만 추출하여 변곡 확인
    gate_levels = []
    cross_indices = df.index[df['gate_cross_up']].tolist()
    
    df['gate_up_turnaround'] = False
    
    for i, idx in enumerate(cross_indices):
        curr_gate = df.loc[idx, 'theme_gate']
        gate_levels.append((idx, curr_gate))
        
        # 최소 3번의 골든크로스 기록이 있으면 변곡 판정 가능
        if len(gate_levels) >= 3:
            prev2_gate = gate_levels[-3][1]
            prev1_gate = gate_levels[-2][1]
            curr_val = gate_levels[-1][1]
            
            # G[k-2] > G[k-1] (하락하던 테마급등관문선) and G[k] > G[k-1] (상승변곡 시작)
            if prev2_gate > prev1_gate and curr_val > prev1_gate:
                df.loc[idx, 'gate_up_turnaround'] = True
        elif len(gate_levels) == 2:
            # 기록이 2개일 때는 직전보다 상승 시 변곡 시작으로 인정
            prev1_gate = gate_levels[-2][1]
            curr_val = gate_levels[-1][1]
            if curr_val > prev1_gate:
                df.loc[idx, 'gate_up_turnaround'] = True
                
    # 보조: 60분봉 TEMA 5선의 U턴 변곡
    # TEMA1(t-2) > TEMA1(t-1) and TEMA1(t-1) < TEMA1(t)
    tema_fast = df['tema_fast']
    df['tema_fast_uturn'] = (tema_fast.shift(2) > tema_fast.shift(1)) & (tema_fast.shift(1) < tema_fast)
    
    return df

def calculate_daily_tema_deadcross(df_daily: pd.DataFrame, p1: int = 5, p2: int = 20) -> pd.DataFrame:
    """
    일봉 기준 TEMA 5-20 데드크로스 감지
    Dead Cross: TEMA1이 TEMA2를 하향 이탈할 때 True
    """
    df = df_daily.copy()
    tema1 = calculate_tema(df['close'], p1)
    tema2 = calculate_tema(df['close'], p2)
    
    df['daily_tema_fast'] = tema1
    df['daily_tema_slow'] = tema2
    
    # 일봉 데드크로스
    dead_cross = (tema1.shift(1) >= tema2.shift(1)) & (tema1 < tema2)
    df['daily_dead_cross'] = dead_cross
    
    # 일봉 추세 상태 (골든 유지: True, 데드 상태: False)
    df['daily_trend_bull'] = tema1 > tema2
    
    return df

def calculate_all_60m_indicators(df_60m: pd.DataFrame, p1: int = 5, p2: int = 20, p_slow: int = 60) -> pd.DataFrame:
    """60분봉 지표 전체 계산 파이프라인"""
    df = df_60m.copy()
    df = calculate_theme_gate_line(df, p1, p2)
    df = calculate_theme_gate_high(df, p1, p2)
    df = calculate_theme_gijun_line(df, p1, p2, p_slow)
    df = detect_gate_inflection(df)
    return df

def calculate_120t_tema_indicators(df_120t: pd.DataFrame) -> pd.DataFrame:
    """
    120틱 캔들 전용 테마(TEMA) 5, 20, 60, 120 계산 및 정배열/데드크로스 감지
    - 테마 5 > 20 > 60 > 120 완전 정배열: is_tema_aligned_120t (재매수 타점)
    - 테마 5 < 20 데드크로스: is_tema_dead_5_20 (모든 매도 일원화 타점)
    """
    if df_120t is None or df_120t.empty:
        return pd.DataFrame()
        
    df = df_120t.copy()
    if 'close' not in df.columns:
        return pd.DataFrame()
        
    df['close'] = pd.to_numeric(df['close'], errors='coerce').ffill().bfill()
    df['tema5'] = calculate_tema(df['close'], 5)
    df['tema20'] = calculate_tema(df['close'], 20)
    df['tema60'] = calculate_tema(df['close'], 60)
    df['tema120'] = calculate_tema(df['close'], 120)
    
    # 5 > 20 > 60 > 120 완전 정배열
    df['is_tema_aligned_120t'] = (
        (df['tema5'] > df['tema20']) & 
        (df['tema20'] > df['tema60']) & 
        (df['tema60'] > df['tema120'])
    )
    
    # 5 < 20 매도 신호
    df['is_tema_dead_5_20'] = df['tema5'] < df['tema20']
    
    return df

def calculate_day3_m_line(df_daily: Optional[pd.DataFrame], current_price: float) -> Tuple[float, float, float, float]:
    """
    영웅문(키움 HTS) 실시간 3일선 M/3 수식선 계산:
    M = 종가 + nPreDayClose(1) + nPreDayClose(2);
    수식선 = M / 3.0

    HTS 함수 정의:
    - 종가: 당일 실시간 현재가(체결가)
    - nPreDayClose(1): 1일전 전일 종가
    - nPreDayClose(2): 2일전 전전일 종가

    Returns:
        Tuple[float, float, float, float]: (day3_m_line, m_val, pred1, pred2)
    """
    if df_daily is None or len(df_daily) < 2 or current_price <= 0:
        return 0.0, 0.0, 0.0, 0.0

    df_d = df_daily.copy()
    col_map = {col: str(col).lower() for col in df_d.columns if str(col).lower() in ('open', 'high', 'low', 'close', 'date')}
    df_d.rename(columns=col_map, inplace=True)

    today_str = datetime.now().strftime('%Y%m%d')

    if 'date' in df_d.columns:
        last_date = str(df_d['date'].iloc[-1]).replace('-', '').replace('/', '').strip()[:8]
        # 오늘 날짜 일봉 캔들이 이미 포함되어 있으면 Day-1(전일), Day-2(전전일) 사용
        if last_date == today_str and len(df_d) >= 3:
            pred1 = float(df_d['close'].iloc[-2])
            pred2 = float(df_d['close'].iloc[-3])
        else:
            pred1 = float(df_d['close'].iloc[-1])
            pred2 = float(df_d['close'].iloc[-2]) if len(df_d) >= 2 else pred1
    else:
        # date 컬럼이 없는 경우 인덱스 확인
        last_idx_str = str(df_d.index[-1]).replace('-', '').replace('/', '').strip()[:8]
        if last_idx_str == today_str and len(df_d) >= 3:
            pred1 = float(df_d['close'].iloc[-2])
            pred2 = float(df_d['close'].iloc[-3])
        else:
            pred1 = float(df_d['close'].iloc[-1])
            pred2 = float(df_d['close'].iloc[-2]) if len(df_d) >= 2 else pred1

    m_val = float(current_price) + pred1 + pred2
    day3_m_line = m_val / 3.0
    return day3_m_line, m_val, pred1, pred2


def calculate_pred_volume_ratio(df_daily: Optional[pd.DataFrame], curr_day_vol: float) -> Tuple[float, float]:
    """
    ⚡ [장초반 3% 번개 돌파]: 전일 거래량 대비 당일 누적 거래량 잠식률(%) 및 전일 거래량 산출
    Returns:
        Tuple[float, float]: (vol_ratio_prev, pre_day_vol)
        - vol_ratio_prev: (curr_day_vol / pre_day_vol) * 100.0 (%)
        - pre_day_vol: 전일 1일 전체 거래량 (주)
    """
    if df_daily is None or len(df_daily) < 1:
        return 0.0, 0.0

    df_d = df_daily.copy()
    col_map = {col: str(col).lower() for col in df_d.columns if str(col).lower() in ('volume', 'date')}
    df_d.rename(columns=col_map, inplace=True)

    if 'volume' not in df_d.columns:
        return 0.0, 0.0

    today_str = datetime.now().strftime('%Y%m%d')
    pre_day_vol = 0.0

    if 'date' in df_d.columns and len(df_d) >= 2:
        last_date = str(df_d['date'].iloc[-1]).replace('-', '').replace('/', '').strip()[:8]
        if last_date == today_str and len(df_d) >= 2:
            pre_day_vol = float(df_d['volume'].iloc[-2])
            if curr_day_vol <= 0:
                curr_day_vol = float(df_d['volume'].iloc[-1])
        else:
            pre_day_vol = float(df_d['volume'].iloc[-1])
    elif len(df_d) >= 2:
        pre_day_vol = float(df_d['volume'].iloc[-2])
    else:
        pre_day_vol = float(df_d['volume'].iloc[-1])

    if pre_day_vol <= 0:
        return 0.0, 0.0

    vol_ratio_prev = (float(curr_day_vol) / pre_day_vol) * 100.0
    return vol_ratio_prev, pre_day_vol



