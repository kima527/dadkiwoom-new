"""
strategy_takeprofit.py - 3분봉 SMA 데드크로스 수익실현 전략
===========================================================================

수익실현 로직:
  - 3분봉에서 SMA5가 SMA20을 데드크로스(하향 돌파)할 때
  - 현재가가 매입단가(buy_price)보다 높은 상태(수익 중)일 경우에만
  - 전량 수익실현 매도

사용 데이터: 3분봉 (tic_scope="3")
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 3분봉 SMA 데드크로스 수익실현 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_takeprofit_signals(df: pd.DataFrame, buy_price: float = 0.0) -> dict:
    """
    3분봉 DataFrame과 매입단가를 받아 수익실현 매도 신호를 생성합니다.

    Parameters
    ----------
    df : pd.DataFrame
        3분봉 데이터 (open, high, low, close, volume)
    buy_price : float
        평균 매입단가. 0이면 수익 여부를 판단하지 않고 데드크로스만으로 신호 생성.

    Returns
    -------
    dict:
        sell     : bool   - 수익실현 매도 신호
        reason   : str    - 매도 사유 메시지
        sma5     : float  - 현재 SMA5 값
        sma20    : float  - 현재 SMA20 값
        profit_pct : float - 현재 수익률 (%)
    """
    if df is None or df.empty or len(df) < 25:
        return {"sell": False, "reason": "", "sma5": 0.0, "sma20": 0.0, "profit_pct": 0.0}

    df = df.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns:
        return {"sell": False, "reason": "", "sma5": 0.0, "sma20": 0.0, "profit_pct": 0.0}

    # ── SMA 계산 ──
    df['sma5'] = df['close'].rolling(window=5, min_periods=1).mean()
    df['sma20'] = df['close'].rolling(window=20, min_periods=1).mean()

    # ── RSI(14) 계산 (Wilder's Smoothing) ──
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=1, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=1, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # ── 감지 로직: 데드크로스 및 RSI 70 하향 이탈 ──
    df['dead_cross'] = (
        (df['sma5'] < df['sma20']) &
        (df['sma5'].shift(1) >= df['sma20'].shift(1))
    )
    df['rsi_cross_down'] = (
        (df['rsi'] < 70) &
        (df['rsi'].shift(1) >= 70)
    )

    latest = df.iloc[-1]
    close_price = float(latest['close'])
    sma5_now = float(latest['sma5']) if pd.notna(latest['sma5']) else 0.0
    sma20_now = float(latest['sma20']) if pd.notna(latest['sma20']) else 0.0
    rsi_now = float(latest['rsi']) if pd.notna(latest['rsi']) else 0.0

    # 수익률 계산
    profit_pct = 0.0
    if buy_price > 0:
        profit_pct = ((close_price - buy_price) / buy_price) * 100

    result = {
        "sell": False,
        "reason": "",
        "sma5": sma5_now,
        "sma20": sma20_now,
        "rsi": rsi_now,
        "profit_pct": round(profit_pct, 2)
    }

    # ── 수익실현 판단 ──
    is_dead_cross = bool(latest['dead_cross']) if pd.notna(latest['dead_cross']) else False
    is_rsi_exit = bool(latest['rsi_cross_down']) if pd.notna(latest['rsi_cross_down']) else False

    if is_dead_cross or is_rsi_exit:
        if buy_price > 0 and close_price > buy_price:
            # 수익 중일 때만 익절
            result["sell"] = True
            if is_rsi_exit:
                result["reason"] = (
                    f"RSI({rsi_now:.1f}) 과매수권(70) 하향 이탈 발생, "
                    f"수익률 +{profit_pct:.1f}% 수익실현"
                )
            else:
                result["reason"] = (
                    f"3분봉 SMA5({sma5_now:,.0f})<SMA20({sma20_now:,.0f}) 데드크로스 발생, "
                    f"수익률 +{profit_pct:.1f}% 수익실현"
                )
        elif buy_price <= 0:
            # 매입단가 정보 없으면 신호만으로도 발생 (안전 우선)
            result["sell"] = True
            if is_rsi_exit:
                result["reason"] = (
                    f"RSI({rsi_now:.1f}) 과매수권(70) 하향 이탈 발생 "
                    f"(매입단가 미확인, 안전 매도)"
                )
            else:
                result["reason"] = (
                    f"3분봉 SMA5({sma5_now:,.0f})<SMA20({sma20_now:,.0f}) 데드크로스 발생 "
                    f"(매입단가 미확인, 안전 매도)"
                )

    return result
