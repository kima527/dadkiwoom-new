"""
strategy_15m_4formula_buy.py
=============================================================================
15분봉 기반 4대 수식 완성 종목 전용 매수 전략 모듈

[4대 필수 조건]
1. 15분봉 수급 폭발봉:
   - 15분봉 거래대금(수급) >= 20억원
   - 양봉 (Open < Close)
   - 강한 몸통 (Close - Open > (High - Close) * 1.2)
   - 직전 2개봉 평균 거래대금 대비 3배 이상 폭증
2. 황룡선 / 룡선(TEMA) 및 M선(정배열 피크 저항선) 완성 & 수급 충족:
   - SMA 5-20-60 정배열 고점선 (M선) 및 TEMA 5-20-60 정배열 고점선 (M1선)
3. 1-20-60 정배열 첫 전환:
   - 현재봉: 1이평(종가) > 20이평 > 60이평
   - 직전봉: 1-20-60 정배열 미충족 (오늘 첫 정배열 완성)
4. M선 상향 돌파 (CrossUp):
   - 1-20-60 첫 정배열 전환과 동시에 현재가(1이평)가 M선(직전 정배열 피크 저항선)을 상향 돌파

=> 위 4가지 조건이 '동시에 완성'된 종목만을 최종 매수(Buy) 대상으로 판정
=============================================================================
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Formula4Params:
    """15분봉 4대 수식 매수 파라미터"""
    min_supply_money: float = 20.0        # 15분봉 최소 수급(거래대금) (기본 20억원)
    body_tail_ratio: float = 1.2          # 캔들 몸통 / 윗꼬리 비율 (기본 1.2배 이상)
    supply_surge_multiplier: float = 3.0  # 직전 2개봉 평균 수급 대비 폭증 배수 (기본 3.0배)
    supply_ma20_multiplier: float = 5.0   # 20봉 평균 수급 대비 폭증 배수 (5배: A >= AvgA * 5)
    max_bar_gain_pct: float = 7.5         # 단일 15분봉 종가 상승률 상한선 (7.5% 초과 과열 급등봉 추격 금지)
    max_spread_pct: float = 8.0           # 단일 15분봉 (고가-저가) 변동 편차 상한선 (8.0% 초과 롤러코스터 휩소봉 배제)
    sma_fast: int = 1                     # 단기 이평 (1 = 종가)
    sma_mid: int = 20                     # 중기 이평 (20)
    sma_long: int = 60                    # 장기 이평 (60)
    sma_hwang: int = 5                    # 황룡선 기준 이평 (5)


def calculate_tema(series: pd.Series, period: int) -> pd.Series:
    """
    삼중지수이동평균 (TEMA - Triple Exponential Moving Average)
    TEMA = 3*EMA1 - 3*EMA2 + EMA3
    """
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return 3.0 * ema1 - 3.0 * ema2 + ema3


def calculate_m_lines(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    [수식 2 & 4] M선(SMA 기반 피크 저항선), 황룡선, M1선(TEMA 기반 피크 저항선), 룡선 계산
    - a = avg(c,5); b = avg(c,20); d = avg(c,60);
    - K = valuewhen(1, a>b && b>d && a>d, C);
    - M = valuewhen(1, K(2)<K(1) && K(1)>K, K(1));
    - 황룡선 = valuewhen(1, crossup(a, M), a);
    """
    close = df['close']
    a = close.rolling(5, min_periods=5).mean()
    b = close.rolling(20, min_periods=20).mean()
    d = close.rolling(60, min_periods=60).mean()

    # SMA 5-20-60 정배열
    cond_align_sma = (a > b) & (b > d) & (a > d)
    k_sma = close.where(cond_align_sma).ffill()
    
    # 국소 고점 (Peak): K(2) < K(1) and K(1) > K
    k_shift1 = k_sma.shift(1)
    k_shift2 = k_sma.shift(2)
    cond_peak_sma = (k_shift1 > k_shift2) & (k_shift1 > k_sma)
    m_line = k_shift1.where(cond_peak_sma).ffill()

    # 황룡선 = valuewhen(1, crossup(a, M), a)
    crossup_hwang = (a.shift(1) <= m_line.shift(1)) & (a > m_line)
    hwangryong = a.where(crossup_hwang).ffill()

    # TEMA 5, 20, 60
    e = calculate_tema(close, 5)
    f = calculate_tema(close, 20)
    g = calculate_tema(close, 60)

    cond_align_tema = (e > f) & (f > g) & (e > g)
    k_tema = close.where(cond_align_tema).ffill()
    
    k1_shift1 = k_tema.shift(1)
    k1_shift2 = k_tema.shift(2)
    cond_peak_tema = (k1_shift1 > k1_shift2) & (k1_shift1 > k_tema)
    m1_line = k1_shift1.where(cond_peak_tema).ffill()

    crossup_ryong = (a.shift(1) <= m1_line.shift(1)) & (a > m1_line)
    ryong = a.where(crossup_ryong).ffill()

    return m_line, hwangryong, m1_line, ryong


