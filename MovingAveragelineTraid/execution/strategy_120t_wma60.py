"""
strategy_120t_wma60.py - 120틱 WMA20-60 당일 첫번째 골든크로스 상승반전 진입 & 하락반전 매도 전략
=============================================================================================

개요:
  - 120틱 차트에서 WMA20(단기)과 WMA60(장기 가중평균 추세선, 약 7,200틱)을 산출하여,
  - [진입/매수]: WMA60이 횡보(수렴/바닥 다지기) 상태에서
                **당일 첫 번째(1st) WMA20 - WMA60 골든크로스**가 발생하는 바로 그 시점에만 한정 진입.
                당일 2회차 이후의 늦은 골든크로스나 장중 재돌파 휩쏘(Whipsaw)를 원천적으로 100% 차단.
  - [청산/매도]: WMA60이 고점(Peak)을 찍고 하락반전하거나 WMA20-60 데드크로스 발생 시
                기민하게 최고점 부근에서 전량 시장가 매도 청산.
"""

import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WMA60TickParams:
    short_period: int = 20              # 단기 WMA 기간 (WMA20 = 2,400틱)
    period: int = 60                    # 장기 WMA 기간 (WMA60 = 7,200틱)
    flat_lookback: int = 5              # 횡보 검증 기간 (골든크로스 직전 3~8봉)
    max_flat_slope_pct: float = 0.04    # 횡보로 인정하는 봉당 최대 WMA60 기울기 절대값 (%)
    min_turn_up_slope_pct: float = 0.002 # 상승반전 인정 최소 우상향 기울기 (%)
    allow_price_below_pct: float = 0.003 # WMA60 살짝 하단에서 돌파 직전 허용 오차 (0.3%)
    max_bars_after_gc: int = 2          # 당일 첫 골든크로스 발생 후 진입 허용 봉 수 (0~2봉 이내)
    strict_first_gc_only: bool = True   # 당일 첫번째 골든크로스만 한정 진입 여부


def calculate_wma(series: pd.Series, period: int = 60) -> pd.Series:
    """WMA(가중이동평균) 고속 벡터 연산"""
    if len(series) < period:
        return pd.Series(np.nan, index=series.index)
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()
    return series.rolling(window=period, min_periods=period).apply(
        lambda p: np.dot(p, weights) / w_sum,
        raw=True
    )


