"""
strategy_15m_squeeze_alignment.py
=============================================================================
15분봉 이평선 수평 응축(20·40·60·130) + 3·5·20·40·60·130 정배열 + 수급 폭발 매수 전략 모듈

[전략 조건 및 메커니즘]
1. 15분봉 20, 40, 60, 130 이평선 수평 응축 (Squeeze / Consolidation):
   - 최근 N봉(기본 3봉) 이내 15분봉 20이평, 40이평, 60이평, 130이평선의 최대/최소 격차가 1.5% 이내로 밀집
   - 장기/중기 매수 매도 주체의 평균 단가가 평탄화되며 대규모 변동성 폭발 직전 상태 형성
2. 3·5·20·40·60·130 완벽한 정배열 전환 (Full Bullish Sequence Alignment):
   - 현재 15분봉 종가 기준 MA3 > MA5 > MA20 > MA40 > MA60 > MA130 완성
3. 수급 폭발 (Volume / Money Flow Surge):
   - 15분봉 거래대금 >= 15억원 (또는 20억원)
   - 직전 20봉 평균 거래대금 대비 5배 이상(A >= AvgA * 5) 또는 직전 2봉 평균 대비 3배 이상 폭증
4. 캔들 형태 및 과열 방지:
   - 양봉 몸통이 윗꼬리보다 긴 강한 캔들 (Close > Open & Body >= Upper Tail * 1.0)
   - 단일 15분봉 종가 상승률 <= 7.5% (추격 과열봉 배제)
   - 당일 등락률 <= 20.0% (과도하게 폭등한 종목 추격 배제)
=============================================================================
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class SqueezeAlignmentParams:
    """15분봉 이평선 수평 응축 및 정배열 수급 돌파 파라미터"""
    max_squeeze_pct: float = 1.5          # 20,40,60,130 이평선 최대/최소 격차 비율 (%) (기본 1.5% 이내 밀집)
    squeeze_lookback_bars: int = 3        # 최근 몇 봉 이내에 응축 상태가 존재해야 하는가 (기본 3봉)
    min_supply_money_15m: float = 15.0    # 15분봉 돌파봉 최소 거래대금 (15억원 이상)
    supply_surge_multiplier: float = 3.0  # 직전 2봉 평균 대비 수급 폭증 배수 (3배)
    supply_ma20_multiplier: float = 5.0   # 20봉 평균 대비 수급 폭증 배수 (5배: A >= AvgA * 5)
    max_bar_gain_pct: float = 7.5         # 단일 15분봉 종가 상승률 상한선 (7.5% 초과 추격 금지)
    max_daily_gain_pct: float = 20.0      # 당일 등락률 상한선 (20% 초과 late-afternoon 과열주 방지)
    min_body_ratio: float = 1.0           # 양봉 몸통 / 윗꼬리 비율 (최소 1.0배 이상)
    min_bars_15m: int = 135               # 130이평 계산을 위한 최소 요구 15분봉 데이터 개수


def calculate_15m_squeeze_indicators(df_15m: pd.DataFrame) -> pd.DataFrame:
    """
    15분봉 데이터프레임에 이평선(3, 5, 20, 40, 60, 130), 응축도(Squeeze Ratio), 수급 지표 계산
    """
    df = df_15m.copy()
    close = df['close']
    high = df['high']
    low = df['low']
    open_p = df['open']
    volume = df['volume']

    # 15분봉 이평선 (130이평선 추가)
    df['ma3'] = close.rolling(3, min_periods=3).mean()
    df['ma5'] = close.rolling(5, min_periods=5).mean()
    df['ma20'] = close.rolling(20, min_periods=20).mean()
    df['ma40'] = close.rolling(40, min_periods=40).mean()
    df['ma60'] = close.rolling(60, min_periods=60).mean()
    df['ma130'] = close.rolling(130, min_periods=130).mean()

    # 15분봉 거래대금 (억원 단위)
    df['m15_money'] = (close * volume) / 100_000_000.0

    # 20, 40, 60, 130 이평선 최대/최소 수평 응축 비율 계산
    ma_mid_group = df[['ma20', 'ma40', 'ma60', 'ma130']]
    ma_max = ma_mid_group.max(axis=1)
    ma_min = ma_mid_group.min(axis=1)
    
    # 응축도 (%) = ((최대이평 - 최소이평) / 최소이평) * 100
    df['squeeze_pct'] = ((ma_max - ma_min) / ma_min) * 100.0
    
    # 완벽한 3 > 5 > 20 > 40 > 60 > 130 정배열 여부
    df['is_full_bullish'] = (
        (df['ma3'] > df['ma5']) &
        (df['ma5'] > df['ma20']) &
        (df['ma20'] > df['ma40']) &
        (df['ma40'] > df['ma60']) &
        (df['ma60'] > df['ma130'])
    )

    # 캔들 특징
    df['bar_gain_pct'] = ((close - open_p) / open_p) * 100.0
    df['body'] = (close - open_p).abs()
    df['upper_tail'] = high - df[['open', 'close']].max(axis=1)

    # 수급 관련 지표
    df['avg_money_20'] = df['m15_money'].rolling(20, min_periods=5).mean().shift(1)
    df['avg_money_prev2'] = df['m15_money'].shift(1).rolling(2, min_periods=1).mean()

    return df


def evaluate_15m_squeeze_alignment(
    code: str,
    name: str,
    df_15m: pd.DataFrame,
    daily_df: Optional[pd.DataFrame] = None,
    params: SqueezeAlignmentParams = SqueezeAlignmentParams()
) -> Dict[str, Any]:
    """
    단일 종목의 15분봉 차트를 분석하여
    '15분봉 20·40·60·130 이평선 응축 + 3·5·20·40·60·130 정배열 + 수급 폭발' 조건 충족 여부 판정
    """
    res = {
        "code": code,
        "name": name,
        "is_buy_signal": False,
        "reason": "",
        "squeeze_pct": 0.0,
        "is_squeezed": False,
        "is_aligned": False,
        "is_supply_surge": False,
        "current_price": 0.0,
        "m15_money": 0.0,
        "bar_gain_pct": 0.0,
        "daily_gain_pct": 0.0,
        "details": {}
    }

    if df_15m is None or len(df_15m) < params.min_bars_15m:
        res["reason"] = f"15분봉 데이터 부족 ({len(df_15m) if df_15m is not None else 0} < {params.min_bars_15m})"
        return res

    df = calculate_15m_squeeze_indicators(df_15m)
    curr = df.iloc[-1]
    res["current_price"] = float(curr['close'])
    res["m15_money"] = float(curr['m15_money'])
    res["bar_gain_pct"] = float(curr['bar_gain_pct'])
    res["squeeze_pct"] = float(curr['squeeze_pct'])

    # 당일 등락률 계산 (일봉 지원 시)
    if daily_df is not None and not daily_df.empty:
        prev_close = float(daily_df['close'].iloc[-2]) if len(daily_df) >= 2 else float(daily_df['open'].iloc[-1])
        res["daily_gain_pct"] = ((res["current_price"] - prev_close) / prev_close) * 100.0
    else:
        res["daily_gain_pct"] = float(curr['bar_gain_pct'])

    # 1. 최근 N봉 이내 20, 40, 60, 130 이평선 응축 조건 검증
    recent_squeeze_series = df['squeeze_pct'].iloc[-params.squeeze_lookback_bars:]
    is_squeezed = (recent_squeeze_series <= params.max_squeeze_pct).any()
    res["is_squeezed"] = bool(is_squeezed)

    if not is_squeezed:
        res["reason"] = f"이평선(20·40·60·130) 응축 미충족 (최근 {params.squeeze_lookback_bars}봉 최소 격차: {recent_squeeze_series.min():.2f}% > {params.max_squeeze_pct}%)"
        return res

    # 2. 현재봉 3 > 5 > 20 > 40 > 60 > 130 완벽 정배열 검증
    is_aligned = bool(curr['is_full_bullish'])
    res["is_aligned"] = is_aligned
    if not is_aligned:
        res["reason"] = f"3·5·20·40·60·130 정배열 미충족 (MA3={curr['ma3']:.1f}, MA5={curr['ma5']:.1f}, MA20={curr['ma20']:.1f}, MA40={curr['ma40']:.1f}, MA60={curr['ma60']:.1f}, MA130={curr['ma130']:.1f})"
        return res

    # 3. 수급 폭발 조건 검증 (15분 거래대금 >= 15억 & 20봉 평균의 5배 OR 직전 2봉의 3배)
    curr_money = float(curr['m15_money'])
    avg_20 = float(curr['avg_money_20']) if not pd.isna(curr['avg_money_20']) else 1.0
    avg_prev2 = float(curr['avg_money_prev2']) if not pd.isna(curr['avg_money_prev2']) else 1.0

    cond_min_money = curr_money >= params.min_supply_money_15m
    cond_surge_20 = curr_money >= (avg_20 * params.supply_ma20_multiplier)
    cond_surge_prev2 = curr_money >= (avg_prev2 * params.supply_surge_multiplier)

    is_supply_surge = cond_min_money and (cond_surge_20 or cond_surge_prev2)
    res["is_supply_surge"] = bool(is_supply_surge)

    if not is_supply_surge:
        res["reason"] = f"15분 수급 폭발 미충족 (거래대금: {curr_money:.2f}억 / 20봉평균 대비: {curr_money/avg_20:.1f}배 / 직전대비: {curr_money/avg_prev2:.1f}배)"
        return res

    # 4. 캔들 몸통 및 과열 방지 검증
    is_positive_body = curr['close'] > curr['open']
    body_val = float(curr['body'])
    upper_tail_val = float(curr['upper_tail'])
    is_strong_body = is_positive_body and (body_val >= upper_tail_val * params.min_body_ratio)

    if not is_strong_body:
        res["reason"] = f"캔들 형태 미달 (양봉 여부: {is_positive_body}, 몸통={body_val:.0f} < 윗꼬리={upper_tail_val:.0f})"
        return res

    if curr['bar_gain_pct'] > params.max_bar_gain_pct:
        res["reason"] = f"단일 15분봉 과열 급등 ({curr['bar_gain_pct']:.2f}% > {params.max_bar_gain_pct}%)"
        return res

    if res["daily_gain_pct"] > params.max_daily_gain_pct:
        res["reason"] = f"당일 과열 종목 추격 배제 ({res['daily_gain_pct']:.2f}% > {params.max_daily_gain_pct}%)"
        return res

    # 5. 모든 조건 100% 충족 -> 최종 매수 신호 발화
    res["is_buy_signal"] = True
    res["reason"] = (
        f"🎯 [수급 130이평 응축 정배열 돌파 완료] "
        f"응축도={recent_squeeze_series.min():.2f}%, 3-5-20-40-60-130 정배열, "
        f"15분 수급={curr_money:.2f}억원(20봉평균 대비 {curr_money/avg_20:.1f}배)"
    )
    res["details"] = {
        "ma3": float(curr['ma3']),
        "ma5": float(curr['ma5']),
        "ma20": float(curr['ma20']),
        "ma40": float(curr['ma40']),
        "ma60": float(curr['ma60']),
        "ma130": float(curr['ma130']),
        "squeeze_pct_min": float(recent_squeeze_series.min()),
        "money_multiplier_20": float(curr_money / avg_20) if avg_20 > 0 else 0.0
    }

    return res
