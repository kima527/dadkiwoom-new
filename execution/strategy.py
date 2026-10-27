from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np

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

class ThemeGate60mStrategy:
    """
    60분봉 테마급등관문선 & 테마기준선 분할/순환 매매 전략 엔진
    """
    def __init__(self, initial_capital: float = 10_000_000, 
                 gate_sl_pct: float = 0.015,
                 max_reentry: int = 5):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.gate_sl_pct = gate_sl_pct
        self.max_reentry = max_reentry
        self.position = PositionTracker()
        self.trade_history: List[TradeOrder] = []
        
    def evaluate_bar(self, row: pd.Series, daily_dead_cross: bool = False, daily_bull: bool = True, row_120t: Optional[pd.Series] = None) -> Optional[TradeOrder]:
        """
        단일 60분봉 및 120틱 데이터에 대한 상태 전이 및 주문 발생 평가
        - 매도시점 일원화: 120틱 테마 5 < 20
        - 재매수 진입타점: 120틱 테마 5 > 20 > 60 > 120 완전 정배열
        - 재매수 휩쏘 방어: 재매수 후 -0.5% 이내(-0.5% ~ 0.0%)의 미세 하락은 5<20 데드가 떠도 매도 차단 홀딩
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

        # 120틱 현재가 및 지표
        if row_120t is not None and 'close' in row_120t and pd.notna(row_120t['close']) and float(row_120t['close']) > 0:
            tick_close = float(row_120t['close'])
        else:
            tick_close = float(close)

        is_120t_dead = False
        is_120t_aligned = False
        tema5_120t = 0.0
        tema20_120t = 0.0

        if row_120t is not None:
            dead_val = row_120t.get('is_tema_dead_5_20', False)
            if pd.notna(dead_val) and bool(dead_val) is True:
                is_120t_dead = True
                
            aligned_val = row_120t.get('is_tema_aligned_120t', False)
            if pd.notna(aligned_val) and bool(aligned_val) is True:
                is_120t_aligned = True
                
            t5 = row_120t.get('tema5', 0.0)
            t20 = row_120t.get('tema20', 0.0)
            tema5_120t = float(t5) if pd.notna(t5) else 0.0
            tema20_120t = float(t20) if pd.notna(t20) else 0.0

        
        # ─────────────────────────────────────────────────────────────
        # 0. 최우선 규칙: 일봉 기준 테마 5-20 데드크로스 발생 시 전량 청산 및 종료
        # ─────────────────────────────────────────────────────────────
        if daily_dead_cross:
            if self.position.total_qty > 0:
                sell_qty = self.position.total_qty
                sell_amt = sell_qty * tick_close
                self.cash += sell_amt
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

            gate_support = is_gate_up or (not np.isnan(gate_line) and close >= gate_line * 0.990 and low <= gate_line * 1.015)
            gijun_breakout = (not np.isnan(gijun_line) and gijun_line > 0 and tick_close >= gijun_line)
            
            if is_bull_support and (gate_support or gijun_breakout) and (not np.isnan(gate_line) or not np.isnan(gijun_line)):
                budget = self.cash * 0.50
                buy_price = tick_close
                qty = int(budget // buy_price)
                if qty > 0:
                    cost = qty * buy_price
                    self.cash -= cost
                    prev_base = self.position.base_account_qty
                    self.position.total_qty = qty + prev_base
                    self.position.base_account_qty = 0
                    self.position.avg_price = buy_price
                    self.position.first_buy_price = buy_price
                    self.position.first_buy_qty = qty
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
        # 2. FIRST_BUY_DONE 상태: 2차 매수 (50% 불타기) 또는 120틱 5<20 전량 매도
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FIRST_BUY_DONE:
            # 모든 매도시점 일원화: 120틱 5 < 20 하향 이탈 시 전량 매도 (손절/청산)
            is_sell_signal = is_120t_dead if row_120t is not None else (not np.isnan(gate_line) and close < gate_line * (1.0 - self.gate_sl_pct))
            if is_sell_signal:
                sell_qty = self.position.total_qty
                exit_price = tick_close
                sell_amt = sell_qty * exit_price
                self.cash += sell_amt
                profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100
                order = TradeOrder(
                    timestamp=timestamp,
                    action="STOP_LOSS" if profit_rate < 0 else "TAKE_PROFIT",
                    price=exit_price,
                    qty=sell_qty,
                    amount=sell_amt,
                    reason=f"1차 매수 후 120틱 테마 5<20 하향 이탈 전량 매도 (수익률: {profit_rate:+.2f}%)",
                    stage="IDLE"
                )
                self.trade_history.append(order)
                self.position = PositionTracker()
                return order

            # 2차 매수 조건: 실시간 현재가(tick_close)가 60분봉 테마기준선(M선)을 상향 돌파 시 집행
            is_breakout = False
            breakout_target = 0.0
            breakout_name = ""
            
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
        # 3. FULL_POSITION 상태: 모든 매도시점 일원화 -> 120틱 5 < 20 시점에 전량 매도
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FULL_POSITION:
            is_sell_signal = False
            sell_reason = ""
            action_type = "TAKE_PROFIT"
            exit_price = tick_close

            if row_120t is not None:
                if is_120t_dead:
                    is_sell_signal = True
                    profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100
                    action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                    sell_reason = f"120틱 테마 5<20 하향 이탈 전량 매도 (수익률: {profit_rate:+.2f}%, TEMA5: {tema5_120t:.0f} < 20: {tema20_120t:.0f})"
            else:
                # Fallback: 관문선 이탈 손절
                if not np.isnan(gate_line) and close < gate_line * (1.0 - self.gate_sl_pct):
                    is_sell_signal = True
                    action_type = "STOP_LOSS"
                    exit_price = close
                    sell_reason = "테마급등관문선 하향 이탈 전량 손절"
                # Fallback: 기준선 도달 익절
                min_profit_target = self.position.avg_price * 1.010
                if not np.isnan(gijun_line) and (high >= gijun_line) and (high >= min_profit_target):
                    is_sell_signal = True
                    action_type = "TAKE_PROFIT"
                    exit_price = min(max(gijun_line, open_price) if open_price > gijun_line else gijun_line, high)
                    profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100
                    sell_reason = f"테마기준선(M선) 상향 돌파 전량 익절 (수익률: {profit_rate:+.2f}%)"

            if is_sell_signal:
                sell_qty = self.position.total_qty
                sell_amt = sell_qty * exit_price
                self.cash += sell_amt
                order = TradeOrder(
                    timestamp=timestamp,
                    action=action_type,
                    price=exit_price,
                    qty=sell_qty,
                    amount=sell_amt,
                    reason=sell_reason,
                    stage="PROFIT_TAKEN"
                )
                self.trade_history.append(order)
                # 재매수 대기 모드로 전환
                self.position.total_qty = 0
                self.position.reentry_qty = sell_qty
                self.position.last_gijun_line = gijun_line
                self.position.state = StrategyState.PROFIT_TAKEN
                return order

        # ─────────────────────────────────────────────────────────────
        # 4. PROFIT_TAKEN 상태: "120틱 테마 5>20>60>120 완전 정배열 시 재매수"
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.PROFIT_TAKEN:
            if not daily_bull:
                return None  # 일봉이 하락 추세(5<20)일 때는 재매수 차단 대기
            if self.position.reentry_count >= self.max_reentry:
                self.position = PositionTracker()  # 최대 재매수 횟수(기본 5회) 도달 시 관심종목(IDLE)으로 초기화 복귀
                return None

                
            is_reentry_trigger = False
            re_reason = ""
            buy_price = tick_close
            
            if row_120t is not None:
                if is_120t_aligned:
                    is_reentry_trigger = True
                    re_reason = f"120틱 테마 5>20>60>120 정배열 완성 재매수 (재매수 {self.position.reentry_count + 1}회차)"
                elif not np.isnan(gijun_line) and gijun_line > 0 and tick_close >= gijun_line:
                    is_reentry_trigger = True
                    re_reason = f"60분봉 기준선(M선 {gijun_line:,.0f}원) 상향 돌파 재매수 (재매수 {self.position.reentry_count + 1}회차)"
            else:
                # Fallback: 60분봉 관문선 지지/도달
                is_touch_gate = (low <= gate_line * 1.008) and (close >= gate_line * 0.990)
                if not np.isnan(gate_line) and (is_touch_gate or gate_cross_up):
                    is_reentry_trigger = True
                    buy_price = close
                    re_reason = f"다음 테마급등관문선 지지/도달 시 재매수 (재매수 회차: {self.position.reentry_count + 1})"

            if is_reentry_trigger:
                re_qty = self.position.reentry_qty
                if re_qty <= 0:
                    re_qty = int((self.cash * 0.95) // buy_price)
                if self.cash < re_qty * buy_price:
                    re_qty = int(self.cash // buy_price)
                    
                if re_qty > 0:
                    cost = re_qty * buy_price
                    self.cash -= cost
                    prev_base = self.position.base_account_qty
                    self.position.total_qty = re_qty + prev_base
                    self.position.base_account_qty = 0
                    self.position.avg_price = buy_price
                    self.position.reentry_price = buy_price  # 휩쏘 방어를 위한 재매수 단가 기록
                    self.position.last_gate_line = gate_line
                    self.position.reentry_count += 1
                    self.position.state = StrategyState.REENTRY_HOLDING
                    
                    order = TradeOrder(
                        timestamp=timestamp,
                        action="RE_BUY",
                        price=buy_price,
                        qty=re_qty,
                        amount=cost,
                        reason=re_reason,
                        stage="REENTRY_HOLDING"
                    )
                    self.trade_history.append(order)
                    return order

        # ─────────────────────────────────────────────────────────────
        # 5. REENTRY_HOLDING 상태: 재매수 포지션 -> 120틱 5 < 20 시점에 매도
        # 단, 재매수 후 -0.5% 이내의 휩쏘(-0.5% <= 손실률 < 0%)는 매도 차단 홀딩
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.REENTRY_HOLDING:
            exit_price = tick_close
            base_price = self.position.reentry_price if self.position.reentry_price > 0 else self.position.avg_price
            pnl_pct = ((exit_price - base_price) / base_price) * 100 if base_price > 0 else 0.0

            is_sell_signal = False
            action_type = "RE_SELL"
            sell_reason = ""

            # 🚨 [비상 하방 손절]: 재매수 단가 대비 -2.0% 이하 급락 시 120틱 신호 지연과 무관하게 즉시 안전 손절
            emergency_sl_pct = -max(1.5, self.gate_sl_pct * 100)
            if pnl_pct <= emergency_sl_pct:
                is_sell_signal = True
                action_type = "STOP_LOSS"
                sell_reason = f"🚨 [비상 하방 손절] 재매수 단가({base_price:,.0f}원) 대비 {pnl_pct:+.2f}% 급락으로 안전 비상손절 발동"

            elif row_120t is not None:
                if is_120t_dead:
                    # 🛡️ [재매수 휩쏘 방어 로직]:
                    # 재매수 후 -0.5% 까지는(-0.5% <= pnl_pct < 0.0) 5<20이 떠도 매도하지 않고 대기
                    if -0.5 <= pnl_pct < 0.0:
                        return None
                    elif pnl_pct >= 0.0:
                        is_sell_signal = True
                        action_type = "RE_SELL"
                        sell_reason = f"재매수 후 120틱 테마 5<20 하향 이탈 전량 익절 (수익률: {pnl_pct:+.2f}%, TEMA5: {tema5_120t:.0f} < 20: {tema20_120t:.0f})"
                    else:
                        # pnl_pct < -0.5%: 휩쏘 마진 초과 손절
                        is_sell_signal = True
                        action_type = "STOP_LOSS"
                        sell_reason = f"재매수 후 120틱 테마 5<20 및 -0.5% 휩쏘 마진 초과 손절 (손실률: {pnl_pct:+.2f}%, TEMA5: {tema5_120t:.0f} < 20: {tema20_120t:.0f})"

            else:
                # Fallback: 관문선 이탈 또는 기준선 도달
                if not np.isnan(gate_line) and close < gate_line * (1.0 - self.gate_sl_pct):
                    is_sell_signal = True
                    action_type = "STOP_LOSS"
                    exit_price = close
                    sell_reason = "재매수 후 테마급등관문선 이탈 손절"
                elif not np.isnan(gijun_line) and high >= gijun_line:
                    is_sell_signal = True
                    action_type = "RE_SELL"
                    exit_price = min(max(gijun_line, open_price) if open_price > gijun_line else gijun_line, high)
                    sell_reason = f"재매수 후 테마기준선(M선) 도달 전량 익절 (기준선: {gijun_line:.1f})"

            if is_sell_signal:
                sell_qty = self.position.total_qty
                sell_amt = sell_qty * exit_price
                self.cash += sell_amt
                
                order = TradeOrder(
                    timestamp=timestamp,
                    action=action_type,
                    price=exit_price,
                    qty=sell_qty,
                    amount=sell_amt,
                    reason=sell_reason,
                    stage="PROFIT_TAKEN"
                )
                self.trade_history.append(order)
                self.position.total_qty = 0
                self.position.state = StrategyState.PROFIT_TAKEN  # 다시 다음 120틱 정배열 재매수 대기
                return order
                
        return None
