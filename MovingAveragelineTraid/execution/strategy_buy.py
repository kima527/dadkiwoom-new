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
# 30분봉 260이평선 W자 반등(이중바닥 재돌파) 검출
# ═══════════════════════════════════════════════════════════════
def detect_w_rebound_30m(df30: pd.DataFrame, lookback: int = 280) -> tuple[bool, dict]:
    """
    30분봉 차트에서 단순 260이평선 기준 W자 반등 패턴을 검출:
    (단기 3~5일 주기 및 20일 전 1차 돌파 후 재돌파하는 중기 20일 주기까지 모두 탐색)
    1) 1차 상승: 과거 260이평선 위로 상승했던 이력 (Peak 1, High > SMA260) - 최대 20~25영업일 전
    2) 하락/눌림: 1차 상승 이후 260이평선 아래 또는 부근으로 눌림목 형성 (Trough, Low <= SMA260)
    3) 2차 반등: 눌림 이후 다시 반등하여 260이평선을 재차 상향 돌파/안착 (Right arm Rebound)
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

    # sma260이 유효하게 계산된 구간에서 최근 lookback(최대 280봉, 약 20~22영업일) 추출
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

    # 현재가는 260이평선 위이거나 돌파 직후 안착 상태여야 함 (0.5% 오차 허용)
    if curr_c < curr_sma * 0.995:
        return empty_res

    # 1. 최근 1~6봉 내에 260이평선 재돌파(Rebound) 또는 지지 반등 확인
    recent_rebound_idx = None
    for i in range(n - 1, max(0, n - 7), -1):
        if closes[i] >= sma260s[i] * 0.998:
            recent_rebound_idx = i
            break

    if recent_rebound_idx is None:
        return empty_res

    # 2. recent_rebound_idx 이전에 260이평선 아래 또는 부근으로 하락했던 눌림목(Trough) 탐색 (최대 250봉 전까지 탐색)
    trough_idx = None
    trough_low = float('inf')
    for i in range(recent_rebound_idx - 1, max(0, recent_rebound_idx - 250), -1):
        # 260이평선 아래로 내려갔거나 260이평선에 밀착된 저점
        if closes[i] < sma260s[i] or lows[i] <= sma260s[i] * 1.002:
            if lows[i] < trough_low:
                trough_low = lows[i]
                trough_idx = i

    if trough_idx is None or (recent_rebound_idx - trough_idx < 1):
        return empty_res

    # 3. trough_idx 이전에 260이평선 위로 상승했던 1차 상승(Peak 1) 탐색 (눌림목 이전 전체 구간 탐색)
    peak1_idx = None
    peak1_high = float('-inf')
    for i in range(trough_idx - 1, -1, -1):
        if highs[i] > sma260s[i] * 1.002 or closes[i] > sma260s[i]:
            if highs[i] > peak1_high:
                peak1_high = highs[i]
                peak1_idx = i

    if peak1_idx is None or (trough_idx - peak1_idx < 1):
        return empty_res

    # 4. 형상 유효성 검증:
    # 1차 고점 > 눌림 저점
    if peak1_high <= trough_low:
        return empty_res

    # 반등 탄력도(%)
    rebound_pct = ((curr_c - trough_low) / trough_low) * 100 if trough_low > 0 else 0.0
    peak1_bars_ago = n - 1 - peak1_idx
    trough_bars_ago = n - 1 - trough_idx

    # 주기 유형 분류 (단기 W자 vs 20일 전 1차 돌파 중기 W자)
    days_ago = peak1_bars_ago / 13.0
    if peak1_bars_ago >= 130:
        cycle_name = f"중기 20일선 W자 재돌파 ({days_ago:.1f}일 전 1차돌파)"
    else:
        cycle_name = f"단기 W자 반등 ({max(1, int(days_ago + 0.5))}일 주기)"

    w_info = {
        "is_w_rebound": True,
        "cycle_name": cycle_name,
        "peak1_high": peak1_high,
        "peak1_bars_ago": peak1_bars_ago,
        "peak1_days_ago": round(days_ago, 1),
        "trough_low": trough_low,
        "trough_bars_ago": trough_bars_ago,
        "sma260": curr_sma,
        "current_price": curr_c,
        "rebound_pct": rebound_pct,
        "description": (
            f"[{cycle_name}] 완성 (1차고점:{peak1_high:,.0f}원[{peak1_bars_ago}봉전({days_ago:.1f}일전)] ➔ "
            f"눌림저점:{trough_low:,.0f}원[{trough_bars_ago}봉전] ➔ "
            f"260이평({curr_sma:,.0f}원) 재돌파 +{rebound_pct:.1f}%)"
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
    # 1. 일봉 차트 검사
    # ─────────────────────────────────────────────────
    if daily_df is not None and not daily_df.empty and len(daily_df) >= 20:
        df_d = daily_df.copy()
        df_d.rename(columns={col: col.lower() for col in df_d.columns}, inplace=True)
        
        # 일봉 SMA 20 (최소 20개 필요)
        df_d['sma20'] = df_d['close'].rolling(window=20, min_periods=20).mean()
        
        # 일봉 HH (가중 5-20 고가선)
        df_d['hh'] = calculate_hh(df_d)
        
        if len(df_d) >= 2:
            d_latest = df_d.iloc[-1]
            d_prev = df_d.iloc[-2]
            
            d_sma20 = float(d_latest['sma20']) if pd.notna(d_latest['sma20']) else 0.0
            d_prev_sma20 = float(d_prev['sma20']) if pd.notna(d_prev['sma20']) else 0.0

            prev_hh_val = float(d_prev['hh']) if (pd.notna(d_prev['hh']) and float(d_prev['hh']) > 0) else 0.0
            latest_hh_val = float(d_latest['hh']) if pd.notna(d_latest['hh']) else 0.0
            d_hh = prev_hh_val if prev_hh_val > 0 else latest_hh_val
            
            if d_sma20 > 0 and d_prev_sma20 > 0 and d_hh > 0:
                daily_sma20_crossup = (float(d_prev['close']) <= d_prev_sma20) and (current_price > d_sma20)
                daily_above_hh = (current_price > d_hh) or (current_price >= latest_hh_val)
                daily_hh_val = d_hh
                
                if daily_sma20_crossup and daily_above_hh:
                    is_daily_condition_met = True
                    daily_reason = (
                        f"일봉 조건 충족: 당일 SMA20({d_sma20:,.0f}) 돌파 & "
                        f"가중5-20고가선({d_hh:,.0f}) 위 위치 (현재가: {current_price:,.0f})"
                    )

    # ─────────────────────────────────────────────────
    # 2. 30분봉 차트 검사
    # ─────────────────────────────────────────────────
    is_30m_condition_met = False
    m30_reason = ""
    m30_hh_val = 0.0
    
    if len(df30) >= 260:
        # 30분봉 SMA 260
        df30['sma260'] = df30['close'].rolling(window=260, min_periods=260).mean()
        
        # 30분봉 HH (가중 5-20 고가선)
        df30['hh'] = calculate_hh(df30)
        
        m30_latest = df30.iloc[-1]
        m30_prev = df30.iloc[-2] if len(df30) >= 2 else m30_latest
        
        m30_sma260 = float(m30_latest['sma260']) if pd.notna(m30_latest['sma260']) else 0.0
        
        prev_m30_hh = float(m30_prev['hh']) if (pd.notna(m30_prev['hh']) and float(m30_prev['hh']) > 0) else 0.0
        latest_m30_hh = float(m30_latest['hh']) if pd.notna(m30_latest['hh']) else 0.0
        m30_hh = prev_m30_hh if prev_m30_hh > 0 else latest_m30_hh
        m30_hh_val = m30_hh

        if m30_sma260 > 0 and m30_hh > 0:
            if isinstance(df30.index, pd.DatetimeIndex):
                today_date = df30.index[-1].date()
                today_mask = df30.index.date == today_date
                df30_today = df30[today_mask]
                df30_prev_days = df30[~today_mask]
            else:
                df30_today = df30.iloc[-13:]
                df30_prev_days = df30.iloc[:-13]

            prev_day_last_close = float(df30_prev_days.iloc[-1]['close']) if not df30_prev_days.empty else 0.0
            prev_day_last_sma260 = float(df30_prev_days.iloc[-1]['sma260']) if (not df30_prev_days.empty and pd.notna(df30_prev_days.iloc[-1]['sma260'])) else 0.0
            
            climbed_from_prev_day = (prev_day_last_close <= prev_day_last_sma260) and (current_price > m30_sma260)
            
            today_crossup_sma260 = False
            if len(df30_today) >= 2:
                crosses = (df30_today['close'] > df30_today['sma260']) & (df30_today['close'].shift(1) <= df30_today['sma260'].shift(1))
                today_crossup_sma260 = bool(crosses.any())

            m30_sma260_climbed = (current_price > m30_sma260) and (climbed_from_prev_day or today_crossup_sma260 or is_w_rebound)

            prior_m30_hh = float(df30_prev_days['hh'].dropna().iloc[-1]) if (not df30_prev_days.empty and df30_prev_days['hh'].notna().any()) else latest_m30_hh
            m30_hh_val = prior_m30_hh if prior_m30_hh > 0 else latest_m30_hh

            m30_above_hh = (current_price > prior_m30_hh) or (current_price >= latest_m30_hh)

            if m30_sma260_climbed and m30_above_hh and m30_hh_val > 0:
                is_30m_condition_met = True
                if is_w_rebound:
                    m30_reason = (
                        f"🔥 [30분봉 260이평 W자 반등 최우선] {w_info['description']} & "
                        f"가중5-20고가선({m30_hh_val:,.0f}) 돌파 (현재가: {current_price:,.0f})"
                    )
                else:
                    m30_reason = (
                        f"30분봉 조건 충족: 당일 SMA260({m30_sma260:,.0f}) 돌파 & "
                        f"가중5-20고가선({m30_hh_val:,.0f}) 돌파 (현재가: {current_price:,.0f})"
                    )

    # ─────────────────────────────────────────────────
    # 3. 매수 신호 종합 (W자 반등 우선 적용)
    # ─────────────────────────────────────────────────
    if is_w_rebound and (is_30m_condition_met or is_daily_condition_met):
        result['buy'] = True
        result['reason'] = m30_reason if is_30m_condition_met else (f"🔥 [30분봉 W자 반등 최우선] {w_info['description']} & " + daily_reason)
        result['ll'] = m30_hh_val if is_30m_condition_met else daily_hh_val
        result['priority_score'] = 100.0 + min(w_info.get('rebound_pct', 0.0), 20.0)

    elif is_30m_condition_met:
        result['buy'] = True
        result['reason'] = m30_reason
        result['ll'] = m30_hh_val
        result['priority_score'] = 80.0

    elif is_daily_condition_met:
        result['buy'] = True
        result['reason'] = daily_reason
        result['ll'] = daily_hh_val
        result['priority_score'] = 75.0

    return result
