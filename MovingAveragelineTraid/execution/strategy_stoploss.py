"""
strategy_stoploss.py - 5분봉 TEMA 기반 손절 전략
===========================================================================

손절 로직:
  TEMA(Triple Exponential Moving Average) 계산:
    TEMA = 3*EMA(C,기간) - 3*EMA(EMA(C,기간),기간) + EMA(EMA(EMA(C,기간),기간),기간)

  TEMA1 (기간=5), TEMA2 (기간=20)

  손절라인:
    조건 = CrossUp(TEMA1, TEMA2)
    손절가 = ValueWhen(1, 조건, TEMA1) * 0.95

  → 현재가가 이 손절가를 하향 돌파하면 무조건 전량 매도

사용 데이터: 5분봉 (tic_scope="5")
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TEMA (Triple Exponential Moving Average) 계산
# ═══════════════════════════════════════════════════════════════
def tema(series: pd.Series, period: int) -> pd.Series:
    """
    TEMA = 3*EMA(C,기간) - 3*EMA(EMA(C,기간),기간) + EMA(EMA(EMA(C,기간),기간),기간)

    키움증권 수식과 동일:
      TEMA1 = 3*eavg(c,기간1) - 3*eavg(eavg(c,기간1),기간1) + eavg(eavg(eavg(c,기간1),기간1),기간1)
    """
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return 3 * ema1 - 3 * ema2 + ema3


# ═══════════════════════════════════════════════════════════════
# 5분봉 TEMA 기반 손절 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_stoploss_signals(df: pd.DataFrame) -> dict:
    """
    5분봉 DataFrame을 받아 TEMA 기반 손절 신호를 생성합니다.

    Returns
    -------
    dict:
        tema_sl_price : float  - TEMA 기반 손절가 (ValueWhen * 0.95)
        sell           : bool   - 매도 신호 (손절가 하향 이탈)
        reason         : str    - 매도 사유 메시지
        tema1          : float  - 현재 TEMA1(5) 값
        tema2          : float  - 현재 TEMA2(20) 값
    """
    period1 = 5   # 단기 TEMA
    period2 = 20  # 장기 TEMA

    if df is None or df.empty or len(df) < 25:
        return {"sell": False, "tema_sl_price": 0.0, "reason": ""}

    df = df.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns:
        return {"sell": False, "tema_sl_price": 0.0, "reason": ""}

    # ── TEMA 계산 ──
    df['tema1'] = tema(df['close'], period1)
    df['tema2'] = tema(df['close'], period2)

    # ── CrossUp(TEMA1, TEMA2) 감지 ──
    df['tema_cross'] = (
        (df['tema1'] > df['tema2']) &
        (df['tema1'].shift(1) <= df['tema2'].shift(1))
    )

    # ── ValueWhen(1, 조건, TEMA1) → 가장 최근 TEMA 골든크로스 시점의 TEMA1 값 ──
    df['_raw_tema_val'] = np.where(df['tema_cross'], df['tema1'], np.nan)
    df['tema_cross_val'] = df['_raw_tema_val'].ffill()

    # ── 손절가 = ValueWhen * 0.95 ──
    df['tema_sl_price'] = df['tema_cross_val'] * 0.95

    latest = df.iloc[-1]
    close_price = float(latest['close'])
    sl_price = float(latest['tema_sl_price']) if pd.notna(latest['tema_sl_price']) else 0.0
    tema1_now = float(latest['tema1']) if pd.notna(latest['tema1']) else 0.0
    tema2_now = float(latest['tema2']) if pd.notna(latest['tema2']) else 0.0

    result = {
        "sell": False,
        "tema_sl_price": sl_price,
        "tema1": tema1_now,
        "tema2": tema2_now,
        "reason": ""
    }

    # ── 손절 판단: 현재가가 손절라인 하향 돌파 ──
    if sl_price > 0 and close_price < sl_price:
        result["sell"] = True
        result["reason"] = (
            f"TEMA 손절선({sl_price:,.0f}) 하향 이탈! "
            f"종가({close_price:,.0f}), TEMA1({tema1_now:,.0f}), TEMA2({tema2_now:,.0f})"
        )

    return result


# ═══════════════════════════════════════════════════════════════
# 매수 진입 시점에 TEMA 손절가만 계산하는 헬퍼
# ═══════════════════════════════════════════════════════════════
def get_tema_stoploss_price(df: pd.DataFrame) -> float:
    """
    5분봉 DataFrame을 받아 TEMA 기반 손절가만 계산하여 반환합니다.
    BuyManager가 매수 진입 시점에 한 번 호출하여 TradeState에 고정합니다.

    Returns
    -------
    float
        TEMA 손절가 (ValueWhen(1, CrossUp(TEMA1,TEMA2), TEMA1) * 0.95)
        계산 불가 시 0.0 반환
    """
    period1 = 5
    period2 = 20

    if df is None or df.empty or len(df) < 25:
        return 0.0

    df = df.copy()
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns:
        return 0.0

    df['tema1'] = tema(df['close'], period1)
    df['tema2'] = tema(df['close'], period2)

    df['tema_cross'] = (
        (df['tema1'] > df['tema2']) &
        (df['tema1'].shift(1) <= df['tema2'].shift(1))
    )

    df['_raw_tema_val'] = np.where(df['tema_cross'], df['tema1'], np.nan)
    df['tema_cross_val'] = df['_raw_tema_val'].ffill()

    latest = df.iloc[-1]
    cross_val = float(latest['tema_cross_val']) if pd.notna(latest['tema_cross_val']) else 0.0

    return cross_val * 0.95 if cross_val > 0 else 0.0

