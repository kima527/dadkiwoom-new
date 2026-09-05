"""
strategy_15m_turnaround.py - 15분봉 및 일봉 수급/이평 변곡 매매 전략 모듈
===========================================================================

[키움증권 수식관리자 기반 4대 수식 및 조합 타점]
1. [수식 4] 일봉 20억 수급 베이스 + 15분봉 수급 폭발봉 (당일 일봉 거래대금 20억 이상 + 15분봉 3배 수급 급증 + 윗꼬리 짧은 양봉)
2. [수식 3] 3일선 단기 U턴 변곡 (실시간 일봉 3일선 변곡 + 15분봉 3이평 변곡 + 당일 시가위 + 분봉 거래량 3이평 돌파)
3. [수식 2] 일봉 3일선과 20일선의 골든크로스 (CrossUp(3선, 20선))
4. [수식 1] 5일선 중단기 U턴 변곡 & 황룡선/룡선(TEMA) 추세 돌파

[3대 핵심 진입 조합]
- Combo 3+4: [공격형 수급 변곡] 일봉 20억 수급 + 15분봉 수급폭발 & 3일선 U턴 (최우선 급등 초입 타점)
- Combo 2+3: [추세 대전환 돌파] 일봉 3-20 골든크로스 + 15분봉 3일선 변곡 (대세 상승 초입)
- Combo 1+3: [안정형 더블 변곡] 3일선 + 5일선 동시 변곡 & 황룡선 돌파 (안정적 눌림목)
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 전략 설정 파라미터
# ═══════════════════════════════════════════════════════════════
@dataclass
class Turnaround15mParams:
    """15분봉 및 일봉 수급 변곡 전략 파라미터"""
    # [수식 4: 일봉 및 15분봉 수급 기준]
    min_daily_supply_money: float = 20.0  # 당일 일봉 최소 거래대금 (기본 20.0 = 20억원)
    body_to_upper_tail_ratio: float = 1.2 # 양봉 몸통 > 윗꼬리 * 1.2
    supply_surge_multiplier: float = 3.0  # 직전 2개봉 평균 대비 수급 폭증 배수 (3배)

    # [수식 1, 3: 이평 기간]
    sma_fast_m15: int = 3                # 분봉 단기 이평
    sma_mid_m15: int = 5                 # 분봉 중기 이평
    vol_sma_period: int = 3              # 거래량 이평 기간

    # [수식 1: TEMA 기간]
    tema_short: int = 5
    tema_mid: int = 20
    tema_long: int = 60

    # [공통 필터]
    require_above_day_open: bool = True  # 당일 시가(DayOpen) 이상 유지 필수 여부
    min_bars_15m: int = 30               # 최소 요구 15분봉 데이터 개수
    min_bars_daily: int = 25             # 최소 요구 일봉 데이터 개수


# ═══════════════════════════════════════════════════════════════
# 보조 지표 계산 헬퍼 함수
# ═══════════════════════════════════════════════════════════════
def ema(series: pd.Series, period: int) -> pd.Series:
    """지수이동평균(Exponential Moving Average)"""
    return series.ewm(span=period, adjust=False).mean()


def tema(series: pd.Series, period: int) -> pd.Series:
    """
    삼중지수이동평균(TEMA - Triple Exponential Moving Average)
    TEMA = 3*EMA1 - 3*EMA2 + EMA3
    """
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return 3.0 * ema1 - 3.0 * ema2 + ema3


def calculate_hwangryong_line(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    [수식 1의 황룡선 & M선(정배열 직전 최고 정점 저항선) & 룡선(TEMA) 계산]
    - a = avg(c,5), b = avg(c,20), d = avg(c,60)
    - K = valuewhen(1, a>b && b>d && a>d, C)
    - M = valuewhen(1, K(2)<K(1) && K(1)>K, K(1))
    - 황룡선 = valuewhen(1, crossup(a, M), a)
    """
    close = df['close']
    a = close.rolling(5, min_periods=5).mean()
    b = close.rolling(20, min_periods=20).mean()
    d = close.rolling(60, min_periods=60).mean()

    # 정배열 조건
    cond_align = (a > b) & (b > d)
    k_series = close.where(cond_align).ffill()
    
    k_shift1 = k_series.shift(1)
    k_shift2 = k_series.shift(2)
    cond_peak = (k_shift1 > k_shift2) & (k_shift1 > k_series)
    m_series = k_shift1.where(cond_peak).ffill()
    
    crossup_m = (a.shift(1) <= m_series.shift(1)) & (a > m_series)
    hwangryong = a.where(crossup_m).ffill()

    # TEMA 룡선 계산
    e_tema = tema(close, 5)
    f_tema = tema(close, 20)
    g_tema = tema(close, 60)

    cond_align_tema = (e_tema > f_tema) & (f_tema > g_tema)
    k1_series = close.where(cond_align_tema).ffill()
    k1_shift1 = k1_series.shift(1)
    k1_shift2 = k1_series.shift(2)
    cond_peak_tema = (k1_shift1 > k1_shift2) & (k1_shift1 > k1_series)
    m1_series = k1_shift1.where(cond_peak_tema).ffill()

    crossup_m1 = (a.shift(1) <= m1_series.shift(1)) & (a > m1_series)
    ryong_line = a.where(crossup_m1).ffill()

    return hwangryong, ryong_line, m_series