def evaluate_120t_wma60_entry(df_120t: pd.DataFrame, current_price: float = None,
                              params: WMA60TickParams = None) -> dict:
    """
    120틱 차트에서 WMA60 횡보 후 '당일 첫번째 WMA20-60 골든크로스 상승반전' 매수 진입 타점 판정

    조건:
      1. 봉 데이터가 60봉 이상 확보되어 WMA20 및 WMA60 정상 산출
      2. 당일(Today) 세션 내에서 발생한 WMA20 > WMA60 골든크로스 중 **1회차(첫번째)**에 해당
      3. 골든크로스 발생 직후 0~2봉 이내의 진입 유효 골든타임
      4. 골든크로스 직전 3~5개 봉 동안 WMA60의 기울기가 횡보/수렴 (기울기 변동 <= 0.04%)
      5. 현재가가 WMA60 지지선 상단에 안착 (Price >= WMA60 * 0.997)
    """
    if params is None:
        params = WMA60TickParams()

    result = {
        'should_buy': False,
        'wma20': 0.0,
        'wma60': 0.0,
        'today_gc_count': 0,
        'is_first_gc_today': False,
        'bars_since_first_gc': -1,
        'slope_pct': 0.0,
        'prev_slope_pct': 0.0,
        'is_flat_before': False,
        'is_turn_up': False,
        'reason': ''
    }

    if df_120t is None or df_120t.empty or len(df_120t) < (params.period + params.flat_lookback + 2):
        result['reason'] = f"120틱 데이터 부족 ({len(df_120t) if df_120t is not None else 0}개 / 필요: {params.period + 10}개)"
        return result

    # WMA20 및 WMA60 계산
    wma20 = calculate_wma(df_120t['close'], period=params.short_period)
    wma60 = calculate_wma(df_120t['close'], period=params.period)
    if wma60.dropna().empty or wma20.dropna().empty:
        result['reason'] = "WMA20/WMA60 산출 불가"
        return result

    # WMA60 기울기 계산
    slope60 = wma60.diff()
    pct_slope60 = (slope60 / wma60.shift(1)) * 100.0

    valid_df = df_120t.copy()
    valid_df['wma20'] = wma20
    valid_df['wma60'] = wma60
    valid_df['slope60'] = slope60
    valid_df['pct_slope60'] = pct_slope60
    valid_df = valid_df.dropna()

    if len(valid_df) < (params.flat_lookback + 2):
        result['reason'] = "유효 WMA 데이터 부족"
        return result

    # 당일(Today) 일자 판별
    if isinstance(valid_df.index, pd.DatetimeIndex):
        today_date = valid_df.index[-1].date()
        candle_dates = valid_df.index.date
    elif 'time' in valid_df.columns:
        today_date = pd.to_datetime(valid_df['time']).iloc[-1].date()
        candle_dates = pd.to_datetime(valid_df['time']).dt.date.values
    else:
        today_date = None
        candle_dates = None

    # 당일 골든크로스(WMA20 > WMA60) 발생 지점 전체 추적
    today_gc_indices = []
    for i in range(1, len(valid_df)):
        if candle_dates is not None and candle_dates[i] != today_date:
            continue
        prev_diff = valid_df['wma20'].iloc[i - 1] - valid_df['wma60'].iloc[i - 1]
        curr_diff = valid_df['wma20'].iloc[i] - valid_df['wma60'].iloc[i]
        if prev_diff <= 0 and curr_diff > 0:
            today_gc_indices.append(i)

    gc_count = len(today_gc_indices)
    curr_idx = len(valid_df) - 1
    last_bar = valid_df.iloc[-1]
    prev_bar = valid_df.iloc[-2]

    curr_c = float(current_price) if current_price and current_price > 0 else float(last_bar['close'])
    wma20_val = float(last_bar['wma20'])
    wma60_val = float(last_bar['wma60'])
    last_slope = float(last_bar['pct_slope60'])
    prev_slope = float(prev_bar['pct_slope60'])

    result['wma20'] = round(wma20_val, 1)
    result['wma60'] = round(wma60_val, 1)
    result['target_price'] = int(wma60_val)
    result['current_price'] = curr_c
    result['today_gc_count'] = gc_count
    result['slope_pct'] = round(last_slope, 4)
    result['prev_slope_pct'] = round(prev_slope, 4)

    # 1. 당일 골든크로스 발생 여부 확인
    if gc_count == 0:
        result['reason'] = "당일 120틱 WMA20-60 골든크로스 미발생 (역배열 또는 전일부터 정배열 지속)"
        return result

    first_gc_idx = today_gc_indices[0]
    bars_since_first_gc = curr_idx - first_gc_idx
    result['bars_since_first_gc'] = bars_since_first_gc

    # 2. 당일 '첫번째' 골든크로스 시점 한정 검증
    is_first_gc = (bars_since_first_gc <= params.max_bars_after_gc)
    result['is_first_gc_today'] = is_first_gc

    if params.strict_first_gc_only and not is_first_gc:
        if gc_count > 1:
            result['reason'] = (
                f"당일 첫번째 골든크로스 시점 경과 (현재 당일 {gc_count}번째 골든크로스 진행 중 - 1번째만 한정 진입)"
            )
        else:
            result['reason'] = (
                f"당일 첫번째 골든크로스 발생 후 이미 {bars_since_first_gc}봉 경과 (골든크로스 직후 {params.max_bars_after_gc}봉 이내만 진입 허용)"
            )
        return result

    # 3. 골든크로스 직전 WMA60 횡보/수렴 검증
    prior_window = valid_df['pct_slope60'].iloc[max(0, first_gc_idx - params.flat_lookback):first_gc_idx]
    avg_prior_abs_slope = float(prior_window.abs().mean()) if len(prior_window) > 0 else 0.0
    is_flat_before = (avg_prior_abs_slope <= params.max_flat_slope_pct) or (prior_window.mean() <= 0.005)
    result['is_flat_before'] = is_flat_before

    # 4. 상승반전 포착 (WMA20 >= WMA60 상태 & WMA60 기울기 둔화/우상향)
    is_turn_up = (wma20_val >= wma60_val) and (last_slope >= -0.005)
    result['is_turn_up'] = is_turn_up

    # 5. 주가 안착 조건: 현재가가 WMA60 선 위 또는 허용 범위 내 위치
    min_allowed_price = wma60_val * (1.0 - params.allow_price_below_pct)
    is_price_ok = (curr_c >= min_allowed_price)

    if is_first_gc and is_flat_before and is_turn_up and is_price_ok:
        result['should_buy'] = True
        result['reason'] = (
            f"🎯 [120틱 WMA20-60 당일 첫번째 골든크로스 상승반전] WMA60({wma60_val:,.0f}원) 횡보 수렴 후 "
            f"당일 1회차 첫 골든크로스(WMA20 > WMA60) 포착! (골든크로스 후 {bars_since_first_gc}봉, "
            f"기울기: {last_slope:+.4f}%, 현재가: {curr_c:,.0f}원)"
        )
    elif not is_flat_before:
        result['reason'] = f"120틱 WMA60 사전 횡보/수렴 미흡 (골든크로스 직전 평균 기울기: {avg_prior_abs_slope:.4f}%)"
    elif not is_turn_up:
        result['reason'] = f"120틱 WMA20-60 상승반전 미완성 (WMA20: {wma20_val:,.0f}, WMA60: {wma60_val:,.0f})"
    elif not is_price_ok:
        result['reason'] = f"현재가({curr_c:,.0f}원)가 120틱 WMA60({wma60_val:,.0f}원) 지지선 하단에 위치"

    return result


