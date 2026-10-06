"""
strategy_15m_m_wma_squeeze.py - 15분봉 수식1(황룡선) & 수식2(WMA 골든선) 1% 이내 초수렴 + 1번식 변곡 돌파 전략
=========================================================================================================

[전략 개요]
1. 수식 1 (M선 돌파 황룡선):
   a=avg(c,5); b=avg(c,20); d=avg(c,60);
   K=valuewhen(1, a>b && b>d && a>d, C);
   M=valuewhen(1, K(2)<K(1) && K(1)>K, K(1));
   Formula1 = valuewhen(1, crossup(a, M), a);

2. 수식 2 (WMA 5-20 골든크로스선):
   M5=MA(C,5,가중); M20=MA(C,20,가중);
   조건=CrossUp(M5, M20);
   Formula2 = ValueWhen(1, 조건, M5);

3. 매수 타점 (Buy Signal):
   - 15분봉에서 Formula1과 Formula2의 가격 차이가 1.0% 이내로 초밀착(응축 / Squeeze)된 상태
   - 1번 식이 상향 변곡(5이평이 M선을 돌파하는 CrossUp 또는 황룡선 상향 돌파)이 일어날 때의 가격에 매수!

4. 매도 타점 (Sell Exit):
   - M = 종가 + nPreDayClose(1) + nPreDayClose(2);
   - 15분봉의 저가(Low)가 M/3(실시간 3일 이동평균선) 아래로 떨어질 때 전량 매도!
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def calc_wma(series: pd.Series, period: int) -> pd.Series:
    """가중이동평균(Weighted Moving Average) 계산"""
    if series is None or len(series) < period:
        return pd.Series([np.nan] * (len(series) if series is not None else 0), index=series.index if series is not None else None)
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=period, min_periods=period).apply(
        lambda p: np.dot(p, weights) / weight_sum, raw=True
    )


def calculate_day3_m_line(daily_df: Optional[pd.DataFrame], current_price: float) -> float:
    """
    실시간 3일선 M/3 계산:
    M = 종가 + nPreDayClose(1) + nPreDayClose(2)
    기준선 = M / 3.0
    """
    if daily_df is None or len(daily_df) < 2 or current_price <= 0:
        return 0.0

    df_d = daily_df.copy()
    today_str = datetime.now().strftime('%Y%m%d')

    if 'date' in df_d.columns:
        last_date = str(df_d['date'].iloc[-1]).replace('-', '').strip()
        if last_date == today_str and len(df_d) >= 3:
            pred1 = float(df_d['close'].iloc[-2])
            pred2 = float(df_d['close'].iloc[-3])
        else:
            pred1 = float(df_d['close'].iloc[-1])
            pred2 = float(df_d['close'].iloc[-2]) if len(df_d) >= 2 else pred1
    else:
        pred1 = float(df_d['close'].iloc[-1])
        pred2 = float(df_d['close'].iloc[-2]) if len(df_d) >= 2 else pred1

    m = float(current_price) + pred1 + pred2
    return m / 3.0


def evaluate_15m_m_wma_squeeze(
    code: str,
    name: str,
    df_15m: pd.DataFrame,
    daily_df: Optional[pd.DataFrame] = None,
    current_price: Optional[float] = None
) -> Dict[str, Any]:
    """
    15분봉 수식1(황룡선)과 수식2(WMA 골든선) 1% 이내 초응축 + 1번식 변곡 매수 분석
    """
    default_res = {
        'code': code,
        'name': name,
        'should_buy': False,
        'price': 0.0,
        'target_price': 0.0,
        'formula1': 0.0,
        'formula2': 0.0,
        'diff_pct': 999.0,
        'day3_line': 0.0,
        'reason': '',
        'priority_score': 0.0
    }

    if df_15m is None or df_15m.empty or len(df_15m) < 30:
        return default_res

    df = df_15m.copy()
    col_map = {c: str(c).lower() for c in df.columns if str(c).lower() in ('open', 'high', 'low', 'close', 'volume')}
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns or len(df) < 20:
        return default_res

    close = df['close']
    latest_bar = df.iloc[-1]
    curr_c = float(current_price) if current_price and current_price > 0 else float(latest_bar['close'])
    curr_o = float(latest_bar['open'])

    # ─────────────────────────────────────────────────────────────
    # [수식 1] M선(정배열 직전 피크 저항선) 및 황룡선 계산
    # a=avg(c,5); b=avg(c,20); d=avg(c,60);
    # K=valuewhen(1, a>b && b>d && a>d, C);
    # M=valuewhen(1, K(2)<K(1) && K(1)>K, K(1));
    # Formula1 = valuewhen(1, crossup(a, M), a);
    # ─────────────────────────────────────────────────────────────
    a = close.rolling(5, min_periods=5).mean()
    b = close.rolling(20, min_periods=20).mean()
    d = close.rolling(60, min_periods=min(len(close), 60)).mean()

    # SMA 5 > 20 > 60 정배열
    cond_align = (a > b) & (b > d) & (a > d)
    k = close.where(cond_align).ffill()

    # K 피크 변곡
    k1 = k.shift(1)
    k2 = k.shift(2)
    cond_peak = (k2 < k1) & (k1 > k)
    m_line = k1.where(cond_peak).ffill()

    # 황룡선 (5이평의 M선 상향 돌파 시점 5이평값)
    crossup_a_m = (a.shift(1) <= m_line.shift(1)) & (a > m_line)
    formula1_series = a.where(crossup_a_m).ffill()

    # ─────────────────────────────────────────────────────────────
    # [수식 2] WMA 5-20 골든크로스 지지선 계산
    # M5=MA(C,5,가중); M20=MA(C,20,가중);
    # 조건=CrossUp(M5, M20);
    # Formula2 = ValueWhen(1, 조건, M5);
    # ─────────────────────────────────────────────────────────────
    wma5 = calc_wma(close, 5)
    wma20 = calc_wma(close, 20)
    crossup_wma = (wma5.shift(1) <= wma20.shift(1)) & (wma5 > wma20)
    formula2_series = wma5.where(crossup_wma).ffill()

    valid_f1 = formula1_series.dropna()
    valid_f2 = formula2_series.dropna()
    if valid_f1.empty or valid_f2.empty:
        return default_res

    f1_val = float(valid_f1.iloc[-1])
    f2_val = float(valid_f2.iloc[-1])
    if f1_val <= 0 or f2_val <= 0:
        return default_res

    # ─────────────────────────────────────────────────────────────
    # [조건 1] 두 수식선 가격이 1.0% 이내로 좁혀진 상태 (응축 Squeeze)
    # ─────────────────────────────────────────────────────────────
    diff_pct = (abs(f1_val - f2_val) / min(f1_val, f2_val)) * 100.0
    is_squeeze_1pct = diff_pct <= 1.0

    # ─────────────────────────────────────────────────────────────
    # [조건 2] 1번 식이 변곡이 일어날 때 (Turnaround / Breakout)
    # 1) 현재 15분봉에서 5이평이 M선을 CrossUp하여 새로운 수식1선이 생성되는 순간!
    # 2) 또는 수렴 상태에서 현재 종가가 수식1선(황룡선)을 상향 돌파하는 순간!
    # ─────────────────────────────────────────────────────────────
    is_crossup_m = bool(crossup_a_m.iloc[-1]) if len(crossup_a_m) > 0 else False
    is_crossup_prev = bool(crossup_a_m.iloc[-2]) if len(crossup_a_m) > 1 else False
    is_breakout_f1 = (curr_c >= f1_val) and (float(df['close'].iloc[-2]) <= f1_val * 1.002)

    is_turnaround = is_crossup_m or (is_crossup_prev and curr_c >= f1_val) or is_breakout_f1

    # 양봉 확인 필터 (당일 15분봉 캔들이 양봉 또는 도지여야 안전)
    is_bull = curr_c >= curr_o

    # 실시간 3일선 M/3 계산 (매수 시 목표/손절 기준선 파악용)
    day3_line = calculate_day3_m_line(daily_df, curr_c)

    if is_squeeze_1pct and is_turnaround and is_bull:
        target_p = f1_val
        default_res.update({
            'should_buy': True,
            'price': curr_c,
            'target_price': target_p,
            'formula1': f1_val,
            'formula2': f2_val,
            'diff_pct': diff_pct,
            'day3_line': day3_line,
            'priority_score': 365.0,  # 강력한 우선순위 서브 전략 (365점)
            'reason': (
                f"💎 [수식1-2 1% 초응축 변곡 돌파] "
                f"황룡선({f1_val:,.0f}원)과 WMA골든선({f2_val:,.0f}원) 초수렴({diff_pct:.2f}% <= 1.0%) "
                f"+ 1번식 변곡 포착 (실시간 3일선 M/3: {day3_line:,.0f}원)"
            )
        })

    return default_res
