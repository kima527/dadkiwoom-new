"""
strategy_sell.py - 실시간 3일선 저가 하향 이탈 단일 매도 전략
===========================================================================

[단일 매도 원칙]
1. 저가가 실시간 3일선(M/3) 아래로 떨어지면 즉시 전량 매도:
   - 일봉 실시간 3일선 공식:
     M = 현재가 + 전일종가(1) + 전전일종가(2)
     기준선 = M / 3.0
   - 당봉 저가(Low) 또는 실시간 현재가가 3일선 미만(low < day3_line 또는 curr < day3_line)으로
     이탈할 때 전량 시장가 매도.
2. 저가가 3일선 이상 지지 유지 시에는 지속 홀딩하여 상승 추세 수익을 극대화.
3. WMA 3-5 데드크로스, 다이나믹 트레일링 스탑 등 복잡한 다중 지표를 배제하고
   '저가 3일선 이탈'로 단일화.
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 실시간 3일선(M/3) 계산 함수
# ═══════════════════════════════════════════════════════════════
def calculate_day3_m_line(daily_df: Optional[pd.DataFrame], current_price: float) -> float:
    """
    일봉 실시간 3일선 M/3 계산:
    M = 현재가 + 전일종가(1) + 전전일종가(2)
    기준선 = M / 3.0
    """
    if daily_df is None or len(daily_df) < 2 or current_price <= 0:
        return 0.0

    df_d = daily_df.copy()
    col_map = {col: str(col).lower() for col in df_d.columns if str(col).lower() in ('open', 'high', 'low', 'close', 'date')}
    df_d.rename(columns=col_map, inplace=True)

    today_str = datetime.now().strftime('%Y%m%d')

    if 'date' in df_d.columns:
        last_date = str(df_d['date'].iloc[-1]).replace('-', '').strip()
        # 오늘 날짜 일봉 캔들이 이미 포함되어 있으면 Day-1(전일), Day-2(전전일) 사용
        if last_date == today_str and len(df_d) >= 3:
            pred1 = float(df_d['close'].iloc[-2])
            pred2 = float(df_d['close'].iloc[-3])
        else:
            pred1 = float(df_d['close'].iloc[-1])
            pred2 = float(df_d['close'].iloc[-2]) if len(df_d) >= 2 else pred1
    else:
        pred1 = float(df_d['close'].iloc[-1])
        pred2 = float(df_d['close'].iloc[-2]) if len(df_d) >= 2 else pred1

    m = float(current_price) + pred1 + pred2
    return m / 3.0


# ═══════════════════════════════════════════════════════════════
# 실시간 3일선 저가 이탈 단일 매도 신호 분석
# ═══════════════════════════════════════════════════════════════
def analyze_sell_signals(
    df_15m: Optional[pd.DataFrame] = None,
    daily_df: Optional[pd.DataFrame] = None,
    buy_price: float = 0.0,
    current_price: Optional[float] = None,
    touch_high: float = 0.0
) -> Dict[str, Any]:
    """
    저가가 실시간 3일선(M/3) 아래로 떨어지면 전량 매도하는 단일화 매도 로직.

    Parameters
    ----------
    df_15m : Optional[pd.DataFrame]
        15분봉 데이터 (최신 캔들의 low/close 확인용)
    daily_df : Optional[pd.DataFrame]
        일봉 데이터 (실시간 3일선 산출용)
    buy_price : float
        매수 평단가
    current_price : Optional[float]
        실시간 현재가
    touch_high : float
        장중 최고가 (참고용)

    Returns
    -------
    dict:
        sell           : bool   - 매도 신호 여부
        close          : float  - 현재 종가 / 실시간가
        low            : float  - 당봉 저가
        buy_price      : float  - 매입단가
        profit_pct     : float  - 현재 수익률(%)
        day3_m_line    : float  - 실시간 3일선(M/3) 가격
        m_resistance   : float  - 3일선 가격 (하위 호환)
        wma3           : float  - 하위 호환용 (0.0)
        wma5           : float  - 하위 호환용 (0.0)
        sma5           : float  - 하위 호환용 (0.0)
        sma20          : float  - 하위 호환용 (0.0)
        sma40          : float  - 하위 호환용 (0.0)
        reason         : str    - 매도/홀딩 사유 메시지
        exit_type      : str    - 'DAY3_LOW_BREAK' 또는 ''
    """
    default_res = {
        "sell": False,
        "close": 0.0,
        "low": 0.0,
        "buy_price": buy_price,
        "profit_pct": 0.0,
        "day3_m_line": 0.0,
        "m_resistance": 0.0,
        "wma3": 0.0,
        "wma5": 0.0,
        "sma5": 0.0,
        "sma20": 0.0,
        "sma40": 0.0,
        "reason": "",
        "exit_type": ""
    }

    # 1. 현재가 및 최신 봉 저가(low) 추출
    close_p = 0.0
    low_p = 0.0

    if df_15m is not None and not df_15m.empty:
        df = df_15m.copy()
        col_map = {col: str(col).lower() for col in df.columns if str(col).lower() in ('open', 'high', 'low', 'close', 'volume')}
        df.rename(columns=col_map, inplace=True)
        latest = df.iloc[-1]
        close_p = float(latest['close']) if 'close' in latest and pd.notna(latest['close']) else 0.0
        low_p = float(latest['low']) if 'low' in latest and pd.notna(latest['low']) else close_p

    curr_p = float(current_price) if current_price and current_price > 0 else close_p
    if low_p <= 0:
        low_p = curr_p

    profit_pct = ((curr_p - buy_price) / buy_price * 100.0) if buy_price > 0 else 0.0

    # 2. 실시간 3일선 M/3 계산
    day3_m_line = calculate_day3_m_line(daily_df, curr_p)

    default_res.update({
        "close": curr_p,
        "low": low_p,
        "profit_pct": profit_pct,
        "day3_m_line": day3_m_line,
        "m_resistance": day3_m_line,
    })

    # 3. 단일 매도 판단: 저가가 3일선 아래로 떨어지면 매도!
    if day3_m_line > 0:
        # 15분봉 당봉 저가 또는 실시간 현재가가 3일선 미만으로 하향 이탈 시 매도
        if low_p < day3_m_line or curr_p < day3_m_line:
            diff_pct = ((curr_p - day3_m_line) / day3_m_line) * 100.0
            default_res.update({
                "sell": True,
                "reason": (
                    f"📉 [3일선 저가 이탈 단일 매도] 저가({low_p:,.0f}원)가 "
                    f"실시간 3일선({day3_m_line:,.0f}원) 하향 이탈 "
                    f"(현재가: {curr_p:,.0f}원, 3일선 대비: {diff_pct:+.2f}%, 손익률: {profit_pct:+.2f}%)"
                ),
                "exit_type": "DAY3_LOW_BREAK"
            })
            return default_res
        else:
            default_res.update({
                "sell": False,
                "reason": (
                    f"✅ [3일선 지지 유지] 저가({low_p:,.0f}원) >= 3일선({day3_m_line:,.0f}원) "
                    f"(현재가: {curr_p:,.0f}원, 손익률: {profit_pct:+.2f}%, 지속 홀딩)"
                ),
                "exit_type": ""
            })
            return default_res

    # 4. 일봉 데이터 미수신/부족 시 비상 하드 손절(-5.0%) 안전망
    if profit_pct <= -5.0 and buy_price > 0:
        default_res.update({
            "sell": True,
            "reason": f"🚨 [비상 하드 손절] 손실률({profit_pct:+.2f}%) <= -5.0% 마지노선 도달 (3일선 미수신 안전망)",
            "exit_type": "EMERGENCY_STOP_LOSS"
        })
        return default_res

    default_res["reason"] = f"3일선 데이터 산출 대기 중 (현재가: {curr_p:,.0f}원)"
    return default_res
