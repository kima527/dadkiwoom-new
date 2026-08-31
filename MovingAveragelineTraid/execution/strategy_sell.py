"""
strategy_sell.py - 15분봉 SMA5/SMA40 데드크로스 매도 전략
===========================================================================

매도 로직:
  1. SMA5 = SMA(종가, 5) / SMA40 = SMA(종가, 40) 계산
  2. 매도 신호: CrossDown(SMA5, SMA40) → SMA5가 SMA40을 하향 돌파(데드크로스)

사용 데이터: 15분봉
"""

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 15분봉 매도 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_sell_signals(df_15m: pd.DataFrame, daily_df: pd.DataFrame = None) -> dict:
    """
    15분봉 DataFrame(및 일봉)을 받아 매도 신호를 생성합니다.

    매도 조건:
    1. [전일 상한가 종목 익일 시가 돌파 실패/이탈]:
       - 전일에 상한가(등락률 >= +29.0% 또는 고가 29.5%+ 안착)를 기록한 종목인 경우,
       - 익일(당일) 현재가가 시가(Open)를 돌파하지 못하고 하회(현재가 < 시가)하면 즉시 전량 매도.
    2. [15분봉 SMA5/SMA40 데드크로스]:
       - 15분봉 SMA5가 SMA40을 하향 돌파(CrossDown) 시 전량 매도.

    Returns
    -------
    dict:
        sell      : bool   - 매도 신호
        close     : float  - 현재 종가
        sma5      : float  - 현재 SMA5 값
        sma40     : float  - 현재 SMA40 값
        reason    : str    - 매도 사유 메시지
    """
    if df_15m is None or df_15m.empty or len(df_15m) < 45:
        return {"sell": False, "close": 0.0, "sma5": 0.0, "sma40": 0.0, "reason": ""}

    df = df_15m.copy()

    # 컬럼명 소문자 통일
    col_map = {}
    for col in df.columns:
        lower = str(col).lower()
        if lower in ('open', 'high', 'low', 'close', 'volume'):
            col_map[col] = lower
    df.rename(columns=col_map, inplace=True)

    if 'close' not in df.columns or 'open' not in df.columns:
        return {"sell": False, "close": 0.0, "sma5": 0.0, "sma40": 0.0, "reason": ""}

    close_price = float(df.iloc[-1]['close'])

    # ── [조건 1] 전일 상한가 종목의 익일 시가 돌파 실패 매도 검사 ──
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
                    
                    # 전일 상한가 달성 여부 (+29% 이상 종가 마감 또는 +29.5% 상한가 터치 후 고가 근처 유지)
                    is_yesterday_upper_limit = (yest_ret >= 29.0) or (yest_high_ret >= 29.5 and yest_close >= yest_high * 0.985)
                    
                    if is_yesterday_upper_limit:
                        today_open = float(df_today.iloc[0]['open'])
                        
                        # 당일 시가를 돌파하지 못하고 2% 이상 하회 시 (현재가 < 시가 * 0.98) - 휩쏘(흔들기) 방지 버퍼
                        if close_price < today_open * 0.98:
                            diff_pct = ((close_price - today_open) / today_open) * 100
                            sma5_val = float(df['close'].rolling(5, min_periods=5).mean().iloc[-1]) if len(df) >= 5 else 0.0
                            sma40_val = float(df['close'].rolling(40, min_periods=40).mean().iloc[-1]) if len(df) >= 40 else 0.0
                            
                            return {
                                "sell": True,
                                "close": close_price,
                                "sma5": sma5_val,
                                "sma40": sma40_val,
                                "reason": (
                                    f"⚡ [전일 상한가 종목] 시가대비 -2% 이탈 "
                                    f"(현재가: {close_price:,.0f}원, 시가대비: {diff_pct:+.2f}%) -> 개미털기 버퍼 초과, 전량 매도"
                                )
                            }
    except Exception as e:
        logger.debug(f"상한가 시가 검사 중 예외: {e}")

    # ── [조건 2] 15분봉 SMA5/SMA40 데드크로스 매도 ──
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

    result = {
        "sell": False,
        "close": close_price,
        "sma5": sma5_now,
        "sma40": sma40_now,
        "reason": ""
    }

    # 1호가 미세 흔들림(이격도 미세)으로 인한 휩쏘 방지:
    # 1) SMA5가 SMA40 대비 최소 0.4% 이상 확실하게 하회 이탈(SMA5 < SMA40 * 0.996)하거나 현재가가 SMA40을 하회
    # 2) 과거 15봉 중 5이평이 40이평 위에 머물렀던 '선행 상승 추세' 이력이 최소 3봉 이상 존재할 때만 매도
    if sma5_now > 0 and sma40_now > 0:
        is_cross_down = bool(latest['dead_cross']) or bool(prev['dead_cross'])
        is_meaningful_breakdown = (sma5_now < sma40_now * 0.996) or (close_price < sma40_now * 0.995)
        
        lookback_df = df.iloc[-15:-1] if len(df) >= 15 else df.iloc[:-1]
        had_prior_uptrend = bool((lookback_df['sma5'] > lookback_df['sma40']).sum() >= 3) if not lookback_df.empty else True

        if is_cross_down and is_meaningful_breakdown and had_prior_uptrend:
            diff_pct = ((sma5_now - sma40_now) / sma40_now) * 100
            result["sell"] = True
            result["reason"] = (
                f"15분봉 SMA5({sma5_now:,.0f})<SMA40({sma40_now:,.0f}) 데드크로스 이탈 확인 "
                f"(이격도: {diff_pct:+.2f}%, 종가: {close_price:,.0f})"
            )

    return result
