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
    tema60_bull_armed: bool = False     # 매수 진입 이후 테마60 > 테마120 정배열 안착 확인 여부 (사자마자 즉시 매도 원천 방지)
    tema30_60_armed: bool = False       # 매수 진입 이후 테마30 >= 테마60 정배열 안착 확인 여부
    tema15_120_armed: bool = False      # 매수 진입 이후 테마15 >= 테마120 안착 확인 여부
    sma5_60_armed: bool = False         # 매수 진입 이후 120틱 단순5이평 >= 단순60이평 안착 확인 여부
    sma5_60_buy2_armed: bool = True     # 1차 매수 시점 기준 신규 5-60 GC 2차 매수 대기 가능 여부
    # ── [3관문선(테마관문·WMA관문·WMA고가) + 기준선 파동 연속 대응 필드] ──
    entry_tri_ceiling: float = 0.0      # 진입 당시 3관문 천장 가격
    entry_tri_floor: float = 0.0        # 진입 당시 3관문 바닥 가격
    tri_gate_cleared: bool = False      # 3관문 돌파 완료 여부
    target_gijun_price: float = 0.0     # 현재 목표로 삼고 있는 변곡 기준선 가격
    touched_target_gijun: bool = False  # 목표 기준선 부근(99.5%~) 접근 이력
    support_gijun_price: float = 0.0    # 돌파 완료 후 지지선으로 승격된 직전 기준선 가격
    failed_gijun_price: float = 0.0     # 돌파 실패 후 하락을 야기한 기준선 가격
    gijun_cleared_count: int = 0        # 당일 연속 기준선 돌파 횟수
    wave_no: int = 1                    # 당일 해당 종목 파동 차수 (1=바닥 1차, 2+=3관문 재돌파)
    wave_high_price: float = 0.0        # 현재 보유 파동 중 최고가
    session_high_price: float = 0.0     # 당일 포착 이후 최고가
    prev_wave_tri_floor: float = 0.0    # 직전 상승 파동의 3관문 바닥 가격 (계단 하향 비교용)
    saw_gate_pullback: bool = False     # PROFIT_TAKEN 후 관문선 아래/근접 조정 경유 여부
    saw_rebound_to_gate: bool = False   # 조정 후 3관문 재도전 반등 시작 여부
    consecutive_losses: int = 0         # 당일 연속 손실 횟수
    realized_pnl_pct_today: float = 0.0 # 당일 누적 실현손익 (%)
    last_exit_price: float = 0.0        # 직전 매도 체결가
    last_exit_time: float = 0.0         # 직전 매도 시각
    last_exit_pnl_pct: float = 0.0      # 직전 매도 수익률 (%)
    top_confirmed_reason: str = ""      # 3관문 재돌파 실패 시 고점 확정 사유
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

        # ⚡ [120틱 상·하단 통합 파동 및 단순 이평(SMA 5/40/60) 연산 (하위 호환 df_3m/df_10m fallback 지원)]:
        # 핵심: 120틱 단순 5-40 GC(1차 매수), 단순 5-60 GC(2차 매수), 단순 5-60 DC(전량 매도)
        df_120t = kwargs.get('df_120t', None)
        if df_120t is None:
            df_120t = kwargs.get('df_3m', None)
        if df_120t is None:
            df_120t = kwargs.get('df_10m', None)
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
        t240 = 0.0
        s5 = np.nan
        s40 = np.nan
        s60 = np.nan
        is_sma40_lt_60 = False
        is_sma40_60_bull = False
        is_sma40_60_dc_bar = False
        is_sma60_rising = False
        is_sma5_40_bull = False
        is_sma5_40_gc_bar = False
        is_sma5_40_dc_bar = False
        bars_since_5_40_gc = np.nan
        sma5_40_gc_price = np.nan
        is_sma5_60_bull = False
        is_sma5_60_gc_bar = False
        is_sma5_60_dc_bar = False
        is_sma5_60_dead = False
        bars_since_5_60_gc = np.nan
        sma5_60_gc_price = np.nan
        wma_gate_120t = np.nan
        wma_gate_high_120t = np.nan
        tri_gate_ceiling_120t = np.nan
        tri_gate_floor_120t = np.nan
        settled_gijun_120t = np.nan
        settled_tri_ceiling_120t = np.nan
        settled_tri_floor_120t = np.nan
        is_wma5_20_bull = False
        is_wma5_20_dead = False
        is_tema5_20_dead = False
        last_120t_high = tick_close
        last_120t_open = tick_close
        is_tema60_120_dead = False
        is_tema60_120_gc_bar = False
        is_tema60_120_dc_bar = False
        bars_since_gc = np.nan
        is_tema60_240_bull = False
        is_tema60_240_gc_bar = False
        bars_since_60_240_gc = np.nan
        is_tema60_rising = False
        is_tema15_30_bull = False
        is_tema15_30_gc_bar = False
        is_tema15_30_dc_bar = False
        is_tema15_30_dead = False
        is_tema30_60_bull = False
        is_tema30_60_dc_bar = False
        is_tema30_60_dead = False
        is_tema_aligned_15_30_60_120 = False
        is_tema15_120_dc_bar = False
        is_tema15_120_dead = False
        is_tema15_rising = False
        bars_since_15_30_gc = np.nan
        tema15_30_gc_price = np.nan

        if df_120t is not None and not df_120t.empty and len(df_120t) >= 40 and 'close' in df_120t:
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
                t240 = float(last_120t.get('tema240', np.nan))
                s5 = float(last_120t.get('sma5', np.nan))
                s40 = float(last_120t.get('sma40', np.nan))
                s60 = float(last_120t.get('sma60', np.nan))
                is_sma40_lt_60 = bool(
                    not np.isnan(s40) and not np.isnan(s60) and s60 > 0 and s40 < s60
                )
                is_sma5_40_gc_bar = bool(last_120t.get('is_sma5_40_gc', False))
                is_sma5_40_dc_bar = bool(last_120t.get('is_sma5_40_dc', False))
                is_sma5_40_bull = bool(
                    not np.isnan(s5) and not np.isnan(s40) and s40 > 0 and s5 > s40
                )
                bars_since_5_40_gc = float(last_120t.get('bars_since_sma5_40_gc', np.nan))
                sma5_40_gc_price = float(last_120t.get('sma5_40_gc_price', np.nan))
                is_sma5_60_gc_bar = bool(last_120t.get('is_sma5_60_gc', False))
                is_sma5_60_dc_bar = bool(last_120t.get('is_sma5_60_dc', False))
                is_sma5_60_bull = bool(
                    not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 > s60
                )
                is_sma5_60_dead = bool(
                    is_sma5_60_dc_bar
                    or (not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 < s60)
                )
                bars_since_5_60_gc = float(last_120t.get('bars_since_sma5_60_gc', np.nan))
                sma5_60_gc_price = float(last_120t.get('sma5_60_gc_price', np.nan))
                is_sma40_60_bull = bool(last_120t.get('is_sma40_60_bull', False))
                is_sma40_60_dc_bar = bool(last_120t.get('is_sma40_60_dc', False))
                is_sma60_rising = bool(last_120t.get('is_sma60_rising', False))
                wma_gate_120t = float(last_120t.get('wma_gate', np.nan))
                wma_gate_high_120t = float(last_120t.get('wma_gate_high', np.nan))
                tri_gate_ceiling_120t = float(last_120t.get('tri_gate_ceiling', np.nan))
                tri_gate_floor_120t = float(last_120t.get('tri_gate_floor', np.nan))
                is_wma5_20_bull = bool(last_120t.get('is_wma5_20_bull', False))
                is_wma5_20_dead = bool(last_120t.get('is_wma5_20_dc', False))
                is_tema5_20_dead = bool(last_120t.get('is_tema_dead_5_20', False))
                last_120t_high = float(last_120t.get('high', tick_close))
                last_120t_open = float(last_120t.get('open', tick_close))

                # 120틱 미완성 봉 떨림(Flicker) 방지: 레벨 확정은 직전 완성봉(-2) 우선 참조
                ref_bar_120t = df_120t_calc.iloc[-2] if len(df_120t_calc) >= 2 else last_120t
                _sg = float(ref_bar_120t.get('theme_gijun', np.nan))
                settled_gijun_120t = _sg if (not np.isnan(_sg) and _sg > 0) else gijun_120t
                _stc = float(ref_bar_120t.get('tri_gate_ceiling', np.nan))
                settled_tri_ceiling_120t = _stc if (not np.isnan(_stc) and _stc > 0) else tri_gate_ceiling_120t
                _stf = float(ref_bar_120t.get('tri_gate_floor', np.nan))
                settled_tri_floor_120t = _stf if (not np.isnan(_stf) and _stf > 0) else tri_gate_floor_120t
                is_tema60_120_gc_bar = bool(last_120t.get('is_tema60_120_gc', False))
                is_tema60_120_dc_bar = bool(last_120t.get('is_tema60_120_dc', False))
                is_tema60_120_dead = bool(
                    is_tema60_120_dc_bar
                    or (not np.isnan(t60) and not np.isnan(t120) and t120 > 0 and t60 < t120)
                )
                bars_since_gc = float(last_120t.get('bars_since_tema60_120_gc', np.nan))
                is_tema60_240_gc_bar = bool(last_120t.get('is_tema60_240_gc', False))
                is_tema60_240_bull = bool(
                    last_120t.get('is_tema60_240_bull', False)
                    or (not np.isnan(t60) and not np.isnan(t240) and t240 > 0 and t60 > t240)
                )
                bars_since_60_240_gc = float(last_120t.get('bars_since_tema60_240_gc', np.nan))
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
                is_tema30_60_bull = bool(
                    last_120t.get('is_tema30_60_bull', False)
                    or (not np.isnan(t30) and not np.isnan(t60) and t60 > 0 and t30 > t60)
                )
                is_tema30_60_dc_bar = bool(last_120t.get('is_tema30_60_dc', False))
                is_tema30_60_dead = bool(
                    is_tema30_60_dc_bar
                    or (not np.isnan(t30) and not np.isnan(t60) and t60 > 0 and t30 < t60)
                )
                is_tema_aligned_15_30_60_120 = bool(
                    not np.isnan(t15) and not np.isnan(t30) and not np.isnan(t60) and not np.isnan(t120)
                    and t120 > 0 and (t15 > t30 > t60 > t120)
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

        # 유효 관문선(노란선) · 관문고가선(검정점선) · 기준선(분홍선) · 3관문 결정 (120틱 완성봉 레벨 우선)
        active_gate = gate_120t if (has_120t_wave and not np.isnan(gate_120t) and gate_120t > 0) else gate_line
        active_gate_high = gate_high_120t if (has_120t_wave and not np.isnan(gate_high_120t) and gate_high_120t > 0) else gate_high
        active_gijun = (
            settled_gijun_120t
            if (has_120t_wave and not np.isnan(settled_gijun_120t) and settled_gijun_120t > 0)
            else (gijun_120t if (has_120t_wave and not np.isnan(gijun_120t) and gijun_120t > 0) else gijun_line)
        )
        active_tri_ceiling = (
            settled_tri_ceiling_120t
            if (has_120t_wave and not np.isnan(settled_tri_ceiling_120t) and settled_tri_ceiling_120t > 0)
            else tri_gate_ceiling_120t
        )
        active_tri_floor = (
            settled_tri_floor_120t
            if (has_120t_wave and not np.isnan(settled_tri_floor_120t) and settled_tri_floor_120t > 0)
            else tri_gate_floor_120t
        )

        # 고점 확정(TERMINATED) 종목은 일자 전환 전까지 절대 자동 리셋하지 않음
        if self.position.state == StrategyState.TERMINATED:
            return None

        if tick_close > self.position.session_high_price:
            self.position.session_high_price = tick_close
        if self.position.state in (StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION, StrategyState.REENTRY_HOLDING):
            if tick_close > self.position.wave_high_price:
                self.position.wave_high_price = tick_close
            if last_120t_high > self.position.wave_high_price:
                self.position.wave_high_price = last_120t_high

        enable_core_swing_split = bool(kwargs.get('enable_core_swing_split', True))

        def _sync_wave_targets(cur_p: float, hi_p: float):
            """보유 중 3관문 돌파 및 기준선 출현·돌파·다음 변곡 기준선 계단 상향 추적"""
            if not np.isnan(active_tri_ceiling) and active_tri_ceiling > 0:
                if cur_p >= active_tri_ceiling * 1.001:
                    self.position.tri_gate_cleared = True
            if not np.isnan(active_gijun) and active_gijun > 0:
                ref_floor = self.position.support_gijun_price if self.position.support_gijun_price > 0 else self.position.avg_price
                failed_floor = (
                    self.position.failed_gijun_price * 1.001
                    if (self.position.state == StrategyState.REENTRY_HOLDING and self.position.failed_gijun_price > 0)
                    else 0.0
                )
                # 1) 아직 목표 기준선이 없으면, 직전 지지/평단 대비 +0.3% 이상 위에 새 기준선 출현 시 목표 잠금
                # (분할익절 직후 REENTRY_HOLDING 구간에서는 이미 실패한 직전 기준선을 재목표로 잡지 않음)
                if self.position.target_gijun_price <= 0:
                    if ref_floor > 0 and active_gijun > ref_floor * 1.003 and active_gijun > failed_floor:
                        self.position.target_gijun_price = active_gijun
                        self.position.touched_target_gijun = (max(cur_p, hi_p) >= active_gijun * 0.995)
                else:
                    # 2) 목표 기준선 접근 및 돌파 검사
                    if max(cur_p, hi_p) >= self.position.target_gijun_price * 0.995:
                        self.position.touched_target_gijun = True
                    if cur_p >= self.position.target_gijun_price * 1.002:
                        # 기준선 돌파 성공 ➔ 지지로 승격 & 다음 변곡 기준선까지 상승 홀딩
                        self.position.support_gijun_price = self.position.target_gijun_price
                        self.position.cleared_gijun_price = self.position.target_gijun_price
                        self.position.first_gijun_cleared = True
                        self.position.gijun_cleared_count += 1
                        self.position.touched_target_gijun = False
                        if active_gijun > self.position.support_gijun_price * 1.003:
                            self.position.target_gijun_price = active_gijun
                        else:
                            self.position.target_gijun_price = 0.0

        # ─────────────────────────────────────────────────────────────
        # 1. IDLE 상태: 1차 매수 (일봉 자격 / 교체 상승률<=20% 확인 후 120틱 단순 5이평-40이평 골든크로스 & SMA40<60)
        # ─────────────────────────────────────────────────────────────
        if self.position.state == StrategyState.IDLE:
            # 🔍 조건검색 관찰/눌림 기록 갱신 (모니터링 가시화용)
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
            if not is_replacement_mode:
                if not is_daily_3_5_ok:
                    return None
                qual_tag = f"[{daily_3_5_label}] "
            else:
                if day_ret_pct > 20.0:
                    return None
                qual_tag = f"[순환교체(등락률 {day_ret_pct:+.2f}%<=20%)] "

            # ⚡ [2단계: 실제 1차 매수 집행 = 120틱 단순 5-40 골든크로스 (0~1봉 이내 & 매수시점 SMA40 < SMA60 필수)]
            if not has_120t_wave or not is_sma40_lt_60 or not is_sma5_40_bull or is_sma5_40_dc_bar:
                return None

            is_gc5_40_within_1bar = is_sma5_40_gc_bar or (not np.isnan(bars_since_5_40_gc) and 0 <= bars_since_5_40_gc <= 1)
            if not is_gc5_40_within_1bar:
                return None

            has_valid_gate = (not np.isnan(active_gate) and active_gate > 0)
            is_gate_entry = (day_ret_pct <= 25.0)

            if is_gate_entry:
                buy_price = tick_close
                if getattr(self, 'fixed_qty', 0) > 0:
                    qty = self.fixed_qty
                    cost = qty * buy_price
                else:
                    budget = self.cash * 0.50  # 1차 매수 50% (2차 5-60 GC 추가 매수 여력 50% 보존)
                    qty = int(budget // buy_price)
                    cost = qty * buy_price
                if qty > 0:
                    s_gc_p = sma5_40_gc_price if (not np.isnan(sma5_40_gc_price) and sma5_40_gc_price > 0) else buy_price
                    self.cash = max(0.0, self.cash - cost)
                    self.position.total_qty = qty
                    self.position.avg_price = buy_price
                    self.position.first_buy_price = buy_price
                    self.position.first_buy_qty = qty
                    self.position.entry_time = time.time()
                    self.position.wave_high_price = max(buy_price, last_120t_high)
                    if max(buy_price, last_120t_high) > self.position.session_high_price:
                        self.position.session_high_price = max(buy_price, last_120t_high)
                    self.position.last_gate_line = active_gate if has_valid_gate else 0.0
                    self.position.last_gate_high = active_gate_high if (not np.isnan(active_gate_high) and active_gate_high > 0) else 0.0
                    self.position.last_gijun_line = active_gijun if (not np.isnan(active_gijun) and active_gijun > 0) else 0.0
                    self.position.entry_tri_ceiling = float(active_tri_ceiling) if (not np.isnan(active_tri_ceiling) and active_tri_ceiling > 0) else 0.0
                    self.position.entry_tri_floor = float(active_tri_floor) if (not np.isnan(active_tri_floor) and active_tri_floor > 0) else 0.0
                    self.position.tri_gate_cleared = bool(self.position.entry_tri_ceiling > 0 and buy_price >= self.position.entry_tri_ceiling * 1.001)
                    self.position.target_gijun_price = float(active_gijun) if (not np.isnan(active_gijun) and active_gijun > buy_price * 1.003) else 0.0
                    self.position.touched_target_gijun = False
                    self.position.support_gijun_price = 0.0
                    self.position.state = StrategyState.FIRST_BUY_DONE
                    self.position.entry_mode = "120T_SMA"
                    self.position.tema60_bull_armed = bool(not np.isnan(t60) and not np.isnan(t120) and t120 > 0 and t60 >= t120)
                    self.position.tema30_60_armed = bool(not np.isnan(t30) and not np.isnan(t60) and t60 > 0 and t30 >= t60)
                    self.position.tema15_120_armed = bool(not np.isnan(t15) and not np.isnan(t120) and t120 > 0 and t15 >= t120)
                    self.position.sma5_60_armed = bool(not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 >= s60)
                    # 이미 과거 봉에서 5-60 GC가 먼저 나온 상태(예: 40>60 추세)로 1차 진입 시 기존 5-60 GC 잔여 1봉으로 2차 오발동 방지
                    had_prior_5_60_gc = bool(not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 >= s60 and not is_sma5_60_gc_bar)
                    self.position.sma5_60_buy2_armed = (not had_prior_5_60_gc)
                    self.position.low_5m = ref_low if ref_low > 0 else (low_5m if low_5m > 0 else buy_price * 0.992)
                    self.position.open_5m = ref_open if ref_open > 0 else buy_price
                    self.position.first_cross_type = "SMA5_40_GC"
                    self.position.first_cross_price = s_gc_p

                    if not np.isnan(active_gijun) and active_gijun > 0 and buy_price >= active_gijun * 1.001:
                        self.position.first_gijun_cleared = True
                        self.position.cleared_gijun_price = active_gijun
                    else:
                        self.position.first_gijun_cleared = False
                        self.position.cleared_gijun_price = active_gijun if (not np.isnan(active_gijun) and active_gijun > 0) else 0.0
                    self.position.second_gijun_price = 0.0

                    cond_tag = "🔔[실시간조건검색] " if is_condition_pick else ""
                    gc5_40_age = int(bars_since_5_40_gc) if not np.isnan(bars_since_5_40_gc) else 0
                    trigger_str = (
                        f"⚡ [120틱 1차 매수·단순 5-40 GC({gc5_40_age}봉·40<60)] "
                        f"단순5이평({s5:,.0f}원) > 단순40이평({s40:,.0f}원) < 단순60이평({s60:,.0f}원) 골든크로스 {qty}주 매수"
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
        # 2. FIRST_BUY_DONE 상태: 2차 매수 (120틱 단순 5-60 골든크로스) & 기준선·5-60 DC 매도 감시
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FIRST_BUY_DONE:
            _sync_wave_targets(tick_close, last_120t_high)
            base_p1 = self.position.first_buy_price if self.position.first_buy_price > 0 else self.position.avg_price
            first_pnl = ((tick_close - base_p1) / base_p1) * 100.0 if base_p1 > 0 else 0.0
            if first_pnl > self.position.max_profit_pct:
                self.position.max_profit_pct = first_pnl

            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0

            # 1) 단순 5-60 데드크로스 / 기준선 저항 꺾임 / -2.5% 비상손절 평가
            exit_early = self._evaluate_exit(
                timestamp, tick_close, base_p1, first_pnl, holding_sec, s5, s60, is_sma5_60_dead,
                is_wma_dead=(is_wma5_20_dead or is_tema5_20_dead),
                active_tri_floor=active_tri_floor,
                allow_partial=False,
            )
            if exit_early is not None:
                return exit_early

            if not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 <= s60:
                self.position.sma5_60_buy2_armed = True

            # ⚡ 2차 매수 판단 (14:30 이후 중단, 1차 바닥파동은 SMA40<60 & 5-60 GC, N차 재돌파 파동은 3관문/5-60 재돌파 허용)
            is_gc5_60_within_1bar = is_sma5_60_gc_bar or (not np.isnan(bars_since_5_60_gc) and 0 <= bars_since_5_60_gc <= 1)
            allow_40_60_for_buy2 = is_sma40_lt_60 or (self.position.wave_no >= 2 and (is_sma60_rising or is_yellow_cloud_120t))
            is_buy2_signal = bool(
                allow_new_buys
                and holding_sec >= 5.0
                and has_120t_wave
                and allow_40_60_for_buy2
                and getattr(self.position, 'sma5_60_buy2_armed', True)
                and is_sma5_60_bull
                and not is_sma5_60_dead
                and is_gc5_60_within_1bar
            )
            gc5_60_age = int(bars_since_5_60_gc) if not np.isnan(bars_since_5_60_gc) else 0
            arr_tag = "40<60" if is_sma40_lt_60 else "N파추세"
            buy2_reason = (
                f"⚡ [120틱 2차 매수·단순 5-60 GC({gc5_60_age}봉·{arr_tag})] "
                f"단순5이평({s5:,.0f}원) > 단순60이평({s60:,.0f}원) (40:{s40:,.0f} / 60:{s60:,.0f}) 골든크로스 불타기 분할 매수"
            )

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
                    self.position.sma5_60_armed = True
                    self.position.sma5_60_buy2_armed = False
                    if not np.isnan(active_gate) and active_gate > 0:
                        self.position.last_gate_line = active_gate
                    if not np.isnan(active_gate_high) and active_gate_high > 0:
                        self.position.last_gate_high = active_gate_high
                    if not np.isnan(active_tri_floor) and active_tri_floor > 0 and self.position.entry_tri_floor <= 0:
                        self.position.entry_tri_floor = float(active_tri_floor)
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
                timestamp, tick_close, base_p1, first_pnl, holding_sec, s5, s60, is_sma5_60_dead,
                is_wma_dead=(is_wma5_20_dead or is_tema5_20_dead),
                active_tri_floor=active_tri_floor,
                allow_partial=False,
            )

        # ─────────────────────────────────────────────────────────────
        # 3. FULL_POSITION 상태: 기준선 돌파 실패 50% 분할익절(4주+) / 5-60 DC / 트레일링 청산
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.FULL_POSITION:
            _sync_wave_targets(tick_close, last_120t_high)
            bot_entry_price = self.position.avg_price if self.position.avg_price > 0 else self.position.first_buy_price
            profit_rate = ((tick_close - bot_entry_price) / bot_entry_price) * 100.0 if bot_entry_price > 0 else 0.0
            if profit_rate > self.position.max_profit_pct:
                self.position.max_profit_pct = profit_rate
            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0

            return self._evaluate_exit(
                timestamp, tick_close, bot_entry_price, profit_rate, holding_sec, s5, s60, is_sma5_60_dead,
                is_wma_dead=(is_wma5_20_dead or is_tema5_20_dead),
                active_tri_floor=active_tri_floor,
                allow_partial=(enable_core_swing_split and self.position.total_qty >= 4),
            )

        # ─────────────────────────────────────────────────────────────
        # 4. REENTRY_HOLDING 상태: 잔여 코어 보유 중 재돌파 불타기(+2주) OR 최종 청산
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.REENTRY_HOLDING:
            _sync_wave_targets(tick_close, last_120t_high)
            bot_entry_price = self.position.avg_price if self.position.avg_price > 0 else self.position.first_buy_price
            profit_rate = ((tick_close - bot_entry_price) / bot_entry_price) * 100.0 if bot_entry_price > 0 else 0.0
            if profit_rate > self.position.max_profit_pct:
                self.position.max_profit_pct = profit_rate
            holding_sec = (time.time() - self.position.entry_time) if self.position.entry_time > 0 else 999.0

            exit_rem = self._evaluate_exit(
                timestamp, tick_close, bot_entry_price, profit_rate, holding_sec, s5, s60, is_sma5_60_dead,
                is_wma_dead=(is_wma5_20_dead or is_tema5_20_dead),
                active_tri_floor=active_tri_floor,
                allow_partial=False,
            )
            if exit_rem is not None:
                return exit_rem

            # 눌림 후 3관문 천장 재돌파(+여백 >= 1% or 직전 실패기준선 돌파) 시 코어 위에 스윙 50% 재불타기
            if not np.isnan(active_tri_floor) and active_tri_floor > 0 and tick_close <= active_tri_floor:
                self.position.saw_gate_pullback = True
            failed_gj = self.position.failed_gijun_price
            has_headroom = (
                failed_gj <= 0
                or ((failed_gj / active_tri_ceiling - 1.0) >= 0.010 if (not np.isnan(active_tri_ceiling) and active_tri_ceiling > 0) else False)
                or (tick_close >= failed_gj * 1.001)
            )
            can_core_rebuy = bool(
                allow_new_buys
                and has_120t_wave
                and self.position.saw_gate_pullback
                and (self.last_sell_time <= 0 or (time.time() - self.last_sell_time) >= 8.0)
                and not np.isnan(active_tri_ceiling) and active_tri_ceiling > 0
                and (active_tri_ceiling * 1.001 <= tick_close <= active_tri_ceiling * 1.012)
                and is_wma5_20_bull
                and (is_sma60_rising or is_yellow_cloud_120t)
                and has_headroom
                and day_ret_pct <= 25.0
            )
            if can_core_rebuy:
                qty = self.fixed_qty if getattr(self, 'fixed_qty', 0) > 0 else max(1, self.position.total_qty)
                buy_price = tick_close
                cost = qty * buy_price
                self.cash = max(0.0, self.cash - cost)
                prev_qty = self.position.total_qty
                prev_cost = prev_qty * self.position.avg_price
                self.position.total_qty += qty
                self.position.avg_price = (prev_cost + cost) / self.position.total_qty
                self.position.second_buy_price = buy_price
                self.position.second_buy_qty = qty
                self.position.second_buy_time = time.time()
                self.position.saw_gate_pullback = False
                self.position.saw_rebound_to_gate = False
                self.position.target_gijun_price = 0.0
                self.position.touched_target_gijun = False
                self.position.wave_high_price = max(buy_price, last_120t_high)
                self.position.max_profit_pct = max(0.0, ((buy_price - self.position.avg_price) / self.position.avg_price) * 100.0) if self.position.avg_price > 0 else 0.0
                self.position.bep_locked = False
                self.position.wave_no += 1
                self.position.state = StrategyState.FULL_POSITION
                order = TradeOrder(
                    timestamp=timestamp,
                    action="BUY_2",
                    price=buy_price,
                    qty=qty,
                    amount=cost,
                    reason=(
                        f"⚡ [120틱 코어+스윙 {self.position.wave_no}파 재돌파 2차 매수] "
                        f"3관문 천장({active_tri_ceiling:,.0f}원) 재돌파 확인 {qty}주 재불타기 (체결가: {buy_price:,.0f}원)"
                    ),
                    stage="FULL_POSITION"
                )
                self.trade_history.append(order)
                return order

        # ─────────────────────────────────────────────────────────────
        # 5. PROFIT_TAKEN 상태: 하락 후 3관문(테마관문·WMA관문·WMA고가) 재돌파(반복) vs 재돌파 실패(고점 확정)
        # ─────────────────────────────────────────────────────────────
        elif self.position.state == StrategyState.PROFIT_TAKEN:
            cur_tf = active_tri_floor if (not np.isnan(active_tri_floor) and active_tri_floor > 0) else 0.0
            cur_tc = active_tri_ceiling if (not np.isnan(active_tri_ceiling) and active_tri_ceiling > 0) else 0.0
            failed_gj = self.position.failed_gijun_price

            # 1) 눌림 및 3관문 재도전 경유 추적
            if has_120t_wave:
                if (cur_tf > 0 and tick_close <= cur_tf * 1.001) or (failed_gj > 0 and tick_close <= failed_gj * 0.993) or not is_wma5_20_bull:
                    self.position.saw_gate_pullback = True
                if self.position.saw_gate_pullback and cur_tf > 0 and tick_close >= cur_tf * 0.995:
                    self.position.saw_rebound_to_gate = True

            # 2) [고점 확정 심판 -> TERMINATED]: 하락 후 3관문 재돌파 실패 / 계단 하향 붕괴 / 2연패 졸업
            elapsed_since_exit = (time.time() - self.position.last_exit_time) if self.position.last_exit_time > 0 else 0.0
            is_failed_retest = bool(
                has_120t_wave
                and self.position.saw_gate_pullback
                and self.position.saw_rebound_to_gate
                and elapsed_since_exit >= 10.0
                and cur_tf > 0
                and cur_tc > 0
                and tick_close < cur_tf * 0.996
                and (is_wma5_20_dead or is_tema5_20_dead)
                and (cur_tc <= 0 or self.position.wave_high_price < cur_tc * 1.005 or tick_close < cur_tf * 0.992)
            )
            is_lower_gate_breakdown = bool(
                has_120t_wave
                and self.position.prev_wave_tri_floor > 0
                and cur_tf > 0
                and cur_tf < self.position.prev_wave_tri_floor * 0.996
                and is_sma40_lt_60
                and not is_yellow_cloud_120t
                and tick_close < cur_tf
            )
            is_session_collapse = bool(
                self.position.session_high_price > 0
                and tick_close <= self.position.session_high_price * 0.965
                and not is_sma40_60_bull
                and (not is_yellow_cloud_120t or is_sma40_60_dc_bar)
            )
            is_risk_graduated = (
                self.position.consecutive_losses >= 2
                or self.position.realized_pnl_pct_today <= -2.5
                or self.position.wave_no >= 5
            )

            if is_risk_graduated or is_failed_retest or is_lower_gate_breakdown or is_session_collapse:
                if is_risk_graduated:
                    top_msg = f"리스크 졸업(연속손실 {self.position.consecutive_losses}회/누적 {self.position.realized_pnl_pct_today:+.2f}%)"
                elif is_failed_retest:
                    top_msg = f"하락 후 3관문({cur_tc:,.0f}원) 재돌파 실패 ➔ 최종 고점 확정"
                elif is_lower_gate_breakdown:
                    top_msg = f"3관문 하향 계단 붕괴({cur_tf:,.0f} < 직전 {self.position.prev_wave_tri_floor:,.0f}) ➔ 최종 고점 확정"
                else:
                    top_msg = f"당일 고점({self.position.session_high_price:,.0f}원) 대비 -3.5% 이탈 및 40<60 꺾임 ➔ 최종 고점 확정"
                self.position.top_confirmed_reason = top_msg
                self.position.state = StrategyState.TERMINATED
                return None

            # 3) [N차 재상승 파동 점화]: 하락 후 3관문(테마관문·WMA관문·WMA고가) 모두 재돌파 ➔ 재매수!
            if not allow_new_buys or not has_120t_wave:
                return None
            reentry_cd = 10.0 if self.position.last_exit_pnl_pct >= 0.3 else 60.0
            if self.last_sell_time > 0 and (time.time() - self.last_sell_time) < reentry_cd:
                return None

            has_headroom = (
                failed_gj <= 0
                or ((failed_gj / cur_tc - 1.0) >= 0.010 if cur_tc > 0 else False)
                or (tick_close >= failed_gj * 1.001)
            )
            trend_alive = bool(
                (is_sma60_rising or is_yellow_cloud_120t)
                or (is_sma40_lt_60 and is_sma5_40_bull)
            )
            if (
                self.position.saw_gate_pullback
                and cur_tc > 0
                and (cur_tc * 1.001 <= tick_close <= cur_tc * 1.012)
                and is_wma5_20_bull
                and (tick_close >= last_120t_open)
                and trend_alive
                and has_headroom
                and day_ret_pct <= 25.0
            ):
                buy_price = tick_close
                qty = self.fixed_qty if getattr(self, 'fixed_qty', 0) > 0 else max(1, int((self.cash * 0.50) // buy_price))
                cost = qty * buy_price
                if qty > 0:
                    self.cash = max(0.0, self.cash - cost)
                    self.position.total_qty = qty
                    self.position.avg_price = buy_price
                    self.position.first_buy_price = buy_price
                    self.position.first_buy_qty = qty
                    self.position.second_buy_price = 0.0
                    self.position.second_buy_qty = 0
                    self.position.entry_time = time.time()
                    self.position.wave_no += 1
                    self.position.wave_high_price = max(buy_price, last_120t_high)
                    self.position.max_profit_pct = 0.0
                    self.position.bep_locked = False
                    self.position.entry_mode = "120T_SMA"
                    self.position.first_cross_type = "TRI_GATE_REENTRY"
                    self.position.first_cross_price = cur_tc
                    self.position.entry_tri_ceiling = float(cur_tc)
                    self.position.entry_tri_floor = float(cur_tf) if cur_tf > 0 else self.position.prev_wave_tri_floor
                    self.position.tri_gate_cleared = True
                    self.position.target_gijun_price = float(active_gijun) if (not np.isnan(active_gijun) and active_gijun > buy_price * 1.003) else 0.0
                    self.position.touched_target_gijun = False
                    self.position.support_gijun_price = float(active_gijun) if (not np.isnan(active_gijun) and 0 < active_gijun <= buy_price) else 0.0
                    self.position.saw_gate_pullback = False
                    self.position.saw_rebound_to_gate = False
                    self.position.sma5_60_armed = bool(not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 >= s60)
                    had_prior_5_60_gc = bool(not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 >= s60 and not is_sma5_60_gc_bar)
                    self.position.sma5_60_buy2_armed = (not had_prior_5_60_gc)
                    self.position.state = StrategyState.FIRST_BUY_DONE

                    order = TradeOrder(
                        timestamp=timestamp,
                        action="BUY_1",
                        price=buy_price,
                        qty=qty,
                        amount=cost,
                        reason=(
                            f"⚡ [120틱 {self.position.wave_no}파 재매수·3관문 재돌파] "
                            f"테마·WMA·WMA고가 3중 관문({cur_tc:,.0f}원) 재돌파 {qty}주 진입 (체결가: {buy_price:,.0f}원)"
                        ),
                        stage="FIRST_BUY_DONE"
                    )
                    self.trade_history.append(order)
                    return order

        return None

    def _evaluate_exit(
        self,
        timestamp: Any,
        tick_close: float,
        entry_ref_price: float,
        profit_rate: float,
        holding_sec: float,
        s5: float,
        s60: float,
        is_sma5_60_dead: bool,
        **kwargs
    ) -> Optional[TradeOrder]:
        """
        공통 매도 평가:
        0) -2.5% 비상 하드손절 (전량 청산)
        1) 120틱 단순 5-60 데드크로스 (4주+ 수익시 2주 분할익절 ➔ REENTRY_HOLDING, 그외 전량 청산)
        2) 목표 기준선 돌파 실패 후 꺾임 익절 (하락 선제 대응, 실패 기준선 기록)
        3) 돌파 완료 지지 기준선 재이탈 익절
        4) +1.5%↑ 도달 시 +0.45% 비용보전 본절락 & +3.5%↑ 고점 대비 -1.5%p 트레일링
        """
        if not self.position.entry_mode or self.position.total_qty <= 0:
            return None

        if not np.isnan(s5) and not np.isnan(s60) and s60 > 0 and s5 >= s60:
            self.position.sma5_60_armed = True
        if self.position.max_profit_pct >= 1.5:
            self.position.bep_locked = True

        is_wma_dead = bool(kwargs.get('is_wma_dead', False))
        allow_partial = bool(kwargs.get('allow_partial', False)) and (self.position.total_qty >= 4)
        active_tri_floor = float(kwargs.get('active_tri_floor', np.nan))
        drop_from_wave_high_pct = (
            ((self.position.wave_high_price - tick_close) / self.position.wave_high_price) * 100.0
            if self.position.wave_high_price > 0 else 0.0
        )

        is_exit = False
        is_partial_exit = False
        action_type = "TAKE_PROFIT"
        sell_reason = ""
        failed_gijun_hit = 0.0

        # 0. 🛑 [비상 하드 방어선]: -2.5% 도달 시 보유 시간 5초+ 즉시 전량 손절
        if holding_sec >= 5.0 and entry_ref_price > 0 and tick_close <= entry_ref_price * 0.975:
            is_exit = True
            action_type = "STOP_LOSS"
            sell_reason = (
                f"🛑 [비상 하드 방어선] -2.5% 도달 계좌 보호 전량 손절 "
                f"(매수가: {entry_ref_price:,.0f}원, 현재가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
            )
        # 1. ⚡ [주력 추세 매도]: 120틱 단순 5-60 데드크로스
        elif holding_sec >= 5.0 and self.position.sma5_60_armed and is_sma5_60_dead:
            is_exit = True
            if allow_partial and profit_rate >= 0.5:
                is_partial_exit = True
                action_type = "PARTIAL_TAKE_PROFIT"
                sell_reason = (
                    f"🌓 [120틱 단순 5-60 데드크로스 50% 분할 익절] 단순5이평({s5:,.0f}원) < 단순60이평({s60:,.0f}원) "
                    f"➔ 절반 익절 + 잔여 코어 홀딩 (체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
            else:
                action_type = "TAKE_PROFIT" if profit_rate >= 0.0 else "STOP_LOSS"
                sell_reason = (
                    f"⚡ [120틱 단순 5-60 데드크로스 매도] 단순5이평({s5:,.0f}원) < 단순60이평({s60:,.0f}원) "
                    f"데드크로스 발생 전량 매도 (체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
        # 2. 🎯 [기준선 돌파 실패 꺾임 조기 익절]: 다음 기준선 못 넘고 밀리면 하락 전 선제 수익실현
        elif (
            holding_sec >= 5.0
            and profit_rate >= 0.5
            and self.position.target_gijun_price > 0
            and self.position.touched_target_gijun
            and tick_close < self.position.target_gijun_price * 0.996
            and (is_wma_dead or drop_from_wave_high_pct >= 0.6)
        ):
            is_exit = True
            failed_gijun_hit = self.position.target_gijun_price
            if allow_partial:
                is_partial_exit = True
                action_type = "PARTIAL_TAKE_PROFIT"
                sell_reason = (
                    f"🌓 [기준선({failed_gijun_hit:,.0f}원) 돌파 실패 꺾임 50% 분할 익절] 하락 전 스윙 익절 + 코어 홀딩 "
                    f"(체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
            else:
                action_type = "TAKE_PROFIT"
                sell_reason = (
                    f"🏛️ [기준선({failed_gijun_hit:,.0f}원) 돌파 실패 꺾임 전량 익절] 하락 초입 현금화 "
                    f"(체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
        # 3. 📉 [돌파 완료 기준선 재이탈 익절]
        elif (
            holding_sec >= 5.0
            and profit_rate >= 0.5
            and self.position.support_gijun_price > 0
            and tick_close < self.position.support_gijun_price * 0.995
            and is_wma_dead
        ):
            is_exit = True
            failed_gijun_hit = self.position.target_gijun_price or self.position.support_gijun_price
            if allow_partial:
                is_partial_exit = True
                action_type = "PARTIAL_TAKE_PROFIT"
                sell_reason = (
                    f"🌓 [지지 기준선({self.position.support_gijun_price:,.0f}원) 재이탈 50% 분할 익절] "
                    f"(체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
            else:
                action_type = "TAKE_PROFIT"
                sell_reason = (
                    f"📉 [돌파 기준선({self.position.support_gijun_price:,.0f}원) 재이탈 전량 익절] "
                    f"(체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
                )
        # 4. 🔒 [비용보전 본절락 (+1.5%↑ ➔ +0.45%) 및 고점 트레일링 (+3.5%↑ ➔ -1.5%p)]
        elif holding_sec >= 5.0 and self.position.bep_locked and profit_rate <= 0.45:
            is_exit = True
            action_type = "TAKE_PROFIT"
            sell_reason = (
                f"🔒 [비용보전 본절락 수익 보존] 최고 +{self.position.max_profit_pct:.2f}% 도달 후 "
                f"+0.45% 하회 전량 익절 (체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
            )
        elif (
            holding_sec >= 5.0
            and self.position.max_profit_pct >= 3.5
            and (self.position.max_profit_pct - profit_rate) >= 1.5
            and is_wma_dead
        ):
            is_exit = True
            action_type = "TAKE_PROFIT"
            sell_reason = (
                f"🎯 [고점 트레일링 익절] 최고 +{self.position.max_profit_pct:.2f}% 대비 -1.5%p 되밀림 "
                f"(체결가: {tick_close:,.0f}원, 수익률: {profit_rate:+.2f}%)"
            )

        if not is_exit:
            return None

        now_ts = time.time()
        self.last_sell_time = now_ts

        if is_partial_exit:
            sell_qty = self.position.total_qty // 2
            sell_amt = sell_qty * tick_close
            self.cash += sell_amt
            self.position.total_qty -= sell_qty
            self.position.failed_gijun_price = failed_gijun_hit or self.position.target_gijun_price
            self.position.target_gijun_price = 0.0
            self.position.touched_target_gijun = False
            self.position.last_exit_price = tick_close
            self.position.last_exit_time = now_ts
            self.position.last_exit_pnl_pct = profit_rate
            self.position.saw_gate_pullback = False
            self.position.saw_rebound_to_gate = False
            self.position.state = StrategyState.REENTRY_HOLDING
            order = TradeOrder(
                timestamp=timestamp,
                action="PARTIAL_TAKE_PROFIT",
                price=tick_close,
                qty=sell_qty,
                amount=sell_amt,
                reason=sell_reason,
                stage="REENTRY_HOLDING"
            )
            self.trade_history.append(order)
            return order

        # 전량 청산: 다음 파동 3관문 재돌파 시험(PROFIT_TAKEN) 또는 리스크 졸업(TERMINATED)으로 기억 보존 전이
        sell_qty = self.position.total_qty
        sell_amt = sell_qty * tick_close
        self.cash += sell_amt
        prev_trades = self.position.trade_count_today + 1
        prev_losses = self.position.consecutive_losses + (1 if profit_rate < 0 else 0) if profit_rate < 0 else 0
        cum_pnl = self.position.realized_pnl_pct_today + profit_rate
        cur_tf = active_tri_floor if (not np.isnan(active_tri_floor) and active_tri_floor > 0) else self.position.entry_tri_floor
        saved_session_hi = max(self.position.session_high_price, self.position.wave_high_price, tick_close)
        saved_failed_gj = failed_gijun_hit or self.position.target_gijun_price or self.position.failed_gijun_price
        saved_wave_no = self.position.wave_no

        should_terminate_now = (
            prev_losses >= 2
            or cum_pnl <= -2.5
            or saved_wave_no >= 5
        )
        next_state = StrategyState.TERMINATED if should_terminate_now else StrategyState.PROFIT_TAKEN

        order = TradeOrder(
            timestamp=timestamp,
            action=action_type,
            price=tick_close,
            qty=sell_qty,
            amount=sell_amt,
            reason=sell_reason,
            stage=next_state.value
        )
        self.trade_history.append(order)

        next_pos = PositionTracker(
            state=next_state,
            trade_count_today=prev_trades,
            wave_no=saved_wave_no,
            wave_high_price=self.position.wave_high_price,
            session_high_price=saved_session_hi,
            prev_wave_tri_floor=cur_tf,
            failed_gijun_price=saved_failed_gj,
            consecutive_losses=prev_losses,
            realized_pnl_pct_today=cum_pnl,
            last_exit_price=tick_close,
            last_exit_time=now_ts,
            last_exit_pnl_pct=profit_rate,
            saw_gate_pullback=False,
            saw_rebound_to_gate=False,
            top_confirmed_reason=("2연패/손실상한 도달 졸업" if should_terminate_now else ""),
        )
        self.position = next_pos
        return order

