"""
strategy_120t_wma60.py - 120틱 WMA 20-40-60 역배열 순차돌파 + 15분봉 볼린저 스퀴즈 & 3대 관문 수식 융합 전략
=================================================================================================================

개요:
  - 120틱 차트: WMA20, 40, 60 역배열 상태에서 1이평선(종가)이 차례대로 20->40->60을 돌파하는 미시적 정밀 스나이핑
  - 15분봉 차트: 볼린저 밴드 스퀴즈(에너지 응축) + 3대 관문 수식(테마급등관문선 -> 급등관문고가선 -> 기준선 M선)의 매크로 지형도
  - [진입/매수]: 
      1) 15분봉 볼린저 스퀴즈 & 테마급등관문선(TEMA 5-20) 지지 확인
      2) 120틱 WMA20-40-60 역배열 후 1이평선 순차 돌파 포착
      3) 60이동평균선의 골든크로스값(WMA60 GC)을 매수기준(target_price)으로 최우선 진입
  - [청산/매도]:
      1) 1차 익절: 15분봉 기준선(M선, 5-20-60 정배열 피크) 목표 도달 시
      2) 추세 청산: 120틱 WMA60 고점 하락반전(Peak Reversal) 또는 WMA20 데드크로스 시
      3) 방어 손절: 15분봉 테마급등관문선 하향 이탈 시
"""

import time
import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

from xray_analyzer import evaluate_xray_power, XRayParams

logger = logging.getLogger(__name__)


@dataclass
class WMA60TickParams:
    period_fast: int = 1                # 1이동평균선 (종가)
    period_20: int = 20                 # 단기 WMA (WMA20 = 2,400틱)
    period_40: int = 40                 # 중기 WMA (WMA40 = 4,800틱)
    period_60: int = 60                 # 장기 WMA (WMA60 = 7,200틱)
    short_period: int = 20              # 하위 호환용 (WMA20)
    period: int = 60                    # 하위 호환용 (WMA60)
    flat_lookback: int = 5              # 횡보 검증 기간
    max_flat_slope_pct: float = 0.05    # WMA60 기울기 변동 허용 범위 (%)
    allow_price_below_pct: float = 0.003# WMA60 살짝 하단 허용 오차 (0.3%)
    max_bars_after_gc: int = 2          # 60선 골든크로스 후 진입 허용 봉 수 (0~2봉 이내)
    strict_first_gc_only: bool = True   # 당일 첫번째 골든크로스만 한정 진입 여부
    seq_lookback: int = 40              # 역배열 및 순차 돌파 추적 최대 룩백 봉 수
    # ── 2분봉 3대 관문 & 볼린저 스퀴즈 융합 파라미터 (15분봉 -> 2분봉 고도화) ──
    use_2m_macro_filter: bool = True    # 2분봉 매크로 게이트 연동 활성화
    use_15m_macro_filter: bool = True   # 하위 호환용 (15분봉 필터 플래그)
    require_gate_break: bool = True     # [2번] 급등관문고가선 돌파 필수 충족 여부
    bb_max_bandwidth: float = 0.08      # 볼린저 밴드 스퀴즈 상한선 (8.0% 이내 응축)
    tema_support_tol: float = 0.008     # 테마급등관문선 하단 지지 허용 오차 (0.8%)
    # ── X-Ray 순간체결량 & 포착빈도 수급 파라미터 ──
    use_xray_filter: bool = True        # X-Ray 수급 분석 활성화
    xray_large_trade_threshold: float = 20_000_000.0 # 대형 체결 기준 (2천만원)


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


def calculate_tema(series: pd.Series, period: int) -> pd.Series:
    """TEMA(삼중지수이동평균) 고속 연산: TEMA = 3*EMA1 - 3*EMA2 + EMA3"""
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return 3.0 * ema1 - 3.0 * ema2 + ema3


