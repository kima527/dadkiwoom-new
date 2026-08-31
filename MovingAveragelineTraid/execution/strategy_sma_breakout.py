import pandas as pd
import logging
from datetime import datetime, time as dtime

logger = logging.getLogger(__name__)

from utils import get_tick_size, TradeState, calculate_trade_intensity


# ---------------------------------------------------------------------------
# 핵심 전략 함수 — 120봉 돌파 확인 + 체결강도 필터 + 트레일링 스탑
# ---------------------------------------------------------------------------
def calculate_sma_breakout_signals(
    df: pd.DataFrame,
    state: TradeState,
    hold_buy_price: float = 0.0,
    tick_data: list | None = None,
) -> dict:
    """
    Parameters
    ----------
    df : pd.DataFrame
        1분봉 데이터 (마지막 행이 현재 캔들). 최소 120행 이상 권장.
    state : TradeState
        종목별 거래 상태 객체.
    hold_buy_price : float
        보유 중일 때의 매입단가 (0이면 미보유).
    tick_data : list | None
        real_api_adapter.get_tick_data() 가 반환하는 최근 틱 리스트.
        신규 매수 시 체결 강도 판별에 사용.

    Returns
    -------
    dict  {'buy': bool, 'sell': bool, 'add_buy': bool, ...}
    """
    if state.trade_ended or df.empty:
        return {"buy": False, "sell": False, "add_buy": False}

    df = df.copy()

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    close_price = float(latest["close"])
    open_price = float(latest["open"])

    # ===================================================================
    # 1. 120봉 최고가 계산  —  Highest(H, 120)
    # ===================================================================
    lookback = min(len(df), 120)
    highest_120 = float(df["high"].tail(lookback).max())

    # ===================================================================
    # 2. 신규 매수 및 재돌파 매수 로직
    # ===================================================================
    if not state.is_holding:
        # --- 필터 A: 다음 봉 지지 확인 (Next Bar Confirmation) ---
        #   현재 캔들이 양봉이어야 한다 (Close > Open)
        is_bullish_candle = close_price > open_price

        #   현재 종가가 직전 캔들 종가 이상이어야 한다 (되밀림 없음)
        prev_close_ok = True
        if prev is not None:
            prev_close = float(prev["close"])
            prev_close_ok = close_price >= prev_close

        candle_confirmed = is_bullish_candle and prev_close_ok

        # --- 필터 B: 체결 강도 (Trade Intensity) ---
        intensity = calculate_trade_intensity(tick_data or [])
        intensity_ok = intensity["is_strong"]  # ratio >= 1.5

        # [재돌파 매수 판단]
        if state.sold_once:
            if close_price > state.initial_breakout_high:
                if candle_confirmed and intensity_ok:
                    reason_parts = [
                        f"120봉초기고가 재돌파(C{close_price:,.0f}>H{state.initial_breakout_high:,.0f})",
                        f"체결강도 {intensity['ratio']}배"
                    ]
                    logger.info(f"🔄 [재진입 필터 통과] " + " | ".join(reason_parts))
                    return {
                        "buy": True,
                        "is_reentry": True,
                        "reentry_qty": state.reentry_qty,
                        "buy_reason": " + ".join(reason_parts),
                        "price": close_price,
                    }
            # 재진입 조건에 맞지 않으면 대기
            return {"buy": False, "sell": False, "add_buy": False}

        # [최초 신규 매수 판단]
        if candle_confirmed and intensity_ok:
            reason_parts = [
                f"양봉확인(C{close_price:,.0f}>O{open_price:,.0f})",
                f"체결강도 {intensity['ratio']}배(매수{intensity['buy_vol']}≥매도{intensity['sell_vol']}×1.5)",
            ]
            logger.info(
                f"📊 [매수필터 통과] 120봉최고={highest_120:,.0f} | "
                + " | ".join(reason_parts)
            )
            return {
                "buy": True,
                "buy_reason": " + ".join(reason_parts),
                "price": close_price,
            }
        else:
            # 디버깅용: 왜 통과 못 했는지 로그
            if not candle_confirmed:
                logger.debug(
                    f"⏸️ [매수필터 미통과-캔들] 양봉={is_bullish_candle}, "
                    f"전봉종가이상={prev_close_ok}"
                )
            if not intensity_ok:
                logger.debug(
                    f"⏸️ [매수필터 미통과-체결강도] ratio={intensity['ratio']}, "
                    f"buy={intensity['buy_vol']}, sell={intensity['sell_vol']}"
                )

    # ===================================================================
    # 3. 보유 중 — 매입단가 -5% 손절 감시
    # ===================================================================
    else:
        # 3.1 매입단가 기준 -5% 하드 손절
        if hold_buy_price > 0 and close_price <= hold_buy_price * 0.95:
            calc_ret = ((close_price - hold_buy_price) / hold_buy_price) * 100
            return {
                "sell": True,
                "sell_reason": f"⚡ 매입단가({hold_buy_price:,.0f}원) 대비 -5% 하드 손절: 현재가 {close_price:,.0f}원 ({calc_ret:+.2f}%)",
                "price": close_price,
            }

    return {"buy": False, "sell": False, "add_buy": False}

