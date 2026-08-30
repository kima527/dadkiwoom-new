"""
strategy_sell.py - 15분봉 SMA5/SMA40 데드크로스 매도 전략
===========================================================================

매도 로직:
  1. SMA5 = SMA(종가, 5) / SMA40 = SMA(종가, 40) 계산
  2. 매도 신호: CrossDown(SMA5, SMA40) → SMA5가 SMA40을 하향 돌파(데드크로스)

사용 데이터: 15분봉
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 15분봉 매도 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_sell_signals(df_15m: pd.DataFrame) -> dict:
    """
    15분봉 DataFrame을 받아 SMA5/SMA40 데드크로스 매도 신호를 생성합니다.

    Returns
    -------
    dict:
        sell      : bool   - 매도 신호 (SMA5가 SMA40을 하향 돌파)
        close     : float  - 현재 종가
        sma5      : float  - 현재 SMA5 값
        sma40     : float  - 현재 SMA40 값
        reason    : str    - 매도 사유 메시지
    """
    if df_15m is None or df_15m.empty or len(df_15m) < 45:
        return {"sell": False, "close": 0.0, "sma5": 0.0, "sma40": 0.0, "reason": ""}

    df = df_15m.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns:
        return {"sell": False, "close": 0.0, "sma5": 0.0, "sma40": 0.0, "reason": ""}

    # ── SMA 계산 (min_periods를 기간과 동일하게 설정하여 초반 가짜 신호 방지) ──
    df['sma5'] = df['close'].rolling(window=5, min_periods=5).mean()
    df['sma40'] = df['close'].rolling(window=40, min_periods=40).mean()

    # ── 데드크로스 감지: CrossDown(SMA5, SMA40) ──
    # 이전 봉: SMA5 >= SMA40, 현재 봉: SMA5 < SMA40
    df['dead_cross'] = (
        (df['sma5'] < df['sma40']) &
        (df['sma5'].shift(1) >= df['sma40'].shift(1))
    )

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    close_price = float(latest['close'])
    sma5_now = float(latest['sma5']) if pd.notna(latest['sma5']) else 0.0
    sma40_now = float(latest['sma40']) if pd.notna(latest['sma40']) else 0.0

    result = {
        "sell": False,
        "close": close_price,
        "sma5": sma5_now,
        "sma40": sma40_now,
        "reason": ""
    }

    # ── 매도 신호: 현재 봉 또는 직전 완성봉에서 SMA5가 SMA40을 데드크로스 ──
    is_dead_cross = bool(latest['dead_cross']) or bool(prev['dead_cross'])
    if is_dead_cross:
        result["sell"] = True
        result["reason"] = (
            f"15분봉 SMA5({sma5_now:,.0f})<SMA40({sma40_now:,.0f}) 데드크로스 발생, "
            f"종가: {close_price:,.0f}"
        )

    return result
