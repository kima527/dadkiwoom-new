"""
strategy_5d2v_surge_breakout.py
=============================================================================
5거래일 중 2회 이상 전일 대비 130% 거래량 폭증 ➔ 수급봉 최고가 상향 돌파 매수 전략 모듈

[매수 4대 핵심 조건]
1. 최근 5거래일(일봉/분봉) 내 전일 대비 130% 이상 거래량이 터진 수급봉이 2회 이상 발생 (Surge_Count >= 2)
2. 해당 5거래일 내 거래량 폭증 봉(들)의 최고가 레벨(Surge_High) 산출
3. 현재가(종가)가 수급 폭증 봉의 최고가(Surge_High)를 상향 돌파 (Close > Surge_High)
4. 체결강도 102% 이상 (ratio >= 1.02)
=============================================================================
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Surge5D2VParams:
    """5거래일 2회 거래량 130% 폭증 및 고가 돌파 매수 파라미터"""
    lookback_window: int = 5            # 수급 폭증 탐색 거래일 수 (최근 5봉)
    vol_surge_ratio: float = 1.30       # 전일 대비 거래량 폭증 비율 (130% = 1.30배)
    min_surge_count: int = 2            # 윈도우 내 최소 수급 폭증 회수 (2회 이상)
    min_trade_intensity: float = 1.02   # 실시간 체결강도 기준 (102% = 1.02)
    min_daily_volume: int = 100_000     # 최소 일봉 거래량 (10만 주 이상)


def evaluate_5d2v_surge_breakout(
    code: str,
    name: str,
    daily_df: pd.DataFrame,
    df_15m: Optional[pd.DataFrame] = None,
    current_price: Optional[float] = None,
    params: Optional[Surge5D2VParams] = None
) -> Dict[str, Any]:
    """
    최근 5거래일 중 2회 이상 전일 대비 130% 거래량 폭증 후 수급봉 최고가 돌파를 평가합니다.
    """
    if params is None:
        params = Surge5D2VParams()

    res = {
        "should_buy": False,
        "surge_high": 0.0,
        "surge_count": 0,
        "price": 0.0,
        "reason": "",
        "priority_score": 0.0
    }

    if daily_df is None or len(daily_df) < (params.lookback_window + 2):
        return res

    df = daily_df.copy()
    close_col = 'close' if 'close' in df.columns else 'Close'
    high_col = 'high' if 'high' in df.columns else 'High'
    vol_col = 'volume' if 'volume' in df.columns else 'Volume'

    # 전일 대비 거래량 비율 계산
    df['prev_vol'] = df[vol_col].shift(1)
    df['vol_ratio'] = df[vol_col] / df['prev_vol']

    # 수급 폭증 여부 (전일 대비 130% 이상)
    df['is_surge'] = df['vol_ratio'] >= params.vol_surge_ratio

    # 최근 N거래일(lookback_window) 윈도우 슬라이싱 (돌파 판단을 위해 당일 이전 N개봉 검사)
    # 당일봉이 현재 진행 중인 봉이면 직전 N봉 탐색
    recent_bars = df.iloc[-(params.lookback_window + 1):-1]
    
    surge_bars = recent_bars[recent_bars['is_surge']]
    surge_count = len(surge_bars)
    res["surge_count"] = surge_count

    if surge_count < params.min_surge_count:
        res["reason"] = f"최근 {params.lookback_window}거래일 내 130% 거래량 폭증 횟수 부족 ({surge_count}회 < {params.min_surge_count}회)"
        return res

    # 수급 폭증 봉들의 최고가 산출 (Surge_High)
    surge_high = float(surge_bars[high_col].max())
    res["surge_high"] = surge_high

    # 현재가 판별
    curr_p = float(current_price) if current_price and current_price > 0 else float(df[close_col].iloc[-1])
    res["price"] = curr_p
    res["target_price"] = surge_high

    # [핵심] 돌파하는 그 찰나(Golden Moment: 수급봉 최고가 대비 -0.2% ~ +0.8% 이내) 스나이핑
    # 이미 +0.8%를 초과하여 급등한 종목은 상투 추격 매수 방지를 위해 원천 차단!
    disp_pct = ((curr_p - surge_high) / surge_high) * 100.0
    is_breakout_moment = (surge_high * 0.998 <= curr_p <= surge_high * 1.008)

    if is_breakout_moment:
        priority_score = 370.0  # 👑 1.5순위 (370점)
        res["should_buy"] = True
        res["priority_score"] = priority_score
        res["target_price"] = surge_high  # 수급봉 최고가 지정가 매수!
        res["reason"] = (
            f"⚡ [5일 내 수급 2회 폭증 ➔ 돌파 찰나 스나이핑] 5일간 폭증 {surge_count}회 발생! "
            f"수급봉 최고가({surge_high:,.0f}원) 돌파 찰나 포착 (현재가: {curr_p:,.0f}원, 이격: {disp_pct:+.2f}%) ➔ "
            f"수급봉 최고가({surge_high:,.0f}원) 지정가 매수"
        )
    elif curr_p > surge_high * 1.008:
        res["reason"] = (
            f"⏭️ [돌파 찰나 경과] 수급봉 최고가({surge_high:,.0f}원) 대비 이미 +{disp_pct:.2f}% 급등하여 돌파 찰나 경과 (+0.8% 초과) ➔ 상투 추격 매수 방지"
        )
    else:
        res["reason"] = (
            f"👀 [수급 폭증후 돌파 대기] 5일간 130% 폭증 {surge_count}회 완료! "
            f"수급봉 최고가({surge_high:,.0f}원) 미돌파 (현재가: {curr_p:,.0f}원, 이격: {disp_pct:+.2f}%)"
        )

    return res


if __name__ == "__main__":
    # 간단 테스트
    dates = pd.date_range("2026-09-01", periods=10)
    # 2일차: 거래량 130% 폭증, 4일차: 거래량 130% 폭증 인위적 생성
    test_data = pd.DataFrame({
        'open': [10000, 10200, 10500, 10800, 11000, 10900, 11200, 11500, 11400, 12200],
        'high': [10300, 10600, 10800, 11200, 11300, 11100, 11500, 11800, 11600, 12500],
        'low':  [9900,  10100, 10400, 10600, 10800, 10700, 11000, 11300, 11200, 12000],
        'close':[10200, 10500, 10700, 11000, 11100, 10800, 11400, 11600, 11500, 12300],
        'volume': [10000, 14000, 12000, 18000, 15000, 13000, 14000, 15000, 14000, 20000]
    }, index=dates)

    eval_res = evaluate_5d2v_surge_breakout("005930", "삼성전자", test_data)
    print("Test Result:", eval_res)