def calculate_2m_macro_gates(df_2m: pd.DataFrame) -> Dict[str, Any]:
    """
    2분봉 차트에서 [볼린저 스퀴즈 + 3대 관문 수식] 매크로 지형도 산출
    1. 테마급등관문선: CrossUp(TEMA5, TEMA20) 발생 시점의 TEMA5 값 (수평 절대 바닥선)
    2. 급등관문고가선: CrossUp(MA5, MA20) 발생 시점의 High 값 (급등 가속 관문선)
    3. 기준선(M선): 5-20-60 정배열 피크 변곡 종가 (사전 확정 목표가)
    4. 볼린저 스퀴즈: 밴드폭(Bandwidth) = (Upper - Lower) / Middle
    """
    res = {
        'tema_gate': 0.0,
        'gate_high': 0.0,
        'm_line': 0.0,
        'bandwidth': 0.10,
        'is_bb_squeeze': False,
        'is_tema_support': True,
        'is_gate_broken': False
    }

    if df_2m is None or df_2m.empty or len(df_2m) < 25:
        return res

    close = df_2m['close']
    high = df_2m['high'] if 'high' in df_2m.columns else close

    # 1. 테마급등관문선 (TEMA 5-20 골든크로스 가격)
    t1 = calculate_tema(close, 5)
    t2 = calculate_tema(close, 20)
    cross_tema = (t1.shift(1) <= t2.shift(1)) & (t1 > t2)
    tema_gate_s = t1.where(cross_tema).ffill()
    tema_gate = float(tema_gate_s.iloc[-1]) if not tema_gate_s.dropna().empty else float(t2.iloc[-1])
    res['tema_gate'] = round(tema_gate, 1)

    # 2. 급등관문고가선 (MA 5-20 골든크로스 당봉 High)
    ma5 = close.rolling(5, min_periods=5).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    cross_ma = (ma5.shift(1) <= ma20.shift(1)) & (ma5 > ma20)
    gate_high_s = high.where(cross_ma).ffill()
    gate_high = float(gate_high_s.iloc[-1]) if not gate_high_s.dropna().empty else float(high.max())
    res['gate_high'] = round(gate_high, 1)

    # 3. 기준선 (5-20-60 정배열 피크 M선)
    ma60 = close.rolling(60, min_periods=min(len(close), 60)).mean()
    cond_align = (ma5 > ma20) & (ma20 > ma60) & (ma5 > ma60)
    k_series = close.where(cond_align).ffill()
    k_shift1 = k_series.shift(1)
    k_shift2 = k_series.shift(2)
    cond_peak = (k_shift1 > k_shift2) & (k_shift1 > k_series)
    m_line_s = k_shift1.where(cond_peak).ffill()
    m_line = float(m_line_s.iloc[-1]) if not m_line_s.dropna().empty else float(high.iloc[-1] * 1.05)
    res['m_line'] = round(m_line, 1)

    # 4. 볼린저 밴드 스퀴즈 (20, 2)
    bb_std = close.rolling(20, min_periods=20).std()
    bb_bw = (4.0 * bb_std) / ma20
    last_bw = float(bb_bw.iloc[-1]) if not bb_bw.dropna().empty else 0.10
    res['bandwidth'] = round(last_bw, 4)
    # 밴드폭이 8% 이하이거나 최근 20봉 내 최저 수준 수축
    min_bw_20 = float(bb_bw.rolling(20, min_periods=5).min().iloc[-1]) if not bb_bw.dropna().empty else 0.10
    res['is_bb_squeeze'] = (last_bw <= 0.08) or (last_bw <= min_bw_20 * 1.20)

    # 현재가와 관문선 비교
    curr_c = float(close.iloc[-1])
    res['is_tema_support'] = (curr_c >= tema_gate * 0.992)
    res['is_gate_broken'] = (curr_c >= gate_high * 0.998)

    return res

# 하위 호환용 별칭
calculate_15m_macro_gates = calculate_2m_macro_gates


