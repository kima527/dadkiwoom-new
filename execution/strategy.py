from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import time
import pandas as pd
import numpy as np

try:
    from indicators import calculate_day3_m_line
except ImportError:
    from execution.indicators import calculate_day3_m_line

def calculate_wma(series: pd.Series, period: int = 60) -> pd.Series:
    """WMA(가중이동평균) 고속 연산 (120틱 WMA 순차돌파 및 고점 반전 연산)"""
    if series is None or len(series) < period:
        return pd.Series(np.nan, index=getattr(series, 'index', None))
    clean_series = series.ffill().bfill()
    weights = np.arange(1, period + 1, dtype=float)
    w_sum = weights.sum()
    return clean_series.rolling(window=period, min_periods=period).apply(
        lambda p: np.dot(p, weights) / w_sum,
        raw=True
    )

class StrategyState(str, Enum):
    IDLE = "IDLE"                                     # 대기 중 (1차 진입 탐색)
    FIRST_BUY_DONE = "FIRST_BUY_DONE"                 # 1차 매수 완료 (50% 보유)
    FULL_POSITION = "FULL_POSITION"                   # 2차 매수 완료 (100% 보유)
    PROFIT_TAKEN = "PROFIT_TAKEN"                     # 익절 완료 (다음 관문선 재매수 대기)
    REENTRY_HOLDING = "REENTRY_HOLDING"               # 재매수 완료 보유 중
    TERMINATED = "TERMINATED"                         # 일봉 데드크로스로 전략 완전 종료

@dataclass
class TradeOrder:
    timestamp: Any
    action: str                     # "BUY_1", "BUY_2", "TAKE_PROFIT", "RE_BUY", "RE_SELL", "STOP_LOSS", "TERMINATE_EXIT"
    price: float
    qty: int
    amount: float
    reason: str
    stage: str

@dataclass
class PositionTracker:
    state: StrategyState = StrategyState.IDLE
    total_qty: int = 0
    avg_price: float = 0.0
    first_buy_price: float = 0.0
    first_buy_qty: int = 0
    second_buy_price: float = 0.0
    second_buy_qty: int = 0
    second_buy_time: float = 0.0
    max_profit_pct: float = 0.0
    bep_locked: bool = False
    reentry_qty: int = 0
    reentry_price: float = 0.0
    last_gate_line: float = 0.0
    last_gate_high: float = 0.0
    last_gijun_line: float = 0.0
    reentry_count: int = 0
    base_account_qty: int = 0
    entry_time: float = 0.0

