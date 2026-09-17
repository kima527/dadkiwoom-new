"""
strategy_buy.py - 30분봉 260이평 W자 반등 우선 적용 및 일봉/30분봉 가중고가선 돌파 매수 전략
===========================================================================

매수 로직 및 우선순위:
1. [최우선] 30분봉 260이평 W자 반등 (Double Bottom Rebound):
   - 주가가 260이평선 위로 상승(1차 Peak) ➔ 260이평선 아래/부근으로 하락 및 눌림(Trough) ➔ 다시 반등하여 260이평선 재돌파(Rebound)
   - W자 반등 완성 + 가중 5-20 고가선(HH) 돌파 종목에 최우선 매수 권한 부여 (priority_score 최고점)
2. 30분봉 차트 일반 돌파:
   - 당일 단순 260이동평균선(SMA 260) 상향 돌파 (CrossUp)
   - 종가 > 가중 5-20 고가선 (가중 5-20 고가선: WMA5가 WMA20을 CrossUp할 때의 고가(HH))
3. 일봉 차트 돌파:
   - 당일 단순 20이동평균선(SMA 20) 상향 돌파 (CrossUp)
   - 종가 > 가중 5-20 고가선 (가중 5-20 고가선: WMA5가 WMA20을 CrossUp할 때의 고가(HH))
"""

import pandas as pd
import numpy as np
import logging
from strategy_15m_4formula_buy import evaluate_4formula_buy, Formula4Params
from strategy_15m_squeeze_alignment import evaluate_15m_squeeze_alignment, SqueezeAlignmentParams

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# WMA (가중이동평균) 계산
# ═══════════════════════════════════════════════════════════════
def wma(series: pd.Series, period: int) -> pd.Series:
    """가중이동평균(Weighted Moving Average)"""
    if len(series) < period:
        return pd.Series([np.nan] * len(series), index=series.index)
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=period, min_periods=period).apply(
        lambda prices: np.dot(prices, weights) / weight_sum,
        raw=True
    )

def calculate_hh(df: pd.DataFrame) -> pd.Series:
    """
    WMA5가 WMA20을 상향 돌파(CrossUp)할 때의 고가(HH)를 계산하여 반환
    MM=MA(C,5,가중); MN=MA(C,20,가중); 조건=CrossUp(MM,MN); HH=ValueWhen(1,조건,H)
    """
    if 'high' not in df.columns or len(df) < 20:
        return pd.Series([np.nan] * len(df), index=df.index)
    
    df = df.copy()
    df['wma5'] = wma(df['close'], 5)
    df['wma20'] = wma(df['close'], 20)
    
    cond_crossup = (df['wma5'].shift(1) <= df['wma20'].shift(1)) & (df['wma5'] > df['wma20'])
    
    # CrossUp 시점의 High 값을 유지(Forward Fill)
    df['hh_line'] = df['high'].where(cond_crossup).ffill()
    return df['hh_line']

# ═══════════════════════════════════════════════════════════════
# HH선(가중 5-20 고가선) 수급 돌파 & 숨고르기 지지 재반등 평가
# ═══════════════════════════════════════════════════════════════
def evaluate_hh_rebound(df_15m: pd.DataFrame, daily_df: pd.DataFrame = None) -> dict:
    """
    MM=MA(C,5,가중); MN=MA(C,20,가중); 조건=CrossUp(MM,MN); HH=ValueWhen(1,조건,H)
    HH선 상향 돌파 후 HH선 부근(-0.8% ~ +1.8%) 숨고르기 지지 안착 후 15분봉 수급 양봉 재반등 검출
    """
    res = {'should_buy': False, 'hh_price': 0.0, 'reason': '', 'priority_score': 0.0}
    if df_15m is None or len(df_15m) < 20:
        return res

    # 1. 일봉 또는 15분봉 기준 HH선 계산
    target_df = daily_df if (daily_df is not None and len(daily_df) >= 20) else df_15m
    hh_series = calculate_hh(target_df)
    valid_hh = hh_series.dropna()
    if valid_hh.empty:
        return res

    hh_val = float(valid_hh.iloc[-1])
    if hh_val <= 0:
        return res

    # 2. 현재가 및 15분봉 상태 분석
    df15 = df_15m.copy()
    df15.rename(columns={col: col.lower() for col in df15.columns}, inplace=True)
    latest_15m = df15.iloc[-1]
    curr_c = float(latest_15m['close'])
    curr_o = float(latest_15m['open'])
    curr_v = float(latest_15m['volume'])

    # HH선 대비 현재가 이격도 (-0.8% ~ +1.8% 이내 완벽 안착/숨고르기)
    diff_pct = ((curr_c - hh_val) / hh_val) * 100.0
    is_hh_touch = (-0.8 <= diff_pct <= 1.8)

    # 15분봉 양봉 (Close > Open) 및 거래량 수급 반응 (15분봉 거래대금 5억 이상 또는 수급 재반등)
    supply_15m = (latest_15m['high'] + latest_15m['low'] + curr_o + curr_c) / 4.0 * curr_v / 1e8
    is_bull = (curr_c > curr_o)
    is_supply_react = (supply_15m >= 5.0)  # 15분봉 수급 5억 이상 반응

    if is_hh_touch and is_bull and is_supply_react:
        res['should_buy'] = True
        res['hh_price'] = hh_val
        res['priority_score'] = 250.0  # 15분봉 변곡 급 고득점
        res['reason'] = (
            f"🎯 [HH선 숨고르기 지지 안착 재반등] "
            f"HH선({hh_val:,.0f}원) 부근 안착({diff_pct:+.2f}%) + 15분봉 수급({supply_15m:.1f}억) 양봉 재반등 포착"
        )

    return res

