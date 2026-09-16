"""
strategy_sell.py - 15분봉 WMA 3-5 데드크로스 전용 매도 전략
===========================================================================

[통합 매도 로직]
1. [15분봉 WMA 3-5 데드크로스 매도 (단일 원칙)]:
   - 15분봉의 3 가중이동평균(WMA 3)이 5 가중이동평균(WMA 5)을 하향 돌파(WMA 3 < WMA 5)할 때 즉시 전량 매도.
   - WMA 3 >= WMA 5 유지 시 지속 홀딩하여 상승 탄력 구간 수익을 극대화.
   - 가중이동평균(WMA)을 적용하여 장초반 피크 꺾임을 신속하게 포착하고 휩소를 최소화.

사용 데이터: 15분봉
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# WMA (가중이동평균) 계산 헬퍼
# ═══════════════════════════════════════════════════════════════
def calc_wma(series: pd.Series, period: int) -> pd.Series:
    """
    가중이동평균(Weighted Moving Average)을 계산합니다.
    WMA = Σ(가중치 × 가격) / Σ(가중치)
    """
    if series is None or len(series) < period:
        return pd.Series([np.nan] * (len(series) if series is not None else 0))
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=period, min_periods=period).apply(
        lambda prices: np.dot(prices, weights) / weight_sum,
        raw=True
    )


# ═══════════════════════════════════════════════════════════════
# 15분봉 3-5 WMA 데드크로스 매도 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_sell_signals(
    df_15m: pd.DataFrame,
    daily_df: Optional[pd.DataFrame] = None,
    buy_price: float = 0.0,
    current_price: Optional[float] = None,
    touch_high: float = 0.0
) -> Dict[str, Any]:
    """
    15분봉 DataFrame의 WMA 3과 WMA 5를 계산하여 데드크로스(WMA 3 < WMA 5) 시에만 매도 신호를 판정합니다.

    Returns
    -------
    dict:
        sell           : bool   - 매도 신호 여부
        close          : float  - 현재 종가 / 실시간가
        buy_price      : float  - 매입단가
        profit_pct     : float  - 현재 수익률(%)
        m_resistance   : float  - M선 저항 가격 (참고용)
        wma3           : float  - 15분봉 WMA3 값
        wma5           : float  - 15분봉 WMA5 값
        sma5           : float  - 하위 호환용 (WMA3 값)
        sma20          : float  - 하위 호환용 (WMA5 값)
        sma40          : float  - 0.0
        reason         : str    - 매도 사유 메시지
        exit_type      : str    - 'DEAD_CROSS_3_5_WMA'
    """
    default_res = {
        "sell": False,
        "close": 0.0,
        "buy_price": buy_price,
        "profit_pct": 0.0,
        "m_resistance": 0.0,
        "wma3": 0.0,
        "wma5": 0.0,
        "sma5": 0.0,
        "sma20": 0.0,
        "sma40": 0.0,
        "reason": "",
        "exit_type": ""
    }

    if df_15m is None or df_15m.empty:
        return default_res

    df = df_15m.copy()
    col_map = {col: str(col).lower() for col in df.columns if str(col).lower() in ('open', 'high', 'low', 'close', 'volume')}
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns or len(df) < 5:
        return default_res

    close_p = float(df.iloc[-1]['close'])
    curr_p = float(current_price) if current_price and current_price > 0 else close_p
    profit_pct = ((curr_p - buy_price) / buy_price * 100.0) if buy_price > 0 else 0.0

    # 15분봉 WMA3 및 WMA5 계산
    df['wma3'] = calc_wma(df['close'], 3)
    df['wma5'] = calc_wma(df['close'], 5)

    latest = df.iloc[-1]
    wma3_now = float(latest['wma3']) if pd.notna(latest['wma3']) else 0.0
    wma5_now = float(latest['wma5']) if pd.notna(latest['wma5']) else 0.0

    if wma3_now > 0 and wma5_now > 0:
        # ─────────────────────────────────────────────────────────────
        # [단일 매도 원칙] 15분봉 WMA 3-5 데드크로스 발생 시 전량 매도
        # ─────────────────────────────────────────────────────────────
        if wma3_now < wma5_now:
            diff_pct = ((wma3_now - wma5_now) / wma5_now) * 100.0
            return {
                "sell": True,
                "close": curr_p,
                "buy_price": buy_price,
                "profit_pct": profit_pct,
                "m_resistance": 0.0,
                "wma3": wma3_now,
                "wma5": wma5_now,
                "sma5": wma3_now,
                "sma20": wma5_now,
                "sma40": 0.0,
                "reason": (
                    f"📉 [15분봉 3-5 WMA 데드크로스 매도] 15분봉 WMA3({wma3_now:,.0f}원) < "
                    f"WMA5({wma5_now:,.0f}원) 하향 이탈 (이격도: {diff_pct:+.2f}%, 현재가: {curr_p:,.0f}원, 손익률: {profit_pct:+.2f}%)"
                ),
                "exit_type": "DEAD_CROSS_3_5_WMA"
            }

    return {
        "sell": False,
        "close": curr_p,
        "buy_price": buy_price,
        "profit_pct": profit_pct,
        "m_resistance": 0.0,
        "wma3": wma3_now,
        "wma5": wma5_now,
        "sma5": wma3_now,
        "sma20": wma5_now,
        "sma40": 0.0,
        "reason": f"15분봉 WMA3({wma3_now:,.0f}원) >= WMA5({wma5_now:,.0f}원) 정배열/상승 탄력 유지 중 (홀딩)",
        "exit_type": ""
    }

