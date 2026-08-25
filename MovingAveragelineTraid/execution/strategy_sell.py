"""
strategy_sell.py - 30분봉 WMA5/WMA40 데드크로스 매도 전략
===========================================================================

매도 로직:
  1. WMA5 = WMA(종가, 5) / WMA40 = WMA(종가, 40) 계산
  2. 매도 신호: CrossDown(WMA5, WMA40) → WMA5가 WMA40을 하향 돌파(데드크로스)

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


# ═══════════════════════════════════════════════════════════════
# 30분봉 매도 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_sell_signals(df: pd.DataFrame) -> dict:
    """
    30분봉 DataFrame을 받아 WMA5/WMA40 데드크로스 매도 신호를 생성합니다.

    Returns
    -------
    dict:
        sell      : bool   - 매도 신호 (WMA5가 WMA40을 하향 돌파)
        close     : float  - 현재 종가
        wma5      : float  - 현재 WMA5 값
        wma40     : float  - 현재 WMA40 값
        reason    : str    - 매도 사유 메시지
    """
    if df is None or df.empty or len(df) < 45:
        return {"sell": False, "close": 0.0, "wma5": 0.0, "wma40": 0.0, "reason": ""}

    df = df.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns:
        return {"sell": False, "close": 0.0, "wma5": 0.0, "wma40": 0.0, "reason": ""}

    # ── WMA 계산 ──
    df['wma5'] = wma(df['close'], 5)
    df['wma40'] = wma(df['close'], 40)

    # ── 데드크로스 감지: CrossDown(WMA5, WMA40) ──
    # 이전 봉: WMA5 >= WMA40, 현재 봉: WMA5 < WMA40
    df['dead_cross'] = (
        (df['wma5'] < df['wma40']) &
        (df['wma5'].shift(1) >= df['wma40'].shift(1))
    )

    latest = df.iloc[-1]

    close_price = float(latest['close'])
    wma5_now = float(latest['wma5']) if pd.notna(latest['wma5']) else 0.0
    wma40_now = float(latest['wma40']) if pd.notna(latest['wma40']) else 0.0

    result = {
        "sell": False,
        "close": close_price,
        "wma5": wma5_now,
        "wma40": wma40_now,
        "reason": ""
    }

    # ── 매도 신호: WMA5가 WMA40을 데드크로스 ──
    if bool(latest['dead_cross']):
        result["sell"] = True
        result["reason"] = (
            f"WMA5({wma5_now:,.0f})<WMA40({wma40_now:,.0f}) 데드크로스 발생, "
            f"종가: {close_price:,.0f}"
        )

    return result
