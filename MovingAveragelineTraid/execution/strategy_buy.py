"""
strategy_buy.py - 5분봉 WMA 골든크로스 분할매수 전략
===========================================================================

매수 로직:
  1차 매수 (50%): WMA5가 WMA20을 상향 돌파(골든크로스) 시점의 WMA5 값
     → Signal_1 = ValueWhen(1, CrossUp(WMA5, WMA20), WMA5)
     → 현재가가 Signal_1 이상이면 50% 매수

  2차 매수 (50%): 골든크로스 시점의 고가(H)를 강하게 돌파 시
     → Signal_2 = ValueWhen(1, CrossUp(WMA5, WMA20), H)
     → 현재 종가가 Signal_2를 강하게 상향돌파하면 나머지 50% 매수

사용 데이터: 5분봉 (tic_scope="5")
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional

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
# 5분봉 매수 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_buy_signals(df: pd.DataFrame) -> dict:
    """
    5분봉 DataFrame을 받아 WMA 골든크로스 기반 매수 신호를 생성합니다.

    Returns
    -------
    dict:
        signal_1  : float  - 1차 매수 기준가 (골든크로스 시점 WMA5)
        signal_2  : float  - 2차 매수 기준가 (골든크로스 시점 고가 HH)
        buy_1     : bool   - 1차 매수 신호 (골든크로스 발생 & 종가 >= Signal_1)
        buy_2     : bool   - 2차 매수 신호 (종가가 Signal_2를 강하게 돌파)
        close     : float  - 현재 종가
        reason    : str    - 매수 사유 메시지
    """
    if df is None or df.empty or len(df) < 25:
        return {"buy_1": False, "buy_2": False, "signal_1": 0.0, "signal_2": 0.0}

    df = df.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns or 'high' not in df.columns:
        return {"buy_1": False, "buy_2": False, "signal_1": 0.0, "signal_2": 0.0}

    # ── WMA 계산 ──
    df['wma5'] = wma(df['close'], 5)
    df['wma20'] = wma(df['close'], 20)

    # ── 골든크로스 감지: CrossUp(WMA5, WMA20) ──
    df['golden_cross'] = (
        (df['wma5'] > df['wma20']) &
        (df['wma5'].shift(1) <= df['wma20'].shift(1))
    )

    # ── ValueWhen(1, 조건, WMA5) → Signal_1 (지지선) ──
    df['_raw_sig1'] = np.where(df['golden_cross'], df['wma5'], np.nan)
    df['signal_1'] = df['_raw_sig1'].ffill()

    # ── ValueWhen(1, 조건, H) → Signal_2 (고가 돌파선) ──
    df['_raw_sig2'] = np.where(df['golden_cross'], df['high'], np.nan)
    df['signal_2'] = df['_raw_sig2'].ffill()

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    close_price = float(latest['close'])
    sig1 = float(latest['signal_1']) if pd.notna(latest['signal_1']) else 0.0
    sig2 = float(latest['signal_2']) if pd.notna(latest['signal_2']) else 0.0

    result = {
        "buy_1": False,
        "buy_2": False,
        "signal_1": sig1,
        "signal_2": sig2,
        "close": close_price,
        "reason": ""
    }

    # ── 1차 매수: 골든크로스 발생 직후 & 종가가 Signal_1 이상 ──
    if sig1 > 0:
        # 최근 3봉 이내에 골든크로스가 발생했는지 확인
        recent_gc = df['golden_cross'].tail(5).any()
        wma5_now = float(latest['wma5']) if pd.notna(latest['wma5']) else 0
        wma20_now = float(latest['wma20']) if pd.notna(latest['wma20']) else 0

        if recent_gc and wma5_now > wma20_now and close_price >= sig1:
            result["buy_1"] = True
            result["reason"] = (
                f"WMA5({wma5_now:,.0f})>WMA20({wma20_now:,.0f}) 골든크로스, "
                f"종가({close_price:,.0f})>=Signal_1({sig1:,.0f})"
            )

    # ── 2차 매수: 종가가 Signal_2를 '강하게' 돌파 (종가가 sig2 * 1.003 이상) ──
    if sig2 > 0 and close_price > sig2 * 1.003:
        prev_close = float(prev['close']) if pd.notna(prev['close']) else 0
        # 이전 봉에서는 Signal_2 이하였다가 현재 봉에서 돌파 (CrossUp 조건)
        if prev_close <= sig2:
            result["buy_2"] = True
            result["reason"] = (
                f"종가({close_price:,.0f})가 HH({sig2:,.0f})를 강하게 돌파 "
                f"(+{((close_price / sig2) - 1) * 100:.1f}%)"
            )

    return result