def calc_m_resistance_price(df_15m: pd.DataFrame) -> float:
    """
    [수식 1] 정배열 직전 최고 정점 저항선 (M선) 최신값 계산
    a = avg(c, 5), b = avg(c, 20), d = avg(c, 60)
    K = valuewhen(1, a > b && b > d && a > d, C)
    M = valuewhen(1, K(2) < K(1) && K(1) > K, K(1))
    """
    if df_15m is None or df_15m.empty or len(df_15m) < 20:
        return 0.0
    close = df_15m['close']
    a = close.rolling(5, min_periods=5).mean()
    b = close.rolling(20, min_periods=20).mean()
    d = close.rolling(60, min_periods=60).mean()

    cond_align = (a > b) & (b > d)
    k_series = close.where(cond_align).ffill()
    
    k_shift1 = k_series.shift(1)
    k_shift2 = k_series.shift(2)
    cond_peak = (k_shift1 > k_shift2) & (k_shift1 > k_series)
    m_series = k_shift1.where(cond_peak).ffill()
    
    last_m = m_series.dropna()
    if not last_m.empty:
        return float(last_m.iloc[-1])
    return 0.0


# ═══════════════════════════════════════════════════════════════
# 일봉 변곡 및 크로스 계산
# ═══════════════════════════════════════════════════════════════

def calc_realtime_day_inflections(
    curr_close: float,
    daily_closes: List[float]
) -> Dict[str, Any]:
    """
    일봉 3일선, 5일선, 20일선의 실시간 변곡(U턴) 및 골든크로스 계산
    """
    if len(daily_closes) < 6:
        return {
            "d_sma3_inflection": False,
            "d_sma5_inflection": False,
            "d_gc_3_20": False,
            "d_sma3_curr": 0.0,
            "d_sma5_curr": 0.0,
            "d_sma20_curr": 0.0,
        }

    c0 = float(curr_close)
    c1 = float(daily_closes[-1])
    c2 = float(daily_closes[-2])
    c3 = float(daily_closes[-3])
    c4 = float(daily_closes[-4])
    c5 = float(daily_closes[-5])
    c6 = float(daily_closes[-6])

    # ── [수식 3] 일봉 3일선 변곡 ──
    a0 = (c0 + c1 + c2) / 3.0
    a1 = (c1 + c2 + c3) / 3.0
    a2 = (c2 + c3 + c4) / 3.0
    d_sma3_inflection = (a0 > a1) and (a1 <= a2)

    # ── [수식 1] 일봉 5일선 변곡 ──
    a3 = (c0 + c1 + c2 + c3 + c4) / 5.0
    a4 = (c1 + c2 + c3 + c4 + c5) / 5.0
    a5 = (c2 + c3 + c4 + c5 + c6) / 5.0
    d_sma5_inflection = (a3 > a4) and (a4 <= a5)

    # ── [수식 2] 일봉 3일선과 20일선의 골든크로스 ──
    if len(daily_closes) >= 20:
        past_19 = [float(x) for x in daily_closes[-19:]]
        past_20 = [float(x) for x in daily_closes[-20:]]
        n20_curr = (c0 + sum(past_19)) / 20.0
        n20_prev = sum(past_20) / 20.0
        d_gc_3_20 = (a0 > n20_curr) and (a1 <= n20_prev)
    else:
        n20_curr = 0.0
        d_gc_3_20 = False

    return {
        "d_sma3_inflection": bool(d_sma3_inflection),
        "d_sma5_inflection": bool(d_sma5_inflection),
        "d_gc_3_20": bool(d_gc_3_20),
        "d_sma3_curr": a0,
        "d_sma5_curr": a3,
        "d_sma20_curr": n20_curr,
    }


# ═══════════════════════════════════════════════════════════════
# [수식 4] 일봉 20억 수급 + 15분봉 수급 급증 계산 로직
# ═══════════════════════════════════════════════════════════════