# ═══════════════════════════════════════════════════════════════
# TEMA 5-20 수식선 및 최근 5봉 10% 급등 유저 정의 전략 모듈
# ═══════════════════════════════════════════════════════════════
def calculate_tema(series: pd.Series, period: int) -> pd.Series:
    """삼중지수이동평균(TEMA) 계산: 3*EMA1 - 3*EMA2 + EMA3"""
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return 3.0 * ema1 - 3.0 * ema2 + ema3

def calculate_daily_tema_line(daily_df: pd.DataFrame) -> pd.Series:
    """
    일봉 TEMA1(5), TEMA2(20) 상향 돌파 시점의 TEMA1 수식선 계산:
    TEMA1=3*eavg(c,5)-3*eavg(eavg(c,5),5)+eavg(eavg(eavg(c,5),5),5);
    TEMA2=3*eavg(c,20)-3*eavg(eavg(c,20),20)+eavg(eavg(eavg(c,20),20),20);
    조건=CrossUp(TEMA1,TEMA2); ValueWhen(1,조건,TEMA1)
    """
    if daily_df is None or len(daily_df) < 20:
        return pd.Series([np.nan] * (len(daily_df) if daily_df is not None else 0))

    df_d = daily_df.copy()
    df_d.rename(columns={col: col.lower() for col in df_d.columns}, inplace=True)

    t1 = calculate_tema(df_d['close'], 5)
    t2 = calculate_tema(df_d['close'], 20)

    cond_crossup = (t1.shift(1) <= t2.shift(1)) & (t1 > t2)
    df_d['tema_line'] = t1.where(cond_crossup).ffill()
    return df_d['tema_line']

def check_recent_5bar_surge(daily_df: pd.DataFrame) -> tuple[bool, str]:
    """
    최근 5봉(5일) 이내 전일 종가 대비 고가가 +10.0% 이상 급등했던 적이 1회 이상 존재하는지 검증
    """
    if daily_df is None or len(daily_df) < 6:
        return False, "일봉 데이터 수량 부족"

    df_d = daily_df.copy()
    df_d.rename(columns={col: col.lower() for col in df_d.columns}, inplace=True)

    recent = df_d.tail(6)
    for i in range(1, len(recent)):
        curr_h = float(recent.iloc[i]['high'])
        prev_c = float(recent.iloc[i-1]['close'])
        if prev_c > 0:
            gain_pct = ((curr_h - prev_c) / prev_c) * 100.0
            if gain_pct >= 10.0:
                return True, f"최근 5봉 이내 10%+ 폭등 경험 있음({gain_pct:+.1f}%)"
    return False, "최근 5봉 이내 10% 이상 고가 급등 경험 없음"

