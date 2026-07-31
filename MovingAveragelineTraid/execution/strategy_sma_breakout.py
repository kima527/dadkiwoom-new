import pandas as pd
import logging
from datetime import datetime, time as dtime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 호가 단위 (Tick Size) 계산
# ---------------------------------------------------------------------------
def get_tick_size(price: int) -> int:
    """한국 거래소 기준 호가 단위(Tick Size) 계산"""
    if price < 2000:
        return 1
    elif price < 5000:
        return 5
    elif price < 20000:
        return 10
    elif price < 50000:
        return 50
    elif price < 200000:
        return 100
    elif price < 500000:
        return 500
    else:
        return 1000


# ---------------------------------------------------------------------------
# 종목별 거래 상태 관리
# ---------------------------------------------------------------------------
class TradeState:
    def __init__(self):
        self.is_holding = False
        self.trade_ended = False

        self.first_buy_candle_time = None
        self.added_on = False
        self.first_qty = 0

        # 120봉 최고가 트레일링 스탑용 — 보유 중 갱신
        self.trailing_high = 0.0

        # 재돌파(Re-entry) 매수용 상태
        self.initial_breakout_high = 0.0
        self.sold_once = False
        self.reentry_qty = 0


# ---------------------------------------------------------------------------
# 체결 강도(Trade Intensity) 계산 — 틱 데이터 기반
# ---------------------------------------------------------------------------
def calculate_trade_intensity(tick_data: list) -> dict:
    """
    최근 틱(체결) 데이터를 분석하여 매수/매도 체결 비율을 계산합니다.

    Parameters
    ----------
    tick_data : list[dict]
        각 원소는 최소 {'price': float, 'volume': int} 형태.
        'change' 키가 양수(+)이면 매수 체결, 음수(-)이면 매도 체결로 판정합니다.
        'change' 키가 없으면 직전 틱 대비 가격 등락으로 추정합니다.

    Returns
    -------
    dict  {'buy_vol': int, 'sell_vol': int, 'ratio': float, 'is_strong': bool}
        ratio = buy_vol / sell_vol  (sell_vol == 0 이면 999.0)
        is_strong = ratio >= 1.5
    """
    if not tick_data or len(tick_data) < 2:
        return {"buy_vol": 0, "sell_vol": 0, "ratio": 0.0, "is_strong": False}

    buy_vol = 0
    sell_vol = 0

    for i, tick in enumerate(tick_data):
        vol = abs(int(tick.get("volume", tick.get("cnt", 0))))
        change = tick.get("change", None)

        if change is not None:
            # change가 제공되면 부호로 판단
            if float(change) > 0:
                buy_vol += vol
            elif float(change) < 0:
                sell_vol += vol
            else:
                # 보합 체결 — 매수 쪽으로 0.5 반영
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5
        else:
            # change가 없으면 직전 틱과 가격 비교
            if i == 0:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5
                continue
            prev_price = float(tick_data[i - 1].get("price", tick_data[i - 1].get("close", 0)))
            cur_price = float(tick.get("price", tick.get("close", 0)))
            if cur_price > prev_price:
                buy_vol += vol
            elif cur_price < prev_price:
                sell_vol += vol
            else:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5

    ratio = (buy_vol / sell_vol) if sell_vol > 0 else 999.0
    is_strong = ratio >= 1.5

    return {
        "buy_vol": int(buy_vol),
        "sell_vol": int(sell_vol),
        "ratio": round(ratio, 2),
        "is_strong": is_strong,
    }


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
    # 3. 보유 중 — 트레일링 스탑 (120봉 최고가 × 0.98)
    # ===================================================================
    else:
        # 트레일링 고점 갱신 (보유 진입 이후 최고가 추적)
        if highest_120 > state.trailing_high:
            state.trailing_high = highest_120

        stop_price = state.trailing_high * 0.98

        # 현재 종가가 손절선(-2%) 이하로 내려오면 즉시 매도
        if close_price <= stop_price:
            return {
                "sell": True,
                "sell_reason": (
                    f"120봉 최고가({state.trailing_high:,.0f}) × 0.98 = "
                    f"{stop_price:,.0f} 하향이탈"
                ),
                "price": close_price,
            }

    return {"buy": False, "sell": False, "add_buy": False}

