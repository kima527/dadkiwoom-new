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
# 매수 신호 종합 분석 함수
# ═══════════════════════════════════════════════════════════════
def analyze_buy_signals(df_30m: pd.DataFrame, df_120t: pd.DataFrame, daily_df: pd.DataFrame = None) -> dict:
    """
    일봉 및 30분봉 조건을 모두 검사하여 최우선 순위(W자 반등 종목)를 고려해 매수 신호 반환
    - [최우선] 30분봉 260이평 W자 반등(1차상승 ➔ 하락눌림 ➔ 260이평 재돌파) + HH 돌파
    - [조건 1] 일봉: 당일 단순 20이평선(SMA20) 상향 돌파 + 현재가 > 가중 5-20 고가선(HH)
    - [조건 2] 30분봉: 당일 단순 260이평선(SMA260) 상향 돌파 + 현재가 > 가중 5-20 고가선(HH)
    """
    result = {
        "buy": False,
        "ll": 0.0,
        "close": 0.0,
        "reason": "",
        "remove_watchlist": False,
        "is_w_rebound": False,
        "priority_score": 0.0,
        "w_info": {}
    }

    if df_30m is None or df_30m.empty or len(df_30m) < 20:
        return result

    df30 = df_30m.copy()
    df30.rename(columns={col: col.lower() for col in df30.columns}, inplace=True)
    if 'close' not in df30.columns:
        return result
        
    current_price = float(df30.iloc[-1]['close'])
    result['close'] = current_price

    # 30분봉 260이평 W자 반등 패턴 사전 검출
    is_w_rebound, w_info = detect_w_rebound_30m(df30)
    if is_w_rebound:
        result['is_w_rebound'] = True
        result['w_info'] = w_info
        result['priority_score'] = 100.0 + min(w_info.get('rebound_pct', 0.0), 20.0)

    is_daily_condition_met = False
    daily_reason = ""
    daily_hh_val = 0.0

    # ─────────────────────────────────────────────────
    # [조건 1] 30분봉에서 260이평선 당일 돌파 검사
    # ─────────────────────────────────────────────────
    cond1_30m_sma260 = False
    m30_reason = ""
    m30_sma260_val = 0.0

    if len(df30) >= 260:
        df30['sma260'] = df30['close'].rolling(window=260, min_periods=260).mean()
        m30_latest = df30.iloc[-1]
        m30_sma260_val = float(m30_latest['sma260']) if pd.notna(m30_latest['sma260']) else 0.0

        if m30_sma260_val > 0 and current_price > m30_sma260_val:
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
            
            # 어제 종가 <= 어제 SMA260 이었거나, 당일 장중 캔들에서 직접 CrossUp 발생했거나, W자 반등 완성
            climbed_from_prev_day = (prev_day_last_close <= prev_day_last_sma260)
            today_crossup = False
            if len(df30_today) >= 2:
                crosses = (df30_today['close'] > df30_today['sma260']) & (df30_today['close'].shift(1) <= df30_today['sma260'].shift(1))
                today_crossup = bool(crosses.any())

            if climbed_from_prev_day or today_crossup or is_w_rebound:
                cond1_30m_sma260 = True
                diff_pct = ((current_price - m30_sma260_val) / m30_sma260_val) * 100
                if is_w_rebound:
                    m30_reason = (
                        f"🔥 [조건1: 30분봉 260이평 W자 반등 돌파] {w_info['description']} "
                        f"(260이평: {m30_sma260_val:,.0f}원, 현재가: {current_price:,.0f}원, 이격도: {diff_pct:+.2f}%)"
                    )
                else:
                    m30_reason = (
                        f"🟢 [조건1: 30분봉 당일 260이평 상향 돌파] "
                        f"260이평({m30_sma260_val:,.0f}원) 위 안착 (현재가: {current_price:,.0f}원, 이격도: {diff_pct:+.2f}%)"
                    )

    # ─────────────────────────────────────────────────
    # [조건 2] 일봉에서 당일 20이평선 위로 돌파 검사
    # ─────────────────────────────────────────────────
    cond2_daily_sma20 = False
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
                # 전일 종가 <= 전일 20이평 & 현재가 > 당일 20이평
                if (d_prev_close <= d_prev_sma20) and (current_price > d_sma20_val):
                    cond2_daily_sma20 = True
                    diff_pct = ((current_price - d_sma20_val) / d_sma20_val) * 100
                    daily_reason = (
                        f"🟢 [조건2: 일봉 당일 20이평선 상향 돌파] "
                        f"일봉 20이평({d_sma20_val:,.0f}원) 돌파 안착 (현재가: {current_price:,.0f}원, 이격도: {diff_pct:+.2f}%)"
                    )

    # ─────────────────────────────────────────────────
    # [조건 3] 30분봉에서 실시간 3일선이 5일선 당일 돌파 검사 (3일선 우상향 필수)
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

            # 3일선이 5일선 위에 위치(정배열)하고, 반드시 3일선이 직전 대비 '우상향(상향 방향)' 중이어야 함
            is_s3_above_s5 = (curr_sma3 > curr_sma5)
            is_s3_slope_up = (curr_sma3 >= prev_sma3)  # 3일선 상향 방향 확인 (데드크로스/하향 절대 금지)

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
                    diff_pct = ((curr_sma3 - curr_sma5) / curr_sma5) * 100
                    slope_pct = ((curr_sma3 - prev_sma3) / prev_sma3) * 100 if prev_sma3 > 0 else 0.0
                    day_sma_reason = (
                        f"⚡ [조건3: 30분봉 당일 3일-5일선 골든크로스 & 3일선 우상향 돌파!] "
                        f"3일선({curr_sma3:,.0f}원, 기울기:{slope_pct:+.2f}%) > 5일선({curr_sma5:,.0f}원) "
                        f"(이격도: {diff_pct:+.2f}%, 현재가: {current_price:,.0f}원)"
                    )

    # ─────────────────────────────────────────────────
    # [최종 대전제 검증] 3일선-5일선 정배열(3일선>5일선) 및 3일선 우상향 필수
    # ─────────────────────────────────────────────────
    # ⚠️ 조건 1, 2, 3 중 무엇을 만족하든 간에, 단기 3일선이 5일선 아래에 있거나(데드크로스/역배열)
    # 3일선이 아래로 꺾여 하향 중인 종목은 절대로 매수하지 않습니다 (로보티즈 등 손실 유발 차단).
    if curr_sma3 > 0 and curr_sma5 > 0:
        is_strictly_bullish = (curr_sma3 > curr_sma5) and (curr_sma3 >= prev_sma3)
        if not is_strictly_bullish:
            return result

    # ─────────────────────────────────────────────────
    # 매수 신호 판정: 조건 1 OR 조건 2 OR 조건 3
    # ─────────────────────────────────────────────────
    if cond1_30m_sma260 or cond2_daily_sma20 or cond3_day_sma_cross:
        result['buy'] = True
        
        # 사유 조합 및 우선순위 점수 산정
        reasons = []
        if cond1_30m_sma260:
            reasons.append(m30_reason)
            result['ll'] = m30_sma260_val
            base_score = 100.0 + min(w_info.get('rebound_pct', 0.0), 20.0) if is_w_rebound else 85.0
            result['priority_score'] = max(result['priority_score'], base_score)

        if cond3_day_sma_cross:
            reasons.append(day_sma_reason)
            result['ll'] = curr_sma5 if result['ll'] == 0 else result['ll']
            result['priority_score'] = max(result['priority_score'], 90.0)

        if cond2_daily_sma20:
            reasons.append(daily_reason)
            result['ll'] = d_sma20_val if result['ll'] == 0 else result['ll']
            result['priority_score'] = max(result['priority_score'], 80.0)

        result['reason'] = " | ".join(reasons)

    return result
