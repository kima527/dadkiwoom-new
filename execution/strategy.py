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
    low_5m: float = 0.0                 # 첫 5분봉 저가 (제1전략 손절선 기준)
    open_5m: float = 0.0                # 첫 5분봉 시가 (제1전략 지지선 기준)
    trade_count_today: int = 0          # 당일 매매 완료 횟수 (제1전략 ➔ 제2전략 회전 전환용)

class ThemeGate60mStrategy:
    """
    60분봉 테마급등관문선 & 테마기준선 분할/순환 매매 전략 엔진
    """
    def __init__(self, initial_capital: float = 10_000_000, 
                 gate_sl_pct: float = 0.015,
                 max_reentry: int = 0,
                 fixed_qty: int = 2):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.gate_sl_pct = gate_sl_pct
        self.max_reentry = max_reentry
        self.fixed_qty = fixed_qty
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
        t60 = 0.0
        t120 = 0.0
        is_tema60_120_dead = False

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
                t60 = float(last_120t.get('tema60', np.nan))
                t120 = float(last_120t.get('tema120', np.nan))
                recent_tema60_120_dc = bool(df_120t_calc['is_tema60_120_dc'].tail(3).any()) if 'is_tema60_120_dc' in df_120t_calc else False
                is_tema60_120_dead = bool((t60 < t120) or recent_tema60_120_dc) if (not np.isnan(t60) and not np.isnan(t120)) else False

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
            if futures_regime == "CRASH_LOCK" or is_premarket_bridge_window:
                return None

            # 🛡️ 매도 직후 재매수 방지 쿨다운 (3분 동일 종목 재진입 휩소 방어)
            if self.last_sell_time > 0 and (time.time() - self.last_sell_time < 180):
                return None

            open_5m = float(kwargs.get('open_5m', 0.0) or 0.0)
            low_5m = float(kwargs.get('low_5m', 0.0) or 0.0)
            day_open_val = float(kwargs.get('day_open', 0.0) or open_price or 0.0)
            ask_bid_ratio = float(kwargs.get('ask_bid_ratio', 1.0) or 1.0)
            is_first_strategy = bool(kwargs.get('is_first_strategy', False))

            entry_mode_tag = "120T_TEMA"
            trigger_str = ""
            can_trigger_buy = False
            t_gc_p = 0.0

            # ═════════════════════════════════════════════════════════════════
            # 👑 [제1전략: 09:00:45~09:30 시초가 번개돌파 & 첫 5분봉 앵커 스나이핑 — JYP Ent. 모델]
            # ═════════════════════════════════════════════════════════════════
            # 09:00:45 이후 포착된 주도주는 120틱 60>120 정배열 상승추세가 이미 '기정사실'!
            # 장초반 미완성 60분봉 윗꼬리 노이즈나 일봉 5<20 제약을 전면 면제하고,
            # 당일 시가 및 5분봉 저가 지지 안착 & 당일 시가 위 붉은 양봉 사수 확인 시 2주 즉시 스나이핑!
            is_stage1_mode = (
                is_first_strategy
                and self.position.trade_count_today == 0
                and (open_5m > 0 or low_5m > 0 or day_open_val > 0)
            )

            if is_stage1_mode:
                ref_low = low_5m if low_5m > 0 else (open_5m if open_5m > 0 else day_open_val)
                ref_open = day_open_val if day_open_val > 0 else (open_5m if open_5m > 0 else tick_close)

                # 🎯 [시초가 번개돌파(09:02:37) 및 5분봉 지지반등(09:08:22) 정밀 매수 기준]:
                # 1) 기준 저가(ref_low)를 거래량 실려 깨지 않고 사수 (-0.5% 오차 허용)
                holds_5m_low = (ref_low > 0 and tick_close >= ref_low * 0.995)
                # 2) 당일 시가(ref_open) 위 붉은 양봉 사수 (-0.3% 이내 지지 반등)
                holds_day_open = (ref_open > 0 and tick_close >= ref_open * 0.997)
                # 3) 장초반 건전한 상승/눌림목 구간 (시가 대비 +7.0% 이하 안정적 안착, 뇌동 과열 방지)
                not_too_overheated = (ref_open > 0 and tick_close <= ref_open * 1.070)
                # 4) 호가창 수급: 매수세가 적극 유입되는 구간 (매도/매수비 0.70 이상)
                is_hoga_active = (ask_bid_ratio >= 0.70)
                # 5) 120틱 실시간 캔들 순도 (120틱 윗꼬리 60% 이하)
                is_120t_clean = (upper_shadow_ratio_120t <= 0.60)

                if holds_5m_low and holds_day_open and not_too_overheated and is_hoga_active and is_120t_clean:
                    can_trigger_buy = True
                    entry_mode_tag = "STAGE1_5M_ANCHOR"
                    diff_open_pct = ((tick_close - ref_open) / ref_open * 100.0) if ref_open > 0 else 0.0
                    trigger_str = (
                        f"👑 [시초 번개돌파 & 5분봉 앵커] 기준저가({ref_low:,.0f}원) 지지 안착 & "
                        f"당일시가({ref_open:,.0f}원, {diff_open_pct:+.2f}%) 붉은 양봉 사수 2주 즉시 스나이핑"
                    )

            # ═════════════════════════════════════════════════════════════════
            # ⚡ [제2전략: 1차 매도 후 회전 매매 — 120틱 관문선 저점 정석 타점]
            # ═════════════════════════════════════════════════════════════════
            # 1차 매매 완료 후(trade_count_today >= 1) 또는 Stage 1 미해당 일반 장중 타점
            if not can_trigger_buy:
                # 🏆 [금일 시장 지수 대비 상대강도(RS Alpha) 필수 필터]:
                if not is_outperforming_index:
                    return None

                if not daily_bull:
                    return None  # 일봉이 하락 추세(5<20)일 때는 신규 1차 매수 진입 차단

                # 🛡️ [매수 필수 방어벽]: M/3 실시간 3일선 상단 지지 확인
                if day3_m_line > 0 and tick_close < day3_m_line:
                    return None

                # 🛡️ [시가 훼손 방어벽]: 당일 시가 아래로 밀린 파란 음봉 매수 차단
                open_p = float(row.get('open', tick_close))
                if open_p > 0 and tick_close < open_p:
                    return None

                # 🛡️ [60분봉 윗꼬리 매물폭탄 방어벽]: 60분봉 고점 대비 윗꼬리 비율 45% 초과 차단
                c_range = max(float(high) - float(low), 1.0)
                upper_shadow = max(float(high) - max(open_p, tick_close), 0.0)
                if (upper_shadow / c_range) > 0.45:
                    return None

                # 🛡️ [기준선 과열 추격매수 차단]: 유효 기준선 대비 +4.5% 초과 이격 과열 시 차단
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

                # ⚡ 제2전략: 120틱 테마 60-120 골든크로스 & 테마 5-20 관문선 저점 안착 매수
                if has_120t_wave:
                    t_gc_p = tema60_120_gc_price if (not np.isnan(tema60_120_gc_price) and tema60_120_gc_price > 0) else 0.0
                    has_tema60_120_crossed = (recent_tema60_120_gc or is_yellow_cloud_120t)
                    is_near_gate_floor = (
                        not np.isnan(active_gate) and active_gate > 0
                        and (active_gate * 0.992 <= tick_close <= active_gate * 1.010)
                    )
                    if has_tema60_120_crossed and is_near_gate_floor and upper_shadow_ratio_120t <= 0.50:
                        can_trigger_buy = is_60m_sma20_support
                        entry_mode_tag = "STAGE2_120T_GATE"
                        gate_diff = ((tick_close - active_gate) / active_gate * 100.0) if (not np.isnan(active_gate) and active_gate > 0) else 0.0
                        trigger_str = (
                            f"⚡ [Top5 풀 제2전략] 120틱 테마 60-120 골든크로스 확인 후 "
                            f"테마 5-20 관문선({active_gate:,.0f}원, 이격 {gate_diff:+.2f}%) 저점 2주 회전 매수"
                        )

            if can_trigger_buy:
                buy_price = tick_close
                if getattr(self, 'fixed_qty', 0) > 0:
                    qty = self.fixed_qty  # 🌟 [대표님 지시]: 2주 고정 실전 매매 (계좌 예수금 조회 TR 생략)
                    cost = qty * buy_price
                else:
                    budget = self.cash * 0.99  # 저점(테마 5-20 관문선)에서 100% 풀포지션 일괄 매수
                    qty = int(budget // buy_price)
                    cost = qty * buy_price
                if qty > 0:
                    self.cash = max(0.0, self.cash - cost)
                    self.position.total_qty = qty
                    self.position.avg_price = buy_price
                    self.position.first_buy_price = buy_price
                    self.position.first_buy_qty = qty
                    self.position.entry_time = time.time()
                    self.position.last_gate_line = active_gate
                    self.position.last_gate_high = active_gate_high
                    self.position.last_gijun_line = active_gijun
                    self.position.state = StrategyState.FULL_POSITION  # 저점에서 100% 풀포지션 완료!
                    self.position.entry_mode = entry_mode_tag
                    self.position.low_5m = ref_low if ref_low > 0 else (low_5m if low_5m > 0 else buy_price * 0.992)
                    self.position.open_5m = ref_open if ref_open > 0 else buy_price

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
                    self.position.first_cross_type = "TEMA60_120_GC"
                    self.position.first_cross_price = t_gc_p if t_gc_p > 0 else buy_price
                    gate_diff = ((buy_price - active_gate) / active_gate * 100.0) if (not np.isnan(active_gate) and active_gate > 0) else 0.0
                    if not trigger_str:
                        trigger_str = (
                            f"120틱 테마 60-120 골든크로스 확인 후 첫 눌림목 "
                            f"테마 5-20 관문선({active_gate:,.0f}원, 이격 {gate_diff:+.2f}%) 초근접 저점 2주 매수"
                        )

                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_1",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"{cond_tag}{alpha_tag}{trigger_str} (체결가: {buy_price:,.0f}원)",
                        stage="FULL_POSITION"
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

            # 🌟 [대표님 지시]: 저점(테마 5-20 관문선)에서 계속 매수하여 100% 풀포지션 채우기!
            #    느린 SMA 골든크로스를 기다리지 않고, 저점선 지지 확인 시 잔여 예수금으로 즉시 100% 풀매수 완성!
            if has_120t_wave and is_near_gate_floor and self.cash > 0 and futures_regime != "CRASH_LOCK":
                is_breakout = True
                breakout_target = active_gate
                breakout_name = f"테마 5-20 관문선({active_gate:,.0f}원) 저점 추가 매수 100% 완성"
            elif has_120t_wave:
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
                if getattr(self, 'fixed_qty', 0) > 0:
                    qty = self.fixed_qty  # 🌟 [대표님 지시]: 2주 고정 실전 매매
                else:
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
                    self.cash = max(0.0, self.cash - cost)
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
                # 🛡️ [기존 계좌 보유 자산 절대 보호 원칙]
                # 봇이 진입한 포지션(entry_mode != "")이 아니면 1차 매수 청산 평가를 수행하지 않음
                if not self.position.entry_mode:
                    return None

                # 👑 [대표님 지시 확정]: 1차 매수분 매도 로직도 '120틱 테마 60-120 데드크로스'로 전면 일원화!
                if self.position.total_qty > 1:
                    holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0
                    p_rate = first_pnl

                    is_first_exit = False
                    exit_action = "STOP_LOSS"
                    sl_reason = ""

                    # 1. ⚡ [최우선 핵심 매도]: 120틱 테마 60-120 데드크로스 (TEMA 60 < TEMA 120)
                    if holding_sec >= 30.0 and is_tema60_120_dead:
                        is_first_exit = True
                        exit_action = "TAKE_PROFIT" if p_rate >= 0.0 else "STOP_LOSS"
                        sl_reason = (
                            f"⚡ [테마 60-120 데드크로스 일원화 매도] 120틱 테마60({t60:,.0f}원) < 테마120({t120:,.0f}원) "
                            f"데드크로스 발생 1차 물량 전량 매도 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"
                        )
                    # 2. 🛑 [비상 하드 방어선]: 만약의 급락 시 계좌 보호용 -2.5% 방어
                    elif base_p1 > 0 and tick_close <= base_p1 * 0.975:
                        is_first_exit = True
                        exit_action = "STOP_LOSS"
                        sl_reason = f"🛑 [비상 하드 방어선] -2.5% 도달 1차 물량 전량 손절 (체결가: {tick_close:,.0f}원, 수익률: {p_rate:+.2f}%)"

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
                        prev_trades = self.position.trade_count_today + 1
                        self.position = PositionTracker()
                        self.position.trade_count_today = prev_trades
                        return order

        # ─────────────────────────────────────────────────────────────
        # 3. FULL_POSITION 상태: [대표님 지시 확정] 120틱 테마 60-120 데드크로스 전면 일원화 매도
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FULL_POSITION:
            # 🛡️ [계좌 기존 보유 자산 절대 보호 원칙]
            # 봇이 진입한 포지션(entry_mode != "")이 아니거나 1주 이하이면 매도 신호 생성 절대 차단 (자산 100% 보존)
            if not self.position.entry_mode or self.position.total_qty <= 1:
                return None

            is_sell_signal = False
            sell_reason = ""
            action_type = "TAKE_PROFIT"
            exit_price = tick_close

            # 현재 수익률 계산 및 최고 수익률 추적 (ZeroDivisionError 원천 방어)
            profit_rate = ((exit_price - self.position.avg_price) / self.position.avg_price) * 100.0 if self.position.avg_price > 0 else 0.0
            if profit_rate > self.position.max_profit_pct:
                self.position.max_profit_pct = profit_rate

            # 👑 [대표님 지시 확정]: 매도 로직 '120틱 테마 60-120 데드크로스'로 전면 일원화!
            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0

            # 1. ⚡ [최우선 핵심 매도]: 120틱 테마 60-120 데드크로스 (TEMA 60 < TEMA 120)
            if not is_sell_signal and holding_sec >= 30.0 and is_tema60_120_dead:
                is_sell_signal = True
                action_type = "TAKE_PROFIT" if profit_rate >= 0.0 else "STOP_LOSS"
                sell_reason = (
                    f"⚡ [테마 60-120 데드크로스 일원화 매도] 120틱 테마60({t60:,.0f}원) < 테마120({t120:,.0f}원) "
                    f"데드크로스 발생 전량 매도 (체결가: {exit_price:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
            # 2. 🛑 [비상 하드 방어선]: 만약의 급락 시 계좌 보호용 -2.5% 방어
            elif not is_sell_signal and tick_close <= self.position.avg_price * 0.975:
                is_sell_signal = True
                action_type = "STOP_LOSS"
                sell_reason = (
                    f"🛑 [비상 하드 방어선] -2.5% 도달 계좌 보호 전량 손절 "
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
                # 재매수 없이 즉시 전량 청산 완료 및 포지션 초기화 (IDLE 복귀, 당일 매매횟수 누적)
                prev_trades = self.position.trade_count_today + 1
                self.position = PositionTracker()
                self.position.trade_count_today = prev_trades
                return order

        return None

