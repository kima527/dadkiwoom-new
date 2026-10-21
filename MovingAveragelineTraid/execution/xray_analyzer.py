"""
X-Ray 순간체결량 & 실시간 포착빈도 분석 엔진 (xray_analyzer.py)

기능:
  1. [1초 N건 호가 싹쓸이(Sweeping) 탐지]:
     - 동일 1초(동일 타임스탬프) 내에 대형 체결(2천만원~3천만원 이상)이 3건 이상 동시 다발로 터지거나,
     - 1초간 합산 체결금액이 5,000만원~1억원 이상인 세력의 시장가 싹쓸이 체결 포착.
  2. [포착빈도 상위 카운팅 (Rolling Capture Frequency)]:
     - 최근 틱 데이터 중 대형 체결(순매수)이 몇 번이나 누적 카운팅되었는지 산출.
     - 단발성 낚시 체결(1회)과 진짜 지속 주도 대장주(3회~5회 이상)를 명확히 분별.
  3. [매수/매도 방향성 판별]:
     - 호가 상향(Up-tick) 매수 체결 비중(기본 60% 이상)을 검증하여 세력의 투매(Down-tick 덤핑) 원천 배제.
  4. [120틱 고속 체결 속도(Velocity) 융합 지원]:
     - 1-tick 데이터와 120틱 캔들 체결 가속도를 상호 보완하여 최적의 수급 점수 산출.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class XRayParams:
    large_trade_threshold: float = 20_000_000.0    # 1회성 대량 체결 기준 (2,000만원)
    sweeping_count_threshold: int = 3              # 1초당 연속 체결 기준 (1초당 3건 이상)
    sweeping_amount_threshold: float = 50_000_000.0# 1초당 합산 싹쓸이 금액 (5,000만원)
    high_freq_threshold: int = 3                   # 포착빈도 상위 기준 (최근 3회 이상)
    min_buy_ratio: float = 0.60                    # 매수 체결(빨간색) 최소 비율 60%


def analyze_xray_ticks(ticks: List[Dict[str, Any]], params: XRayParams = None) -> Dict[str, Any]:
    """
    실시간 1-tick 체결 스트림을 분석하여 1초 3건 이상 싹쓸이 및 포착빈도 산출
    """
    if params is None:
        params = XRayParams()

    res = {
        'is_xray_strong': False,
        'has_1sec_3trades': False,
        'max_trades_per_sec': 0,
        'max_amount_per_sec': 0.0,
        'capture_frequency': 0,
        'large_buy_count': 0,
        'large_sell_count': 0,
        'total_large_amount': 0.0,
        'buy_ratio': 1.0,
        'grade': 'C',
        'bonus_score': 0.0,
        'tag': '',
        'reason': ''
    }

    if not ticks or len(ticks) < 2:
        return res

    sec_groups: Dict[str, List[Dict[str, Any]]] = {}
    prev_price = None
    buy_amount_total = 0.0
    sell_amount_total = 0.0

    for t in ticks:
        p = float(t.get('close', t.get('price', 0)))
        v = float(t.get('volume', 0))
        amt = p * v
        # 시간 문자열: 초 단위(19자) 추출
        tm = str(t.get('time', ''))[:19]

        # 매수(Up-tick) / 매도(Down-tick) 판정
        is_buy = True
        if prev_price is not None:
            if p < prev_price:
                is_buy = False
            elif p > prev_price:
                is_buy = True
            else:
                is_buy = True  # 호가 유지 매수
        prev_price = p

        if is_buy:
            buy_amount_total += amt
        else:
            sell_amount_total += amt

        is_large = (amt >= params.large_trade_threshold)
        if is_large:
            if is_buy:
                res['large_buy_count'] += 1
            else:
                res['large_sell_count'] += 1
            res['total_large_amount'] += amt

        if tm not in sec_groups:
            sec_groups[tm] = []
        sec_groups[tm].append({
            'price': p, 'volume': v, 'amount': amt, 'is_buy': is_buy, 'is_large': is_large
        })

    tot_amt = buy_amount_total + sell_amount_total
    res['buy_ratio'] = round(buy_amount_total / tot_amt, 2) if tot_amt > 0 else 1.0
    res['capture_frequency'] = res['large_buy_count']  # 포착빈도 = 대형 순매수 체결 횟수

    # 1초당 대형 체결 밀도 분석 (호가 싹쓸이 Sweeping 감지)
    max_trades_sec = 0
    max_amt_sec = 0.0
    has_1sec_sweep = False

    for sec_tm, items in sec_groups.items():
        large_in_sec = sum(1 for it in items if it['is_large'] and it['is_buy'])
        amt_in_sec = sum(it['amount'] for it in items if it['is_buy'])
        count_in_sec = len(items)

        if count_in_sec > max_trades_sec:
            max_trades_sec = count_in_sec
        if amt_in_sec > max_amt_sec:
            max_amt_sec = amt_in_sec

        if (large_in_sec >= params.sweeping_count_threshold) or (
            count_in_sec >= 3 and amt_in_sec >= params.sweeping_amount_threshold
        ):
            has_1sec_sweep = True

    res['max_trades_per_sec'] = max_trades_sec
    res['max_amount_per_sec'] = round(max_amt_sec, 0)
    res['has_1sec_3trades'] = has_1sec_sweep

    # 등급(Grade) 및 보너스 점수 결정
    if has_1sec_sweep or (res['capture_frequency'] >= 4 and res['buy_ratio'] >= params.min_buy_ratio):
        res['is_xray_strong'] = True
        res['grade'] = 'S'
        res['bonus_score'] = 40.0
        amt_str = f"{max_amt_sec/1e7:.1f}천만" if max_amt_sec > 0 else f"{res['total_large_amount']/1e7:.1f}천만"
        res['tag'] = f" [🔥 X-Ray S급: 1초 {max_trades_sec}건 싹쓸이 / 순간 {amt_str} / 포착빈도 {res['capture_frequency']}회]"
        res['reason'] = f"X-Ray 세력 싹쓸이 폭발 (1초 {max_trades_sec}건, 포착빈도 {res['capture_frequency']}회, 매수비율 {res['buy_ratio']*100:.0f}%)"
    elif res['capture_frequency'] >= params.high_freq_threshold and res['buy_ratio'] >= params.min_buy_ratio:
        res['is_xray_strong'] = True
        res['grade'] = 'A'
        res['bonus_score'] = 25.0
        res['tag'] = f" [⚡ X-Ray A급: 포착빈도 {res['capture_frequency']}회 / 대형유입 {res['total_large_amount']/1e7:.1f}천만]"
        res['reason'] = f"X-Ray 대형체결 포착빈도 상위 ({res['capture_frequency']}회 포착)"
    elif res['capture_frequency'] >= 1:
        res['grade'] = 'B'
        res['bonus_score'] = 10.0
        res['tag'] = f" [X-Ray B급: 대형체결 {res['capture_frequency']}회]"
        res['reason'] = f"X-Ray 대형체결 {res['capture_frequency']}회 포착"
    else:
        res['grade'] = 'C'
        res['bonus_score'] = 0.0
        res['reason'] = "X-Ray 대형체결 미발생 (일반 체결)"

    return res


def analyze_120t_xray_velocity(df_120t: pd.DataFrame, params: XRayParams = None) -> Dict[str, Any]:
    """
    120틱 캔들 데이터에서 체결 속도(Velocity) 및 대형 봉 분석 (1-tick 보조/대체)
    """
    if params is None:
        params = XRayParams()

    res = {
        'is_velocity_burst': False,
        'bar_amount': 0.0,
        'seconds_per_bar': 999.0,
        'velocity_score': 0.0,
        'tag': '',
        'reason': ''
    }

    if df_120t is None or len(df_120t) < 3:
        return res

    last_bar = df_120t.iloc[-1]
    prev_bar = df_120t.iloc[-2]

    c = float(last_bar['close'])
    o = float(last_bar.get('open', c))
    v = float(last_bar.get('volume', 0))
    amt = c * v
    res['bar_amount'] = amt

    # 120틱 완성 소요 시간 계산
    sec_diff = 30.0
    try:
        t_curr = pd.to_datetime(last_bar.name if isinstance(df_120t.index, pd.DatetimeIndex) else last_bar.get('time', None))
        t_prev = pd.to_datetime(prev_bar.name if isinstance(df_120t.index, pd.DatetimeIndex) else prev_bar.get('time', None))
        if pd.notnull(t_curr) and pd.notnull(t_prev):
            sec_diff = max(1.0, (t_curr - t_prev).total_seconds())
    except Exception:
        sec_diff = 30.0

    res['seconds_per_bar'] = round(sec_diff, 1)

    # 120틱(120건의 체결)이 10초 이내에 완성되고 거래대금이 3천만원 이상인 경우
    if sec_diff <= 10.0 and amt >= 30_000_000 and c >= o:
        res['is_velocity_burst'] = True
        res['velocity_score'] = 25.0
        res['tag'] = f" [🚀 120틱 초고속 체결 ({sec_diff:.0f}초 만에 120틱 돌파, {amt/1e7:.1f}천만 폭발)]"
        res['reason'] = f"120틱 초고속 수급 폭발 ({sec_diff:.0f}초 완성)"
    elif sec_diff <= 20.0 and amt >= 20_000_000 and c >= o:
        res['is_velocity_burst'] = True
        res['velocity_score'] = 15.0
        res['tag'] = f" [120틱 가속 체결 ({sec_diff:.0f}초, {amt/1e7:.1f}천만)]"
        res['reason'] = f"120틱 수급 가속 ({sec_diff:.0f}초 완성)"

    return res


def evaluate_xray_power(ticks: List[Dict[str, Any]] = None,
                        df_120t: pd.DataFrame = None,
                        params: XRayParams = None) -> Dict[str, Any]:
    """
    [X-Ray 마스터 평가기]
    1틱 데이터와 120틱 캔들 속도를 종합하여 최종 X-Ray 등급 및 가산점 산출
    """
    if params is None:
        params = XRayParams()

    # 1. 1-tick 데이터 기반 X-Ray 정밀 분석 (최우선)
    tick_res = analyze_xray_ticks(ticks, params=params) if ticks else None

    # 2. 120틱 봉 기반 속도 분석
    vel_res = analyze_120t_xray_velocity(df_120t, params=params) if df_120t is not None else None

    final_res = {
        'is_xray_strong': False,
        'has_1sec_3trades': False,
        'capture_frequency': 0,
        'grade': 'C',
        'bonus_score': 0.0,
        'tag': '',
        'reason': ''
    }

    if tick_res and tick_res['is_xray_strong']:
        final_res['is_xray_strong'] = True
        final_res['has_1sec_3trades'] = tick_res['has_1sec_3trades']
        final_res['capture_frequency'] = tick_res['capture_frequency']
        final_res['grade'] = tick_res['grade']
        final_res['bonus_score'] = tick_res['bonus_score']
        final_res['tag'] = tick_res['tag']
        final_res['reason'] = tick_res['reason']
    elif vel_res and vel_res['is_velocity_burst']:
        final_res['is_xray_strong'] = True
        final_res['grade'] = 'A' if vel_res['velocity_score'] >= 20 else 'B'
        final_res['bonus_score'] = vel_res['velocity_score']
        final_res['tag'] = vel_res['tag']
        final_res['reason'] = vel_res['reason']
    elif tick_res:
        final_res['capture_frequency'] = tick_res['capture_frequency']
        final_res['grade'] = tick_res['grade']
        final_res['bonus_score'] = tick_res['bonus_score']
        final_res['tag'] = tick_res['tag']
        final_res['reason'] = tick_res['reason']

    return final_res
