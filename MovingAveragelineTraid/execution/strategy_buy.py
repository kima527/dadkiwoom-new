"""
strategy_buy.py - 30분봉 및 일봉 가중고가선 돌파 매수 전략
===========================================================================

매수 로직 (둘 중 하나라도 먼저 충족 시 매수):
1. 일봉 차트:
   - 당일 단순 20이동평균선(SMA 20) 상향 돌파 (CrossUp)
   - 종가 > 가중 5-20 고가선 (가중 5-20 고가선: WMA5가 WMA20을 CrossUp할 때의 고가(HH))
2. 30분봉 차트:
   - 당일 단순 260이동평균선(SMA 260) 상향 돌파 (CrossUp)
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

def analyze_buy_signals(df_30m: pd.DataFrame, df_120t: pd.DataFrame, daily_df: pd.DataFrame = None) -> dict:
    """
    일봉 및 30분봉 조건을 모두 검사하여 둘 중 하나라도 먼저 만족하면 매수 신호 반환
    - 조건 1 (일봉): 당일 단순 20이평선(SMA20) 상향 돌파 + 현재가 > 가중 5-20 고가선(HH)
    - 조건 2 (30분봉): 당일 단순 260이평선(SMA260) 상향 돌파 + 현재가 > 가중 5-20 고가선(HH)
    """
    result = {
        "buy": False,
        "ll": 0.0,
        "close": 0.0,
        "reason": "",
        "remove_watchlist": False
    }

    if df_30m is None or df_30m.empty or len(df_30m) < 20:
        return result

    df30 = df_30m.copy()
    df30.rename(columns={col: col.lower() for col in df30.columns}, inplace=True)
    if 'close' not in df30.columns:
        return result
        
    current_price = float(df30.iloc[-1]['close'])
    result['close'] = current_price

    is_daily_condition_met = False
    daily_reason = ""
    daily_hh_val = 0.0

    # ─────────────────────────────────────────────────
    # 1. 일봉 차트 검사
    #    (전일 종가는 SMA20 이하이고, 당일 현재가가 SMA20 위로 올라타며,
    #     동시에 가중 5-20 고가선 위에 위치할 때)
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

            # 당일 신규 골든크로스로 인해 당일 고가가 새로 HH로 잡히더라도,
            # '이전부터 형성되어 있던 고가선 저항'을 돌파했는지 판별하기 위해 직전 확정 HH(d_prev['hh'])를 우선 비교
            prev_hh_val = float(d_prev['hh']) if (pd.notna(d_prev['hh']) and float(d_prev['hh']) > 0) else 0.0
            latest_hh_val = float(d_latest['hh']) if pd.notna(d_latest['hh']) else 0.0
            d_hh = prev_hh_val if prev_hh_val > 0 else latest_hh_val
            
            if d_sma20 > 0 and d_prev_sma20 > 0 and d_hh > 0:
                # 전일 종가는 SMA20 이하, 현재가는 SMA20 초과 (당일 상향 돌파)
                daily_sma20_crossup = (float(d_prev['close']) <= d_prev_sma20) and (current_price > d_sma20)
                
                # 종가(현재가)가 가중 5-20 고가선(HH) 위에 위치 (또는 돌파)
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
    #    (당일 30분봉에서 단순 260이평선을 상향 돌파하고,
    #     가중 5-20 고가선(HH)을 돌파 / 위에 위치할 때)
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
            # 당일 캔들 분리 (타임스탬프 기준)
            if isinstance(df30.index, pd.DatetimeIndex):
                today_date = df30.index[-1].date()
                today_mask = df30.index.date == today_date
                df30_today = df30[today_mask]
                df30_prev_days = df30[~today_mask]
            else:
                # 인덱스가 DatetimeIndex가 아닐 경우 최근 13개(1일치 분량)로 추정
                df30_today = df30.iloc[-13:]
                df30_prev_days = df30.iloc[:-13]

            # 1) 당일 단순 260이평선 위로 올라탔는지 확인:
            prev_day_last_close = float(df30_prev_days.iloc[-1]['close']) if not df30_prev_days.empty else 0.0
            prev_day_last_sma260 = float(df30_prev_days.iloc[-1]['sma260']) if (not df30_prev_days.empty and pd.notna(df30_prev_days.iloc[-1]['sma260'])) else 0.0
            
            climbed_from_prev_day = (prev_day_last_close <= prev_day_last_sma260) and (current_price > m30_sma260)
            
            # 당일 봉 내에서 260이평 상향 돌파가 발생했는지 체크
            today_crossup_sma260 = False
            if len(df30_today) >= 2:
                crosses = (df30_today['close'] > df30_today['sma260']) & (df30_today['close'].shift(1) <= df30_today['sma260'].shift(1))
                today_crossup_sma260 = bool(crosses.any())

            m30_sma260_climbed = (current_price > m30_sma260) and (climbed_from_prev_day or today_crossup_sma260)

            # 전일까지 형성되어 있던 기준 가중5-20고가선 (prior_hh)
            prior_m30_hh = float(df30_prev_days['hh'].dropna().iloc[-1]) if (not df30_prev_days.empty and df30_prev_days['hh'].notna().any()) else latest_m30_hh
            m30_hh_val = prior_m30_hh if prior_m30_hh > 0 else latest_m30_hh

            # 2) 가중 5-20 고가선(HH) 돌파 확인:
            #    전일 기준 고가선(prior_m30_hh)을 넘어섰거나 현재 고가선 이상으로 상승했을 때
            m30_above_hh = (current_price > prior_m30_hh) or (current_price >= latest_m30_hh)

            if m30_sma260_climbed and m30_above_hh and m30_hh_val > 0:
                is_30m_condition_met = True
                m30_reason = (
                    f"30분봉 조건 충족: 당일 SMA260({m30_sma260:,.0f}) 돌파 & "
                    f"가중5-20고가선({m30_hh_val:,.0f}) 돌파 (현재가: {current_price:,.0f})"
                )

    # ─────────────────────────────────────────────────
    # 3. 매수 신호 종합 (먼저 충족된 조건으로 즉시 매수)
    # ─────────────────────────────────────────────────
    if is_daily_condition_met:
        result['buy'] = True
        result['reason'] = daily_reason
        result['ll'] = daily_hh_val
        
    elif is_30m_condition_met:
        result['buy'] = True
        result['reason'] = m30_reason
        result['ll'] = m30_hh_val

    return result
