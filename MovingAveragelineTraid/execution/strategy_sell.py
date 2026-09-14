"""
strategy_sell.py - 15분봉 기반 통합 매도 전략
===========================================================================

[통합 매도 로직]
1. [절대적 매도 조건 - 원금 보호]:
   - 매수가 대비 -2.0% 이하 도달 시 (현재가 <= 매수가 * 0.98), 수익 여부와 무관하게 즉시 전량 매도.

2. [수익 중 M선 돌파 여부 확인 및 실패 시 전량 매도]:
   - 계좌가 수익 중(현재가 > 매수가)일 때, 정배열 국소 고점선인 M선 돌파 여부를 실시간 감시.
   - M선 산출 공식:
     a = avg(c, 5); b = avg(c, 20); d = avg(c, 60);
     K = valuewhen(1, a > b && b > d && a > d, C);
     M = valuewhen(1, K(2) < K(1) && K(1) > K, K(1));
   - 돌파 실패 조건:
     1) 현재가가 M선 저항(99% 이상) 부근에 도달한 후 돌파하지 못하고 하락 꺾임 발생 (고점 대비 -1.5% 이상 하락 또는 M선의 98.5% 하회)
     2) 또는 M선 저항선 하향 재이탈 발생 시 전량 매도하여 수익 100% 확정.

3. [전일 상한가 종목 익일 시가 이탈]:
   - 전일 상한가 종목이 익일 당일 시가 대비 -2% 이탈 시 전량 매도.

4. [15분봉 SMA5/SMA40 데드크로스]:
   - 15분봉 SMA5가 SMA40을 하향 돌파(CrossDown) 시 전량 매도.

사용 데이터: 15분봉 (및 일봉)
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# M선 (정배열 국소 고점 저항선) 계산 헬퍼
# ═══════════════════════════════════════════════════════════════
def calculate_m_line_series(df: pd.DataFrame) -> pd.Series:
    """
    [M선 계산 수식]
    a = avg(c, 5); b = avg(c, 20); d = avg(c, 60);
    K = valuewhen(1, a > b && b > d && a > d, C);
    M = valuewhen(1, K(2) < K(1) && K(1) > K, K(1));
    """
    if df is None or df.empty or len(df) < 20 or 'close' not in df.columns:
        return pd.Series([np.nan] * (len(df) if df is not None else 0))

    close = df['close']
    a = close.rolling(5, min_periods=5).mean()
    b = close.rolling(20, min_periods=20).mean()
    d = close.rolling(60, min_periods=60).mean()

    # 정배열 조건 (a > b && b > d && a > d)
    cond_align = (a > b) & (b > d) & (a > d)
    k_series = close.where(cond_align).ffill()

    # 국소 고점 (Peak): K(2) < K(1) && K(1) > K
    k_shift1 = k_series.shift(1)
    k_shift2 = k_series.shift(2)
    cond_peak = (k_shift1 > k_shift2) & (k_shift1 > k_series)
    m_series = k_shift1.where(cond_peak).ffill()

    return m_series


def calc_m_resistance(df_15m: pd.DataFrame) -> float:
    """최신 15분봉 기준 M선 저항선 가격 반환"""
    if df_15m is None or df_15m.empty:
        return 0.0
    df = df_15m.copy()
    df.rename(columns={col: str(col).lower() for col in df.columns}, inplace=True)
    m_series = calculate_m_line_series(df)
    valid_m = m_series.dropna()
    if not valid_m.empty:
        return float(valid_m.iloc[-1])
    return 0.0


# ═══════════════════════════════════════════════════════════════
# 15분봉 통합 매도 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_sell_signals(
    df_15m: pd.DataFrame,
    daily_df: Optional[pd.DataFrame] = None,
    buy_price: float = 0.0,
    current_price: Optional[float] = None,
    touch_high: float = 0.0
) -> Dict[str, Any]:
    """
    15분봉 DataFrame, 일봉, 매수가를 종합하여 통합 매도 신호를 판정합니다.

    Returns
    -------
    dict:
        sell           : bool   - 매도 신호 여부
        close          : float  - 현재 종가
        buy_price      : float  - 매입단가
        profit_pct     : float  - 현재 수익률(%)
        m_resistance   : float  - M선 저항 가격
        sma5           : float  - 현재 SMA5 값
        sma40          : float  - 현재 SMA40 값
        reason         : str    - 매도 사유 메시지
        exit_type      : str    - 'STOP_LOSS_2PCT', 'M_BREAKOUT_FAIL', 'UPPER_LIMIT_EXIT', 'DEAD_CROSS'
    """
    default_res = {
        "sell": False,
        "close": 0.0,
        "buy_price": buy_price,
        "profit_pct": 0.0,
        "m_resistance": 0.0,
        "sma5": 0.0,
        "sma40": 0.0,
        "reason": "",
        "exit_type": ""
    }

    if df_15m is None or df_15m.empty:
        return default_res

    df = df_15m.copy()
    col_map = {col: str(col).lower() for col in df.columns if str(col).lower() in ('open', 'high', 'low', 'close', 'volume')}
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns or 'open' not in df.columns:
        return default_res

    close_p = float(df.iloc[-1]['close'])
    curr_p = float(current_price) if current_price and current_price > 0 else close_p
    
    profit_pct = ((curr_p - buy_price) / buy_price * 100.0) if buy_price > 0 else 0.0
    m_res = calc_m_resistance(df)

    # ─────────────────────────────────────────────────────────────
    # [우선순위 1] 절대적 매도 조건: 매수가 대비 -2.0% 도달 시 즉시 전량 손절
    # ─────────────────────────────────────────────────────────────
    if buy_price > 0 and (curr_p <= buy_price * 0.98 or profit_pct <= -2.0):
        return {
            "sell": True,
            "close": curr_p,
            "buy_price": buy_price,
            "profit_pct": profit_pct,
            "m_resistance": m_res,
            "sma5": 0.0,
            "sma40": 0.0,
            "reason": (
                f"🛑 [절대적 매도 조건 발동] 매수가 대비 -2.0% 도달 "
                f"(매수가: {buy_price:,.0f}원 -> 현재가: {curr_p:,.0f}원, 손익률: {profit_pct:+.2f}%) -> 전량 즉시 손절매"
            ),
            "exit_type": "STOP_LOSS_2PCT"
        }

    # ─────────────────────────────────────────────────────────────
    # [우선순위 2] 수익 중일 때 M선 돌파 여부 확인 및 실패 시 전량 매도
    # E{"M선 돌파 여부 확인"} 돌파 실패 시 전량매도 (수익 중일 때)
    # ─────────────────────────────────────────────────────────────
    if buy_price > 0 and curr_p > buy_price and m_res > 0:
        high_price = max(touch_high, float(df.iloc[-1]['high']), curr_p)
        
        # M선 저항선 근처(99.0% 이상)에 도달했거나 진입했던 이력이 있는 경우
        is_near_or_reached_m = high_price >= (m_res * 0.99)

        if is_near_or_reached_m:
            # 돌파 실패 조건:
            # 1. 현재가가 M선 98.5% 미만으로 하락 꺾임 (저항 돌파 실패)
            # 2. 또는 M선 도달 최고가 대비 -1.5% 이상 하락 꺾임
            is_breakout_failed = (curr_p < m_res * 0.985) or (curr_p < high_price * 0.985)
            
            if is_breakout_failed:
                return {
                    "sell": True,
                    "close": curr_p,
                    "buy_price": buy_price,
                    "profit_pct": profit_pct,
                    "m_resistance": m_res,
                    "sma5": 0.0,
                    "sma40": 0.0,
                    "reason": (
                        f"🎯 [수익 중 M선 돌파 실패 매도] "
                        f"정배열 최고 정점 M선({m_res:,.0f}원) 돌파 실패 및 꺾임 확인 "
                        f"(수익률: {profit_pct:+.2f}%, 고점: {high_price:,.0f}원 -> 현재가: {curr_p:,.0f}원) -> 전량 익절 청산"
                    ),
                    "exit_type": "M_BREAKOUT_FAIL"
                }

    # ─────────────────────────────────────────────────────────────
    # [우선순위 3] 전일 상한가 종목의 익일 시가 돌파 실패(-2% 이탈) 매도 검사
    # ─────────────────────────────────────────────────────────────
    try:
        if hasattr(df.index, 'date'):
            unique_dates = sorted(list(set(df.index.date)))
            if len(unique_dates) >= 2:
                today_date = unique_dates[-1]
                yesterday_date = unique_dates[-2]
                
                df_yesterday = df[df.index.date == yesterday_date]
                df_today = df[df.index.date == today_date]
                df_prior = df[df.index.date < yesterday_date]
                
                if not df_prior.empty and not df_yesterday.empty and not df_today.empty:
                    prior_close = float(df_prior.iloc[-1]['close'])
                    yest_close = float(df_yesterday.iloc[-1]['close'])
                    yest_high = float(df_yesterday['high'].max())
                    
                    yest_ret = ((yest_close - prior_close) / prior_close) * 100 if prior_close > 0 else 0.0
                    yest_high_ret = ((yest_high - prior_close) / prior_close) * 100 if prior_close > 0 else 0.0
                    
                    is_yesterday_upper_limit = (yest_ret >= 29.0) or (yest_high_ret >= 29.5 and yest_close >= yest_high * 0.985)
                    
                    if is_yesterday_upper_limit:
                        today_open = float(df_today.iloc[0]['open'])
                        if curr_p < today_open * 0.98:
                            diff_pct = ((curr_p - today_open) / today_open) * 100
                            return {
                                "sell": True,
                                "close": curr_p,
                                "buy_price": buy_price,
                                "profit_pct": profit_pct,
                                "m_resistance": m_res,
                                "sma5": 0.0,
                                "sma40": 0.0,
                                "reason": (
                                    f"⚡ [전일 상한가 종목] 시가대비 -2% 이탈 "
                                    f"(현재가: {curr_p:,.0f}원, 시가대비: {diff_pct:+.2f}%) -> 전량 매도"
                                ),
                                "exit_type": "UPPER_LIMIT_EXIT"
                            }
    except Exception as e:
        logger.debug(f"상한가 시가 검사 중 예외: {e}")

    # ─────────────────────────────────────────────────────────────
    # [우선순위 4] 15분봉 SMA5/SMA40 데드크로스 매도
    # ─────────────────────────────────────────────────────────────
    if len(df) >= 45:
        df['sma5'] = df['close'].rolling(window=5, min_periods=5).mean()
        df['sma40'] = df['close'].rolling(window=40, min_periods=40).mean()

        df['dead_cross'] = (
            (df['sma5'] < df['sma40']) &
            (df['sma5'].shift(1) >= df['sma40'].shift(1))
        )

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest

        sma5_now = float(latest['sma5']) if pd.notna(latest['sma5']) else 0.0
        sma40_now = float(latest['sma40']) if pd.notna(latest['sma40']) else 0.0

        if sma5_now > 0 and sma40_now > 0:
            is_cross_down = bool(latest['dead_cross']) or bool(prev['dead_cross'])
            is_meaningful_breakdown = (sma5_now < sma40_now * 0.996) or (curr_p < sma40_now * 0.995)
            
            lookback_df = df.iloc[-15:-1] if len(df) >= 15 else df.iloc[:-1]
            had_prior_uptrend = bool((lookback_df['sma5'] > lookback_df['sma40']).sum() >= 3) if not lookback_df.empty else True

            if is_cross_down and is_meaningful_breakdown and had_prior_uptrend:
                diff_pct = ((sma5_now - sma40_now) / sma40_now) * 100
                return {
                    "sell": True,
                    "close": curr_p,
                    "buy_price": buy_price,
                    "profit_pct": profit_pct,
                    "m_resistance": m_res,
                    "sma5": sma5_now,
                    "sma40": sma40_now,
                    "reason": (
                        f"15분봉 SMA5({sma5_now:,.0f})<SMA40({sma40_now:,.0f}) 데드크로스 이탈 확인 "
                        f"(이격도: {diff_pct:+.2f}%, 현재가: {curr_p:,.0f}원, 손익률: {profit_pct:+.2f}%)"
                    ),
                    "exit_type": "DEAD_CROSS"
                }

    return default_res


# ═══════════════════════════════════════════════════════════════
# 15분봉 M선 근접 시 1분봉 M선 돌파/실패 정밀 판별 함수
# ═══════════════════════════════════════════════════════════════
def evaluate_1m_m_breakout(
    df_1m: pd.DataFrame,
    m_resistance: float,
    buy_price: float = 0.0,
    current_price: Optional[float] = None,
    touch_high: float = 0.0
) -> Dict[str, Any]:
    """
    [15분봉 M선 근접 시 가동되는 1분봉 M선 돌파/실패 정밀 판별 함수]

    판별 규칙:
    1. [돌파 실패 A: 터치 후 저항 꺾임]
       - 1분봉 현재가가 M선의 99.5% 이상 터치했거나 터치 후,
       - 1분봉에서 2연속 음봉 발생 및 1분봉 5이평선(SMA 5) 하향 이탈 시 전량 매도
    2. [돌파 실패 B: 가짜 돌파(Bull Trap) 후 M선 재이탈]
       - 1분봉 고가가 M선을 돌파(High >= M)했으나, 1분봉 종가가 M선 아래로 재이탈(Close < M * 0.995) 시 전량 매도
    3. [돌파 실패 C: 고점 대비 트레일링 꺾임]
       - M선 부근에서 기록한 1분봉 최고가(touch_high) 대비 현재가가 -1.2% 이상 하락 꺾임 시 전량 매도
    4. [돌파 성공 및 지지]:
       - 1분봉 종가가 M선 위에 안착(Close >= M)하고 1분봉 5이평선 지지 유지 시 홀딩(sell=False)
    """
    if df_1m is None or df_1m.empty or len(df_1m) < 2 or m_resistance <= 0:
        return {
            "sell": False, "reason": "", "exit_type": "",
            "touch_high": touch_high, "profit_pct": 0.0
        }

    df = df_1m.copy()
    col_map = {col: str(col).lower() for col in df.columns if str(col).lower() in ('open', 'high', 'low', 'close', 'volume')}
    df.rename(columns=col_map, inplace=True)

    curr_p = float(current_price) if current_price and current_price > 0 else float(df.iloc[-1]['close'])
    profit_pct = ((curr_p - buy_price) / buy_price * 100.0) if buy_price > 0 else 0.0
    
    # 1분봉 최고가 갱신
    recent_high = float(df['high'].iloc[-10:].max())
    new_touch_high = max(touch_high, recent_high, curr_p)

    # 1분봉 5이평선 계산
    df['sma5'] = df['close'].rolling(5, min_periods=1).mean()
    sma5_now = float(df['sma5'].iloc[-1])

    latest = df.iloc[-1]
    prev1 = df.iloc[-2] if len(df) >= 2 else latest
    
    is_curr_bear = bool(latest['close'] < latest['open'])
    is_prev_bear = bool(prev1['close'] < prev1['open'])
    consecutive_2_bears = is_curr_bear and is_prev_bear

    # 1) [실패 패턴 A: M선 터치 저항 꺾임]
    if new_touch_high >= (m_resistance * 0.995):
        if consecutive_2_bears and (curr_p < sma5_now) and (curr_p < m_resistance):
            return {
                "sell": True,
                "reason": (
                    f"🎯 [1분봉 M선 터치 저항 꺾임] M선({m_resistance:,.0f}원) 터치 후 "
                    f"1분봉 2연속 음봉 및 1분봉 5선({sma5_now:,.0f}원) 이탈 "
                    f"(수익률: {profit_pct:+.2f}%, 고점: {new_touch_high:,.0f}원 -> 현재가: {curr_p:,.0f}원) -> 전량 익절"
                ),
                "exit_type": "1M_M_REJECTION",
                "touch_high": new_touch_high,
                "profit_pct": profit_pct
            }

    # 2) [실패 패턴 B: 1분봉 가짜 돌파(Bull Trap) 후 M선 재이탈]
    if new_touch_high >= m_resistance:
        if curr_p < m_resistance * 0.995:
            return {
                "sell": True,
                "reason": (
                    f"🎯 [1분봉 M선 휩쏘 재이탈] M선({m_resistance:,.0f}원) 일시 돌파 후 "
                    f"1분봉 종가가 M선 아래({curr_p:,.0f}원)로 재붕괴 "
                    f"(수익률: {profit_pct:+.2f}%, 고점: {new_touch_high:,.0f}원) -> 전량 익절"
                ),
                "exit_type": "1M_BULL_TRAP",
                "touch_high": new_touch_high,
                "profit_pct": profit_pct
            }

    # 3) [실패 패턴 C: 1분봉 고점 대비 트레일링 꺾임]
    if new_touch_high >= (m_resistance * 0.990):
        if curr_p < new_touch_high * 0.988:
            diff_from_peak = ((curr_p - new_touch_high) / new_touch_high) * 100.0
            return {
                "sell": True,
                "reason": (
                    f"🎯 [1분봉 고점 대비 꺾임] M선 저항 부근 최고가({new_touch_high:,.0f}원) 대비 "
                    f"{diff_from_peak:+.2f}% 하락 꺾임 확인 "
                    f"(수익률: {profit_pct:+.2f}%, 현재가: {curr_p:,.0f}원) -> 전량 익절"
                ),
                "exit_type": "1M_TRAILING_FALL",
                "touch_high": new_touch_high,
                "profit_pct": profit_pct
            }

    # 4) [돌파 성공 및 지지 유지]
    if curr_p >= m_resistance:
        return {
            "sell": False,
            "reason": f"1분봉 M선({m_resistance:,.0f}원) 돌파 안착 지지 중 (현재가: {curr_p:,.0f}원, 홀딩)",
            "exit_type": "HOLD_BREAKOUT",
            "touch_high": new_touch_high,
            "profit_pct": profit_pct
        }

    return {
        "sell": False,
        "reason": "1분봉 M선 근접 관찰 중",
        "exit_type": "",
        "touch_high": new_touch_high,
        "profit_pct": profit_pct
    }
