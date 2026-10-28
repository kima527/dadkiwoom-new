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
            if self.position.total_qty > 0:
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

            gate_support = is_gate_up or (not np.isnan(gate_line) and close >= gate_line * 0.990 and low <= gate_line * 1.015)
            gijun_breakout = (not np.isnan(gijun_line) and gijun_line > 0 and tick_close >= gijun_line)
            
            if is_bull_support and (gate_support or gijun_breakout) and (not np.isnan(gate_line) or not np.isnan(gijun_line)):
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
        # 2. FIRST_BUY_DONE 상태: 2차 매수 (50% 불타기) 또는 M/3 수식선 이탈 전량 매도
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FIRST_BUY_DONE:
            is_sell_signal = False
            sell_reason = ""
            action_type = "TAKE_PROFIT"
            exit_price = tick_close

            # 🛡️ 진입 직후 1~2틱 호가 노이즈 털림 방지 (최소 3분간 노이즈 버퍼 적용):
            is_recent_entry = (self.position.entry_time > 0 and (time.time() - self.position.entry_time < 180))
            m3_thresh = day3_m_line * 0.995 if is_recent_entry else day3_m_line * 0.998
            gijun_thresh = gijun_line * 0.993 if is_recent_entry else gijun_line * 0.995

            # 매도 원칙:
            # 1) M=종가+nPreDayClose(1)+nPreDayClose(2); M/3 수식선 이탈 즉시 전량 매도
            if day3_m_line > 0 and tick_close < m3_thresh:
                is_sell_signal = True
                diff_pct = ((tick_close - day3_m_line) / day3_m_line) * 100.0
                profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"1차 매수 후 M/3 수식선({day3_m_line:,.0f}원) 하향 이탈 즉시 전량 매도 "
                    f"(현재가: {exit_price:,.0f}원, M/3대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                )
            # 2) 60분봉 기준선 변곡선(M선) 넘지 못할 경우 전량 매도 (기준선 돌파 진입 후 하향 이탈 또는 저항 꺾임)
            elif not np.isnan(gijun_line) and gijun_line > 0:
                was_near_gijun = (self.position.first_buy_price >= gijun_line * 0.998) or (tick_close >= gijun_line)
                if was_near_gijun and tick_close < gijun_thresh:
                    is_sell_signal = True
                    diff_pct = ((tick_close - gijun_line) / gijun_line) * 100.0
                    profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0
                    action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                    sell_reason = (
                        f"1차 매수 후 60분봉 기준선 변곡선({gijun_line:,.0f}원) 미돌파/하향 이탈 즉시 전량 매도 "
                        f"(현재가: {exit_price:,.0f}원, 기준선대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                    )
            elif day3_m_line <= 0:
                # Fallback: 관문선 하향 이탈
                if not np.isnan(gate_line) and close < gate_line * (1.0 - self.gate_sl_pct):
                    is_sell_signal = True
                    profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0
                    action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                    sell_reason = "1차 매수 후 테마급등관문선 하향 이탈 전량 손절"

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
                self.position = PositionTracker()
                return order

            # 2차 매수 조건 (분할 매수 및 더블 바잉 방지):
            # 1) 1차 매수를 관문선 지지로 진입한 경우: 60분봉 테마기준선(M선) 상향 돌파 시 2차 매수
            # 2) 1차 매수를 이미 기준선 돌파로 진입한 경우: 급등관문고가선(HH) 돌파 또는 1차 매수가 대비 +0.5% 이상 추가 상승 시 불타기
            is_breakout = False
            breakout_target = 0.0
            breakout_name = ""

            was_first_bought_at_gijun = (self.position.first_buy_price >= gijun_line * 0.998) if (not np.isnan(gijun_line) and gijun_line > 0) else False

            if was_first_bought_at_gijun:
                # 1차를 기준선 돌파로 진입한 경우: 고가선(HH) 돌파 또는 1차 매수가 대비 +0.5% 추가 상승 시 불타기 (더블 바잉 방지)
                if not np.isnan(gate_high) and gate_high > self.position.first_buy_price and tick_close >= gate_high:
                    is_breakout = True
                    breakout_target = gate_high
                    breakout_name = "급등관문고가선(HH)"
                elif tick_close >= self.position.first_buy_price * 1.005:
                    is_breakout = True
                    breakout_target = self.position.first_buy_price * 1.005
                    breakout_name = "1차매수가 대비 +0.5% 추가상승 돌파"
            else:
                # 1차를 관문선 바닥에서 진입한 경우: 테마기준선(M선) 도달 및 상향 돌파 시 2차 매수
                if not np.isnan(gijun_line) and gijun_line > 0 and tick_close >= gijun_line:
                    is_breakout = True
                    breakout_target = gijun_line
                    breakout_name = "테마기준선(M선)"

            if is_breakout:
                buy_price = tick_close
                # 2차 매수 수량: 1차 매수 수량과 1:1 동일 수량 추가 매수 (1차 50% + 2차 50% 분할 원칙)
                target_qty = self.position.first_buy_qty if self.position.first_buy_qty > 0 else self.position.total_qty
                if target_qty <= 0:
                    target_qty = int((self.cash * 0.50) // buy_price)
                if self.cash < target_qty * buy_price:
                    target_qty = int(self.cash // buy_price)
                    
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

        # ─────────────────────────────────────────────────────────────
        # 3. FULL_POSITION 상태: 매도 2대 원칙 충족 시 전량 매도 -> 즉시 IDLE 복귀 (재매수 없음)
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FULL_POSITION:
            is_sell_signal = False
            sell_reason = ""
            action_type = "TAKE_PROFIT"
            exit_price = tick_close

            # 🛡️ 진입 직후 1~2틱 호가 노이즈 털림 방지 (최소 3분간 노이즈 버퍼 적용):
            is_recent_entry = (self.position.entry_time > 0 and (time.time() - self.position.entry_time < 180))
            m3_thresh = day3_m_line * 0.995 if is_recent_entry else day3_m_line * 0.998
            gijun_thresh = gijun_line * 0.993 if is_recent_entry else gijun_line * 0.995

            # 매도 원칙:
            # 1) M=종가+nPreDayClose(1)+nPreDayClose(2); M/3 수식선 이탈 즉시 전량 매도
            if day3_m_line > 0 and tick_close < m3_thresh:
                is_sell_signal = True
                diff_pct = ((tick_close - day3_m_line) / day3_m_line) * 100.0
                profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"M/3 수식선({day3_m_line:,.0f}원) 하향 이탈 즉시 전량 매도 "
                    f"(현재가: {exit_price:,.0f}원, M/3대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                )
            # 2) 60분봉 기준선 변곡선(M선) 넘지 못할 경우 전량 매도 (하향 이탈 또는 돌파 실패)
            elif not np.isnan(gijun_line) and gijun_line > 0 and tick_close < gijun_thresh:
                is_sell_signal = True
                diff_pct = ((tick_close - gijun_line) / gijun_line) * 100.0
                profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"60분봉 기준선 변곡선({gijun_line:,.0f}원) 미돌파/하향 이탈 즉시 전량 매도 "
                    f"(현재가: {exit_price:,.0f}원, 기준선대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                )
            elif day3_m_line <= 0:
                # Fallback: 관문선 하향 이탈
                if not np.isnan(gate_line) and close < gate_line * (1.0 - self.gate_sl_pct):
                    is_sell_signal = True
                    action_type = "STOP_LOSS"
                    exit_price = close
                    sell_reason = "테마급등관문선 하향 이탈 전량 손절"

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