def analyze_15m_4formulas(
    df_15m: pd.DataFrame,
    params: Optional[Formula4Params] = None
) -> pd.DataFrame:
    """
    15분봉 데이터프레임에 대해 4대 수식 완성 여부를 시계열로 계산
    """
    if params is None:
        params = Formula4Params()

    if df_15m is None or df_15m.empty or len(df_15m) < 60:
        return pd.DataFrame()

    df = df_15m.copy()
    df.rename(columns={col: col.lower() for col in df.columns}, inplace=True)

    # ─────────────────────────────────────────────────────────────
    # [수식 1] 15분봉 수급 및 캔들 파워 계산
    # 수급 = (H+L+O+C)/4 * V / 100,000,000
    # ─────────────────────────────────────────────────────────────
    df['supply'] = (df['high'] + df['low'] + df['open'] + df['close']) / 4.0 * df['volume'] / 1e8
    
    # 1. 수급 >= 20억
    cond_supply_20 = df['supply'] >= params.min_supply_money
    
    # 2. 20봉 평균 수급 대비 5배 이상 (A >= AvgA * 5)
    df['supply_ma20'] = df['supply'].rolling(20, min_periods=1).mean()
    cond_supply_5x_ma20 = df['supply'] >= (df['supply_ma20'] * params.supply_ma20_multiplier)

    # 3. 양봉 (o < c)
    cond_bull = df['close'] > df['open']
    
    # 4. 몸통 > 윗꼬리 * 1.2 (c - o > (h - c) * 1.2)
    body = df['close'] - df['open']
    upper_tail = (df['high'] - df['close']).clip(lower=0)
    cond_strong_body = body > (upper_tail * params.body_tail_ratio)
    
    # 5. 수급 >= (수급(1) + 수급(2)) / 2 * 3
    prev_2_supply_avg = (df['supply'].shift(1) + df['supply'].shift(2)) / 2.0
    prev_2_supply_avg = prev_2_supply_avg.replace(0, np.nan).fillna(df['supply'].rolling(5).mean())
    cond_supply_surge = df['supply'] >= (prev_2_supply_avg * params.supply_surge_multiplier)

    # 6. 단일 15분봉 내 과열/8% 급등락 롤러코스터 방어 필터
    candle_gain_pct = (df['close'] - df['open']) / df['open'] * 100.0
    candle_spread_pct = (df['high'] - df['low']) / df['open'] * 100.0
    cond_not_overheated = (candle_gain_pct <= params.max_bar_gain_pct) & (candle_spread_pct <= params.max_spread_pct)

    df['cond_1_supply_candle'] = (
        cond_supply_20 & cond_supply_5x_ma20 & cond_bull & 
        cond_strong_body & cond_supply_surge & cond_not_overheated
    )

    # ─────────────────────────────────────────────────────────────
    # [수식 2] M선, 황룡선, M1선, 룡선 계산
    # ─────────────────────────────────────────────────────────────
    m_line, hwangryong, m1_line, ryong = calculate_m_lines(df)
    df['m_line'] = m_line
    df['hwangryong'] = hwangryong
    df['m1_line'] = m1_line
    df['ryong'] = ryong
    
    # 수식 2의 수급 조건 (수식 1과 동일)
    df['cond_2_hwang_ryong_supply'] = df['cond_1_supply_candle'] & df['m_line'].notna()

    # ─────────────────────────────────────────────────────────────
    # [수식 3] 1-20-60 정배열 첫 완성 (오늘 첫 전환)
    # A = ma(C, 1); B = ma(C, 20); D = ma(C, 60);
    # 조건오늘 = A > B && B > D;
    # 조건어제 = A(1) > B(1) && B(1) > D(1);
    # 조건오늘 && !조건어제
    # ─────────────────────────────────────────────────────────────
    df['ma1'] = df['close']  # ma(C, 1) = 현재 종가
    df['ma20'] = df['close'].rolling(20, min_periods=20).mean()
    df['ma60'] = df['close'].rolling(60, min_periods=60).mean()

    cond_align_today = (df['ma1'] > df['ma20']) & (df['ma20'] > df['ma60'])
    cond_align_prev = (df['ma1'].shift(1) > df['ma20'].shift(1)) & (df['ma20'].shift(1) > df['ma60'].shift(1))
    
    df['cond_3_align_first_bar'] = cond_align_today & (~cond_align_prev)

    # ─────────────────────────────────────────────────────────────
    # [수식 4] 1-20-60 첫 정배열 완성 & M선 상향 돌파 (CrossUp(a, M))
    # A오늘 && !A어제 && crossup(a, M)
    # ─────────────────────────────────────────────────────────────
    # a = ma(C, 1) = close
    crossup_a_m = (df['ma1'].shift(1) <= df['m_line'].shift(1)) & (df['ma1'] > df['m_line'])
    df['cond_4_align_and_m_breakout'] = df['cond_3_align_first_bar'] & crossup_a_m

    # ═════════════════════════════════════════════════════════════
    # 🎯 최종 4가지 수식 '동시 완성' 매수 시그널
    # ═════════════════════════════════════════════════════════════
    df['buy_signal_all_4'] = (
        df['cond_1_supply_candle'] & 
        df['cond_2_hwang_ryong_supply'] & 
        df['cond_3_align_first_bar'] & 
        df['cond_4_align_and_m_breakout']
    )

    return df


