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


# ═══════════════════════════════════════════════════════════════
# 30분봉 매수 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_buy_signals(df: pd.DataFrame) -> dict:
    """
    30분봉 DataFrame을 받아 WMA 골든크로스 고가(HH) 돌파 매수 신호를 생성합니다.

    Returns
    -------
    dict:
        hh        : float  - 골든크로스 시점의 고가 (매수 돌파 기준선)
        buy       : bool   - 매수 신호 (종가가 HH를 상향 돌파)
        close     : float  - 현재 종가
        reason    : str    - 매수 사유 메시지
    """
    if df is None or df.empty or len(df) < 25:
        return {"buy": False, "hh": 0.0, "close": 0.0, "reason": ""}

    df = df.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns or 'high' not in df.columns:
        return {"buy": False, "hh": 0.0, "close": 0.0, "reason": ""}

    # ── WMA 계산 ──
    df['wma5'] = wma(df['close'], 5)
    df['wma20'] = wma(df['close'], 20)

    # ── 골든크로스 감지: CrossUp(WMA5, WMA20) ──
    df['golden_cross'] = (
        (df['wma5'] > df['wma20']) &
        (df['wma5'].shift(1) <= df['wma20'].shift(1))
    )

    # ── HH = ValueWhen(1, 골든크로스, High) → 가장 최근 골든크로스 시점의 고가 ──
    df['_raw_hh'] = np.where(df['golden_cross'], df['high'], np.nan)
    df['hh'] = df['_raw_hh'].ffill()

    # ── 최근 골든크로스 여부 확인 (너무 오래된 신호 제외) ──
    # 30분봉 기준 하루 약 13봉. 최근 15봉(약 1일 남짓) 이내에 골든크로스가 있었는지 확인
    recent_gc = df['golden_cross'].tail(15).any()

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    close_price = float(latest['close'])
    hh = float(latest['hh']) if pd.notna(latest['hh']) else 0.0

    result = {
        "buy": False,
        "hh": hh,
        "close": close_price,
        "reason": ""
    }

    # ── 매수 신호: 종가가 HH를 상향 돌파 ──
    if hh > 0:
        prev_close = float(prev['close']) if pd.notna(prev['close']) else 0.0
        wma5_now = float(latest['wma5']) if pd.notna(latest['wma5']) else 0.0
        wma20_now = float(latest['wma20']) if pd.notna(latest['wma20']) else 0.0

        # 조건: 
        # 1. 이전봉 종가 <= HH, 현재봉 종가 > HH (정확히 돌파하는 시점)
        # 2. 너무 갭이 떠서 시점이 지나버린 것 방지 (돌파가 기준 +3% 이하)
        # 3. 골든크로스가 최근 15봉 이내에 발생했어야 함
        # 4. WMA5 > WMA20 (정배열 유지)
        if prev_close <= hh and close_price > hh and close_price <= hh * 1.03 and recent_gc and wma5_now > wma20_now:
            result["buy"] = True
            result["reason"] = (
                f"WMA5>WMA20 정배열(최근 GC), "
                f"종가({close_price:,.0f})가 HH({hh:,.0f}) 돌파 "
                f"(+{((close_price / hh) - 1) * 100:.1f}%)"
            )

    return result