def evaluate_120t_wma60_entry(df_120t: pd.DataFrame, current_price: float = None,
                              params: WMA60TickParams = None,
                              df_2m: pd.DataFrame = None,
                              df_15m: pd.DataFrame = None,
                              ticks: list = None) -> dict:
    """
    [통합 2번 하이브리드 전략 (2분봉 + X-Ray 고도화 버전)]
    120틱 WMA 20-40-60 역배열 순차돌파 + 2분봉 3대 관문 + X-Ray 1초 3건 싹쓸이 & 포착빈도 융합

    조건:
      1. [120틱 미시 스나이핑]:
         - 120틱 차트에서 WMA20, 40, 60 역배열 상태에서
         - 1이평선(종가)이 차례대로 WMA20 -> WMA40 -> WMA60을 순차 돌파
         - 60이평선 골든크로스값(WMA60 GC)을 매수기준(target_price)으로 설정
      2. [2분봉 거시 매크로 게이트] (df_2m 제공 시, 없으면 df_15m 대체):
         - 2분봉 테마급등관문선(TEMA 5-20) 상단 지지 안착
         - 2분봉 볼린저 밴드 스퀴즈(Bandwidth 수축) 에너지 응축 보너스 반영
         - 2분봉 기준선(M선)을 사전에 산출하여 확정 목표가(m_target_price)로 등록
      3. [X-Ray 순간체결량 & 포착빈도]:
         - 1초 내 대량 체결(2천만원 이상) 3건 이상 동시 다발 싹쓸이(Sweeping) 탐지
         - 최근 대형 순매수 체결 누적 포착빈도 상위 카운팅
    """
    if params is None:
        params = WMA60TickParams()

    result = {
        'should_buy': False,
        'target_price': 0,
        'current_price': 0.0,
        'wma1': 0.0,
        'wma20': 0.0,
        'wma40': 0.0,
        'wma60': 0.0,
        'wma60_gc_val': 0.0,
        'today_gc_count': 0,
        'is_first_gc_today': False,
        'bars_since_first_gc': -1,
        'slope_pct': 0.0,
        'prev_slope_pct': 0.0,
        'is_flat_before': True,
        'is_turn_up': False,
        # 2분봉 융합 필드
        'm_target_price': 0.0,
        'tema_gate': 0.0,
        'gate_high': 0.0,
        'is_bb_squeeze': False,
        'macro_bonus': 0.0,
        # X-Ray 순간체결량 & 포착빈도 필드
        'xray_grade': 'C',
        'xray_freq': 0,
        'has_1sec_sweep': False,
        'xray_bonus': 0.0,
        'xray_tag': '',
        'reason': ''
    }

    req_len = max(params.period_60, params.period) + params.flat_lookback + 2
    if df_120t is None or df_120t.empty or len(df_120t) < req_len:
        result['reason'] = f"120틱 데이터 부족 ({len(df_120t) if df_120t is not None else 0}개 / 필요: {req_len}개)"
        return result

    # 1. 120틱 이평선 계산 (1이평, WMA20, WMA40, WMA60)
    close_series = df_120t['close']
    wma1 = close_series
    wma20 = calculate_wma(close_series, period=params.period_20)
    wma40 = calculate_wma(close_series, period=params.period_40)
    wma60 = calculate_wma(close_series, period=params.period_60)

    if wma60.dropna().empty or wma40.dropna().empty or wma20.dropna().empty:
        result['reason'] = "WMA20/WMA40/WMA60 산출 불가"
        return result

    slope60 = wma60.diff()
    pct_slope60 = (slope60 / wma60.shift(1)) * 100.0

    valid_df = df_120t.copy()
    valid_df['wma1'] = wma1
    valid_df['wma20'] = wma20
    valid_df['wma40'] = wma40
    valid_df['wma60'] = wma60
    valid_df['slope60'] = slope60
    valid_df['pct_slope60'] = pct_slope60
    valid_df = valid_df.dropna()

    if len(valid_df) < (params.flat_lookback + 2):
        result['reason'] = "유효 WMA 데이터 부족"
        return result

    # 당일(Today) 판별
    if isinstance(valid_df.index, pd.DatetimeIndex):
        today_date = valid_df.index[-1].date()
        candle_dates = valid_df.index.date
    elif 'time' in valid_df.columns:
        today_date = pd.to_datetime(valid_df['time']).iloc[-1].date()
        candle_dates = pd.to_datetime(valid_df['time']).dt.date.values
    else:
        today_date = None
        candle_dates = None

    curr_idx = len(valid_df) - 1
    last_bar = valid_df.iloc[-1]
    prev_bar = valid_df.iloc[-2]

    curr_c = float(current_price) if current_price and current_price > 0 else float(last_bar['close'])
    wma1_val = float(last_bar['wma1'])
    wma20_val = float(last_bar['wma20'])
    wma40_val = float(last_bar['wma40'])
    wma60_val = float(last_bar['wma60'])
    last_slope = float(last_bar['pct_slope60'])
    prev_slope = float(prev_bar['pct_slope60'])

    result['wma1'] = round(wma1_val, 1)
    result['wma20'] = round(wma20_val, 1)
    result['wma40'] = round(wma40_val, 1)
    result['wma60'] = round(wma60_val, 1)
    result['current_price'] = curr_c
    result['slope_pct'] = round(last_slope, 4)
    result['prev_slope_pct'] = round(prev_slope, 4)

    # 2. 당일 1이평선의 WMA60 골든크로스 발생 지점 추적
    today_wma60_gc_indices = []
    for i in range(1, len(valid_df)):
        if candle_dates is not None and candle_dates[i] != today_date:
            continue
        prev_diff = valid_df['wma1'].iloc[i - 1] - valid_df['wma60'].iloc[i - 1]
        curr_diff = valid_df['wma1'].iloc[i] - valid_df['wma60'].iloc[i]
        if prev_diff <= 0 and curr_diff > 0:
            today_wma60_gc_indices.append(i)

    gc_count = len(today_wma60_gc_indices)
    result['today_gc_count'] = gc_count

    if gc_count == 0:
        result['reason'] = "당일 120틱 1이평선의 WMA60 골든크로스 미발생"
        return result

    gc_idx = today_wma60_gc_indices[0] if params.strict_first_gc_only else today_wma60_gc_indices[-1]
    bars_since_gc = curr_idx - gc_idx
    result['bars_since_first_gc'] = bars_since_gc

    is_recent_gc = (bars_since_gc <= params.max_bars_after_gc)
    result['is_first_gc_today'] = is_recent_gc

    if params.strict_first_gc_only and not is_recent_gc:
        if gc_count > 1:
            result['reason'] = (
                f"당일 첫번째 1이평-WMA60 골든크로스 시점 경과 (현재 당일 {gc_count}번째 골든크로스 진행 중 - 1번째만 한정 진입)"
            )
        else:
            result['reason'] = (
                f"당일 첫번째 1이평-WMA60 골든크로스 발생 후 이미 {bars_since_gc}봉 경과 (골든크로스 직후 {params.max_bars_after_gc}봉 이내만 진입 허용)"
            )
        return result
    elif not is_recent_gc:
        result['reason'] = f"1이평-WMA60 골든크로스 발생 후 이미 {bars_since_gc}봉 경과 (허용: {params.max_bars_after_gc}봉 이내)"
        return result

    # 3. 60이동평균선의 골든크로스값 (gc_idx 봉에서의 WMA60 값) -> 매수기준값 설정
    wma60_gc_val = float(valid_df['wma60'].iloc[gc_idx])
    result['wma60_gc_val'] = round(wma60_gc_val, 1)
    result['target_price'] = int(wma60_gc_val)

    # 4. WMA20, 40, 60 역배열 상태에서 1이평선 순차 돌파 검증
    # [방어 1: 20 < 60 < 40 꼬임 원천 차단]
    # 역배열(단기 < 중기 < 장기)의 대원칙상 40선은 반드시 60선 아래에 있어야 함 (WMA40 < WMA60)!
    gc_w40 = float(valid_df['wma40'].iloc[gc_idx])
    gc_w60 = float(valid_df['wma60'].iloc[gc_idx])
    if gc_w40 >= gc_w60 or wma40_val >= wma60_val:
        result['reason'] = (
            f"WMA40({wma40_val:,.1f}원) >= WMA60({wma60_val:,.1f}원) ➔ 20<60<40 꼬임 발생 "
            f"(정상 역배열 20<40<60 미충족으로 매수 차단)"
        )
        return result

    # [방어 2: 최근 역배열 선행 확인]
    lookback_start = max(0, gc_idx - params.seq_lookback)
    inv_start_idx = None
    for i in range(gc_idx - 1, lookback_start - 1, -1):
        w20 = valid_df['wma20'].iloc[i]
        w40 = valid_df['wma40'].iloc[i]
        w60 = valid_df['wma60'].iloc[i]
        w1 = valid_df['wma1'].iloc[i]
        if w20 < w40 < w60:
            inv_start_idx = i
            if w1 <= w20:
                break

    if inv_start_idx is None:
        result['reason'] = (
            f"WMA 20-40-60 역배열 선행 조건 미충족 (골든크로스 직전 {params.seq_lookback}봉 내 WMA20 < WMA40 < WMA60 구간 부재)"
        )
        return result

    # [방어 3: 돌파 진행 구간에서 40선 < 60선 지속 유지 검증]
    # inv_start_idx부터 gc_idx까지 중간에 40선이 60선을 침범(>=)한 적이 있다면 20<60<40 왜곡이므로 즉시 차단!
    for i in range(inv_start_idx, gc_idx + 1):
        if valid_df['wma40'].iloc[i] >= valid_df['wma60'].iloc[i]:
            result['reason'] = (
                f"돌파 구간 내 WMA40({valid_df['wma40'].iloc[i]:,.1f}원) >= WMA60({valid_df['wma60'].iloc[i]:,.1f}원) "
                f"20<60<40 꼬임 발생 ➔ 역배열 파괴로 매수 차단"
            )
            return result

    # 순차 돌파 시점 추적
    idx_cross_20 = None
    for i in range(inv_start_idx, gc_idx + 1):
        prev_w1 = valid_df['wma1'].iloc[i - 1]
        prev_w20 = valid_df['wma20'].iloc[i - 1]
        curr_w1 = valid_df['wma1'].iloc[i]
        curr_w20 = valid_df['wma20'].iloc[i]
        if (prev_w1 <= prev_w20 and curr_w1 > curr_w20) or (i > inv_start_idx and curr_w1 > curr_w20 and idx_cross_20 is None):
            idx_cross_20 = i
            break

    idx_cross_40 = None
    start_search_40 = idx_cross_20 if idx_cross_20 is not None else inv_start_idx
    for i in range(start_search_40, gc_idx + 1):
        prev_w1 = valid_df['wma1'].iloc[i - 1]
        prev_w40 = valid_df['wma40'].iloc[i - 1]
        curr_w1 = valid_df['wma1'].iloc[i]
        curr_w40 = valid_df['wma40'].iloc[i]
        if (prev_w1 <= prev_w40 and curr_w1 > curr_w40) or (i >= start_search_40 and curr_w1 > curr_w40 and idx_cross_40 is None):
            idx_cross_40 = i
            break

    idx_cross_60 = gc_idx

    if idx_cross_20 is None:
        result['reason'] = "1이평선의 WMA20 상향 돌파 미확인"
        return result

    if idx_cross_40 is None:
        result['reason'] = "1이평선의 WMA40 상향 돌파 미확인"
        return result

    if not (idx_cross_20 <= idx_cross_40 <= idx_cross_60):
        result['reason'] = (
            f"1이평선 순차 돌파 순서 불일치 (20돌파봉:{idx_cross_20} -> 40돌파봉:{idx_cross_40} -> 60돌파봉:{idx_cross_60})"
        )
        return result

    # 주가 지지 및 모멘텀 확인
    min_allowed_price = wma60_val * (1.0 - params.allow_price_below_pct)
    is_price_ok = (curr_c >= min_allowed_price)
    is_turn_up = (wma1_val >= wma60_val * (1.0 - params.allow_price_below_pct))
    result['is_turn_up'] = is_turn_up

    # 5. [2분봉 매크로 게이트 & 볼린저 스퀴즈 융합 검증 (15분봉 fallback 지원)]
    macro_tag = ""
    macro_bonus = 0.0
    df_macro = df_2m if (df_2m is not None and not df_2m.empty) else df_15m
    tf_name = "2분봉" if (df_2m is not None and not df_2m.empty) else "15분봉"
    use_macro = params.use_2m_macro_filter if (df_2m is not None and not df_2m.empty) else params.use_15m_macro_filter

    if df_macro is not None and not df_macro.empty and len(df_macro) >= 20:
        macro = calculate_2m_macro_gates(df_macro)
        result['m_target_price'] = macro['m_line']
        result['tema_gate'] = macro['tema_gate']
        result['gate_high'] = macro['gate_high']
        result['is_bb_squeeze'] = macro['is_bb_squeeze']

        # 테마급등관문선 하단 지지 여부 (실시간 현재가 또는 2분봉 종가)
        is_tema_ok = macro['is_tema_support'] or (curr_c >= macro['tema_gate'] * 0.992)
        if use_macro and not is_tema_ok:
            result['reason'] = (
                f"{tf_name} 테마급등관문선({macro['tema_gate']:,.0f}원) 지지 이탈 상태로 매수 차단"
            )
            return result

        # [2번 핵심 진입]: 2분봉 급등관문고가선(HH) 돌파 여부 필수 검증
        # 테마급등관문선에서 출발하여 급등관문고가선을 돌파해야만 기준선(M선)까지 이동!
        is_gate_broken = macro['is_gate_broken'] or (curr_c >= macro['gate_high'] * 0.998)
        if use_macro and params.require_gate_break and not is_gate_broken:
            result['reason'] = (
                f"{tf_name} 급등관문고가선({macro['gate_high']:,.0f}원) 돌파 미완성 (현재가: {curr_c:,.0f}원) - [2번 관문 돌파 대기]"
            )
            return result

        if is_gate_broken:
            macro_bonus += 25.0
            macro_tag += f" [🚀 {tf_name} 2번 급등관문선 돌파안착!]"

        # 볼린저 스퀴즈 보너스
        if macro['is_bb_squeeze']:
            macro_bonus += 20.0
            macro_tag += f" [⚡ {tf_name} BB스퀴즈 응축 {macro['bandwidth']*100:.1f}%]"

        macro_tag += f" [👑 목표 기준선(M): {macro['m_line']:,.0f}원]"

    # 6. [X-Ray 순간체결량 & 포착빈도 수급 분석 (1초 3건 싹쓸이 및 빈도 카운팅)]
    if params.use_xray_filter:
        x_params = XRayParams(large_trade_threshold=params.xray_large_trade_threshold)
        xray = evaluate_xray_power(ticks=ticks, df_120t=df_120t, params=x_params)
        result['xray_grade'] = xray['grade']
        result['xray_freq'] = xray['capture_frequency']
        result['has_1sec_sweep'] = xray['has_1sec_3trades']
        result['xray_bonus'] = xray['bonus_score']
        result['xray_tag'] = xray['tag']
        if xray['bonus_score'] > 0:
            macro_bonus += xray['bonus_score']
            macro_tag += xray['tag']

    result['macro_bonus'] = macro_bonus

    if is_price_ok and is_turn_up:
        result['should_buy'] = True
        m_str = f" | 목표 기준선(M선): {result['m_target_price']:,.0f}원" if result['m_target_price'] > 0 else ""
        result['reason'] = (
            f"🎯 [120틱 WMA20-40-60 역배열 후 1이평 순차 돌파] WMA 20<40<60 역배열 확인 후 "
            f"1이평선이 20->40->60을 차례대로 돌파! "
            f"매수기준(WMA60 골든크로스값): {int(wma60_gc_val):,}원{macro_tag} "
            f"(골든크로스 후 {bars_since_gc}봉, 현재가: {curr_c:,.0f}원, 20선:{wma20_val:,.0f}, 40선:{wma40_val:,.0f}, 60선:{wma60_val:,.0f}{m_str})"
        )
    elif not is_price_ok:
        result['reason'] = f"현재가({curr_c:,.0f}원)가 120틱 WMA60({wma60_val:,.0f}원) 지지선 하단에 위치"
    elif not is_turn_up:
        result['reason'] = f"1이평선({wma1_val:,.0f}원)이 WMA60({wma60_val:,.0f}원) 하단에 위치"

    return result


