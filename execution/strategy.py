from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import time
import pandas as pd
import numpy as np

try:
    from indicators import calculate_day3_m_line, calculate_120t_tema_indicators, check_daily_ma3_5_eligible
except ImportError:
    from execution.indicators import calculate_day3_m_line, calculate_120t_tema_indicators, check_daily_ma3_5_eligible

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
    tema60_bull_armed: bool = False     # 매수 진입 이후 120틱 테마60 > 테마120 정배열 안착 확인 여부 (사자마자 즉시 매도 원천 방지)
    tema15_120_armed: bool = False      # 매수 진입 이후 120틱 테마15 >= 테마120 안착 확인 여부
    watch_initialized: bool = False     # 120틱 관찰 시작 기록 여부 (포착 즉시 매수 차단용)
    watch_start_bar_key: str = ""       # 관찰 시작 시점 120틱 마지막 봉 식별자
    saw_decline_phase: bool = False     # 관찰 이후 120틱 하락(파란색 음운: TEMA60 < TEMA120) 경유 확인 여부
    saw_15_30_cooling: bool = False     # 관찰 이후 120틱 단기 눌림/조정(TEMA15 <= TEMA30) 확인 여부
    peak_price_since_watch: float = 0.0 # IDLE 관찰 기간 최고가

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

    def _update_idle_decline_phase(
        self,
        df_120t: Optional[pd.DataFrame],
        df_120t_calc: pd.DataFrame,
        tick_close: float
    ) -> None:
        """
        조건검색 포착 즉시 매수('이미 진행 중인 15>30 추격 매수')를 방지하고,
        관찰 시작 이후 120틱 하락(파란색 음운: 60<120) 또는 단기 눌림(15<=30) 경유 여부를 추적.
        """
        if df_120t_calc is None or df_120t_calc.empty:
            return

        ts_list = None
        if df_120t is not None and len(df_120t) == len(df_120t_calc):
            if 'time' in df_120t.columns:
                ts_list = df_120t['time'].astype(str).str[:19].tolist()
            elif isinstance(df_120t.index, pd.DatetimeIndex):
                ts_list = df_120t.index.strftime('%Y-%m-%d %H:%M:%S').tolist()

        if ts_list:
            last_ts = ts_list[-1]
            same_last_cnt = sum(1 for t in ts_list if t == last_ts)
            cur_key = f"TS|{last_ts}|{same_last_cnt}"
        else:
            cur_key = f"IDX|{len(df_120t_calc)}"

        last_row = df_120t_calc.iloc[-1]
        cur_yellow = bool(last_row.get('is_yellow_cloud', False))
        t60_val = float(last_row.get('tema60', np.nan))
        t120_val = float(last_row.get('tema120', np.nan))
        t15_val = float(last_row.get('tema15', np.nan))
        t30_val = float(last_row.get('tema30', np.nan))
        cur_clear_blue = (not cur_yellow) and (
            np.isnan(t60_val) or np.isnan(t120_val) or t120_val <= 0 or t60_val < t120_val * 0.9998
        )
        cur_15_cooling = (
            not np.isnan(t15_val) and not np.isnan(t30_val) and t15_val <= t30_val
        )

        if not self.position.watch_initialized:
            self.position.watch_initialized = True
            self.position.watch_start_bar_key = cur_key
            self.position.peak_price_since_watch = tick_close
            self.position.saw_decline_phase = bool(cur_clear_blue)
            self.position.saw_15_30_cooling = bool(cur_15_cooling)
            return

        if tick_close > self.position.peak_price_since_watch:
            self.position.peak_price_since_watch = tick_close

        if cur_clear_blue:
            self.position.saw_decline_phase = True
        if cur_15_cooling:
            self.position.saw_15_30_cooling = True

        if self.position.saw_decline_phase and self.position.saw_15_30_cooling:
            return

        # 3~5초 폴링 사이클 사이에 발생한 단기 눌림(15<=30) 또는 음운(60<120) 구간까지 타임스탬프 기준으로 누락 없이 포착
        start_key = str(self.position.watch_start_bar_key or "")
        if ts_list and start_key.startswith("TS|"):
            parts = start_key.split("|")
            if len(parts) == 3:
                start_ts = parts[1]
                start_cnt = int(parts[2])
                seen_same = 0
                after_indices = []
                for idx_pos, t_str in enumerate(ts_list):
                    if t_str > start_ts:
                        after_indices.append(idx_pos)
                    elif t_str == start_ts:
                        seen_same += 1
                        if seen_same > start_cnt:
                            after_indices.append(idx_pos)
                if after_indices:
                    post_df = df_120t_calc.iloc[after_indices]
                    blue_mask = ~post_df['is_yellow_cloud'].astype(bool)
                    deep_blue = (post_df['tema60'] < post_df['tema120'] * 0.9995)
                    if int(blue_mask.sum()) >= 2 or bool((blue_mask & deep_blue).any()):
                        self.position.saw_decline_phase = True
                    if 'is_tema15_30_bull' in post_df.columns and bool((~post_df['is_tema15_30_bull'].astype(bool)).any()):
                        self.position.saw_15_30_cooling = True
        elif start_key.startswith("IDX|"):
            try:
                start_len = int(start_key.split("|")[1])
                if len(df_120t_calc) > start_len:
                    post_df = df_120t_calc.iloc[-(len(df_120t_calc) - start_len):]
                    blue_mask = ~post_df['is_yellow_cloud'].astype(bool)
                    if bool(blue_mask.any()):
                        self.position.saw_decline_phase = True
                    if 'is_tema15_30_bull' in post_df.columns and bool((~post_df['is_tema15_30_bull'].astype(bool)).any()):
                        self.position.saw_15_30_cooling = True
            except Exception:
                pass
        
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
        is_condition_pick = bool(kwargs.get('is_condition_pick', False))
        day_alpha = float(kwargs.get('day_alpha', 0.0) or 0.0)
        is_replacement_mode = bool(kwargs.get('is_replacement_mode', False))
        allow_new_buys = bool(kwargs.get('allow_new_buys', True))

        day_ret_kw = kwargs.get('day_ret_pct', None)
        if day_ret_kw is not None:
            day_ret_pct = float(day_ret_kw)
        elif pred1 > 0:
            day_ret_pct = ((tick_close - pred1) / pred1) * 100.0
        else:
            day_ret_pct = 0.0

        daily_3_5_kw = kwargs.get('is_daily_3_5_eligible', None)
        if daily_3_5_kw is not None:
            is_daily_3_5_ok = bool(daily_3_5_kw)
            daily_3_5_label = str(kwargs.get('daily_3_5_label', '일봉 3-5 충족'))
        else:
            is_daily_3_5_ok, daily_3_5_label = check_daily_ma3_5_eligible(df_daily, tick_close)

        has_120t_wave = False
        df_120t_calc = None
        gate_120t = np.nan
        gate_high_120t = np.nan
        gijun_120t = np.nan
        is_gate_up_120t = False
        recent_gate_cross_up_120t = False
        is_yellow_cloud_120t = False
        recent_tema60_120_gc = False
        tema60_120_gc_price = np.nan
        recent_sma40_60_gc = False
        is_sma40_60_bull_120t = False
        sma40_60_gc_price = np.nan
        upper_shadow_ratio_120t = 0.0
        t5 = np.nan
        t15 = np.nan
        t20 = np.nan
        t30 = np.nan
        t60 = 0.0
        t120 = 0.0
        is_tema60_120_dead = False
        bars_since_gc = np.nan
        is_tema60_rising = False
        is_tema15_30_bull = False
        is_tema15_30_gc_bar = False
        is_tema15_30_dc_bar = False
        is_tema15_30_dead = False
        is_tema15_120_dc_bar = False
        is_tema15_120_dead = False
        is_tema15_rising = False
        bars_since_15_30_gc = np.nan
        tema15_30_gc_price = np.nan

        if df_120t is not None and not df_120t.empty and len(df_120t) >= 25 and 'close' in df_120t:
            df_120t_calc = calculate_120t_tema_indicators(df_120t, current_price=tick_close)
            if not df_120t_calc.empty:
                has_120t_wave = True
                last_120t = df_120t_calc.iloc[-1]
                gate_120t = float(last_120t.get('theme_gate', np.nan))
                gate_high_120t = float(last_120t.get('theme_gate_high', np.nan))
                gijun_120t = float(last_120t.get('theme_gijun', np.nan))
                is_gate_up_120t = bool(last_120t.get('gate_up_turnaround', False))
                recent_gate_cross_up_120t = bool(df_120t_calc['gate_cross_up'].tail(5).any()) if 'gate_cross_up' in df_120t_calc else False
                is_yellow_cloud_120t = bool(last_120t.get('is_yellow_cloud', False))
                t5 = float(last_120t.get('tema5', np.nan))
                t15 = float(last_120t.get('tema15', np.nan))
                t20 = float(last_120t.get('tema20', np.nan))
                t30 = float(last_120t.get('tema30', np.nan))
                t60 = float(last_120t.get('tema60', np.nan))
                t120 = float(last_120t.get('tema120', np.nan))
                is_tema60_120_dead = bool(t60 < t120 * 0.9995) if (not np.isnan(t60) and not np.isnan(t120) and t120 > 0) else False
                bars_since_gc = float(last_120t.get('bars_since_tema60_120_gc', np.nan))
                is_tema60_rising = bool(last_120t.get('is_tema60_rising', False))
                is_tema15_30_bull = bool(last_120t.get('is_tema15_30_bull', False))
                is_tema15_30_gc_bar = bool(last_120t.get('is_tema15_30_gc', False))
                is_tema15_30_dc_bar = bool(last_120t.get('is_tema15_30_dc', False))
                is_tema15_rising = bool(last_120t.get('is_tema15_rising', False))
                bars_since_15_30_gc = float(last_120t.get('bars_since_tema15_30_gc', np.nan))
                tema15_30_gc_price = float(last_120t.get('tema15_30_gc_price', np.nan))
                is_tema15_30_dead = bool(
                    is_tema15_30_dc_bar
                    or (not np.isnan(t15) and not np.isnan(t30) and t30 > 0 and t15 < t30)
                )
                is_tema15_120_dc_bar = bool(last_120t.get('is_tema15_120_dc', False))
                is_tema15_120_dead = bool(
                    is_tema15_120_dc_bar
                    or (not np.isnan(t15) and not np.isnan(t120) and t120 > 0 and t15 < t120)
                )

                recent_tema60_120_gc = bool(df_120t_calc['is_tema60_120_gc'].tail(8).any()) if 'is_tema60_120_gc' in df_120t_calc else False
                tema60_120_gc_price = float(last_120t.get('tema60_120_gc_price', np.nan))

                is_sma40_60_bull_120t = bool(last_120t.get('is_sma40_60_bull', False))
                recent_sma40_60_gc = bool(df_120t_calc['is_sma40_60_gc'].tail(5).any()) if 'is_sma40_60_gc' in df_120t_calc else False
                sma40_60_gc_price = float(last_120t.get('sma40_60_gc_price', np.nan))

                h_120 = float(last_120t.get('high', tick_close))
                l_120 = float(last_120t.get('low', tick_close))
                o_120 = float(last_120t.get('open', tick_close))
                rng_120 = max(h_120 - l_120, 1.0)
                upper_shadow_ratio_120t = max(h_120 - max(o_120, tick_close), 0.0) / rng_120

        # 유효 관문선(노란선) · 관문고가선(검정점선) · 기준선(분홍선) 결정 (120틱 우선, 부재 시 60분봉 연동)
        active_gate = gate_120t if (has_120t_wave and not np.isnan(gate_120t) and gate_120t > 0) else gate_line
        active_gate_high = gate_high_120t if (has_120t_wave and not np.isnan(gate_high_120t) and gate_high_120t > 0) else gate_high
        active_gijun = gijun_120t if (has_120t_wave and not np.isnan(gijun_120t) and gijun_120t > 0) else gijun_line

        if self.position.state == StrategyState.TERMINATED:
            self.position = PositionTracker()

        # ─────────────────────────────────────────────────────────────
        # 1. IDLE 상태: 1차 매수 (일봉 자격 / 교체 상승률<=20% 확인 후 120틱 60-120 GC + 관문선 진입)
        # ─────────────────────────────────────────────────────────────
        if self.position.state == StrategyState.IDLE:
            # 🔍 조건검색 포착 즉시('뜨자마자') 매수 방지용 120틱 하락(파란색 음운) 추적
            if has_120t_wave and df_120t_calc is not None:
                self._update_idle_decline_phase(df_120t, df_120t_calc, tick_close)

            # ⏰ [14:30 이후 신규 매수 종료]
            if not allow_new_buys:
                return None

            # 🛡️ 매도 직후 재매수 방지 쿨다운 (20초 동일 종목 체결 안정화 대기)
            if self.last_sell_time > 0 and (time.time() - self.last_sell_time < 20):
                return None

            open_5m = float(kwargs.get('open_5m', 0.0) or 0.0)
            low_5m = float(kwargs.get('low_5m', 0.0) or 0.0)
            day_open_val = float(kwargs.get('day_open', 0.0) or open_price or 0.0)
            ref_low = low_5m if low_5m > 0 else (open_5m if open_5m > 0 else day_open_val)
            ref_open = day_open_val if day_open_val > 0 else (open_5m if open_5m > 0 else tick_close)

            # 📋 [1단계: 종목 진입 자격 확인]
            # - 최초 매수전략: 일봉 3-5 골든크로스 OR 3>5 정배열 확인
            # - 매도 후 다른 종목 교체 순환매매: 상승률 20% 이하이면 모두 진입 가능
            if not is_replacement_mode:
                if not is_daily_3_5_ok:
                    return None
                qual_tag = f"[{daily_3_5_label}] "
            else:
                if day_ret_pct > 20.0:
                    return None
                qual_tag = f"[순환교체(등락률 {day_ret_pct:+.2f}%<=20%)] "

            # ⚡ [2단계: 실제 매수 집행 = 120틱 기준 (테마 60>120 or 60-120골든크로스) & 테마 15-30 골든크로스 시 매수]
            if not has_120t_wave or is_tema60_120_dead or not is_yellow_cloud_120t:
                return None

            is_60_gt_120 = (not np.isnan(t60) and not np.isnan(t120) and t120 > 0 and t60 > t120)
            is_fresh_60_120_gc = (not np.isnan(bars_since_gc) and bars_since_gc <= 3)
            if not (is_60_gt_120 or is_fresh_60_120_gc):
                return None

            if not is_tema15_30_bull or is_tema15_30_dead:
                return None

            require_post_decline_gc = bool(kwargs.get('require_post_decline_gc', True))
            if require_post_decline_gc and not self.position.saw_15_30_cooling:
                return None

            # ① 60>120 또는 60-120 GC 상태에서 15-30 골든크로스 막 발생(0~3봉)
            # ② 바닥에서 15-30 GC(<=10봉)가 선행하고 60-120 골든크로스(0~2봉)가 방금 합류 완성된 경우
            is_fresh_15_30_gc = is_tema15_30_gc_bar or (not np.isnan(bars_since_15_30_gc) and bars_since_15_30_gc <= 3)
            is_dual_gc_confirm = (
                (not np.isnan(bars_since_gc) and bars_since_gc <= 2)
                and (not np.isnan(bars_since_15_30_gc) and bars_since_15_30_gc <= 10)
            )
            if not (is_fresh_15_30_gc or is_dual_gc_confirm):
                return None

            has_valid_gate = (not np.isnan(active_gate) and active_gate > 0)
            is_within_gate_120t = has_valid_gate and (tick_close <= active_gate * 1.005)
            gc_ref_price = tema15_30_gc_price if (not np.isnan(tema15_30_gc_price) and tema15_30_gc_price > 0) else (
                tema60_120_gc_price if (not np.isnan(tema60_120_gc_price) and tema60_120_gc_price > 0) else tick_close
            )
            is_short_momentum_ok = (is_tema15_rising or t15 > t30)
            is_gc_onset_entry = (
                (is_fresh_15_30_gc or is_dual_gc_confirm)
                and is_yellow_cloud_120t
                and is_tema15_30_bull
                and is_short_momentum_ok
                and (tick_close <= gc_ref_price * 1.035)
                and (day_ret_pct <= 22.0)
                and (upper_shadow_ratio_120t <= 0.65)
            )

            is_gate_entry = is_gc_onset_entry

            if is_gate_entry:
                buy_price = tick_close
                if getattr(self, 'fixed_qty', 0) > 0:
                    qty = self.fixed_qty
                    cost = qty * buy_price
                else:
                    budget = self.cash * 0.50  # 1차 매수 50% (2차 관문선 추가 매수 여력 50% 보존)
                    qty = int(budget // buy_price)
                    cost = qty * buy_price
                if qty > 0:
                    t_gc_p = tema60_120_gc_price if (not np.isnan(tema60_120_gc_price) and tema60_120_gc_price > 0) else buy_price
                    self.cash = max(0.0, self.cash - cost)
                    self.position.total_qty = qty
                    self.position.avg_price = buy_price
                    self.position.first_buy_price = buy_price
                    self.position.first_buy_qty = qty
                    self.position.entry_time = time.time()
                    self.position.last_gate_line = active_gate if has_valid_gate else 0.0
                    self.position.last_gate_high = active_gate_high if (not np.isnan(active_gate_high) and active_gate_high > 0) else 0.0
                    self.position.last_gijun_line = active_gijun if (not np.isnan(active_gijun) and active_gijun > 0) else 0.0
                    self.position.state = StrategyState.FIRST_BUY_DONE
                    self.position.entry_mode = "120T_TEMA"
                    self.position.tema60_bull_armed = False
                    self.position.tema15_120_armed = bool(not np.isnan(t15) and not np.isnan(t120) and t120 > 0 and t15 >= t120)
                    self.position.low_5m = ref_low if ref_low > 0 else (low_5m if low_5m > 0 else buy_price * 0.992)
                    self.position.open_5m = ref_open if ref_open > 0 else buy_price
                    self.position.first_cross_type = "TEMA15_30_GC"
                    self.position.first_cross_price = t_gc_p

                    if not np.isnan(active_gijun) and active_gijun > 0 and buy_price >= active_gijun * 1.001:
                        self.position.first_gijun_cleared = True
                        self.position.cleared_gijun_price = active_gijun
                    else:
                        self.position.first_gijun_cleared = False
                        self.position.cleared_gijun_price = active_gijun if (not np.isnan(active_gijun) and active_gijun > 0) else 0.0
                    self.position.second_gijun_price = 0.0

                    cond_tag = "🔔[실시간조건검색] " if is_condition_pick else ""
                    if has_valid_gate:
                        gate_diff = ((buy_price - active_gate) / active_gate * 100.0)
                        gate_desc = f"테마급등관문선({active_gate:,.0f}원, 이격 {gate_diff:+.2f}%)"
                    else:
                        gate_desc = "관문선 형성초기"

                    gc15_age = int(bars_since_15_30_gc) if not np.isnan(bars_since_15_30_gc) else 0
                    if is_fresh_60_120_gc:
                        trigger_str = (
                            f"⚡ [120틱 1차 매수·60-120 GC + 15-30 GC({gc15_age}봉)] "
                            f"양운 전환·단기 골든크로스 동시 돌파 {qty}주 매수"
                        )
                    else:
                        trigger_str = (
                            f"⚡ [120틱 1차 매수·60>120 + 15-30 GC({gc15_age}봉)] "
                            f"양운 유지 중 15-30 골든크로스 발생 ({gate_desc}) {qty}주 매수"
                        )
                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_1",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"{cond_tag}{qual_tag}{trigger_str} (체결가: {buy_price:,.0f}원)",
                        stage="FIRST_BUY_DONE"
                    )
                    self.trade_history.append(order)
                    return order

        # ─────────────────────────────────────────────────────────────
        # 2. FIRST_BUY_DONE 상태: 2차 매수 (테마급등관문선 완성) 및 1차 물량 매도 감시
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FIRST_BUY_DONE:
            base_p1 = self.position.first_buy_price if self.position.first_buy_price > 0 else self.position.avg_price
            first_pnl = ((tick_close - base_p1) / base_p1) * 100.0 if base_p1 > 0 else 0.0
            if first_pnl > self.position.max_profit_pct:
                self.position.max_profit_pct = first_pnl

            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0

            # 1) 15-120 데드크로스 / 60-120 데드크로스 / 비상손절은 2차 매수보다 먼저 즉시 청산 평가
            exit_early = self._evaluate_exit(
                timestamp, tick_close, base_p1, first_pnl, holding_sec, t60, t120, is_tema60_120_dead,
                t15=t15, t30=t30, is_tema15_30_dead=is_tema15_30_dead,
                is_tema15_120_dc_bar=is_tema15_120_dc_bar, is_tema15_120_dead=is_tema15_120_dead
            )
            if exit_early is not None:
                return exit_early

            # ⚡ 2차 매수 판단 (14:30 이후 중단, 15>30 & 15>120 & 60>=120 정배열 유지 중일 때 실질 눌림·계단 돌파 분할 매수)
            is_buy2_signal = False
            buy2_reason = ""
            has_valid_gate = (not np.isnan(active_gate) and active_gate > 0)
            if (
                allow_new_buys
                and holding_sec >= 20.0
                and has_120t_wave
                and (recent_tema60_120_gc or is_yellow_cloud_120t)
                and not is_tema60_120_dead
                and is_tema15_30_bull
                and not is_tema15_30_dead
                and not is_tema15_120_dead
                and has_valid_gate
            ):
                gate_diff = ((tick_close - active_gate) / active_gate * 100.0)
                is_within_gate_120t = (tick_close <= active_gate * 1.005)
                is_gate_minus_dip = (
                    tick_close <= active_gate * 0.9995
                    and (tick_close <= base_p1 * 0.996 or base_p1 > active_gate * 1.003)
                )
                is_pullback_discount = (
                    is_within_gate_120t
                    and tick_close <= base_p1 * 0.994
                )
                gate_advanced = (
                    (self.position.last_gate_line <= 0 and recent_gate_cross_up_120t)
                    or (self.position.last_gate_line > 0 and active_gate >= self.position.last_gate_line * 1.005)
                )
                is_stepped_up_gate_entry = (
                    is_within_gate_120t
                    and gate_advanced
                    and (recent_gate_cross_up_120t or tick_close >= active_gate * 0.998)
                )

                if is_gate_minus_dip:
                    is_buy2_signal = True
                    buy2_reason = f"⚡ [120틱 2차 매수] 테마급등관문선({active_gate:,.0f}원, {gate_diff:+.2f}%) (-) 눌림 저점 분할 매수"
                elif is_pullback_discount:
                    p1_diff = ((tick_close - base_p1) / base_p1 * 100.0) if base_p1 > 0 else 0.0
                    is_buy2_signal = True
                    buy2_reason = f"⚡ [120틱 2차 매수] 1차 대비 {p1_diff:+.2f}% 양운 눌림({active_gate:,.0f}원, {gate_diff:+.2f}%) 분할 매수"
                elif is_stepped_up_gate_entry:
                    is_buy2_signal = True
                    buy2_reason = f"⚡ [120틱 2차 매수] 신규 상향 테마급등관문선({active_gate:,.0f}원, {gate_diff:+.2f}%) 계단식 돌파·지지 분할 매수"

            if is_buy2_signal:
                buy_price = tick_close
                if getattr(self, 'fixed_qty', 0) > 0:
                    qty = self.fixed_qty
                else:
                    usable_cash = self.cash * 0.99
                    target_qty = self.position.first_buy_qty if self.position.first_buy_qty > 0 else self.position.total_qty
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
                    self.position.entry_time = time.time()
                    self.position.tema60_bull_armed = False
                    self.position.tema15_120_armed = bool(not np.isnan(t15) and not np.isnan(t120) and t120 > 0 and t15 >= t120)
                    self.position.last_gate_line = active_gate
                    self.position.last_gate_high = active_gate_high
                    self.position.state = StrategyState.FULL_POSITION

                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_2",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=f"{buy2_reason} (체결가: {buy_price:,.0f}원)",
                        stage="FULL_POSITION"
                    )
                    self.trade_history.append(order)
                    return order

            return self._evaluate_exit(
                timestamp, tick_close, base_p1, first_pnl, holding_sec, t60, t120, is_tema60_120_dead,
                t15=t15, t30=t30, is_tema15_30_dead=is_tema15_30_dead,
                is_tema15_120_dc_bar=is_tema15_120_dc_bar, is_tema15_120_dead=is_tema15_120_dead
            )

        # ─────────────────────────────────────────────────────────────
        # 3. FULL_POSITION 상태: 120틱 테마 15-120 / 60-120 데드크로스 & 비상 하드손절 매도
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FULL_POSITION:
            bot_entry_price = self.position.avg_price if self.position.avg_price > 0 else self.position.first_buy_price
            profit_rate = ((tick_close - bot_entry_price) / bot_entry_price) * 100.0 if bot_entry_price > 0 else 0.0
            if profit_rate > self.position.max_profit_pct:
                self.position.max_profit_pct = profit_rate
            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0

            return self._evaluate_exit(
                timestamp, tick_close, bot_entry_price, profit_rate, holding_sec, t60, t120, is_tema60_120_dead,
                t15=t15, t30=t30, is_tema15_30_dead=is_tema15_30_dead,
                is_tema15_120_dc_bar=is_tema15_120_dc_bar, is_tema15_120_dead=is_tema15_120_dead
            )

        return None

    def _evaluate_exit(
        self,
        timestamp: Any,
        tick_close: float,
        entry_ref_price: float,
        profit_rate: float,
        holding_sec: float,
        t60: float,
        t120: float,
        is_tema60_120_dead: bool,
        t15: float = np.nan,
        t30: float = np.nan,
        is_tema15_30_dead: bool = False,
        is_tema15_120_dc_bar: bool = False,
        is_tema15_120_dead: bool = False
    ) -> Optional[TradeOrder]:
        """공통 전량 매도 평가: 120틱 테마 15-120 데드크로스(주력) / 60-120 데드크로스 / -2.5% 비상 하드손절"""
        if not self.position.entry_mode or self.position.total_qty <= 1:
            return None

        if not np.isnan(t15) and not np.isnan(t120) and t120 > 0 and t15 >= t120:
            self.position.tema15_120_armed = True
        if holding_sec >= 5.0 and not np.isnan(t60) and not np.isnan(t120) and t120 > 0 and t60 > t120 * 1.0002:
            self.position.tema60_bull_armed = True

        is_exit = False
        action_type = "TAKE_PROFIT"
        sell_reason = ""

        # 1. ⚡ [주력 매도]: 120틱 테마 15-120 데드크로스 즉시 전량 매도 (추세 유지·수익 극대화)
        can_exit_15_120 = bool(self.position.tema15_120_armed or is_tema15_120_dc_bar)
        if holding_sec >= 5.0 and can_exit_15_120 and is_tema15_120_dead:
            is_exit = True
            action_type = "TAKE_PROFIT" if profit_rate >= 0.0 else "STOP_LOSS"
            sell_reason = (
                f"⚡ [120틱 테마 15-120 데드크로스 매도] 테마15({t15:,.0f}원) < 테마120({t120:,.0f}원) "
                f"데드크로스 발생 전량 매도 (체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
            )
        # 2. ⚡ [추세 붕괴 백업 매도]: 120틱 테마 60-120 데드크로스 시 전량 매도
        elif holding_sec >= 5.0 and self.position.tema60_bull_armed and is_tema60_120_dead:
            is_exit = True
            action_type = "TAKE_PROFIT" if profit_rate >= 0.0 else "STOP_LOSS"
            sell_reason = (
                f"⚡ [테마 60-120 데드크로스 백업 매도] 120틱 테마60({t60:,.0f}원) < 테마120({t120:,.0f}원) "
                f"데드크로스 발생 전량 매도 (체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
            )
        # 3. 🛑 [비상 하드 방어선 유지]: -2.5% 도달 시 계좌 보호 전량 손절
        elif holding_sec >= 10.0 and entry_ref_price > 0 and tick_close <= entry_ref_price * 0.975:
            is_exit = True
            action_type = "STOP_LOSS"
            sell_reason = (
                f"🛑 [비상 하드 방어선] -2.5% 도달 계좌 보호 전량 손절 "
                f"(매수가: {entry_ref_price:,.0f}원, 현재가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
            )

        if not is_exit:
            return None

        sell_qty = self.position.total_qty
        sell_amt = sell_qty * tick_close
        self.cash += sell_amt
        self.last_sell_time = time.time()
        order = TradeOrder(
            timestamp=timestamp,
            action=action_type,
            price=tick_close,
            qty=sell_qty,
            amount=sell_amt,
            reason=sell_reason,
            stage="IDLE"
        )
        self.trade_history.append(order)
        prev_trades = self.position.trade_count_today + 1
        self.position = PositionTracker()
        self.position.trade_count_today = prev_trades
        return order

