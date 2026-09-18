"""
strategy_wma_squeeze_breakout.py - 52개 관심종목 대상 WMA(3,5) 역배열 이격수렴 후 15분봉 급등관문고가선 돌파 매수 전략
=================================================================================================================

전략 요약:
  1. 대상 유니버스: 바탕화면 500pick.csv 등 엄선된 주도주 (20봉 고가 20%+ & 거래대금 500억+ 검증 완료 종목)
  2. 수렴 감시 (Condition C & D):
     - 조건 C: 15분봉 가중이동평균 WMA(3) < WMA(5) (역배열)
     - 조건 D: WMA(3)과 WMA(5) 이격도 -2.0% 이상 ~ 0.0% 미만 (Disparity Squeeze)
     - 추세 D2: 이격도가 전봉 대비 확대/우상향하며 0% 방향으로 축소 중 (Disparity Narrowing)
  3. 돌파 매수 (Breakout Trigger):
     - 수렴(C & D) 상태에서 15분봉 종가가 15분봉 급등관문고가선(최근 저항 고가선 / HH선)을 상향 돌파 시 즉시 매수!
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WMASqueezeParams:
    """WMA 3/5 역배열 이격수렴 & 15분봉 급등관문 돌파 파라미터"""
    wma_short: int = 3                # 단기 가중이동평균 (WMA 3)
    wma_long: int = 5                 # 중기 가중이동평균 (WMA 5)
    min_disparity_pct: float = -2.0   # 이격도 하한선 (-2.0%)
    max_disparity_pct: float = 0.0    # 이격도 상한선 (0.0% 미만 = 역배열)
    gate_lookback_bars: int = 20      # 급등관문고가선 계산을 위한 최근 15분봉 수
    vol_surge_multiplier: float = 2.0 # 15분봉 거래량 폭증 배수 (2배 이상)


def wma(series: pd.Series, period: int) -> pd.Series:
    """가중이동평균 (Weighted Moving Average)"""
    if len(series) < period:
        return pd.Series([np.nan] * len(series), index=series.index)
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=period, min_periods=period).apply(
        lambda prices: np.dot(prices, weights) / weight_sum,
        raw=True
    )


def calculate_gateway_high(df_15m: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    15분봉 급등관문고가선(Gate High Line) 계산:
    - 최근 lookback개 15분봉의 고가(High) 최대 저항선
    """
    if 'high' not in df_15m.columns or len(df_15m) < 5:
        return pd.Series([np.nan] * len(df_15m), index=df_15m.index)
    return df_15m['high'].shift(1).rolling(window=lookback, min_periods=5).max()


def evaluate_wma35_squeeze_gateway(
    df_15m: pd.DataFrame,
    params: Optional[WMASqueezeParams] = None
) -> Dict[str, Any]:
    """
    52개 관심종목 대상 15분봉 WMA(3,5) 역배열 이격수렴 및 급등관문고가선 돌파 평가 함수
    """
    if params is None:
        params = WMASqueezeParams()

    result = {
        "buy_signal": False,
        "is_squeezed": False,
        "disparity_pct": 0.0,
        "wma3": 0.0,
        "wma5": 0.0,
        "gateway_high": 0.0,
        "reason": "",
        "priority_score": 0
    }

    if df_15m is None or len(df_15m) < params.wma_long + 2:
        result["reason"] = "15분봉 데이터 부족"
        return result

    close = df_15m['close']
    high = df_15m['high']
    volume = df_15m['volume']

    # WMA(3) 및 WMA(5) 산출
    wma3_series = wma(close, params.wma_short)
    wma5_series = wma(close, params.wma_long)

    curr_wma3 = wma3_series.iloc[-1]
    curr_wma5 = wma5_series.iloc[-1]
    prev_wma3 = wma3_series.iloc[-2]
    prev_wma5 = wma5_series.iloc[-2]

    if pd.isna(curr_wma3) or pd.isna(curr_wma5) or curr_wma5 == 0:
        result["reason"] = "WMA 산출 불가"
        return result

    # 이격도 계산 (%)
    disparity_curr = ((curr_wma3 - curr_wma5) / curr_wma5) * 100.0
    disparity_prev = ((prev_wma3 - prev_wma5) / prev_wma5) * 100.0

    result["wma3"] = float(curr_wma3)
    result["wma5"] = float(curr_wma5)
    result["disparity_pct"] = float(disparity_curr)

    # -------------------------------------------------------------
    # 1. Condition C: 역배열 (WMA3 < WMA5)
    # -------------------------------------------------------------
    is_reverse_alignment = curr_wma3 < curr_wma5

    # -------------------------------------------------------------
    # 2. Condition D: 이격도 -2.0% ~ 0.0% 수렴
    # -------------------------------------------------------------
    is_in_squeeze_range = (params.min_disparity_pct <= disparity_curr < params.max_disparity_pct)
    is_narrowing = (disparity_curr > disparity_prev)  # 이격도가 0% 방향으로 우상향 축소 중

    result["is_squeezed"] = is_reverse_alignment and is_in_squeeze_range and is_narrowing

    if not result["is_squeezed"]:
        if not is_reverse_alignment:
            result["reason"] = f"WMA(3,5) 정배열/크로스 상태 (이격도: {disparity_curr:+.2f}%)"
        elif not is_in_squeeze_range:
            result["reason"] = f"이격도 수렴 범위 초과 (현재: {disparity_curr:+.2f}%, 기준: -2.0%~0.0%)"
        else:
            result["reason"] = f"이격도 확대 중 (전봉: {disparity_prev:+.2f}% -> 현재: {disparity_curr:+.2f}%)"
        return result

    # -------------------------------------------------------------
    # 3. 15분봉 급등관문고가선 계산 및 돌파 트리거 검증
    # -------------------------------------------------------------
    gateway_series = calculate_gateway_high(df_15m, params.gate_lookback_bars)
    curr_gateway = gateway_series.iloc[-1]
    curr_close = close.iloc[-1]

    if pd.isna(curr_gateway):
        # 관문고가선 부재 시 최근 10봉 전까지의 최고가 사용
        curr_gateway = high.iloc[-params.gate_lookback_bars:-1].max()

    result["gateway_high"] = float(curr_gateway)

    # 수급 확인 (거래량 이평 대비 수급 유입)
    vol_ma20 = volume.iloc[-21:-1].mean() if len(volume) >= 21 else volume.mean()
    curr_vol = volume.iloc[-1]
    has_volume = curr_vol >= (vol_ma20 * params.vol_surge_multiplier) if vol_ma20 > 0 else True

    # 돌파 조건: 종가가 15분봉 급등관문고가선을 상향 돌파
    is_breakout = curr_close > curr_gateway

    if is_breakout:
        result["buy_signal"] = True
        result["priority_score"] = 98  # 최상위 전략 매수 점수
        result["reason"] = (
            f"🔥 [WMA 3/5 역배열 수렴 돌파] 이격도: {disparity_curr:+.2f}% (-2%이내 근접), "
            f"15분봉 관문고가선({curr_gateway:,.0f}원) 상향 돌파 (현재가: {curr_close:,.0f}원)"
        )
    else:
        result["reason"] = (
            f"👀 [수렴 완료 관찰 중] 이격도: {disparity_curr:+.2f}% 수렴 중, "
            f"관문고가선({curr_gateway:,.0f}원) 돌파 대기 중 (현재가: {curr_close:,.0f}원)"
        )

    return result