def evaluate_user_master_strategy(
    df_15m: pd.DataFrame,
    df_30m: pd.DataFrame = None,
    daily_df: pd.DataFrame = None,
    is_naver_theme: bool = True
) -> dict:
    """
    [유저 지정 핵심 4대 수식 & 타점 통합 전략]
    1. 일봉 종가 >= TEMA 5-20 수식선 위 위치
    2. 최근 5봉 이내 전일대비 고가 10% 이상 급등 경험 1회 이상
    3. NAVER 증권 당일 테마주 포함 종목
    4. MM(WMA5)-MN(WMA20) 돌파 관찰
    5. [최종 매수 타점]: 15분봉 WMA3이 WMA5를 상향 돌파 (CrossUp(WMA3, WMA5)) 시 지정가 매수!
    """
    res = {'should_buy': False, 'price': 0.0, 'reason': '', 'priority_score': 0.0, 'limit_price': 0.0}

    # 0. 네이버 테마주 검증
    if not is_naver_theme:
        res['reason'] = "❌ 네이버 증권 당일 테마주 미포함"
        return res

    if daily_df is None or len(daily_df) < 20 or df_15m is None or len(df_15m) < 20:
        res['reason'] = "❌ 차트 데이터 수량 부족"
        return res

    # 1. 일봉 TEMA 5-20 수식선 위 위치 검증
    tema_line_series = calculate_daily_tema_line(daily_df)
    valid_tema = tema_line_series.dropna()
    if valid_tema.empty:
        res['reason'] = "❌ 일봉 TEMA 수식선 생성 불가"
        return res

    tema_val = float(valid_tema.iloc[-1])
    curr_daily_close = float(daily_df.iloc[-1]['close'])

    if curr_daily_close < tema_val:
        res['reason'] = f"❌ 일봉 종가({curr_daily_close:,.0f}원) < TEMA 수식선({tema_val:,.0f}원) 이탈"
        return res

    # 2. 최근 5봉 이내 고가 10%+ 1회 이상 경험 검증
    has_5bar_surge, surge_msg = check_recent_5bar_surge(daily_df)
    if not has_5bar_surge:
        res['reason'] = f"❌ {surge_msg}"
        return res

    # 3. 15분봉 차트 기준 WMA3, WMA5, WMA20 및 5대 정밀 수급 수식 계산
    df15 = df_15m.copy()
    df15.rename(columns={col: col.lower() for col in df15.columns}, inplace=True)

    df15['wma3'] = wma(df15['close'], 3)
    df15['wma5'] = wma(df15['close'], 5)
    df15['wma20'] = wma(df15['close'], 20)

    # A = (H + L + O + C) / 4 * V / 100,000,000 (15분봉 거래대금 (억원))
    # AvgA = ma(A, 20)
    df15['a'] = (df15['high'] + df15['low'] + df15['open'] + df15['close']) / 4.0 * df15['volume'] / 1e8
    df15['avga'] = df15['a'].rolling(20, min_periods=1).mean()

    latest = df15.iloc[-1]
    prev = df15.iloc[-2] if len(df15) >= 2 else latest
    prev2 = df15.iloc[-3] if len(df15) >= 3 else prev

    curr_c = float(latest['close'])
    curr_o = float(latest['open'])
    curr_h = float(latest['high'])

    wma3_curr = float(latest['wma3'])
    wma5_curr = float(latest['wma5'])
    wma20_curr = float(latest['wma20'])

    wma3_prev = float(prev['wma3'])
    wma5_prev = float(prev['wma5'])

    a_val = float(latest['a'])
    avga_val = float(latest['avga'])
    a1_val = float(prev['a'])
    a2_val = float(prev2['a'])
    prev_2_avg = (a1_val + a2_val) / 2.0

    # 유저 지정 15분봉 4대 수급 수식 검증
    # 1. A >= AvgA * 5 (20봉 평균 수급 대비 5배 폭증)
    cond1_avga_5x = (a_val >= avga_val * 5.0) if avga_val > 0 else True
    # 2. O < C (양봉)
    cond2_bull = (curr_c > curr_o)
    # 3. C - O > (H - C) * 1.2 (양봉 몸통 > 윗꼬리 * 1.2배 탄탄한 양봉)
    cond3_body_strong = (curr_c - curr_o) > ((curr_h - curr_c) * 1.2)
    # 4. A >= (A(1) + A(2)) / 2 * 3 (직전 2개봉 평균 대비 3배 폭증)
    cond4_prev2_3x = (a_val >= prev_2_avg * 3.0) if prev_2_avg > 0 else True

    is_supply_formula_met = cond1_avga_5x and cond2_bull and cond3_body_strong and cond4_prev2_3x

    # 4. MM(WMA5) >= MN(WMA20) 돌파 관찰 조건
    is_wma5_above_20 = (wma5_curr >= wma20_curr * 0.995)

    # 5. [최종 매수 타점] CrossUp(WMA3, WMA5) - 3일선이 5일선 상향 돌파
    is_crossup_3_5 = (wma3_prev <= wma5_prev) and (wma3_curr > wma5_curr)
    is_3_5_tight = (wma3_curr >= wma5_curr) and (((wma3_curr - wma5_curr) / wma5_curr) <= 0.005)

    if is_supply_formula_met and is_wma5_above_20 and (is_crossup_3_5 or is_3_5_tight):
        # 꼭대기 추격 매수 방지: WMA5 대비 +1.5% 초과 치솟은 꼭대기는 거부
        diff_from_wma5 = ((curr_c - wma5_curr) / wma5_curr) * 100.0
        if diff_from_wma5 > 1.5:
            res['reason'] = f"⚠️ WMA5 대비 +{diff_from_wma5:.2f}% 상단 초과 (꼭대기 추격 매수 방지 차단)"
            return res

        res['should_buy'] = True
        res['price'] = curr_c
        res['limit_price'] = wma5_curr
        res['priority_score'] = 400.0  # 유저 수식 100% 완벽 충족 최고점
        res['reason'] = (
            f"🔥 [유저 15분봉 수급+TEMA 수식 완벽 매수 타점] "
            f"일봉 TEMA선({tema_val:,.0f}원) 위 + 5봉내 10% 급등 + "
            f"15분봉 거래대금 A({a_val:.1f}억 >= AvgA의 5배) + 양봉 몸통>윗꼬리*1.2 + "
            f"WMA3({wma3_curr:,.0f}원) > WMA5({wma5_curr:,.0f}원) 골든크로스 터짐!"
        )

    return res