def calc_formula_4_supply(
    df_15m: pd.DataFrame,
    params: Turnaround15mParams
) -> pd.DataFrame:
    """
    [수식 4] 일봉 20억 수급 베이스 + 15분봉 수급 폭발봉 계산
    1. 일봉 기준: 당일 누적 거래대금 >= 20억원 & 당일 시가 위(일봉 양봉)
    2. 15분봉 기준: 15분봉 양봉 & 몸통 > 윗꼬리*1.2 & 직전 2개 15분봉 평균 수급 대비 3배 폭증
    """
    df = df_15m.copy()
    
    # 15분봉 개별 봉 거래대금 (억원)
    df['m15_money'] = (df['high'] + df['low'] + df['open'] + df['close']) / 4.0 * df['volume'] / 1e8
    
    # 15분봉 양봉 및 몸통 완성도
    df['is_15m_bull'] = df['close'] > df['open']
    df['body_15m'] = df['close'] - df['open']
    df['upper_tail_15m'] = (df['high'] - df['close']).clip(lower=0)
    df['is_15m_strong_body'] = df['is_15m_bull'] & (df['body_15m'] > (df['upper_tail_15m'] * params.body_to_upper_tail_ratio))

    # 15분봉 수급 3배 폭증 (직전 2개봉 평균 대비)
    prev_2_avg_15m = (df['m15_money'].shift(1) + df['m15_money'].shift(2)) / 2.0
    prev_2_avg_15m = prev_2_avg_15m.replace(0, np.nan).fillna(df['m15_money'].rolling(5).mean())
    df['is_15m_supply_surge'] = df['m15_money'] >= (prev_2_avg_15m * params.supply_surge_multiplier)

    # 당일 누적 일봉 거래대금 계산
    if 'date_key' not in df.columns:
        if isinstance(df.index, pd.DatetimeIndex):
            df['date_key'] = df.index.date
        elif 'time' in df.columns:
            df['date_key'] = pd.to_datetime(df['time']).dt.date
        else:
            df['date_key'] = 0

    df['day_open'] = df.groupby('date_key')['open'].transform('first')
    df['day_high'] = df.groupby('date_key')['high'].cummax()
    df['day_low'] = df.groupby('date_key')['low'].cummin()
    df['day_volume'] = df.groupby('date_key')['volume'].cumsum()
    df['day_supply_money'] = (df['day_high'] + df['day_low'] + df['day_open'] + df['close']) / 4.0 * df['day_volume'] / 1e8

    # 일봉 20억 이상 충족 여부
    df['is_daily_money_over'] = df['day_supply_money'] >= params.min_daily_supply_money
    df['is_daily_bull'] = df['close'] >= df['day_open']

    # [수식 4 종합 신호]
    # 일봉 20억 수급 만족 + 15분봉 양봉 & 윗꼬리 짧음 & 3배 수급 폭발
    df['sig_f4'] = (
        df['is_daily_money_over'] & 
        df['is_daily_bull'] & 
        df['is_15m_strong_body'] & 
        df['is_15m_supply_surge']
    )
    
    return df


# ═══════════════════════════════════════════════════════════════
# 통합 분석 함수 (15분봉 + 일봉)
# ═══════════════════════════════════════════════════════════════

