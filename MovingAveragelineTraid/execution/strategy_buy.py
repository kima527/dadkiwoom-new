"""
strategy_buy.py - 30분봉 WMA 골든크로스 고가(HH) 돌파 매수 전략
===========================================================================

매수 로직:
  1. WMA5 = WMA(종가, 5) / WMA20 = WMA(종가, 20) 계산
  2. 골든크로스 = CrossUp(WMA5, WMA20) 감지
  3. HH = ValueWhen(1, 골든크로스, 고가)  → 가장 최근 골든크로스 시점의 고가
  4. 매수 신호: 현재 종가가 HH를 상향 돌파 (이전봉 종가 <= HH, 현재봉 종가 > HH)

사용 데이터: 30분봉 (tic_scope="30")
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# WMA (가중이동평균) 계산
# ═══════════════════════════════════════════════════════════════
def wma(series: pd.Series, period: int) -> pd.Series:
    """
    가중이동평균(Weighted Moving Average)
    가중치: 1, 2, 3, ..., n  (최근 값에 큰 가중치)
    """
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=period, min_periods=period).apply(
        lambda prices: np.dot(prices, weights) / weight_sum,
        raw=True
    )


def analyze_buy_signals(df_30m: pd.DataFrame, df_120t: pd.DataFrame) -> dict:
    """
    30분봉과 120틱 하이브리드 로직:
    1. 30분봉에서 검정색 선(M) 지지 여부 확인 (a > M 또는 가격이 M 위에 위치)
    2. 120틱 차트에서 가격이 M 부근(+2% 이내)으로 눌렸는지 확인
    3. 120틱 차트에서 3일선이 5일선을 골든크로스 할 때 매수 (최저점 반등 확인)
    """
    result = {
        "buy": False,
        "ll": 0.0,
        "close": 0.0,
        "reason": ""
    }

    if df_30m is None or df_30m.empty or len(df_30m) < 60:
        return result
    if df_120t is None or df_120t.empty or len(df_120t) < 5:
        return result

    df30 = df_30m.copy()
    df120 = df_120t.copy()

    # 컬럼명 소문자 통일
    df30.rename(columns={col: col.lower() for col in df30.columns}, inplace=True)
    df120.rename(columns={col: col.lower() for col in df120.columns}, inplace=True)

    if 'close' not in df30.columns or 'close' not in df120.columns:
        return result

    # ─────────────────────────────────────────────────
    # 1. 30분봉 (거시 지지선 'M' 계산)
    # ─────────────────────────────────────────────────
    df30['a'] = df30['close'].rolling(window=5, min_periods=1).mean()
    df30['b'] = df30['close'].rolling(window=20, min_periods=1).mean()
    df30['d'] = df30['close'].rolling(window=60, min_periods=1).mean()

    cond_K = (df30['a'] > df30['b']) & (df30['b'] > df30['d'])
    df30['K'] = kiwoom_valuewhen(cond_K, df30['close'])

    cond_M = (df30['K'].shift(2) < df30['K'].shift(1)) & (df30['K'].shift(1) > df30['K'])
    df30['M'] = kiwoom_valuewhen(cond_M, df30['K'].shift(1))

    latest_30m = df30.iloc[-1]
    M_val = float(latest_30m['M']) if pd.notna(latest_30m['M']) else 0.0
    a_val = float(latest_30m['a']) if pd.notna(latest_30m['a']) else 0.0

    result['ll'] = M_val
    current_price = float(df120.iloc[-1]['close'])
    result['close'] = current_price

    # 아직 한 번도 M(저항/지지선)이 형성되지 않았다면 보류
    if M_val == 0.0:
        return result

    # 거시적 조건: 최소한 5일선이나 주가가 검정색 선 위에 있어야 '상승 중 눌림'으로 인정
    if a_val <= M_val and current_price <= M_val:
        return result  # 완전히 꺾인 하락세

    # ─────────────────────────────────────────────────
    # 2. 120틱 (미시 타점 계산: 근접도 & 골든크로스)
    # ─────────────────────────────────────────────────
    # M값 근접 확인: 120틱 차트의 최근 30개 틱 중 최저가가 M선의 +2% 이내로 들어온 적이 있는지 (눌림목 터치)
    recent_lows = df120['low'].tail(30)
    touched_support = any(recent_lows <= (M_val * 1.02))

    if not touched_support:
        return result  # 아직 지지선 부근까지 충분히 눌리지 않음 (허공에 떠 있음)

    # 120틱 이평선 계산 (3이평, 5이평)
    df120['sma3'] = df120['close'].rolling(window=3, min_periods=1).mean()
    df120['sma5'] = df120['close'].rolling(window=5, min_periods=1).mean()

    # 3이평이 5이평을 상향 돌파 (골든크로스)
    df120['gc'] = (df120['sma3'].shift(1) <= df120['sma5'].shift(1)) & (df120['sma3'] > df120['sma5'])
    
    latest_120t = df120.iloc[-1]
    
    if bool(latest_120t['gc']):
        result['buy'] = True
        result['reason'] = (
            f"30m 지지선(M: {M_val:,.0f}) 터치 후 "
            f"120t 골든크로스(SMA3>SMA5) 발생! (현재가: {current_price:,.0f})"
        )

    return result