# ═══════════════════════════════════════════════════════════════
# 30분봉 실시간 3일선 / 5일선 계산 (키움증권 분봉 수식)
# ═══════════════════════════════════════════════════════════════
def calculate_realtime_day_smas(df_30m: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    30분봉 차트에서 키움증권 일봉 3일선/5일선을 실시간 계산:
      3일선 = (npredayclose(2) + npredayclose(1) + dayclose()) / 3
      5일선 = (npredayclose(4) + npredayclose(3) + npredayclose(2) + npredayclose(1) + dayclose()) / 5
    """
    if df_30m is None or df_30m.empty or daily_df is None or len(daily_df) < 5:
        return df_30m

    df30 = df_30m.copy()
    df30.rename(columns={col: col.lower() for col in df30.columns}, inplace=True)

    df_d = daily_df.copy()
    df_d.rename(columns={col: col.lower() for col in df_d.columns}, inplace=True)

    if 'date' in df_d.columns:
        df_d['dt'] = pd.to_datetime(df_d['date']).dt.date
    elif isinstance(df_d.index, pd.DatetimeIndex):
        df_d['dt'] = df_d.index.date
    else:
        df_d['dt'] = pd.date_range(end=pd.Timestamp.today().date(), periods=len(df_d)).date

    df_d.sort_values('dt', inplace=True)

    df_d['c_d1'] = df_d['close'].shift(1)  # npredayclose(1)
    df_d['c_d2'] = df_d['close'].shift(2)  # npredayclose(2)
    df_d['c_d3'] = df_d['close'].shift(3)  # npredayclose(3)
    df_d['c_d4'] = df_d['close'].shift(4)  # npredayclose(4)

    day_map = df_d.set_index('dt')[['c_d1', 'c_d2', 'c_d3', 'c_d4']].to_dict(orient='index')

    if isinstance(df30.index, pd.DatetimeIndex):
        df30['dt'] = df30.index.date
    elif 'time' in df30.columns:
        df30['dt'] = pd.to_datetime(df30['time']).dt.date
    else:
        latest_dt = df_d['dt'].iloc[-1]
        df30['dt'] = latest_dt

    d1_list, d2_list, d3_list, d4_list = [], [], [], []
    for d in df30['dt']:
        vals = day_map.get(d)
        if not vals:
            vals = df_d[['c_d1', 'c_d2', 'c_d3', 'c_d4']].iloc[-1].to_dict()
        d1_list.append(vals['c_d1'])
        d2_list.append(vals['c_d2'])
        d3_list.append(vals['c_d3'])
        d4_list.append(vals['c_d4'])

    df30['c_d1'] = d1_list
    df30['c_d2'] = d2_list
    df30['c_d3'] = d3_list
    df30['c_d4'] = d4_list

    df30['day_sma3'] = (df30['c_d2'] + df30['c_d1'] + df30['close']) / 3.0
    df30['day_sma5'] = (df30['c_d4'] + df30['c_d3'] + df30['c_d2'] + df30['c_d1'] + df30['close']) / 5.0

    df30['gc_3_5'] = (df30['day_sma3'] > df30['day_sma5']) & (df30['day_sma3'].shift(1) <= df30['day_sma5'].shift(1))
    return df30

# ═══════════════════════════════════════════════════════════════
# 30분봉 260이평선 W자 반등(이중바닥 재돌파) 검출
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
def detect_w_rebound_30m(df30: pd.DataFrame, lookback: int = 200) -> tuple[bool, dict]:
    """
    30분봉 260이평선을 '중심 기준선(Baseline)'으로 잡고 W자 이중바닥 반등 패턴 검출:
    1) 1차 바닥 (Left Bottom): 260이평선 아래로 이탈 또는 260선 지지 터치 (Low <= SMA260 * 1.01)
    2) 중간 반등 (Middle Peak): 260이평선 위로 상승 (High >= SMA260 * 1.015)
    3) 2차 바닥 (Right Bottom/눌림): 다시 260선으로 내려와 지지 형성 (Low <= SMA260 * 1.015)
    4) W자 완성 돌파 (Breakout): 당일 260선(기준선)을 상향 돌파/지지 후 갓 올라선 상태 (이격도 +0% ~ +3.5% 이내)
    """
    empty_res = (False, {})
    if df30 is None or len(df30) < 260:
        return empty_res

    df = df30.copy()
    df.rename(columns={col: col.lower() for col in df.columns}, inplace=True)
    if 'close' not in df.columns:
        return empty_res

    if 'sma260' not in df.columns:
        df['sma260'] = df['close'].rolling(window=260, min_periods=260).mean()

    valid_df = df.dropna(subset=['sma260'])
    if valid_df.empty:
        return empty_res

    lookback_len = min(len(valid_df), lookback)
    recent_df = valid_df.iloc[-lookback_len:].copy()

    closes = recent_df['close'].values.astype(float)
    highs = recent_df['high'].values.astype(float)
    lows = recent_df['low'].values.astype(float)
    sma260s = recent_df['sma260'].values.astype(float)
    n = len(closes)

    curr_c = closes[-1]
    curr_sma = sma260s[-1]

    # [핵심 1] 기준선 이격도 엄격 제한:
    # W자 패턴 완성 타점은 260이평선(기준선) 바로 위/근처(+0.0% ~ +3.5% 이내)여야 함!
    # 이미 260선에서 +10%, +20% 폭등해 있는 고점 종목(예: 성광벤드)은 원천 탈락!
    if curr_c < curr_sma * 0.995 or curr_c > curr_sma * 1.035:
        return empty_res

    # [핵심 2] 당일/최근 260선 기준선 상향 돌파 또는 지지 반등 확인
    recent_breakout = False
    for i in range(n - 1, max(0, n - 5), -1):
        if closes[i] >= sma260s[i] * 0.998 and (i == 0 or closes[i - 1] <= sma260s[i - 1] * 1.005 or lows[i] <= sma260s[i] * 1.005):
            recent_breakout = True
            break

    if not recent_breakout:
        return empty_res

    # [핵심 3] 2차 바닥 (Right Bottom / 260선 부근 눌림 지지) 탐색 (최근 2~60봉 내)
    right_trough_idx = None
    right_trough_low = float('inf')
    for i in range(n - 2, max(0, n - 65), -1):
        if lows[i] <= sma260s[i] * 1.015:
            if lows[i] < right_trough_low:
                right_trough_low = lows[i]
                right_trough_idx = i

    if right_trough_idx is None:
        return empty_res

    # [핵심 4] 중간 반등 고점 (Middle Peak) 탐색 (2차 바닥 이전)
    middle_peak_idx = None
    middle_peak_high = float('-inf')
    for i in range(right_trough_idx - 1, max(0, right_trough_idx - 80), -1):
        if highs[i] >= sma260s[i] * 1.015 or closes[i] > sma260s[i]:
            if highs[i] > middle_peak_high:
                middle_peak_high = highs[i]
                middle_peak_idx = i

    if middle_peak_idx is None:
        return empty_res

    # [핵심 5] 1차 바닥 (Left Bottom) 탐색 (중간 반등 이전)
    left_trough_idx = None
    left_trough_low = float('inf')
    for i in range(middle_peak_idx - 1, max(0, middle_peak_idx - 100), -1):
        if lows[i] <= sma260s[i] * 1.015:
            if lows[i] < left_trough_low:
                left_trough_low = lows[i]
                left_trough_idx = i

    if left_trough_idx is None:
        return empty_res

    # [핵심 6] W자 형상 검증: 중간 고점 > 1차 바닥 & 2차 바닥
    if middle_peak_high <= left_trough_low or middle_peak_high <= right_trough_low:
        return empty_res

    rebound_pct = ((curr_c - right_trough_low) / right_trough_low) * 100 if right_trough_low > 0 else 0.0
    left_bars_ago = n - 1 - left_trough_idx
    peak_bars_ago = n - 1 - middle_peak_idx
    right_bars_ago = n - 1 - right_trough_idx

    w_info = {
        "is_w_rebound": True,
        "cycle_name": "30분봉 260이평 기준선 W자 반등",
        "left_bottom_low": left_trough_low,
        "left_bars_ago": left_bars_ago,
        "middle_peak_high": middle_peak_high,
        "middle_bars_ago": peak_bars_ago,
        "right_bottom_low": right_trough_low,
        "right_bars_ago": right_bars_ago,
        "sma260": curr_sma,
        "current_price": curr_c,
        "rebound_pct": rebound_pct,
        "diff_from_sma260_pct": ((curr_c - curr_sma) / curr_sma) * 100,
        "description": (
            f"[30분봉 260이평 기준선 W자 패턴 완성] "
            f"1차바닥:{left_trough_low:,.0f}원[{left_bars_ago}봉전] ➔ "
            f"중간반등:{middle_peak_high:,.0f}원[{peak_bars_ago}봉전] ➔ "
            f"2차지지바닥:{right_trough_low:,.0f}원[{right_bars_ago}봉전] ➔ "
            f"260이평({curr_sma:,.0f}원) 기준선 재돌파 안착 (현재가:{curr_c:,.0f}원, 이격도:{((curr_c - curr_sma)/curr_sma)*100:+.2f}%)"
        )
    }
    return True, w_info

# ═══════════════════════════════════════════════════════════════
# 중소형주 분봉 수급 폭발 신호 검출
# A = (H+L+O+C)/4*V/100000000;
# AvgA = ma(A, 20);
# A >= AvgA * 5 AND O < C AND C - O > (H - C) * 1.2 AND A >= (A(1) + A(2)) / 2 * 3
# ═══════════════════════════════════════════════════════════════
def check_smallcap_supply_signal(df: pd.DataFrame) -> tuple[bool, dict]:
    """
    중소형주 분봉 수급 공식 완성 검출
    """
    if df is None or len(df) < 22:
        return False, {}
    
    df_c = df.copy()
    col_map = {c: str(c).lower() for c in df_c.columns if str(c).lower() in ('open', 'high', 'low', 'close', 'volume')}
    df_c.rename(columns=col_map, inplace=True)
    
    if not all(k in df_c.columns for k in ('open', 'high', 'low', 'close', 'volume')):
        return False, {}
        
    df_c['supply'] = (df_c['high'] + df_c['low'] + df_c['open'] + df_c['close']) / 4.0 * df_c['volume'] / 1e8
    df_c['supply_ma20'] = df_c['supply'].rolling(20, min_periods=1).mean()
    
    latest = df_c.iloc[-1]
    prev1 = df_c.iloc[-2]
    prev2 = df_c.iloc[-3]
    
    a_val = float(latest['supply'])
    avga_val = float(latest['supply_ma20'])
    o_val = float(latest['open'])
    c_val = float(latest['close'])
    h_val = float(latest['high'])
    
    a1_val = float(prev1['supply'])
    a2_val = float(prev2['supply'])
    prev_2_avg = (a1_val + a2_val) / 2.0
    
    cond_ma20_5x = (a_val >= avga_val * 5.0) if avga_val > 0 else True
    cond_bull = (c_val > o_val)
    cond_body_strong = (c_val - o_val) > ((h_val - c_val) * 1.2)
    cond_prev2_3x = (a_val >= prev_2_avg * 3.0) if prev_2_avg > 0 else True
    
    is_signal = bool(cond_ma20_5x and cond_bull and cond_body_strong and cond_prev2_3x)
    info = {
        "is_signal": is_signal,
        "supply_억": round(a_val, 2),
        "supply_ma20_억": round(avga_val, 2),
        "surge_ratio_ma20": round(a_val / avga_val, 1) if avga_val > 0 else 0.0,
        "surge_ratio_prev2": round(a_val / prev_2_avg, 1) if prev_2_avg > 0 else 0.0,
        "close": c_val
    }
    return is_signal, info

# ═══════════════════════════════════════════════════════════════
# 매수 신호 종합 분석 함수
# ═══════════════════════════════════════════════════════════════
def analyze_buy_signals(df_30m: pd.DataFrame, df_120t: pd.DataFrame = None, daily_df: pd.DataFrame = None, df_15m: pd.DataFrame = None) -> dict:
    """
    일봉 및 30분봉, 15분봉 조건을 모두 검사하여 최우선 순위를 고려해 매수 신호 반환
    - [15분봉 4대 수식] 수급 20억 + 황룡선/M선 + 1-20-60 첫 정배열 + M선 상향 돌파 (최우선)
    - [중소형주 수급] 20봉 평균 5배 + 양봉 몸통>윗꼬리*1.2 + 직전2봉 3배 폭증
    - [최우선] 30분봉 260이평 W자 반등(1차상승 ➔ 하락눌림 ➔ 260이평 재돌파)
    - [원칙 1] 일봉: 당일 단순 20이평선(SMA20) 상향 돌파
    - [원칙 2] 30분봉: 당일 단순 260이평선(SMA260) 상향 돌파
    - [원칙 3] 30분봉: 3일선이 5일선 상향 골든크로스 & 우상향
    """
    result = {
        "buy": False,
        "ll": 0.0,
        "close": 0.0,
        "reason": "",
        "remove_watchlist": False,
        "is_w_rebound": False,
        "is_supply_surge": False,
        "is_4formula_buy": False,
        "priority_score": 0.0,
        "w_info": {},
        "supply_info": {},
        "formula4_info": {}
    }

    if df_30m is None or df_30m.empty or len(df_30m) < 20:
        return result

    df30 = df_30m.copy()
    df30.rename(columns={col: col.lower() for col in df30.columns}, inplace=True)
    if 'close' not in df30.columns:
        return result
        
    current_price = float(df30.iloc[-1]['close'])
    result['close'] = current_price

    # 0-B. 👑 [최우선 1순위] 15분봉 20/40/60 이평선 수평 응축 + 3-5-20-40-60 정배열 수급 돌파 (전략 B)
    is_squeeze_b_sig = False
    squeeze_b_info = {}
    if df_15m is not None and not df_15m.empty and len(df_15m) >= 60:
        sq_res = evaluate_15m_squeeze_alignment(code="", name="", df_15m=df_15m, daily_df=daily_df)
        if sq_res.get("is_buy_signal"):
            is_squeeze_b_sig = True
            squeeze_b_info = sq_res
            result['is_squeeze_b_buy'] = True
            result['squeeze_b_info'] = squeeze_b_info
            result['priority_score'] = max(result['priority_score'], 300.0)

    # 0. 15분봉 4대 수식 올인원 돌파 신호 검출
    is_f4_sig = False
    f4_info = {}
    if df_15m is not None and not df_15m.empty and len(df_15m) >= 60:
        f4_res = evaluate_4formula_buy(code="", name="", df_15m=df_15m, current_price=current_price)
        if f4_res.get("should_buy"):
            is_f4_sig = True
            f4_info = f4_res
            result['is_4formula_buy'] = True
            result['formula4_info'] = f4_info
            result['priority_score'] = max(result['priority_score'], 200.0)

    # 1. 중소형주 분봉 수급 폭발 신호 검출
    is_supply_sig, supply_info = check_smallcap_supply_signal(df30)
    if is_supply_sig:
        result['is_supply_surge'] = True
        result['supply_info'] = supply_info
        result['priority_score'] += 150.0

    # 2. 30분봉 260이평 W자 반등 패턴 사전 검출
    is_w_rebound, w_info = detect_w_rebound_30m(df30)
    if is_w_rebound:
        result['is_w_rebound'] = True
        result['w_info'] = w_info
        result['priority_score'] = max(result['priority_score'], 100.0 + min(w_info.get('rebound_pct', 0.0), 20.0))

    is_daily_condition_met = False
    daily_reason = ""
    daily_hh_val = 0.0

    # ─────────────────────────────────────────────────
    # [원칙 1] 일봉 1-20 골든크로스 (당일 주가가 일봉 20이평선 상향 돌파 시점)
    # ─────────────────────────────────────────────────
    cond1_daily_sma20 = False
    daily_reason = ""
    d_sma20_val = 0.0

    if daily_df is not None and not daily_df.empty and len(daily_df) >= 20:
        df_d = daily_df.copy()
        df_d.rename(columns={col: col.lower() for col in df_d.columns}, inplace=True)
        df_d['sma20'] = df_d['close'].rolling(window=20, min_periods=20).mean()

        if len(df_d) >= 2:
            d_latest = df_d.iloc[-1]
            d_prev = df_d.iloc[-2]
            d_sma20_val = float(d_latest['sma20']) if pd.notna(d_latest['sma20']) else 0.0
            d_prev_sma20 = float(d_prev['sma20']) if pd.notna(d_prev['sma20']) else 0.0
            d_prev_close = float(d_prev['close']) if pd.notna(d_prev['close']) else 0.0

            if d_sma20_val > 0 and d_prev_sma20 > 0:
                if (d_prev_close <= d_prev_sma20) and (current_price >= d_sma20_val):
                    cond1_daily_sma20 = True
                    diff_pct = ((current_price - d_sma20_val) / d_sma20_val) * 100
                    daily_reason = (
                        f"🟢 [원칙1: 일봉 1-20 골든크로스] "
                        f"일봉 20이평선({d_sma20_val:,.0f}원) 돌파 ➔ 20일선 지정가 예약매수 (현재가: {current_price:,.0f}원, 이격도: {diff_pct:+.2f}%)"
                    )

    # ─────────────────────────────────────────────────
    # [원칙 2] 30분봉 1-260 골든크로스 (당일 주가가 30분봉 260이평선 상향 돌파 시점)
    # ─────────────────────────────────────────────────
    cond2_30m_sma260 = False
    m30_reason = ""
    m30_sma260_val = 0.0

    if len(df30) >= 260:
        df30['sma260'] = df30['close'].rolling(window=260, min_periods=260).mean()
        m30_latest = df30.iloc[-1]
        m30_sma260_val = float(m30_latest['sma260']) if pd.notna(m30_latest['sma260']) else 0.0

        if m30_sma260_val > 0 and current_price >= m30_sma260_val:
            if isinstance(df30.index, pd.DatetimeIndex):
                today_date = df30.index[-1].date()
                today_mask = df30.index.date == today_date
                df30_today = df30[today_mask]
                df30_prev = df30[~today_mask]
            else:
                df30_today = df30.iloc[-13:]
                df30_prev = df30.iloc[:-13]

            prev_day_last_close = float(df30_prev.iloc[-1]['close']) if not df30_prev.empty else 0.0
            prev_day_last_sma260 = float(df30_prev.iloc[-1]['sma260']) if (not df30_prev.empty and pd.notna(df30_prev.iloc[-1]['sma260'])) else 0.0
            
            climbed_from_prev_day = (prev_day_last_close <= prev_day_last_sma260)
            today_crossup = False
            if len(df30_today) >= 2:
                crosses = (df30_today['close'] > df30_today['sma260']) & (df30_today['close'].shift(1) <= df30_today['sma260'].shift(1))
                today_crossup = bool(crosses.any())

            if climbed_from_prev_day or today_crossup or is_w_rebound:
                cond2_30m_sma260 = True
                diff_pct = ((current_price - m30_sma260_val) / m30_sma260_val) * 100
                if is_w_rebound:
                    m30_reason = (
                        f"🔥 [원칙2: 30분봉 1-260 W자 반등 골든크로스] {w_info['description']} "
                        f"➔ 260이평선({m30_sma260_val:,.0f}원) 지정가 예약매수 (현재가: {current_price:,.0f}원, 이격도: {diff_pct:+.2f}%)"
                    )
                else:
                    m30_reason = (
                        f"🟢 [원칙2: 30분봉 1-260 골든크로스] "
                        f"260이평선({m30_sma260_val:,.0f}원) 돌파 ➔ 260이평 지정가 예약매수 (현재가: {current_price:,.0f}원, 이격도: {diff_pct:+.2f}%)"
                    )

    # ─────────────────────────────────────────────────
    # [원칙 3] 30분봉 3이평-5이평 골든크로스 (당일 3일선이 5일선 상향 돌파 시점)
    # ─────────────────────────────────────────────────
    cond3_day_sma_cross = False
    day_sma_reason = ""
    curr_sma3 = 0.0
    curr_sma5 = 0.0
    prev_sma3 = 0.0

    if daily_df is not None and len(daily_df) >= 5:
        df30_day_sma = calculate_realtime_day_smas(df30, daily_df)
        if 'day_sma3' in df30_day_sma.columns and 'day_sma5' in df30_day_sma.columns:
            latest_s = df30_day_sma.iloc[-1]
            prev_s = df30_day_sma.iloc[-2] if len(df30_day_sma) >= 2 else latest_s

            curr_sma3 = float(latest_s['day_sma3']) if pd.notna(latest_s['day_sma3']) else 0.0
            curr_sma5 = float(latest_s['day_sma5']) if pd.notna(latest_s['day_sma5']) else 0.0
            prev_sma3 = float(prev_s['day_sma3']) if pd.notna(prev_s['day_sma3']) else 0.0

            is_s3_above_s5 = (curr_sma3 > curr_sma5)
            is_s3_slope_up = (curr_sma3 >= prev_sma3)

            if curr_sma3 > 0 and curr_sma5 > 0 and is_s3_above_s5 and is_s3_slope_up:
                if isinstance(df30_day_sma.index, pd.DatetimeIndex):
                    today_date = df30_day_sma.index[-1].date()
                    today_mask = df30_day_sma.index.date == today_date
                    df30_today_smas = df30_day_sma[today_mask]
                    df30_prev_smas = df30_day_sma[~today_mask]
                else:
                    df30_today_smas = df30_day_sma.iloc[-13:]
                    df30_prev_smas = df30_day_sma.iloc[:-13]

                was_below_yesterday = True
                if not df30_prev_smas.empty:
                    prev_last_s3 = float(df30_prev_smas.iloc[-1]['day_sma3'])
                    prev_last_s5 = float(df30_prev_smas.iloc[-1]['day_sma5'])
                    was_below_yesterday = (prev_last_s3 <= prev_last_s5)

                today_crossup = False
                if len(df30_today_smas) >= 2:
                    crosses = (df30_today_smas['day_sma3'] > df30_today_smas['day_sma5']) & (df30_today_smas['day_sma3'].shift(1) <= df30_today_smas['day_sma5'].shift(1))
                    today_crossup = bool(crosses.any())

                if was_below_yesterday or today_crossup:
                    cond3_day_sma_cross = True
                    diff_from_sma3 = ((current_price - curr_sma3) / curr_sma3) * 100
                    slope_pct = ((curr_sma3 - prev_sma3) / prev_sma3) * 100 if prev_sma3 > 0 else 0.0
                    day_sma_reason = (
                        f"⚡ [원칙3: 30분봉 3-5 골든크로스] "
                        f"3일선({curr_sma3:,.0f}원, 기울기:{slope_pct:+.2f}%) > 5일선({curr_sma5:,.0f}원) ➔ "
                        f"3일선({curr_sma3:,.0f}원) 지정가 예약매수 (현재가: {current_price:,.0f}원, 이격도: {diff_from_sma3:+.2f}%)"
                    )

    # ─────────────────────────────────────────────────
    # 매수 신호 판정: 15분 이평 응축 정배열(전략B), 15분봉 4대 수식, 수급 폭발 또는 3대 핵심 원칙
    # ─────────────────────────────────────────────────
    if is_squeeze_b_sig or is_f4_sig or is_supply_sig or cond1_daily_sma20 or cond2_30m_sma260 or cond3_day_sma_cross:
        result['buy'] = True
        
        reasons = []
        if is_squeeze_b_sig:
            reasons.append(squeeze_b_info.get('reason', '👑 [1순위: 15분 이평 응축 정배열 수급 돌파] 20-40-60 응축 + 3-5-20-40-60 정배열 + 수급 폭발'))
            result['target_price'] = current_price
            result['ll'] = current_price
            result['priority_score'] = max(result['priority_score'], 300.0)

        if is_f4_sig:
            reasons.append(f4_info.get('reason', '🎯 [15분봉 4대 수식 완성] 15분봉 수급폭증 + 1-20-60 첫정배열 + M선 골든크로스'))
            result['target_price'] = current_price if result.get('target_price', 0) == 0 else result['target_price']
            result['ll'] = current_price if result['ll'] == 0 else result['ll']
            result['priority_score'] = max(result['priority_score'], 200.0)

        if is_supply_sig:
            reasons.append(
                f"🚀 [중소형주 수급 폭발봉] 거래대금 {supply_info['supply_억']:.1f}억 (20이평 대비 {supply_info['surge_ratio_ma20']:.1f}배, 직전2봉 대비 {supply_info['surge_ratio_prev2']:.1f}배) + 탄탄한 양봉"
            )
            result['target_price'] = current_price if result.get('target_price', 0) == 0 else result['target_price']
            result['ll'] = current_price if result['ll'] == 0 else result['ll']

        if cond2_30m_sma260:
            reasons.append(m30_reason)
            result['ll'] = m30_sma260_val if result['ll'] == 0 else result['ll']
            result['target_price'] = m30_sma260_val if result.get('target_price', 0) == 0 else result['target_price']
            base_score = 100.0 + min(w_info.get('rebound_pct', 0.0), 20.0) if is_w_rebound else 85.0
            result['priority_score'] = max(result['priority_score'], base_score)

        if cond1_daily_sma20:
            reasons.append(daily_reason)
            result['ll'] = d_sma20_val if result['ll'] == 0 else result['ll']
            result['target_price'] = d_sma20_val if result.get('target_price', 0) == 0 else result['target_price']
            result['priority_score'] = max(result['priority_score'], 80.0)

        if cond3_day_sma_cross:
            reasons.append(day_sma_reason)
            result['ll'] = curr_sma3 if result['ll'] == 0 else result['ll']
            result['target_price'] = curr_sma3 if result.get('target_price', 0) == 0 else result['target_price']
            result['priority_score'] = max(result['priority_score'], 90.0)

        result['reason'] = " | ".join(reasons)

    return result