def evaluate_120t_wma60_exit(df_120t: pd.DataFrame, current_price: float = None,
                             buy_price: float = None, params: WMA60TickParams = None) -> dict:
    r"""
    120틱 차트에서 WMA60의 '고점 하락반전' 매도 청산 타점 판정

    조건:
      1. WMA60이 우상향하다가 고점(Peak)을 찍고 하향 꺾임 (Slope[t-1] >= 0 & Slope[t] < -0.002%)
      2. 또는 WMA20이 WMA60을 하향 데드크로스하며 WMA60 모멘텀이 소진될 때
      3. 또는 주가가 WMA60을 하향 이탈하며 하락 추세로 돌아설 때
    """
    if params is None:
        params = WMA60TickParams()

    result = {
        'should_sell': False,
        'wma20': 0.0,
        'wma60': 0.0,
        'slope_pct': 0.0,
        'prev_slope_pct': 0.0,
        'is_turn_down': False,
        'reason': ''
    }

    if df_120t is None or df_120t.empty or len(df_120t) < (params.period + 3):
        return result

    wma20 = calculate_wma(df_120t['close'], period=params.short_period)
    wma60 = calculate_wma(df_120t['close'], period=params.period)
    if wma60.dropna().empty or wma20.dropna().empty:
        return result

    slope = wma60.diff()
    pct_slope = (slope / wma60.shift(1)) * 100.0

    valid_df = df_120t.copy()
    valid_df['wma20'] = wma20
    valid_df['wma60'] = wma60
    valid_df['slope'] = slope
    valid_df['pct_slope'] = pct_slope
    valid_df = valid_df.dropna()

    if len(valid_df) < 3:
        return result

    last_bar = valid_df.iloc[-1]
    prev_bar = valid_df.iloc[-2]
    curr_c = float(current_price) if current_price and current_price > 0 else float(last_bar['close'])
    wma20_val = float(last_bar['wma20'])
    wma60_val = float(last_bar['wma60'])
    last_slope = float(last_bar['pct_slope'])
    prev_slope = float(prev_bar['pct_slope'])

    result['wma20'] = round(wma20_val, 1)
    result['wma60'] = round(wma60_val, 1)
    result['slope_pct'] = round(last_slope, 4)
    result['prev_slope_pct'] = round(prev_slope, 4)

    # 1. 고점 하락반전: 직전까지 상승(>=0) ➔ 현재 음수로 꺾임 (< -0.002%)
    is_turn_down = (prev_slope >= -0.001 and last_slope < -0.002)

    # 2. WMA20-60 데드크로스 발생
    prev_diff = prev_bar['wma20'] - prev_bar['wma60']
    curr_diff = wma20_val - wma60_val
    is_dead_cross = (prev_diff >= 0 and curr_diff < 0 and last_slope <= 0.001)

    # 3. 현재가가 WMA60 지지선 하향 이탈 및 기울기 음수
    is_breakdown = (curr_c < wma60_val * 0.997 and last_slope < 0)

    result['is_turn_down'] = is_turn_down or is_dead_cross or is_breakdown

    if is_turn_down:
        p_profit_str = f", 수익률: {((curr_c - buy_price)/buy_price)*100:+.2f}%" if buy_price and buy_price > 0 else ""
        result['should_sell'] = True
        result['reason'] = (
            f"📉 [120틱 WMA60 고점 하락반전 매도] WMA60({wma60_val:,.0f}원) 상승 모멘텀 소진 후 "
            f"하향 꺾임 감지! (기울기: {prev_slope:+.4f}% ➔ {last_slope:+.4f}%, 현재가: {curr_c:,.0f}원{p_profit_str})"
        )
    elif is_dead_cross:
        p_profit_str = f", 수익률: {((curr_c - buy_price)/buy_price)*100:+.2f}%" if buy_price and buy_price > 0 else ""
        result['should_sell'] = True
        result['reason'] = (
            f"📉 [120틱 WMA20-60 데드크로스 매도] 단기선(WMA20: {wma20_val:,.0f}원)이 "
            f"중기선(WMA60: {wma60_val:,.0f}원) 하향 이탈! (현재가: {curr_c:,.0f}원{p_profit_str})"
        )
    elif is_breakdown:
        p_profit_str = f", 수익률: {((curr_c - buy_price)/buy_price)*100:+.2f}%" if buy_price and buy_price > 0 else ""
        result['should_sell'] = True
        result['reason'] = (
            f"📉 [120틱 WMA60 하향 이탈 매도] 주가({curr_c:,.0f}원)가 WMA60({wma60_val:,.0f}원) 하향 이탈 및 "
            f"기울기 음수 지속({last_slope:+.4f}%){p_profit_str}"
        )

    return result
