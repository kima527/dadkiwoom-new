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

    # ─────────────────────────────────────────────────────────────
    # [1단계] 수익구간 방어: 다이나믹 트레일링 스탑 & 본전 보존 스탑 (Dynamic Profit Lock)
    # ─────────────────────────────────────────────────────────────
    max_price = max(touch_high, curr_p)
    max_profit_pct = ((max_price - buy_price) / buy_price * 100.0) if buy_price > 0 else profit_pct

    # 1-1. [본전 보존 스탑 (Break-Even Stop)]
    # 장중 최고 수익률 +1.0% 이상 달성 후 주가가 밀려 본전(+0.2% 수수료 보전)까지 내려오면 원금 보존 즉시 청산!
    if max_profit_pct >= 1.0 and profit_pct <= 0.2:
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
                f"🛡️ [본전 보존 스탑 가동] 최고 수익률(+{max_profit_pct:.2f}%) 도달 후 본전(+0.2%) 회귀 "
                f"➔ 원금 100% 보존 즉시 매도 (현재 손익률: {profit_pct:+.2f}%)"
            ),
            "exit_type": "BREAK_EVEN_STOP"
        }

    # 1-2. [다이나믹 트레일링 익절 (Trailing Stop)]
    # +1.5% 이상 수익 도달 시: 고점 대비 0.5% 하락 시 익절 락인 (+1.5% ➔ +1.0% 스탑)
    # +2.5% 이상 수익 도달 시: 고점 대비 0.8% 하락 시 익절 락인 (+2.5% ➔ +1.7% 스탑)
    # +4.0% 이상 수익 도달 시: 고점 대비 1.0% 하락 시 익절 락인 (+4.0% ➔ +3.0% 스탑)
    if max_profit_pct >= 1.5:
        if max_profit_pct >= 4.0:
            floor_profit_pct = max_profit_pct - 1.0
        elif max_profit_pct >= 2.5:
            floor_profit_pct = max_profit_pct - 0.8
        else:
            floor_profit_pct = max_profit_pct - 0.5

        if profit_pct < floor_profit_pct:
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
                    f"🎯 [다이나믹 트레일링 익절 가동] 최고 수익률(+{max_profit_pct:.2f}%) 대비 "
                    f"마지노선(+{floor_profit_pct:.2f}%) 하향 이탈 ➔ 수익 확정 시장가 매도 (실현: {profit_pct:+.2f}%)"
                ),
                "exit_type": "STEP_TRAILING_STOP"
            }

    if wma3_now > 0 and wma5_now > 0:
        # ─────────────────────────────────────────────────────────────
        # [2단계] 15분봉 WMA 3-5 데드크로스 발생 시 전량 매도
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

    # ─────────────────────────────────────────────────────────────
    # [3단계] -2.5% strict stop-loss 방어
    # ─────────────────────────────────────────────────────────────
    if profit_pct <= -2.5:
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
            "reason": f"🚨 [Strict 손절] 손실률({profit_pct:+.2f}%) <= -2.5% 마지노선 이탈 ➔ 손절 매도",
            "exit_type": "STRICT_STOP_LOSS"
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
        "reason": f"15분봉 WMA3({wma3_now:,.0f}원) >= WMA5({wma5_now:,.0f}원) 정배열/상승 탄력 유지 중 (현재 수익률: {profit_pct:+.2f}%, 최고: +{max_profit_pct:.2f}%)",
        "exit_type": ""
    }