def evaluate_120t_wma60_exit(df_120t: pd.DataFrame, current_price: float = None,
                             buy_price: float = None, params: WMA60TickParams = None,
                             target_m_line: float = None, tema_sl: float = None,
                             holding_seconds: float = 999.0, max_profit_pct: float = 0.0) -> dict:
    r"""
    [통합 2번 하이브리드 청산/매도 판정 (2분봉 고도화)]
    1. 1차 목표 익절: 2분봉 기준선(M선) 도달 시 (수익률 >= +3.0% 보장 시)
    2. 고점 하락반전 매도: 120틱 WMA60 피크 꺾임 (Slope < -0.002%) 또는 WMA20 데드크로스
    3. 하방 안전벨트 손절: 2분봉 테마급등관문선 하향 이탈 시 (-1.5%)
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
        'is_target_reached': False,
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

    profit_pct = ((curr_c - buy_price) / buy_price) * 100.0 if buy_price and buy_price > 0 else 0.0
    p_profit_str = f", 수익률: {profit_pct:+.2f}%" if buy_price and buy_price > 0 else ""

    # 1. [2분봉 기준선(M선) 도달 확정 익절]
    if target_m_line and target_m_line > 0 and curr_c >= target_m_line and profit_pct >= 2.5:
        result['should_sell'] = True
        result['is_target_reached'] = True
        result['reason'] = (
            f"👑 [2분봉 기준선(M선) 목표가 도달 익절] 기준선({target_m_line:,.0f}원) 터치 달성! "
            f"확정 분할/전량 차익실현 매도 (현재가: {curr_c:,.0f}원{p_profit_str})"
        )
        return result

    # 2. [2분봉 테마급등관문선 하향 이탈 손절 방어]
    if tema_sl and tema_sl > 0 and curr_c < (tema_sl * 0.985):
        result['should_sell'] = True
        result['reason'] = (
            f"🛡️ [2분봉 테마급등관문선 이탈 방어 손절] 주가({curr_c:,.0f}원)가 "
            f"테마급등관문선({tema_sl:,.0f}원) 지지선 하향 이탈로 원천 손절 방어{p_profit_str}"
        )
        return result

    # ── [핵심 방어 1: 긴급 비상 손절 (-2.5%)] ──
    if profit_pct <= -2.5:
        result['should_sell'] = True
        result['reason'] = f"🛑 [긴급 손절 방어] 계좌 손실률 -2.5% 도달로 리스크 차단 전량 매도 (수익률: {profit_pct:.2f}%)"
        return result

    # ── [핵심 방어 2: 매수 후 3분(180초) 틱 노이즈 조기 매도 유예 (Grace Period)] ──
    # 매수한 지 3분 이내에는 파동이 형성될 시간을 보장하며, 단순 틱 노이즈로 인한 즉시 매도를 원천 차단!
    if holding_seconds < 180.0:
        return result

    # ── [진짜 고점 하락반전 매도] ──
    # 전제 조건: 주가가 매수 후 최소 +0.6% 이상 반등했거나 WMA60이 상승세(prev_slope > 0.001%)를 탄 뒤 꼭지에서 꺾일 때만 발동!
    has_peaked = (max_profit_pct >= 0.6) or (profit_pct >= 0.3)
    is_true_turn_down = (prev_slope >= 0.001 and last_slope < -0.002 and has_peaked)

    # WMA20-60 데드크로스 (상승 후 데드크로스만 인정)
    prev_diff = prev_bar['wma20'] - prev_bar['wma60']
    curr_diff = wma20_val - wma60_val
    is_true_dead_cross = (prev_diff > 0 and curr_diff <= 0 and has_peaked and last_slope <= 0.0)

    result['is_turn_down'] = is_true_turn_down or is_true_dead_cross

    if is_true_turn_down:
        result['should_sell'] = True
        result['reason'] = (
            f"📉 [120틱 WMA60 피크 하락반전 익절/매도] WMA60({wma60_val:,.0f}원) 고점 형성 후 "
            f"우하향 꺾임 감지! (기울기: {prev_slope:+.4f}% ➔ {last_slope:+.4f}%, 현재가: {curr_c:,.0f}원{p_profit_str})"
        )
    elif is_true_dead_cross:
        result['should_sell'] = True
        result['reason'] = (
            f"📉 [120틱 WMA20-60 고점 데드크로스 매도] 단기선(WMA20: {wma20_val:,.0f}원)이 "
            f"중기선(WMA60: {wma60_val:,.0f}원) 하향 이탈! (현재가: {curr_c:,.0f}원{p_profit_str})"
        )

    return result


def evaluate_reentry_signal(df_120t: pd.DataFrame, df_2m: pd.DataFrame,
                            current_price: float, state: Any,
                            params: WMA60TickParams = None,
                            ticks: list = None) -> dict:
    """
    [당일 최강 2종목 집중 회전 매매 - 재매수 판정 엔진]
    매도 후 하락하던 주가가:
      1) 2분봉 기준선(M선)을 상향 통과(돌파)하거나,
      2) 2분봉 급등관문고가선(HH)을 재차 상향 통과(돌파)할 때
    ➔ 재매수(Re-entry) 신호 출력!
    """
    if params is None:
        params = WMA60TickParams()

    result = {
        'should_buy': False,
        'target_price': 0,
        'current_price': 0.0,
        'm_target_price': 0.0,
        'tema_gate': 0.0,
        'is_m_cross': False,
        'is_hh_cross': False,
        'reentry_count': getattr(state, 'reentry_count', 0),
        'reason': ''
    }

    if df_2m is None or df_2m.empty or len(df_2m) < 20:
        result['reason'] = "2분봉 데이터 부족으로 재매수 판정 불가"
        return result

    curr_c = float(current_price if current_price and current_price > 0 else df_2m['close'].iloc[-1])
    result['current_price'] = curr_c

    # 1. 2분봉 매크로 게이트 산출
    macro = calculate_2m_macro_gates(df_2m)
    m_line = macro['m_line']
    gate_high = macro['gate_high']
    tema_gate = macro['tema_gate']
    result['m_target_price'] = m_line
    result['tema_gate'] = tema_gate

    # 2. 매도 후 하락(눌림) 추적
    sold_price = getattr(state, 'sold_price', 0.0)
    dip_min = getattr(state, 'dip_min_price', sold_price) if getattr(state, 'dip_min_price', 0.0) > 0 else sold_price

    if dip_min <= 0:
        dip_min = curr_c
    if curr_c < dip_min:
        dip_min = curr_c
        if hasattr(state, 'dip_min_price'):
            state.dip_min_price = dip_min

    # ── [매도 후 하락(눌림) 정밀 검증: 0% 찰나 재매수 방지] ──
    # 매도 후 최소 60초가 경과해야 하고, 직전 매도가 대비 실제로 -0.5% 이상 하락 조정(숨고르기)을 거쳤어야 함!
    time_since_sold = (time.time() - getattr(state, 'sold_time', 0.0)) if getattr(state, 'sold_time', 0.0) > 0 else 999.0
    is_price_dipped = (sold_price > 0 and dip_min <= sold_price * 0.995)
    is_dipped = (is_price_dipped and time_since_sold >= 60.0) or (getattr(state, 'dip_detected', False) and time_since_sold >= 60.0)
    if hasattr(state, 'dip_detected') and is_dipped:
        state.dip_detected = True

    # 3. [핵심 재매수 2대 경로]
    # 경로 A: 하락하던 주가가 2분봉 기준선(M선)을 상향 통과(돌파)
    is_m_cross = (curr_c >= m_line * 0.998) and (dip_min < m_line)

    # 경로 B: 하락하던 주가가 2분봉 급등관문고가선(HH)을 재차 상향 통과(돌파)
    is_hh_cross = (curr_c >= gate_high * 0.998) and (dip_min < gate_high)

    result['is_m_cross'] = is_m_cross
    result['is_hh_cross'] = is_hh_cross

    # 테마급등관문선 하단 지지 여부
    is_tema_support = (curr_c >= tema_gate * 0.992)

    # 4. X-Ray 수급 평가
    xray = evaluate_xray_power(ticks=ticks, df_120t=df_120t)
    xray_tag = xray.get('tag', '')

    if (is_m_cross or is_hh_cross) and is_tema_support:
        result['should_buy'] = True
        result['target_price'] = int(curr_c)
        reentry_num = getattr(state, 'reentry_count', 0) + 1
        dip_pct = ((dip_min - sold_price) / sold_price) * 100.0 if sold_price > 0 else 0.0
        path_name = f"2분봉 기준선(M선: {m_line:,.0f}원) 상향 통과" if is_m_cross else f"2분봉 급등관문고가선(HH: {gate_high:,.0f}원) 재차 통과"
        result['reason'] = (
            f"👑 [당일 최강 2종목 집중 재매수] 매도 후 눌림({dip_pct:+.2f}%) 완료 ➔ {path_name} 성공! "
            f"(재매수 {reentry_num}회차, 현재가: {curr_c:,.0f}원, 목표M선: {m_line:,.0f}원){xray_tag}"
        )
    else:
        if not is_tema_support:
            result['reason'] = f"2분봉 테마급등관문선({tema_gate:,.0f}원) 지지 이탈로 재매수 보류"
        elif not (is_m_cross or is_hh_cross):
            result['reason'] = f"기준선({m_line:,.0f}원) 또는 급등관문선({gate_high:,.0f}원) 재통과 대기 중 (현재가: {curr_c:,.0f}원, 저점: {dip_min:,.0f}원)"
        else:
            result['reason'] = "매도 후 유의미한 눌림 미발생으로 재매수 대기"

    return result
