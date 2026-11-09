from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import time
import pandas as pd
import numpy as np

try:
    from indicators import calculate_day3_m_line, calculate_120t_tema_indicators
except ImportError:
    from execution.indicators import calculate_day3_m_line, calculate_120t_tema_indicators

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
    entry_mode: str = ""                # "GATE_SUPPORT" (노란선 1차) or "HIGH_BREAKOUT" (검정점선/기준선 1차)
    first_cross_type: str = ""          # "TEMA60_120_GC" or "SMA40_60_GC"
    first_cross_price: float = 0.0      # 골든크로스 시점의 가격
    first_gijun_cleared: bool = False   # 1번째 분홍색 기준선 돌파 완료 여부
    cleared_gijun_price: float = 0.0    # 돌파 완료한 1번째 분홍색 기준선 가격
    second_gijun_price: float = 0.0     # 고점에서 새로 형성된 2번째 분홍색 기준선 가격
    touched_first_gijun: bool = False   # 1번째 분홍색 기준선 부근(-0.8% 이내) 도달 여부
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

        # ⚡ [120틱 상·하단 통합 파동 지표 연산]:
        # 상단: 노란색 급등관문선(gate_120t) + 검정점선 급등관문고가선(gate_high_120t) + 분홍색 기준선(gijun_120t)
        # 하단: 테마 5, 20, 60, 120 + 테마120 상승변곡(is_tema120_up) + 노란 양운(is_yellow_cloud) + 테마60-120 골든크로스
        df_120t = kwargs.get('df_120t', None)
        futures_regime = str(kwargs.get('futures_regime', 'NORMAL_BULL')).strip()
        futures_label = str(kwargs.get('futures_label', '선물지수')).strip()
        is_premarket_bridge_window = bool(kwargs.get('is_premarket_bridge_window', False))
        is_outperforming_index = bool(kwargs.get('is_outperforming_index', True))
        is_condition_pick = bool(kwargs.get('is_condition_pick', False))
        day_alpha = float(kwargs.get('day_alpha', 0.0) or 0.0)
        has_120t_wave = False
        gate_120t = np.nan
        gate_high_120t = np.nan
        gijun_120t = np.nan
        is_gate_up_120t = False
        is_tema120_up = True
        is_yellow_cloud_120t = False
        is_tema60_120_gc_120t = False
        is_tema5_20_bull_120t = True
        is_tema_dead_5_20_120t = False
        upper_shadow_ratio_120t = 0.0

        if df_120t is not None and not df_120t.empty and len(df_120t) >= 25 and 'close' in df_120t:
            df_120t_calc = calculate_120t_tema_indicators(df_120t, current_price=tick_close)
            if not df_120t_calc.empty:
                has_120t_wave = True
                last_120t = df_120t_calc.iloc[-1]
                gate_120t = float(last_120t.get('theme_gate', np.nan))
                gate_high_120t = float(last_120t.get('theme_gate_high', np.nan))
                gijun_120t = float(last_120t.get('theme_gijun', np.nan))
                is_gate_up_120t = bool(last_120t.get('gate_up_turnaround', False))
                is_tema120_up = bool(last_120t.get('is_tema120_up', True))
                is_yellow_cloud_120t = bool(last_120t.get('is_yellow_cloud', False))

                # 🌟 [120틱 핵심 타점 1]: 테마60-120 골든크로스 발생 여부(최근 5봉) 및 크로스 가격
                recent_tema60_120_gc = bool(df_120t_calc['is_tema60_120_gc'].tail(5).any()) if 'is_tema60_120_gc' in df_120t_calc else False
                tema60_120_gc_price = float(last_120t.get('tema60_120_gc_price', np.nan))
                is_tema60_120_gc_120t = recent_tema60_120_gc or is_yellow_cloud_120t

                # 🌟 [120틱 핵심 타점 2]: SMA 40-60 골든크로스 발생 여부(최근 5봉) 및 크로스 가격
                is_sma40_60_bull_120t = bool(last_120t.get('is_sma40_60_bull', False))
                recent_sma40_60_gc = bool(df_120t_calc['is_sma40_60_gc'].tail(5).any()) if 'is_sma40_60_gc' in df_120t_calc else False
                sma40_60_gc_price = float(last_120t.get('sma40_60_gc_price', np.nan))

                t5 = float(last_120t.get('tema5', np.nan))
                t20 = float(last_120t.get('tema20', np.nan))
                if not np.isnan(t5) and not np.isnan(t20) and t20 > 0:
                    is_tema5_20_bull_120t = (t5 >= t20 * 0.998)
                    is_tema_dead_5_20_120t = (t5 < t20 * 0.999)
                h_120 = float(last_120t.get('high', tick_close))
                l_120 = float(last_120t.get('low', tick_close))
                o_120 = float(last_120t.get('open', tick_close))
                rng_120 = max(h_120 - l_120, 1.0)
                upper_shadow_ratio_120t = max(h_120 - max(o_120, tick_close), 0.0) / rng_120

        # 유효 관문선(노란선) · 관문고가선(검정점선) · 기준선(분홍선) 결정 (120틱 우선, 부재 시 60분봉 연동)
        active_gate = gate_120t if (has_120t_wave and not np.isnan(gate_120t) and gate_120t > 0) else gate_line
        active_gate_high = gate_high_120t if (has_120t_wave and not np.isnan(gate_high_120t) and gate_high_120t > 0) else gate_high
        active_gijun = gijun_120t if (has_120t_wave and not np.isnan(gijun_120t) and gijun_120t > 0) else gijun_line
        active_gate_up = is_gate_up_120t or is_gate_up

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
        # 1. IDLE 상태: 1차 매수 (예수금 50% — 발목 선취매)
        # [정석 공식]:
        # - 정석 1차(일반장 90%): 노란색 급등관문선(active_gate) 상승변곡 또는 바닥 지지 안착 시 1차 50% 매수
        #   (이후 검정 점선 급등관문고가돌파선 확실한 돌파 확인 시 2차 50% 불타기!)
        # - 강세 예외 1차(강한 상승 10%): 테마120 상승 전환(is_tema120_up) + 검정 점선(급등관문고가선) 돌파 시 1차 50% 매수
        # ─────────────────────────────────────────────────────────────
        sma5 = row.get('sma5', np.nan)
        sma20 = row.get('sma20', np.nan)
        sma60 = row.get('sma60', np.nan)
        
        is_bull_support = False
        is_60m_sma20_support = True
        if not np.isnan(sma5) and not np.isnan(sma20):
            is_bull_support = (close >= sma20 * 0.995) and (sma5 >= sma20 * 0.990)
            is_60m_sma20_support = (close >= sma20 * 0.990)

        if self.position.state == StrategyState.IDLE:
            # 🚨 [소속 시장 선물지수 폭락 서킷브레이커 (CRASH_LOCK) 및 08:45~08:49 프리마켓 마감 직전 신규진입 차단]:
            # 1) 코스피 종목은 코스피200선물, 코스닥 종목은 코스닥150선물이 투매/폭락장(CRASH_LOCK)일 때 신규 1차 매수 전면 차단!
            # 2) 08:45~08:49:59 프리마켓 마감 브릿지 구간에서는 08:50~09:00 10분 거래중단(블랙아웃) 보호를 위해 신규 1차 진입 차단!
            if futures_regime == "CRASH_LOCK" or is_premarket_bridge_window:
                return None

            # 🏆 [금일 시장 지수 대비 상대강도(RS Alpha) 필수 필터]:
            # 소속 시장 지수(코스피200선물/코스닥150선물)보다 강하게 움직이는 주도주만 신규 매수 허용
            if not is_outperforming_index:
                return None

            if not daily_bull:
                return None  # 일봉이 하락 추세(5<20)일 때는 신규 1차 매수 진입 차단

            # 🛡️ 매도 직후 재매수 방지 쿨다운 (최소 1시간 동일 종목 재진입 방지)
            if self.last_sell_time > 0 and (time.time() - self.last_sell_time < 3600):
                return None

            # 🛡️ [매수 필수 방어벽]: M/3 실시간 3일선 상단 지지 확인 (M/3선 하회 시 매수 절대 차단)
            if day3_m_line > 0 and tick_close < day3_m_line:
                return None

            # 🛡️ [시가 훼손 방어벽]: 당일 시가 아래로 밀린 파란 음봉(Gap & Crap) 매수 차단 (시가 위 붉은 양봉 유지 필수)
            open_p = float(row.get('open', tick_close))
            if open_p > 0 and tick_close < open_p:
                return None

            # 🛡️ [60분봉 윗꼬리 매물폭탄 방어벽]: 60분봉 고점 대비 윗꼬리 비율이 45%를 초과하면 세력 차익실현/매물 저항으로 간주하여 매수 차단
            c_range = max(float(high) - float(low), 1.0)
            upper_shadow = max(float(high) - max(open_p, tick_close), 0.0)
            if (upper_shadow / c_range) > 0.45:
                return None

            # 🛡️ [기준선 과열 추격매수 차단]: 유효 기준선(120틱 기준선 우선, 부재 시 60분봉 기준선) 대비 +4.5% 초과 이격 과열 시 차단
            ref_overheat_gijun = gijun_120t if (has_120t_wave and not np.isnan(gijun_120t) and gijun_120t > 0) else gijun_line
            if not np.isnan(ref_overheat_gijun) and ref_overheat_gijun > 0 and tick_close > ref_overheat_gijun * 1.045:
                return None

            # ⚡ [120틱 WMA/TEMA 순차돌파 & 실시간 현재가 반영 검증]
            is_120t_breakout = True
            is_120t_wma_seq_breakout = False
            if df_120t is not None and len(df_120t) >= 65 and 'close' in df_120t:
                s_120t = df_120t['close'].astype(float).copy()
                if tick_close > 0:
                    s_120t.iloc[-1] = tick_close
                w1 = float(s_120t.iloc[-1])
                w20 = float(calculate_wma(s_120t, 20).iloc[-1])
                w40 = float(calculate_wma(s_120t, 40).iloc[-1])
                w60 = float(calculate_wma(s_120t, 60).iloc[-1])
                if not np.isnan(w20) and not np.isnan(w60) and w20 > 0 and w60 > 0:
                    is_120t_breakout = ((w1 >= w20 * 0.998) and (w1 >= w60 * 0.995)) or (is_tema5_20_bull_120t and is_tema120_up)
                if not np.isnan(w20) and not np.isnan(w40) and not np.isnan(w60) and w20 > 0 and w40 > 0 and w60 > 0:
                    is_120t_wma_seq_breakout = (w1 >= w20 * 0.998) and (w1 >= w40 * 0.998) and (w1 >= w60 * 0.998)

            # 🌟 [120틱 핵심 타점 1]: 테마 60이평선이 120이평선을 골든크로스 할 때의 가격
            # 🌟 [120틱 핵심 타점 2]: SMA 40, 60이평선 골든크로스 시점
            is_tema60_120_cross_buy = False
            is_sma40_60_cross_buy = False

            if has_120t_wave:
                # 1) 테마 60-120 골든크로스:
                #    최근 5틱봉 이내 골든크로스 발생 또는 노란 양운(테마60 >= 테마120) 상태에서 크로스 시점 가격(tema60_120_gc_price) 지지/안착
                t_gc_p = tema60_120_gc_price if (not np.isnan(tema60_120_gc_price) and tema60_120_gc_price > 0) else 0.0
                price_near_tema_gc = (t_gc_p > 0 and t_gc_p * 0.990 <= tick_close <= t_gc_p * 1.040) if t_gc_p > 0 else is_yellow_cloud_120t
                
                is_tema60_120_cross_buy = (
                    (recent_tema60_120_gc or (is_yellow_cloud_120t and price_near_tema_gc))
                    and is_tema5_20_bull_120t
                    and upper_shadow_ratio_120t <= 0.48
                )

                # 2) SMA 40-60 골든크로스 (만약 SMA 40-60이 먼저 발생했거나 동시에 발생한 경우 1차 매수 진입):
                s_gc_p = sma40_60_gc_price if (not np.isnan(sma40_60_gc_price) and sma40_60_gc_price > 0) else 0.0
                price_near_sma_gc = (s_gc_p > 0 and s_gc_p * 0.990 <= tick_close <= s_gc_p * 1.040) if s_gc_p > 0 else is_sma40_60_bull_120t

                is_sma40_60_cross_buy = (
                    (recent_sma40_60_gc or (is_sma40_60_bull_120t and price_near_sma_gc))
                    and is_tema5_20_bull_120t
                    and upper_shadow_ratio_120t <= 0.48
                )

                can_trigger_120t_buy = is_60m_sma20_support and (is_tema60_120_cross_buy or is_sma40_60_cross_buy)
            else:
                # 120틱 부재 시 60분봉 백업 지지/돌파
                gijun_breakout = (not np.isnan(gijun_line) and gijun_line > 0 and (gijun_line <= tick_close <= gijun_line * 1.035))
                can_trigger_120t_buy = is_bull_support and gijun_breakout
            
            if can_trigger_120t_buy:
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
                    self.position.last_gate_line = active_gate
                    self.position.last_gate_high = active_gate_high
                    self.position.last_gijun_line = active_gijun
                    self.position.state = StrategyState.FIRST_BUY_DONE

                    # 진입 시점에 이미 1번째 분홍 기준선 위인지 여부 기록
                    if not np.isnan(active_gijun) and active_gijun > 0 and buy_price >= active_gijun * 1.001:
                        self.position.first_gijun_cleared = True
                        self.position.cleared_gijun_price = active_gijun
                    else:
                        self.position.first_gijun_cleared = False
                        self.position.cleared_gijun_price = active_gijun if (not np.isnan(active_gijun) and active_gijun > 0) else 0.0
                    self.position.second_gijun_price = 0.0

                    alpha_tag = f"[지수초과강도 {day_alpha:+.2f}%p] " if day_alpha != 0.0 else ""
                    cond_tag = "🔔[실시간조건검색] " if is_condition_pick else ""
                    if is_tema60_120_cross_buy:
                        self.position.entry_mode = "TEMA60_120_GC"
                        self.position.first_cross_type = "TEMA60_120_GC"
                        self.position.first_cross_price = t_gc_p if t_gc_p > 0 else buy_price
                        trigger_str = f"120틱 테마 60이평선 > 120이평선 골든크로스(크로스가격: {self.position.first_cross_price:,.0f}원) 안착"
                    elif is_sma40_60_cross_buy:
                        self.position.entry_mode = "SMA40_60_GC"
                        self.position.first_cross_type = "SMA40_60_GC"
                        self.position.first_cross_price = s_gc_p if s_gc_p > 0 else buy_price
                        trigger_str = f"120틱 SMA 40이평선 > 60이평선 골든크로스(크로스가격: {self.position.first_cross_price:,.0f}원) 안착"
                    else:
                        self.position.entry_mode = "60M_GIJUN"
                        self.position.first_cross_type = "60M_GIJUN"
                        trigger_str = f"60분봉 기준선({gijun_line:,.0f}원) 초기 맥점 돌파"

                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_1",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"{cond_tag}{alpha_tag}{trigger_str} 1차 50% 매수 (체결가: {buy_price:,.0f}원)",
                        stage="FIRST_BUY_DONE"
                    )
                    self.trade_history.append(order)
                    return order

        # ─────────────────────────────────────────────────────────────
        # 2. FIRST_BUY_DONE 상태: 2차 매수 (50% 불타기 — 검정 점선 급등관문고가돌파선 확실한 돌파 확인)
        #    및 1차 물량 3단계 수익 잠금(Ratchet) 방어
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FIRST_BUY_DONE:
            # 1차 매수분 실시간 최고 수익률 추적 및 3단계 수익 잠금 래칫 활성화
            base_p1 = self.position.first_buy_price if self.position.first_buy_price > 0 else self.position.avg_price
            first_pnl = ((tick_close - base_p1) / base_p1) * 100.0 if base_p1 > 0 else 0.0
            if first_pnl > self.position.max_profit_pct:
                self.position.max_profit_pct = first_pnl
            # 소속 시장 선물지수 투매(CRASH_LOCK) 또는 08:45~08:49 프리마켓 마감 브릿지 구간에서는 +0.4%만 수익이어도 즉시 무위험 본절락 조기 가동!
            if futures_regime == "CRASH_LOCK" or is_premarket_bridge_window:
                bep_trigger_p1 = 0.4
            elif futures_regime == "CAUTION_DEFENSE":
                bep_trigger_p1 = 0.5
            else:
                bep_trigger_p1 = 0.8
            if self.position.max_profit_pct >= bep_trigger_p1:
                self.position.bep_locked = True

            # 1번째/2번째 분홍 기준선 상태 실시간 갱신
            if not np.isnan(active_gijun) and active_gijun > 0:
                if not self.position.first_gijun_cleared and tick_close >= active_gijun * 1.001:
                    self.position.first_gijun_cleared = True
                    self.position.cleared_gijun_price = active_gijun
                elif self.position.first_gijun_cleared and active_gijun > self.position.cleared_gijun_price * 1.002:
                    self.position.second_gijun_price = active_gijun

            # 🌟 [사용자 지정 2차 매수 불타기]:
            # 1차 매수가 테마 60-120 골든크로스 시점이었으면 ➔ SMA 40-60 이평선 골든크로스 발생 시점 2차 매수!
            # 1차 매수가 SMA 40-60 골든크로스 시점이었으면 ➔ 테마 60-120 이평선 골든크로스 발생 시점 2차 매수!
            is_breakout = False
            breakout_target = 0.0
            breakout_name = ""

            min_pyramiding_gap = (tick_close >= base_p1 * 1.002) if base_p1 > 0 else False
            is_solid_candle = (upper_shadow_ratio_120t <= 0.45)

            if has_120t_wave:
                s_gc_p = sma40_60_gc_price if (not np.isnan(sma40_60_gc_price) and sma40_60_gc_price > 0) else 0.0
                t_gc_p = tema60_120_gc_price if (not np.isnan(tema60_120_gc_price) and tema60_120_gc_price > 0) else 0.0

                if self.position.first_cross_type == "TEMA60_120_GC":
                    # 🥇 1차가 테마 60-120 크로스였으므로 ➔ SMA 40-60 골든크로스 발생 시점 2차 불타기 매수!
                    if min_pyramiding_gap and is_solid_candle and (recent_sma40_60_gc or is_sma40_60_bull_120t):
                        is_breakout = True
                        breakout_target = s_gc_p if s_gc_p > 0 else (base_p1 * 1.005)
                        breakout_name = f"120틱 SMA 40-60 골든크로스(크로스가격: {breakout_target:,.0f}원) 확증"
                elif self.position.first_cross_type == "SMA40_60_GC":
                    # 🥇 1차가 SMA 40-60 크로스였으므로 ➔ 테마 60-120 골든크로스 발생 시점 2차 불타기 매수!
                    if min_pyramiding_gap and is_solid_candle and (recent_tema60_120_gc or is_yellow_cloud_120t):
                        is_breakout = True
                        breakout_target = t_gc_p if t_gc_p > 0 else (base_p1 * 1.005)
                        breakout_name = f"120틱 테마 60-120 골든크로스(크로스가격: {breakout_target:,.0f}원) 확증"
                else:
                    # 듀얼 크로스 완성 확인 시 2차 불타기 매수
                    if min_pyramiding_gap and is_solid_candle and (recent_sma40_60_gc or recent_tema60_120_gc or (is_yellow_cloud_120t and is_sma40_60_bull_120t)):
                        is_breakout = True
                        breakout_target = base_p1 * 1.005
                        breakout_name = "120틱 테마60-120 & SMA40-60 듀얼 골든크로스 완성"
            else:
                # 120틱 부재 시 60분봉 1번째 분홍 기준선 돌파 백업
                if min_pyramiding_gap and not np.isnan(active_gijun) and active_gijun > base_p1 and tick_close >= active_gijun:
                    is_breakout = True
                    breakout_target = active_gijun
                    breakout_name = "1번째 분홍 기준선(M선) 돌파"

            # 🚨 소속 시장 선물지수가 폭락 투매 서킷브레이커(CRASH_LOCK) 상태일 때는 2차 불타기(BUY_2) 보류!
            if is_breakout and futures_regime != "CRASH_LOCK":
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
                    self.position.last_gate_high = active_gate_high
                    self.position.state = StrategyState.FULL_POSITION
                    
                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_2",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"{breakout_name} 2차 50% 불타기 매수 완료 (돌파선: {breakout_target:,.0f}원, 체결가: {buy_price:,.0f}원)",
                        stage="FULL_POSITION"
                    )
                    self.trade_history.append(order)
                    return order
            else:
                # 🛡️ [1차 매수 물량(50%) 전용 3단계 수익 잠금(Ratchet) + 노란색 관문선/M3선 손절 방어]:
                # 검정 점선(급등관문고가돌파선)을 뚫지 못하고 무너지더라도 50% 가벼운 비중 상태에서 신속히 수익 보존 또는 짧은 손절!
                if self.position.total_qty > 1:
                    holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0
                    is_recent_entry = (holding_sec < 180)
                    m3_thresh = day3_m_line * 0.995 if is_recent_entry else day3_m_line * 0.998
                    p_rate = first_pnl

                    is_first_exit = False
                    exit_action = "STOP_LOSS"
                    sl_reason = ""

                    # 1) 🎯 1차 매수분 고점 대비 트레일링 스탑 (+2.0% 이상 상승 후 고점 대비 -0.7% 되밀릴 시 확정 익절)
                    if self.position.max_profit_pct >= 2.0 and (self.position.max_profit_pct - p_rate) >= 0.7:
                        is_first_exit = True
                        exit_action = "TAKE_PROFIT"
                        sl_reason = (
                            f"🎯 [1차 매수분] 고점대비 트레일링 스탑 확정 익절 (최고수익: +{self.position.max_profit_pct:.2f}%, "
                            f"현재수익률: {p_rate:+.2f}%, 체결가: {tick_close:,.0f}원)"
                        )
                    # 2) 🔒 1차 매수분 무위험 본절/수익 보존 래칫 (+0.8% 도달 시 +0.25% 보존, +1.2% 도달 시 +0.60% 보존)
                    elif self.position.bep_locked and holding_sec >= 60.0 and base_p1 > 0:
                        if self.position.max_profit_pct >= 1.2:
                            bep_p1 = base_p1 * 1.0060
                            r_label = "1차물량 확정수익 보존락(+0.60%)"
                        else:
                            bep_p1 = base_p1 * 1.0025
                            r_label = "1차물량 무위험 본절락(+0.25% 수수료보존)"
                        if tick_close <= bep_p1:
                            is_first_exit = True
                            exit_action = "TAKE_PROFIT" if p_rate >= 0.2 else "STOP_LOSS"
                            sl_reason = (
                                f"🔒 [{r_label}] 발동 전량 청산 (1차매수가: {base_p1:,.0f}원, 보존선: {bep_p1:,.0f}원, "
                                f"체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"
                            )

                    # 3) 🌊 M/3 실시간 3일선 하향 이탈, 노란색 급등관문선 하향 이탈(-1.2%), 08:45~08:49 브릿지 탄력 둔화, 또는 🛑 -1.5% 하드 손절
                    if not is_first_exit:
                        if is_premarket_bridge_window and p_rate < 0.2 and (
                            is_tema_dead_5_20_120t or (not np.isnan(active_gate) and active_gate > 0 and tick_close < active_gate * 0.996)
                        ):
                            is_first_exit = True
                            exit_action = "TAKE_PROFIT" if p_rate >= 0 else "STOP_LOSS"
                            sl_reason = (
                                f"🌉 [08:45~08:49 프리마켓→KRX 브릿지 보호] 08:50 거래중단 전 탄력 둔화 1차 물량 선제 청산 "
                                f"(09:00 KRX 시초 갭하락 방어, 체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"
                            )
                        elif day3_m_line > 0 and tick_close < m3_thresh:
                            is_first_exit = True
                            exit_action = "TAKE_PROFIT" if p_rate >= 0 else "STOP_LOSS"
                            sl_reason = f"1차 매수 후 M/3 수식선({day3_m_line:,.0f}원) 하향 이탈 1차 물량 전량 청산 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"
                        elif not is_recent_entry and not np.isnan(active_gate) and active_gate > 0 and tick_close < active_gate * 0.988:
                            is_first_exit = True
                            exit_action = "TAKE_PROFIT" if p_rate >= 0 else "STOP_LOSS"
                            sl_reason = f"1차 매수 후 노란색 급등관문선({active_gate:,.0f}원) 지지 실패/검정점선 미돌파 전량 청산 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"
                        elif base_p1 > 0 and tick_close <= base_p1 * 0.985:
                            is_first_exit = True
                            exit_action = "STOP_LOSS"
                            sl_reason = f"1차 매수가 대비 -1.5% 하드 손절선 도달 1차 물량 전량 손절 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"

                    if is_first_exit:
                        sell_qty = self.position.total_qty
                        sell_amt = sell_qty * tick_close
                        self.cash += sell_amt
                        self.last_sell_time = time.time()
                        order = TradeOrder(
                            timestamp=timestamp,
                            action=exit_action,
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
        # 3. FULL_POSITION 상태: 1번째·2번째 분홍 기준선 파동 익절 법칙 + 6대 안전망 전량 매도
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
            # 소속 시장 선물지수 투매(CRASH_LOCK) 또는 08:45~08:49 프리마켓 마감 브릿지 구간에서는 +0.4%만 수익이어도 즉시 본절락 조기 장전!
            if futures_regime == "CRASH_LOCK" or is_premarket_bridge_window:
                full_bep_trigger = 0.4
            elif futures_regime == "CAUTION_DEFENSE":
                full_bep_trigger = 0.5
            else:
                full_bep_trigger = 0.6
            if self.position.max_profit_pct >= full_bep_trigger:
                self.position.bep_locked = True

            # 🛡️ 진입 직후 1~2틱 호가 노이즈 털림 방지 (최소 3분간 노이즈 버퍼 적용):
            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0
            is_recent_entry = (holding_sec < 180)
            m3_thresh = day3_m_line * 0.995 if is_recent_entry else day3_m_line * 0.998
            gijun_thresh = gijun_line * 0.993 if is_recent_entry else gijun_line * 0.995

            # 📈 [1번째 분홍 기준선 돌파 & 2번째 분홍 기준선 생성 추적]:
            if not np.isnan(active_gijun) and active_gijun > 0:
                if not self.position.first_gijun_cleared:
                    if tick_close >= active_gijun * 0.992:
                        self.position.touched_first_gijun = True
                    if tick_close >= active_gijun * 1.001:
                        self.position.first_gijun_cleared = True
                        self.position.cleared_gijun_price = active_gijun
                else:
                    # 이미 1번째 분홍 기준선을 돌파한 뒤 고점에서 새로운(더 높은) 2번째 분홍 기준선이 형성된 경우 기록!
                    if active_gijun > self.position.cleared_gijun_price * 1.002:
                        self.position.second_gijun_price = active_gijun

            # ─────────────────────────────────────────────────────────────
            # [통합 매도 원칙: 2번째/1번째 분홍 기준선 어깨 익절 + 6대 무결점 방어망]
            # ─────────────────────────────────────────────────────────────
            
            # 0-A) 🏆 [2번째 분홍색 기준선 돌파 실패(쌍봉 저항) 어깨 전량 익절]:
            #      1번째 기준선 돌파 후 고점에 새로 형성된 2번째 분홍 기준선(second_gijun_price)을 넘지 못하고
            #      120틱 테마5 < 테마20 데드크로스(또는 고점 대비 -0.5%p 되밀림)가 발생할 때 최고점 어깨에서 즉시 전량 익절!
            if (
                self.position.second_gijun_price > 0
                and tick_close <= self.position.second_gijun_price * 1.002
                and (is_tema_dead_5_20_120t or (self.position.max_profit_pct - profit_rate) >= 0.5)
            ):
                is_sell_signal = True
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"🏆 [2번째 분홍 기준선({self.position.second_gijun_price:,.0f}원) 돌파 실패 & 테마 꺾임] "
                    f"어깨 최고점 전량 익절 (1번째 돌파선: {self.position.cleared_gijun_price:,.0f}원, "
                    f"현재가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )

            # 0-B) 🏛️ [1번째 분홍색 기준선 저항 돌파 실패 익절/청산]:
            #      바닥(노란선+검정점선) 매집 후 1번째 분홍 기준선 부근까지 도달(touched_first_gijun)했으나
            #      돌파하지 못하고 테마5 < 테마20 데드크로스와 함께 기준선 대비 -0.7% 아래로 꺾일 때 즉시 전량 청산!
            elif (
                not self.position.first_gijun_cleared
                and self.position.touched_first_gijun
                and not np.isnan(active_gijun)
                and active_gijun > 0
                and tick_close < active_gijun * 0.993
                and is_tema_dead_5_20_120t
            ):
                is_sell_signal = True
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"🏛️ [1번째 분홍 기준선({active_gijun:,.0f}원) 저항 돌파 실패 & 테마 5-20 꺾임] "
                    f"즉시 전량 청산 (현재가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )

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

            if not is_sell_signal and self.position.bep_locked and sec_buy_elapsed >= 60.0 and tick_close <= bep_price:
                is_sell_signal = True
                action_type = "TAKE_PROFIT" if profit_rate >= 0.2 else "STOP_LOSS"
                sell_reason = (
                    f"🔒 {ratchet_label}(BEP Profit Ratchet) 발동: 전량 매도 "
                    f"(매수가: {self.position.avg_price:,.0f}원, 보존선: {bep_price:,.0f}원, 체결가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )

            # 2) 🎯 [Tier 3 고점 대비 트레일링 스탑]: +2.0% 이상 상승 후 고점 대비 -0.7% 되밀릴 시 확정 익절
            elif not is_sell_signal and self.position.max_profit_pct >= 2.0 and (self.position.max_profit_pct - profit_rate) >= 0.7:
                is_sell_signal = True
                action_type = "TAKE_PROFIT"
                sell_reason = (
                    f"🎯 고점대비 트레일링 스탑 확정 익절 (최고수익: +{self.position.max_profit_pct:.2f}%, "
                    f"고점대비 되밀림: -{(self.position.max_profit_pct - profit_rate):.2f}%, 현재수익률: {profit_rate:+.2f}%)"
                )

            # 3) 📉 [120틱 WMA60 피크 하락반전/데드크로스 청산 (실시간 tick_close 반영)]
            elif not is_sell_signal and kwargs.get('df_120t') is not None and len(kwargs.get('df_120t')) >= 65 and not is_recent_entry:
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

            # 5) 🏛️ [1번째 기준선 돌파 후 재이탈 또는 노란색 급등관문선 하향 이탈 매도]
            elif not is_sell_signal:
                if self.position.first_gijun_cleared and self.position.cleared_gijun_price > 0 and tick_close < self.position.cleared_gijun_price * 0.993:
                    is_sell_signal = True
                    action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                    sell_reason = (
                        f"🏛️ 돌파 완료한 1번째 분홍 기준선({self.position.cleared_gijun_price:,.0f}원) 하향 이탈 즉시 전량 매도 "
                        f"(현재가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                    )
                elif not self.position.first_gijun_cleared and self.position.entry_mode == "" and not np.isnan(gijun_line) and gijun_line > 0 and tick_close < gijun_thresh:
                    # 기존 계좌 보유분(entry_mode == "")에 대한 60분봉 기준선 변곡선 이탈 감시 유지
                    is_sell_signal = True
                    diff_pct = ((tick_close - gijun_line) / gijun_line) * 100.0
                    action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                    sell_reason = (
                        f"🏛️ 60분봉 기준선 변곡선({gijun_line:,.0f}원) 미돌파/하향 이탈 즉시 전량 매도 "
                        f"(현재가: {exit_price:,.0f}원, 기준선대비: {diff_pct:+.2f}%, 수익률: {profit_rate:+.2f}%)"
                    )
                elif not is_recent_entry and not np.isnan(active_gate) and active_gate > 0 and tick_close < active_gate * 0.988:
                    is_sell_signal = True
                    action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                    sell_reason = (
                        f"🛡️ 노란색 급등관문선({active_gate:,.0f}원) 바닥 지지선 하향 이탈 전량 매도 "
                        f"(현재가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                    )

            # 6) 🌉 [08:45~08:49 프리마켓→KRX 브릿지 보호 청산] & 🛑 [하드 리스크 방어 손절선 (-1.5%)]
            if not is_sell_signal and is_premarket_bridge_window and profit_rate < 0.2 and (
                is_tema_dead_5_20_120t or (not np.isnan(active_gate) and active_gate > 0 and tick_close < active_gate * 0.996)
            ):
                is_sell_signal = True
                action_type = "TAKE_PROFIT" if profit_rate >= 0 else "STOP_LOSS"
                sell_reason = (
                    f"🌉 [08:45~08:49 프리마켓→KRX 브릿지 보호] 08:50 거래중단 전 탄력 둔화 전량 선제 청산 "
                    f"(09:00 KRX 시초 갭하락 방어, 현재가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )

            if not is_sell_signal and tick_close <= self.position.avg_price * 0.985:
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