def analyze_15m_signals(
    df_15m: pd.DataFrame,
    daily_df: pd.DataFrame,
    params: Optional[Turnaround15mParams] = None
) -> pd.DataFrame:
    """
    15분봉 및 일봉 데이터를 받아 4대 수식 및 3대 조합 시그널(1+3, 2+3, 3+4)을 시계열로 계산하여 반환
    """
    if params is None:
        params = Turnaround15mParams()

    if df_15m is None or df_15m.empty or len(df_15m) < params.min_bars_15m:
        return pd.DataFrame()
    if daily_df is None or daily_df.empty or len(daily_df) < params.min_bars_daily:
        return pd.DataFrame()

    df = df_15m.copy()
    df.rename(columns={col: col.lower() for col in df.columns}, inplace=True)
    
    df_d = daily_df.copy()
    df_d.rename(columns={col: col.lower() for col in df_d.columns}, inplace=True)

    # 1. 수식 4 (일봉 20억 수급 + 15분봉 수급폭발) 계산
    df = calc_formula_4_supply(df, params)

    # 2. 15분봉 이평선 및 분봉 변곡 계산
    df['m15_sma3'] = df['close'].rolling(3).mean()
    df['m15_sma5'] = df['close'].rolling(5).mean()
    df['m15_vol_sma3'] = df['volume'].rolling(3).mean()
    df['m15_vol_sma5'] = df['volume'].rolling(5).mean()

    # 분봉 3이평 변곡 (A > A(1) && A(1) <= A(2))
    df['m15_sma3_inflection'] = (df['m15_sma3'] > df['m15_sma3'].shift(1)) & (df['m15_sma3'].shift(1) <= df['m15_sma3'].shift(2))
    # 분봉 5이평 변곡 (B > B(1) && B(1) <= B(2))
    df['m15_sma5_inflection'] = (df['m15_sma5'] > df['m15_sma5'].shift(1)) & (df['m15_sma5'].shift(1) <= df['m15_sma5'].shift(2))

    # 황룡선, TEMA 룡선 및 정배열 직전 최고 정점 저항선(M선) 계산
    df['hwangryong'], df['ryong_line'], df['m_resistance'] = calculate_hwangryong_line(df)
    df['is_above_day_open'] = df['close'] >= df['day_open']

    # 3. 일봉 데이터 준비 (날짜 매핑을 위한 과거 종가 슬라이싱)
    if 'date' in df_d.columns:
        df_d['dt'] = pd.to_datetime(df_d['date']).dt.date
    elif isinstance(df_d.index, pd.DatetimeIndex):
        df_d['dt'] = df_d.index.date
    else:
        df_d['dt'] = pd.date_range(end=pd.Timestamp.today().date(), periods=len(df_d)).date

    df_d.sort_values('dt', inplace=True)
    daily_closes_all = df_d['close'].tolist()
    daily_dates_all = df_d['dt'].tolist()

    # 4. 각 15분봉 시점별 실시간 일봉 변곡(수식1, 2, 3) 계산
    d_sma3_infl_list = []
    d_sma5_infl_list = []
    d_gc_3_20_list = []
    d_sma3_val_list = []
    d_sma5_val_list = []
    d_sma20_val_list = []

    for idx, row in df.iterrows():
        c0 = row['close']
        row_dt = row['date_key']

        if row_dt in daily_dates_all:
            d_idx = daily_dates_all.index(row_dt)
            past_closes = daily_closes_all[:d_idx]
        else:
            past_closes = daily_closes_all

        infl = calc_realtime_day_inflections(c0, past_closes)
        d_sma3_infl_list.append(infl['d_sma3_inflection'])
        d_sma5_infl_list.append(infl['d_sma5_inflection'])
        d_gc_3_20_list.append(infl['d_gc_3_20'])
        d_sma3_val_list.append(infl['d_sma3_curr'])
        d_sma5_val_list.append(infl['d_sma5_curr'])
        d_sma20_val_list.append(infl['d_sma20_curr'])

    df['d_sma3_inflection'] = d_sma3_infl_list
    df['d_sma5_inflection'] = d_sma5_infl_list
    df['d_gc_3_20'] = d_gc_3_20_list
    df['d_sma3_val'] = d_sma3_val_list
    df['d_sma5_val'] = d_sma5_val_list
    df['d_sma20_val'] = d_sma20_val_list

    # ── [수식 3 완성] 3일선 변곡 + 분봉 3이평 변곡 + 시가위 + 거래량돌파 ──
    df['cond_vol_m15_3'] = df['volume'] > df['m15_vol_sma3']
    df['sig_f3'] = (
        df['d_sma3_inflection'] & 
        df['m15_sma3_inflection'] & 
        df['is_above_day_open'] & 
        df['cond_vol_m15_3']
    )

    # ── [수식 1 완성] 5일선 변곡 + 분봉 5이평 변곡 + 시가위 + 거래량돌파 ──
    df['cond_vol_m15_5'] = df['volume'] > df['m15_vol_sma5']
    df['sig_f1'] = (
        df['d_sma5_inflection'] & 
        df['m15_sma5_inflection'] & 
        df['is_above_day_open'] & 
        df['cond_vol_m15_5']
    )

    # ── [수식 2 완성] 일봉 3-20 골든크로스 ──
    df['sig_f2'] = df['d_gc_3_20']

    # ═══════════════════════════════════════════════════════════════
    # 3대 핵심 조합 시그널 생성
    # ═══════════════════════════════════════════════════════════════

    # ① [Combo 3+4] 공격형 수급 변곡: 일봉 20억 수급 + 15분봉 3일선 변곡
    df['combo_3_4'] = df['sig_f3'] & df['sig_f4']

    # ② [Combo 2+3] 추세 대전환: 일봉 3-20 골든크로스 + 15분봉 3일선 변곡
    df['combo_2_3'] = df['sig_f2'] & df['sig_f3']

    # ③ [Combo 1+3] 안정형 더블 변곡: 3일선 + 5일선 동시 변곡 (& 황룡선 위)
    cond_hwangryong = (df['close'] >= df['hwangryong']) | df['hwangryong'].isna()
    df['combo_1_3'] = df['sig_f3'] & df['sig_f1'] & cond_hwangryong

    # 통합 매수 시그널 (어느 하나라도 충족 시)
    df['any_combo_signal'] = df['combo_3_4'] | df['combo_2_3'] | df['combo_1_3']

    return df