def evaluate_4formula_buy(
    code: str,
    name: str,
    df_15m: pd.DataFrame,
    current_price: Optional[float] = None,
    params: Optional[Formula4Params] = None
) -> Dict[str, Any]:
    """
    실시간 단일 종목 15분봉 4대 수식 완성 여부 최종 검증 및 매수 주문 정보 생성
    """
    result = {
        "code": code,
        "name": name,
        "should_buy": False,
        "price": 0.0,
        "reason": "",
        "details": {}
    }

    df_res = analyze_15m_4formulas(df_15m, params)
    if df_res.empty:
        result["reason"] = "15분봉 데이터 부족 (최소 60봉 필요)"
        return result

    latest = df_res.iloc[-1]
    curr_p = float(current_price) if current_price and current_price > 0 else float(latest['close'])

    c1 = bool(latest['cond_1_supply_candle'])
    c2 = bool(latest['cond_2_hwang_ryong_supply'])
    c3 = bool(latest['cond_3_align_first_bar'])
    c4 = bool(latest['cond_4_align_and_m_breakout'])
    is_buy = bool(latest['buy_signal_all_4'])

    result["details"] = {
        "수식1_수급_캔들완성": c1,
        "수식2_황룡선_수급": c2,
        "수식3_1_20_60_첫정배열": c3,
        "수식4_M선_상향돌파": c4,
        "당봉수급_억원": round(float(latest['supply']), 2),
        "현재가": curr_p,
        "M선_저항가": round(float(latest['m_line']), 2) if pd.notna(latest['m_line']) else 0.0,
        "20이평": round(float(latest['ma20']), 2) if pd.notna(latest['ma20']) else 0.0,
        "60이평": round(float(latest['ma60']), 2) if pd.notna(latest['ma60']) else 0.0,
    }

    if is_buy:
        result["should_buy"] = True
        result["price"] = curr_p
        result["reason"] = (
            f"🎯 [4대 수식 100% 동시 완성] "
            f"15분봉 수급폭증({latest['supply']:.1f}억) + "
            f"1-20-60 첫정배열 전환 + "
            f"M선({latest['m_line']:,.0f}원) 골든크로스 돌파"
        )
        logger.info(f"🚀 [{code} {name}] 매수 신호 포착! {result['reason']}")
    else:
        # 미달성 사유 요약
        missing = []
        if not c1:
            missing.append("수식1(수급/양봉몸통)")
        if not c3:
            missing.append("수식3(1-20-60 첫정배열)")
        if not c4:
            missing.append("수식4(M선 돌파)")
        result["reason"] = f"미충족 조건: {', '.join(missing)}" if missing else "조건 미달"

    return result