class ThemeGate60mStrategy:
    """
    60분봉 테마급등관문선 & 테마기준선 분할/순환 매매 전략 엔진
    """
    def __init__(self, initial_capital: float = 10_000_000, 
                 gate_sl_pct: float = 0.015,
                 max_reentry: int = 0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.gate_sl_pct = gate_sl_pct
        self.max_reentry = max_reentry
        self.last_sell_time: float = 0.0
        self.position = PositionTracker()
        self.trade_history: List[TradeOrder] = []
        
    def evaluate_bar(
        self, 
        row: pd.Series, 
        daily_dead_cross: bool = False, 
        daily_bull: bool = True, 
        row_120t: Optional[pd.Series] = None,
        df_daily: Optional[pd.DataFrame] = None,
        day3_m_line: Optional[float] = None,
        current_price: Optional[float] = None,
        **kwargs
    ) -> Optional[TradeOrder]:
        """
        단일 60분봉 및 일봉 데이터에 대한 상태 전이 및 주문 발생 평가 (120틱 및 재매수 로직 완전 배제)
        - 매수: 1차 매수(관문선 지지/변곡 또는 기준선 돌파) -> 2차 매수(기준선 돌파 50% 불타기)
        - 매도 2대 원칙:
          1) M = 종가 + nPreDayClose(1) + nPreDayClose(2); M/3 실시간 3일선 수식선 이탈 즉시 전량 매도
          2) 60분봉 기준선 변곡선(M선) 넘지 못할 경우 즉시 전량 매도
        - 매도 후: 재매수 없이 즉시 전량 청산 완료(IDLE 복귀) 및 슬롯 반환
        """
        timestamp = row.name if hasattr(row, 'name') else row.get('timestamp')
        close = row['close']
        high = row['high']
        low = row['low']
        open_price = row['open']
        
        gate_line = row.get('theme_gate', np.nan)
        gate_high = row.get('theme_gate_high', np.nan)
        gijun_line = row.get('theme_gijun', np.nan)
        is_gate_up = row.get('gate_up_turnaround', False)
        gate_cross_up = row.get('gate_cross_up', False)

        # 현재가 결정 (120틱 배제): current_price 우선, 전달된 row_120t close fallback, 기본값 60분봉 close
        if current_price is not None and float(current_price) > 0:
            tick_close = float(current_price)
        elif row_120t is not None and 'close' in row_120t and pd.notna(row_120t['close']) and float(row_120t['close']) > 0:
            tick_close = float(row_120t['close'])
        else:
            tick_close = float(close)

        # 실시간 3일선 M/3 수식선 계산: M = 종가 + nPreDayClose(1) + nPreDayClose(2); 수식선 = M / 3.0
        m_val = 0.0
        pred1 = 0.0
        pred2 = 0.0
        if day3_m_line is None or day3_m_line <= 0:
            if df_daily is not None and not df_daily.empty:
                day3_m_line, m_val, pred1, pred2 = calculate_day3_m_line(df_daily, tick_close)
            else:
                day3_m_line = 0.0
        else:
            m_val = day3_m_line * 3.0

        
        # ─────────────────────────────────────────────────────────────
        # 0. 최우선 규칙: 일봉 기준 테마 5-20 데드크로스 발생 시 전량 청산 및 종료
        # ─────────────────────────────────────────────────────────────
        if daily_dead_cross:
            # 🛡️ 실보유 물량이 실제로 2차 매수까지 체결된 경우(수량 > 1)에만 청산 주문 발생 (관종 1주는 매도 차단)
            if self.position.total_qty > 1:
                sell_qty = self.position.total_qty
                sell_amt = sell_qty * tick_close
                self.cash += sell_amt
                self.last_sell_time = time.time()
                order = TradeOrder(
                    timestamp=timestamp,
                    action="TERMINATE_EXIT",
                    price=tick_close,
                    qty=sell_qty,
                    amount=sell_amt,
                    reason="일봉 테마 5-20 데드크로스 발생 전량 청산 및 전략 종료",
                    stage="TERMINATED"
                )
                self.trade_history.append(order)
                self.position.total_qty = 0
                self.position.state = StrategyState.TERMINATED
                return order
            else:
                self.position.state = StrategyState.TERMINATED
                return None
                
        if self.position.state == StrategyState.TERMINATED:
            # 일봉이 다시 상승 추세로 복귀하면 리셋 가능 여부
            if daily_bull and gate_cross_up:
                self.position = PositionTracker() # 재시작
            else:
                return None

        # ─────────────────────────────────────────────────────────────
        # 1. IDLE 상태: 1차 매수 (예수금 50%)
        # 승률 조건:
        # 1) 60분봉 완전 정배열(5>20>60) 또는 20선(검정선) 상단 지지 안착 (매물대를 발밑에 장착)
        # 2) 테마급등관문선 상승변곡 또는 관문선 바닥 지지 확인
        # ─────────────────────────────────────────────────────────────
        sma5 = row.get('sma5', np.nan)
        sma20 = row.get('sma20', np.nan)
        sma60 = row.get('sma60', np.nan)
        
        is_bull_support = False
        if not np.isnan(sma5) and not np.isnan(sma20):
            is_bull_support = (close >= sma20 * 0.995) and (sma5 >= sma20 * 0.990)

        if self.position.state == StrategyState.IDLE:
            if not daily_bull:
                return None  # 일봉이 하락 추세(5<20)일 때는 신규 1차 매수 진입 차단

            # 🛡️ 매도 직후 재매수 방지 쿨다운 (최소 1시간 동일 종목 재진입 방지)
            if self.last_sell_time > 0 and (time.time() - self.last_sell_time < 3600):
                return None

            # 🛡️ [매수 필수 방어벽]: M/3 실시간 3일선 상단 지지 확인 (M/3선 하회 시 매수 절대 차단)
            # 주가가 M/3선 아래에 있는 상태에서 매수하면, 진입 직후 1초만에 M/3선 이탈 매도 조건이 발동하여
            # '매수 후 즉시 매도(Whipsaw)'가 발생하므로 원천 방지
            if day3_m_line > 0 and tick_close < day3_m_line:
                return None

            # 🛡️ [시가 훼손 방어벽]: 당일 시가 아래로 밀린 파란 음봉(Gap & Crap) 매수 차단 (시가 위 붉은 양봉 유지 필수)
            open_p = float(row.get('open', tick_close))
            if open_p > 0 and tick_close < open_p:
                return None

            # ⚡ [120틱 WMA 순차돌파 & 실시간 현재가 반영 검증]: kwargs로 전달된 120틱 데이터에 실시간 tick_close 반영
            df_120t = kwargs.get('df_120t', None)
            is_120t_breakout = True
            if df_120t is not None and len(df_120t) >= 65 and 'close' in df_120t:
                s_120t = df_120t['close'].astype(float).copy()
                if tick_close > 0:
                    s_120t.iloc[-1] = tick_close
                w1 = float(s_120t.iloc[-1])
                w20 = float(calculate_wma(s_120t, 20).iloc[-1])
                w60 = float(calculate_wma(s_120t, 60).iloc[-1])
                if not np.isnan(w20) and not np.isnan(w60) and w20 > 0 and w60 > 0:
                    # 1이평선(현재가)이 WMA20 및 WMA60 상단에 위치하여 순차돌파 완성 중인지 확인
                    is_120t_breakout = (w1 >= w20 * 0.998) and (w1 >= w60 * 0.995)

            gate_support = is_gate_up or (not np.isnan(gate_line) and close >= gate_line * 0.990 and low <= gate_line * 1.015)
            gijun_breakout = (not np.isnan(gijun_line) and gijun_line > 0 and tick_close >= gijun_line)
            
            if is_bull_support and is_120t_breakout and (gate_support or gijun_breakout) and (not np.isnan(gate_line) or not np.isnan(gijun_line)):
                budget = self.cash * 0.50
                buy_price = tick_close
                qty = int(budget // buy_price)
                if qty > 0:
                    cost = qty * buy_price
                    self.cash -= cost
                    self.position.total_qty = qty
                    self.position.avg_price = buy_price
                    self.position.first_buy_price = buy_price
                    self.position.first_buy_qty = qty
                    self.position.entry_time = time.time()
                    self.position.last_gate_line = gate_line
                    self.position.last_gate_high = gate_high
                    self.position.last_gijun_line = gijun_line
                    self.position.state = StrategyState.FIRST_BUY_DONE
                    
                    trigger_str = f"기준선(M선 {gijun_line:,.0f}원) 상향 통과" if gijun_breakout else f"관문선 변곡/지지({gate_line:,.0f}원)"
                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_1",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"60분봉 정배열/20선 지지 + {trigger_str} 1차 50% 매수 (체결가: {buy_price:,.0f}원)",
                        stage="FIRST_BUY_DONE"
                    )
                    self.trade_history.append(order)
                    return order

        # ─────────────────────────────────────────────────────────────
        # 2. FIRST_BUY_DONE 상태: 2차 매수 (50% 불타기) 대기
        # (원칙: 관종 1주 및 1차 매수 물량은 2차 매수가 완료된 FULL_POSITION 상태에서만 매도 6대 원칙 적용,
        #  단 1차 매수 후 돌파 실패 시 M/3선 이탈 및 -1.5% 하드 손절 방어선 가동)
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FIRST_BUY_DONE:
            # 2차 매수 조건 (분할 매수 및 동일가 더블 바잉 원천 방지):
            # - 모든 2차 매수는 1차 매수가 대비 최소 +0.5% 이상 수익 구간(tick_close >= first_buy_price * 1.005)에서만 발동
            # 1) 1차 매수를 관문선 지지로 진입한 경우: 60분봉 테마기준선(M선) 상향 돌파(+0.5% 이상 상승 동반) 시 2차 매수
            # 2) 1차 매수를 이미 기준선 돌파로 진입한 경우: 급등관문고가선(HH) 돌파 또는 1차 매수가 대비 +0.5% 이상 추가 상승 시 불타기
            is_breakout = False
            breakout_target = 0.0
            breakout_name = ""

            min_pyramiding_price = self.position.first_buy_price * 1.005 if self.position.first_buy_price > 0 else 0.0
            has_min_profit_gap = (tick_close >= min_pyramiding_price)

            was_first_bought_at_gijun = (self.position.first_buy_price >= gijun_line * 0.998) if (not np.isnan(gijun_line) and gijun_line > 0) else False

            if was_first_bought_at_gijun:
                # 1차를 기준선 돌파로 진입한 경우: 고가선(HH) 돌파 또는 1차 매수가 대비 +0.5% 추가 상승 시 불타기
                if has_min_profit_gap and not np.isnan(gate_high) and gate_high > self.position.first_buy_price and tick_close >= gate_high:
                    is_breakout = True
                    breakout_target = gate_high
                    breakout_name = "급등관문고가선(HH)"
                elif has_min_profit_gap:
                    is_breakout = True
                    breakout_target = min_pyramiding_price
                    breakout_name = "1차매수가 대비 +0.5% 추가상승 돌파"
            else:
                # 1차를 관문선 바닥에서 진입한 경우: 테마기준선(M선) 상향 돌파 및 1차 매수가 대비 최소 +0.5% 이상 상승 시 2차 매수
                if has_min_profit_gap and not np.isnan(gijun_line) and gijun_line > 0 and tick_close >= gijun_line:
                    is_breakout = True
                    breakout_target = gijun_line
                    breakout_name = "테마기준선(M선)"

            if is_breakout:
                buy_price = tick_close
                # 2차 매수 수량: 1차 매수 수량과 1:1 동일 수량 추가 매수 (수수료/슬리피지 대비 가용 예수금 99% 안전 버퍼 적용)
                usable_cash = self.cash * 0.99
                target_qty = self.position.first_buy_qty if self.position.first_buy_qty > 0 else self.position.total_qty
                if target_qty <= 0:
                    target_qty = int((usable_cash * 0.50) // buy_price)
                if usable_cash < target_qty * buy_price:
                    target_qty = int(usable_cash // buy_price)
                    
                qty = target_qty
                if qty > 0:
                    cost = qty * buy_price
                    self.cash -= cost
                    prev_qty = self.position.total_qty
                    prev_cost = prev_qty * self.position.avg_price
                    self.position.total_qty += qty
                    self.position.avg_price = (prev_cost + cost) / self.position.total_qty
                    self.position.second_buy_price = buy_price
                    self.position.second_buy_qty = qty
                    self.position.second_buy_time = time.time()
                    # 합산 평단가 대비 현재 수익률로 초기 max_profit_pct 설정 (+0.6% 도달 시 3단계 본절/수익 래칫 자동 장전)
                    init_full_pnl = ((buy_price - self.position.avg_price) / self.position.avg_price) * 100.0 if self.position.avg_price > 0 else 0.0
                    self.position.max_profit_pct = max(0.0, init_full_pnl)
                    self.position.bep_locked = (self.position.max_profit_pct >= 0.6)
                    self.position.entry_time = time.time()
                    self.position.last_gate_high = gate_high
                    self.position.state = StrategyState.FULL_POSITION
                    
                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_2",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"{breakout_name} 상향 돌파 2차 50% 추가 매수 (돌파선: {breakout_target:,.0f}원, 체결가: {buy_price:,.0f}원)",
                        stage="FULL_POSITION"
                    )
                    self.trade_history.append(order)
                    return order
            else:
                # 🛡️ [1차 매수 진입 후 돌파 실패 손절 방어 (50% 자금 보호)]
                # 실보유 수량이 1주 초과(실제 1차 매수 체결분)인 경우:
                # 1) M/3 실시간 3일선 하향 이탈
                # 2) 1차 매수가 대비 -1.5% 하드 손절선 도달 시 즉시 손절하여 50% 자금 동결 방지
                if self.position.total_qty > 1:
                    holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0
                    is_recent_entry = (holding_sec < 180)
                    m3_thresh = day3_m_line * 0.995 if is_recent_entry else day3_m_line * 0.998
                    p_rate = ((tick_close - self.position.first_buy_price) / self.position.first_buy_price) * 100.0 if self.position.first_buy_price > 0 else 0.0

                    is_first_buy_sl = False
                    sl_reason = ""
                    if day3_m_line > 0 and tick_close < m3_thresh:
                        is_first_buy_sl = True
                        sl_reason = f"1차 매수 후 M/3 수식선({day3_m_line:,.0f}원) 하향 이탈 1차 물량 전량 손절 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"
                    elif self.position.first_buy_price > 0 and tick_close <= self.position.first_buy_price * 0.985:
                        is_first_buy_sl = True
                        sl_reason = f"1차 매수가 대비 -1.5% 하드 손절선 도달 1차 물량 전량 손절 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"

                    if is_first_buy_sl:
                        sell_qty = self.position.total_qty
                        sell_amt = sell_qty * tick_close
                        self.cash += sell_amt
                        self.last_sell_time = time.time()
                        order = TradeOrder(
                            timestamp=timestamp,
                            action="STOP_LOSS",
                            price=tick_close,
                            qty=sell_qty,
                            amount=sell_amt,
                            reason=sl_reason,
                            stage="IDLE"
                        )
                        self.trade_history.append(order)
                        self.position = PositionTracker()
                        return order

        # ─────────────────────────────────────────────────────────────
        # 3. FULL_POSITION 상태: 매도 2대 원칙 충족 시 전량 매도 -> 즉시 IDLE 복귀 (재매수 없음)
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FULL_POSITION:
            # 🛡️ 관종 1주 매도 절대 차단: 실보유 수량이 1주 이하인 종목은 2차 매수가 완료된 것이 아니므로 매도 신호 차단
            if self.position.total_qty <= 1:
                return None

            is_sell_signal = False
            sell_reason = ""
            action_type = "TAKE_PROFIT"
            exit_price = tick_close

            # 현재 수익률 계산 및 최고 수익률 추적 (ZeroDivisionError 원천 방어)
            profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0 if self.position.avg_price > 0 else 0.0
            if profit_rate > self.position.max_profit_pct:
                self.position.max_profit_pct = profit_rate

            # 🔒 [3단계 수익 잠금 래칫 (3-Tier Profit Ratchet) 자동 장전]:
            # 합산 평단가 대비 +0.60% 이상 도달한 순간부터 무위험 본절락(bep_locked) 영구 활성화
            # (2차 매수 직후 1~2틱 호가 흔들림에 의한 조기 자가청산 방지 및 수수료+세금 완벽 보존)
            if self.position.max_profit_pct >= 0.6:
                self.position.bep_locked = True

            # 🛡️ 진입 직후 1~2틱 호가 노이즈 털림 방지 (최소 3분간 노이즈 버퍼 적용):
            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0
            is_recent_entry = (holding_sec < 180)
            m3_thresh = day3_m_line * 0.995 if is_recent_entry else day3_m_line * 0.998
            gijun_thresh = gijun_line * 0.993 if is_recent_entry else gijun_line * 0.995

            # ─────────────────────────────────────────────────────────────
            # [통합 매도 6대 원칙 (손실 제로 & 수익 극대화 무결점 락)]
            # ─────────────────────────────────────────────────────────────
            
            # 1) 🔒 [무위험 본절/수익 보존 래칫 (3-Tier Profit Ratchet)]:
            #    - Tier 1 (+0.60% 도달 시): 평단가 * 1.0023 (+0.23% 거래세+수수료 보존선, 0원 손실 탈출)
            #    - Tier 2 (+1.20% 도달 시): 평단가 * 1.0060 (+0.60% 확정 순수익 잠금선)
            sec_buy_elapsed = (time.time() - self.position.second_buy_time) if self.position.second_buy_time > 0 else 999.0
            if self.position.max_profit_pct >= 1.2:
                bep_price = self.position.avg_price * 1.0060
                ratchet_label = "확정수익 보존락(+0.60%)"
            else:
                bep_price = self.position.avg_price * 1.0023
                ratchet_label = "무위험 본절락(+0.23% 수수료보존)"

            if self.position.bep_locked and sec_buy_elapsed >= 60.0 and tick_close <= bep_price:
                is_sell_signal = True
                action_type = "TAKE_PROFIT" if profit_rate >= 0.2 else "STOP_LOSS"
                sell_reason = (
                    f"🔒 {ratchet_label}(BEP Profit Ratchet) 발동: 전량 매도 "
                    f"(매수가: {self.position.avg_price:,.0f}원, 보존선: {bep_price:,.0f}원, 체결가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )

            # 2) 🎯 [Tier 3 고점 대비 트레일링 스탑]: +2.0% 이상 상승 후 고점 대비 -0.7% 되밀릴 시 확정 익절
            elif self.position.max_profit_pct >= 2.0 and (self.position.max_profit_pct - profit_rate) >= 0.7:
                is_sell_signal = True
                action_type = "TAKE_PROFIT"
                sell_reason = (
                    f"🎯 고점대비 트레일링 스탑 확정 익절 (최고수익: +{self.position.max_profit_pct:.2f}%, "
                    f"고점대비 되밀림: -{(self.position.max_profit_pct - profit_rate):.2f}%, 현재수익률: {profit_rate:+.2f}%)"
                )

            # 3) 📉 [120틱 WMA60 피크 하락반전/데드크로스 청산 (실시간 tick_close 반영)]
            elif kwargs.get('df_120t') is not None and len(kwargs.get('df_120t')) >= 65 and not is_recent_entry:
                df_120t = kwargs.get('df_120t')
                if 'close' in df_120t:
                    s_120t = df_120t['close'].astype(float).copy()
                    if tick_close > 0:
                        s_120t.iloc[-1] = tick_close
                    w20 = calculate_wma(s_120t, 20)
                    w60 = calculate_wma(s_120t, 60)
                    if len(w60.dropna()) >= 3:
                        slope60 = w60.diff()
                        pct_slope60 = (slope60 / w60.shift(1)) * 100.0
                        last_slope = pct_slope60.iloc[-1]
                        prev_slope = pct_slope60.iloc[-2]
                        has_peaked = (self.position.max_profit_pct >= 0.6) or (profit_rate >= 0.3)
                        is_true_turn_down = (prev_slope >= 0.001 and last_slope < -0.002 and has_peaked)
                        prev_diff = w20.iloc[-2] - w60.iloc[-2]
                        curr_diff = w20.iloc[-1] - w60.iloc[-1]
                        is_true_dead_cross = (prev_diff > 0 and curr_diff <= 0 and has_peaked and last_slope <= 0.0)

                        if is_true_turn_down or is_true_dead_cross:
                            is_sell_signal = True
                            action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                            turn_name = "120틱 WMA60 고점 꺾임(Peak Reversal)" if is_true_turn_down else "120틱 WMA20-60 고점 데드크로스"
                            sell_reason = (
                                f"📉 {turn_name} 감지 즉시 전량 청산 "
                                f"(최고수익: +{self.position.max_profit_pct:.2f}%, 체결가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                            )

            # 4) 🌊 [M/3 실시간 3일선 이탈 매도]: M = 종가+nPreDayClose(1)+nPreDayClose(2); M/3 수식선 이탈 즉시 전량 매도
            if not is_sell_signal and day3_m_line > 0 and tick_close < m3_thresh:
                is_sell_signal = True
                diff_pct = ((tick_close - day3_m_line) / day3_m_line) * 100.0
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"🌊 M/3 수식선({day3_m_line:,.0f}원) 하향 이탈 즉시 전량 매도 "
                    f"(현재가: {exit_price:,.0f}원, M/3대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                )

            # 5) 🏛️ [60분봉 기준선 변곡선(M선) 하향 이탈 매도]
            elif not is_sell_signal and not np.isnan(gijun_line) and gijun_line > 0 and tick_close < gijun_thresh:
                is_sell_signal = True
                diff_pct = ((tick_close - gijun_line) / gijun_line) * 100.0
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"🏛️ 60분봉 기준선 변곡선({gijun_line:,.0f}원) 미돌파/하향 이탈 즉시 전량 매도 "
                    f"(현재가: {exit_price:,.0f}원, 기준선대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                )

            # 6) 🛑 [하드 리스크 방어 손절선 (-1.5%)]: 모든 지표를 초월한 계좌 원천 방어
            elif not is_sell_signal and tick_close <= self.position.avg_price * 0.985:
                is_sell_signal = True
                action_type = "STOP_LOSS"
                sell_reason = (
                    f"🛑 하드 손절선(-1.5%) 도달 리스크 차단 전량 손절 "
                    f"(매수가: {self.position.avg_price:,.0f}원, 현재가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )

            if is_sell_signal:
                sell_qty = self.position.total_qty
                sell_amt = sell_qty * exit_price
                self.cash += sell_amt
                self.last_sell_time = time.time()
                order = TradeOrder(
                    timestamp=timestamp,
                    action=action_type,
                    price=exit_price,
                    qty=sell_qty,
                    amount=sell_amt,
                    reason=sell_reason,
                    stage="IDLE"
                )
                self.trade_history.append(order)
                # 재매수 없이 즉시 전량 청산 완료 및 포지션 초기화 (IDLE 복귀)
                self.position = PositionTracker()
                return order

        return None