# ═══════════════════════════════════════════════════════════════
# 실시간 단일 종목 진입 평가 함수
# ═══════════════════════════════════════════════════════════════

def evaluate_15m_entry(
    code: str,
    name: str,
    df_15m: pd.DataFrame,
    daily_df: pd.DataFrame,
    current_price: Optional[float] = None,
    params: Optional[Turnaround15mParams] = None
) -> Dict[str, Any]:
    """
    실시간 봇 또는 스캐너에서 종목의 15분봉 진입 타점을 즉시 평가하여 반환
    """
    result = {
        "code": code,
        "name": name,
        "should_buy": False,
        "combo_type": "",
        "limit_price": 0.0,
        "priority_score": 0.0,
        "reason": "",
        "details": {}
    }

    df_signals = analyze_15m_signals(df_15m, daily_df, params)
    if df_signals.empty:
        result["reason"] = "데이터 부족 (15분봉/일봉)"
        return result

    latest = df_signals.iloc[-1]
    curr_p = float(current_price) if current_price and current_price > 0 else float(latest['close'])

    is_c34 = bool(latest.get('combo_3_4', False))
    is_c23 = bool(latest.get('combo_2_3', False))
    is_c13 = bool(latest.get('combo_1_3', False))

    if not (is_c34 or is_c23 or is_c13):
        result["reason"] = "15분봉 조합 신호 미발생"
        result["details"] = {
            "sig_f4_supply": bool(latest.get('sig_f4', False)),
            "sig_f3_turnaround": bool(latest.get('sig_f3', False)),
            "sig_f2_gc_3_20": bool(latest.get('sig_f2', False)),
            "sig_f1_turnaround": bool(latest.get('sig_f1', False)),
            "day_supply_money_억": round(float(latest.get('day_supply_money', 0)), 2),
            "m15_money_억": round(float(latest.get('m15_money', 0)), 2),
        }
        return result

    # 진입 타점 및 우선순위 스코어 결정
    reasons = []
    priority_score = 100.0
    combo_type = ""
    limit_price = curr_p

    if is_c34:
        combo_type = "Combo_3_4 (일봉20억수급 + 15분봉 3일선변곡)"
        reasons.append(f"일봉20억수급({latest['day_supply_money']:.1f}억)/15분봉수급폭발({latest['m15_money']:.1f}억) + 15분봉 3일선U턴")
        priority_score += 150.0
        limit_price = curr_p

    elif is_c23:
        combo_type = "Combo_2_3 (일봉 3-20 골든크로스 + 15분봉 3일선변곡)"
        reasons.append("일봉 3-20 골든크로스 + 15분봉 3일선U턴")
        priority_score += 120.0
        limit_price = float(latest['d_sma20_val']) if latest['d_sma20_val'] > 0 else curr_p

    elif is_c13:
        combo_type = "Combo_1_3 (3일+5일 더블변곡 + 황룡선)"
        reasons.append("일봉 3일/5일 동시 U턴 변곡 + TEMA황룡선")
        priority_score += 100.0
        limit_price = float(latest['d_sma3_val']) if latest['d_sma3_val'] > 0 else curr_p

    result.update({
        "should_buy": True,
        "combo_type": combo_type,
        "limit_price": round(limit_price, 0),
        "priority_score": priority_score,
        "reason": " / ".join(reasons),
        "details": {
            "day_supply_money_억": round(float(latest.get('day_supply_money', 0)), 2),
            "m15_money_억": round(float(latest.get('m15_money', 0)), 2),
            "d_sma3_val": round(float(latest.get('d_sma3_val', 0)), 0),
            "d_sma5_val": round(float(latest.get('d_sma5_val', 0)), 0),
            "d_sma20_val": round(float(latest.get('d_sma20_val', 0)), 0),
            "hwangryong": round(float(latest.get('hwangryong', 0)), 0) if not pd.isna(latest.get('hwangryong')) else 0,
            "m_resistance": round(float(latest.get('m_resistance', 0)), 0) if not pd.isna(latest.get('m_resistance')) else 0,
            "m15_sma3": round(float(latest.get('m15_sma3', 0)), 0),
            "close": curr_p
        }
    })

    return result
