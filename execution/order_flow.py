"""
Fundamentally grounded real-time Order Flow & Execution Strength engine (ExecutionStrengthEngine).

Replaces Kiwoom's distorted daily-reset cumulative FID 228 (`체결강도`) and fixes the
FID 10 (daily close sign) vs FID 15 (execution initiator `+`/`-` sign) bug with:
1. Tick classification priority:
   (a) FID 15 explicit '+' / '-' sign (buyer/seller initiated execution)
   (b) Lee-Ready quote rule using best ask/bid (ask1/bid1 from 0D or FID 27/28)
   (c) Tick Rule fallback (up-tick / down-tick / carry last)
2. Simultaneous auction tick exclusion (08:00 / 09:00 opening cross & KRX 15:30 closing cross)
   plus single-tick Winsorization (capped at 3.0 * v_ref_1m) so one block print never locks RVP.
3. Dual exponential decay (tau=60s & tau=180s) Value-Weighted Relative Volume Pressure (RVP)
   with dynamic Laplace smoothing C0 = max(5M * s, 0.15 * v_ref_1m), where s=0.2 in NXT.
4. 180s sliding bucket sums for V_3m, NetBuy_3m, Activity_3m, plus 5m box breakout quality
   (Range_5m >= 0.7%, Close_Pos_5m >= 0.60). No upper RVP or range ceilings ("무규제").
5. Automatic cold-start warmup via ka10003 recent ticks and/or 1m candle CLV proxy.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

LN2_60 = math.log(2.0) / 60.0
LN2_180 = math.log(2.0) / 180.0


def clean_code(code: Any) -> str:
    """Normalize stock code by removing exchange suffixes (_AL/_NX) and 'A' prefix."""
    s = str(code or "").replace("_AL", "").replace("_NX", "").strip()
    if s.startswith("A") and len(s) > 1 and s[1:].isalnum():
        s = s[1:]
    return s


def get_session_info(ts: float, is_nxt: bool = False) -> Tuple[str, float, float, float]:
    """
    Resolve `(session_key, continuous_open_ts, session_reset_ts, rho_t)` for epoch timestamp `ts`.

    - Continuous session anchors (`T_eff` reference): 08:00:00 (NXT_PRE), 09:00:35 (KRX_REG), 15:40:00 (NXT_AFTER)
    - Session boundary reset anchors: 08:00:00 / 09:00:00 / 15:40:00
    - Time-of-day liquidity multiplier `rho_t`: scales daily-average 1m turnover (`prior_5d_avg_1m_amt`)
      to the expected 1m liquidity of the active session & time window without double-scaling `C0`.
    """
    lt = time.localtime(ts)
    date_str = f"{lt.tm_year:04d}{lt.tm_mon:02d}{lt.tm_mday:02d}"
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
    sec = ts - midnight

    if 28800.0 <= sec < 31800.0:  # 08:00:00 ~ 08:50:00 NXT 프리마켓
        rho_t = 0.10 if sec < 29400.0 else 0.15
        open_ts = midnight + 28800.0
        return f"{date_str}_NXT_PRE", open_ts, open_ts, rho_t

    if 31800.0 <= sec < 32400.0:  # 08:50:00 ~ 09:00:00 KRX 장전 동시호가 대기
        return f"{date_str}_KRX_PREAUCTION", midnight + 32435.0, midnight + 31800.0, 1.0

    if 32400.0 <= sec < 55800.0:  # 09:00:00 ~ 15:30:00 KRX 정규장
        if sec < 32700.0:       # 09:00 ~ 09:05
            rho_t = 4.0
        elif sec < 33000.0:     # 09:05 ~ 09:10
            rho_t = 2.5
        elif sec < 33600.0:     # 09:10 ~ 09:20
            rho_t = 1.5
        elif 41400.0 <= sec < 48600.0:  # 11:30 ~ 13:30 점심 저유동
            rho_t = 0.6
        else:
            rho_t = 1.0
        return f"{date_str}_KRX_REG", midnight + 32435.0, midnight + 32400.0, rho_t

    if 55800.0 <= sec < 56400.0:  # 15:30:00 ~ 15:40:00 장후 전환 대기
        return f"{date_str}_AFTER_PREAUCTION", midnight + 56400.0, midnight + 55800.0, 0.15

    if 56400.0 <= sec < 72000.0:  # 15:40:00 ~ 20:00:00 애프터마켓
        open_ts = midnight + 56400.0
        return f"{date_str}_NXT_AFTER", open_ts, open_ts, 0.15

    # 시간외 테스트/오프세션: session_open_ts=0.0 -> 호출측에서 first_tick_ts 기반 처리
    return f"{date_str}_OFF", 0.0, midnight, (0.2 if is_nxt else 1.0)


def compute_c0_180_scale(t_eff: float) -> float:
    """
    Time-aware scaling factor k(T_eff) in [1.0, 3.0] for 180s Laplace smoothing C0_180 = k * C0_60.
    Matches the exact Poisson-arrival decayed integral ratio (1 - 2^(-T/180)) / (1 - 2^(-T/60)) * 3.0.
    Explicitly returns 1.0 when t_eff <= 0.1 to prevent 0/0 division / float precision loss.
    """
    if t_eff <= 0.1:
        return 1.0
    num = 1.0 - math.pow(2.0, -t_eff / 180.0)
    den = 1.0 - math.pow(2.0, -t_eff / 60.0)
    if den <= 1e-12:
        return 1.0
    return max(1.0, min(3.0, 3.0 * (num / den)))


def classify_tick_direction(
    raw_15: Any,
    price: float,
    prev_price: float,
    ask1: float = 0.0,
    bid1: float = 0.0,
    prev_is_buy: bool = True,
) -> bool:
    """
    Determine whether an execution tick was buyer-initiated (`True`) or seller-initiated (`False`).

    Priority:
      1. Kiwoom FID 15 (`순간체결량` / `cntr_trde_qty`) explicit '+' or '-' sign (numeric or string).
      2. Lee-Ready best quote rule when ask1 > 0 and bid1 > 0.
      3. Tick rule against previous execution price, then carry `prev_is_buy`.
    """
    if raw_15 is not None:
        if isinstance(raw_15, (int, float)):
            if raw_15 > 0:
                return True
            if raw_15 < 0:
                return False
        else:
            s15 = str(raw_15).strip()
            if s15.startswith("+"):
                return True
            if s15.startswith("-"):
                return False

    if ask1 > 0 and bid1 > 0 and price > 0:
        if price >= ask1:
            return True
        if price <= bid1:
            return False
        mid = 0.5 * (ask1 + bid1)
        if price > mid:
            return True
        if price < mid:
            return False

    if prev_price > 0 and price > 0:
        if price > prev_price:
            return True
        if price < prev_price:
            return False

    return bool(prev_is_buy)


def is_auction_tick(
    tick_time_str: Any,
    accum_vol: int,
    tick_qty: int,
    is_nxt: bool = False,
    first_session_tick: bool = False,
) -> bool:
    """
    Detect simultaneous auction cross ticks whose huge opening/closing block should not
    distort continuous-session RVP.

    - NXT opens continuously at 08:00:00 and 15:40:00 (never drop 08:00 NXT continuous prints).
    - KRX pre-open wait (08:50:00~08:59:59) and closing single-price auction (15:20:00~15:35:00) are excluded.
    - KRX opening cross supports Random End (09:00:00~09:00:35) via initial-window & `first_session_tick`.
    """
    t = str(tick_time_str or "").replace(":", "").strip()
    if len(t) < 6 or not t[:6].isdigit():
        return False
    hhmmss = t[:6]

    if is_nxt:
        # NXT 08:50~08:59:59 / 15:30~15:39:59 휴지기 혼입만 방어 (08:00·15:40 개시는 즉시 접속매매)
        if ("085000" <= hhmmss < "090000") or ("153000" <= hhmmss < "154000"):
            return True
        return False

    # KRX 동시호가 준비 구간(08:50~08:59:59) 제외
    if "085000" <= hhmmss < "090000":
        return True

    # KRX 시초가 단일가: 09:00:00~09:00:03 초기 체결 및 09:00:00~09:00:35 Random End 첫 단일가 차단
    if "090000" <= hhmmss <= "090035":
        if first_session_tick or ("090000" <= hhmmss <= "090003"):
            return True
        if accum_vol > 0 and tick_qty > 0 and accum_vol == tick_qty:
            return True

    # KRX 장마감 동시호가(15:20:00~15:35:00) 제외
    if "152000" <= hhmmss <= "153500" and tick_qty > 0:
        return True

    return False


def compute_v_ref_1m(df_1m: Optional[pd.DataFrame]) -> Tuple[float, int]:
    """
    Compute robust baseline 1-minute traded value `v_ref_1m` (KRW) and today's 1m bar count.
    `v_ref_1m = max(mean(last 20 active bars C*V), 0.5 * mean(today active bars C*V))`.
    """
    if df_1m is None or df_1m.empty:
        return 0.0, 0

    closes = pd.to_numeric(df_1m.get("close", pd.Series(dtype=float)), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    vols = pd.to_numeric(df_1m.get("volume", pd.Series(dtype=float)), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    if len(closes) == 0:
        return 0.0, 0

    vals = closes * vols
    tail20 = vals[-20:]
    pos20 = tail20[tail20 > 0]
    mean20 = float(np.mean(pos20)) if len(pos20) > 0 else 0.0

    today_bars = len(vals)
    session_mean = mean20
    if "datetime" in df_1m.columns:
        dt_s = df_1m["datetime"].astype(str)
        last_dt = dt_s.iloc[-1].strip()
        if len(last_dt) >= 8:
            day_prefix = last_dt[:8] if "-" not in last_dt else last_dt[:10]
            today_mask = dt_s.str.startswith(day_prefix).to_numpy(dtype=bool)
            today_vals = vals[today_mask]
            today_bars = int(np.sum(today_mask))
            pos_today = today_vals[today_vals > 0]
            if len(pos_today) > 0:
                session_mean = float(np.mean(pos_today))

    v_ref_1m = max(mean20, 0.5 * session_mean, 0.0)
    return v_ref_1m, today_bars


def compute_5m_box_metrics(df_1m: Optional[pd.DataFrame]) -> Tuple[float, float]:
    """
    Compute 5-minute range (%) and close position within the 5-minute high-low range.
    Returns `(range_5m_pct, close_pos_5m)`.
    """
    if df_1m is None or df_1m.empty:
        return 0.0, 0.0

    tail5 = df_1m.tail(5)
    highs = pd.to_numeric(tail5.get("high", tail5.get("close")), errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(tail5.get("low", tail5.get("close")), errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(tail5.get("close"), errors="coerce").to_numpy(dtype=float)

    valid_h = highs[np.isfinite(highs) & (highs > 0)]
    valid_l = lows[np.isfinite(lows) & (lows > 0)]
    valid_c = closes[np.isfinite(closes) & (closes > 0)]
    if len(valid_h) == 0 or len(valid_l) == 0 or len(valid_c) == 0:
        return 0.0, 0.0

    hi5 = float(np.max(valid_h))
    lo5 = float(np.min(valid_l))
    cur_c = float(valid_c[-1])
    span = hi5 - lo5
    range_5m = (span / lo5 * 100.0) if lo5 > 0 else 0.0
    close_pos_5m = ((cur_c - lo5) / span) if span > 1e-9 else 0.5
    return range_5m, max(0.0, min(1.0, close_pos_5m))


def compute_clv_warmup_flow(df_1m: Optional[pd.DataFrame], v_ref_1m: float, c0: float) -> Dict[str, float]:
    """
    Estimate 60s and 180s RVP, V_3m, and NetBuy_3m from recent 1m bars using Close Location Value (CLV)
    when live WS tick history is insufficient (< 30s coverage or < 10 ticks).
    """
    if df_1m is None or df_1m.empty:
        return {"rvp_60s": 100.0, "rvp_180s": 100.0, "v_3m": 0.0, "net_buy_3m": 0.0}

    tail3 = df_1m.tail(3)
    opens = pd.to_numeric(tail3.get("open", tail3.get("close")), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    highs = pd.to_numeric(tail3.get("high", tail3.get("close")), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    lows = pd.to_numeric(tail3.get("low", tail3.get("close")), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    closes = pd.to_numeric(tail3.get("close"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    vols = pd.to_numeric(tail3.get("volume", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)

    buy_vals = []
    sell_vals = []
    tot_vals = []
    for o, h, l, c, v in zip(opens, highs, lows, closes, vols):
        val = max(0.0, c * v)
        if v_ref_1m > 0:
            # Cap single bar distortion gently at 6x ref in warmup
            val = min(val, 6.0 * v_ref_1m)
        span = h - l
        if span > 1e-9:
            clv = max(-1.0, min(1.0, (2.0 * c - h - l) / span))
        else:
            if c > o:
                clv = 0.5
            elif c < o:
                clv = -0.5
            else:
                clv = 0.0
        buy_ratio = 0.5 * (1.0 + clv)
        b_v = val * buy_ratio
        s_v = val * (1.0 - buy_ratio)
        buy_vals.append(b_v)
        sell_vals.append(s_v)
        tot_vals.append(val)

    b_60 = buy_vals[-1] if buy_vals else 0.0
    s_60 = sell_vals[-1] if sell_vals else 0.0
    b_180 = float(sum(buy_vals))
    s_180 = float(sum(sell_vals))
    v_3m = float(sum(tot_vals))
    net_3m = b_180 - s_180

    c0_180 = 3.0 * c0
    denom60 = s_60 + c0
    denom180 = s_180 + c0_180
    rvp_60s = ((b_60 + c0) / denom60 * 100.0) if denom60 > 0 else 100.0
    rvp_180s = ((b_180 + c0_180) / denom180 * 100.0) if denom180 > 0 else 100.0
    return {
        "rvp_60s": rvp_60s,
        "rvp_180s": rvp_180s,
        "v_3m": v_3m,
        "net_buy_3m": net_3m,
    }


@dataclass
class _StockFlowState:
    session_key: str = ""
    session_open_ts: float = 0.0
    has_session_open_tick: bool = False
    last_price: float = 0.0
    last_is_buy: bool = True
    ask1: float = 0.0
    bid1: float = 0.0
    quote_ts: float = 0.0
    last_accum_vol: int = 0
    last_gangdo: float = 100.0
    first_tick_ts: float = 0.0
    last_tick_ts: float = 0.0
    last_decay_ts: float = 0.0
    tick_count: int = 0
    ka10003_seeded: bool = False
    b_60: float = 0.0
    s_60: float = 0.0
    b_180: float = 0.0
    s_180: float = 0.0
    # Deque of [sec_epoch, buy_val, sell_val]
    buckets: Deque[list] = field(default_factory=deque)
    # Clean continuous-session 1m turnover tracker (excludes auction blocks)
    recent_20_1m_vols: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    session_1m_sum: float = 0.0
    session_1m_count: int = 0
    ema_5m_vol: float = 0.0
    cur_min_key: int = -1
    cur_min_amt: float = 0.0

    def reset_for_session(self, session_key: str, session_open_ts: float) -> None:
        """Isolate each continuous session cleanly so premarket state never leaks into KRX open."""
        self.session_key = session_key
        self.session_open_ts = session_open_ts
        self.has_session_open_tick = False
        self.last_price = 0.0
        self.last_is_buy = True
        self.ask1 = 0.0
        self.bid1 = 0.0
        self.quote_ts = 0.0
        self.last_accum_vol = 0
        self.last_gangdo = 100.0
        self.first_tick_ts = 0.0
        self.last_tick_ts = 0.0
        self.last_decay_ts = 0.0
        self.tick_count = 0
        self.ka10003_seeded = False
        self.b_60 = 0.0
        self.s_60 = 0.0
        self.b_180 = 0.0
        self.s_180 = 0.0
        self.buckets.clear()
        self.recent_20_1m_vols.clear()
        self.session_1m_sum = 0.0
        self.session_1m_count = 0
        self.ema_5m_vol = 0.0
        self.cur_min_key = -1
        self.cur_min_amt = 0.0


class ExecutionStrengthEngine:
    """
    Tracks time-decayed value-weighted execution flow (RVP_60s, RVP_180s, V_3m, NetBuy_3m)
    across all subscribed condition-search & held stocks with strict session isolation.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._states: Dict[str, _StockFlowState] = {}

    def get_state(self, code: str) -> _StockFlowState:
        cc = clean_code(code)
        with self._lock:
            st = self._states.get(cc)
            if st is None:
                st = _StockFlowState()
                self._states[cc] = st
            return st

    def on_orderbook(self, code: str, ask1: float, bid1: float, now_ts: Optional[float] = None) -> None:
        cc = clean_code(code)
        if not cc:
            return
        ts = float(time.time() if now_ts is None else now_ts)
        # 08:50~08:59:59 동시호가 교차/허수 호가는 Lee-Ready 참조 캐시에서 배제
        if ask1 > 0 and bid1 > 0 and ask1 < bid1:
            return
        with self._lock:
            st = self.get_state(cc)
            if ask1 > 0:
                st.ask1 = float(ask1)
                st.quote_ts = ts
            if bid1 > 0:
                st.bid1 = float(bid1)
                st.quote_ts = ts

    def on_1m_bar_closed(self, code: str, bar_trade_amt: float, is_auction_bar: bool = False, now_ts: Optional[float] = None) -> None:
        """Record a completed clean 1-minute traded value into the active session baseline."""
        if is_auction_bar or bar_trade_amt < 0:
            return
        cc = clean_code(code)
        if not cc:
            return
        ts = float(time.time() if now_ts is None else now_ts)
        with self._lock:
            st = self.get_state(cc)
            sess_key, sess_open_ts, _, _ = get_session_info(ts, is_nxt=False)
            if st.session_key and st.session_key != sess_key:
                st.reset_for_session(sess_key, sess_open_ts)
            elif not st.session_key:
                st.session_key = sess_key
                st.session_open_ts = sess_open_ts
            val = float(bar_trade_amt)
            st.recent_20_1m_vols.append(val)
            st.session_1m_sum += val
            st.session_1m_count += 1
            alpha = 2.0 / (5.0 + 1.0)
            st.ema_5m_vol = val if st.ema_5m_vol <= 0 else (alpha * val + (1.0 - alpha) * st.ema_5m_vol)

    def _record_clean_1m_tick(self, st: _StockFlowState, ts: float, amt: float) -> None:
        min_key = int(ts // 60.0)
        if st.cur_min_key < 0:
            st.cur_min_key = min_key
            st.cur_min_amt = amt
            return
        if min_key == st.cur_min_key:
            st.cur_min_amt += amt
            return
        if min_key > st.cur_min_key:
            closed_val = float(st.cur_min_amt)
            st.recent_20_1m_vols.append(closed_val)
            st.session_1m_sum += closed_val
            st.session_1m_count += 1
            alpha = 2.0 / (5.0 + 1.0)
            st.ema_5m_vol = closed_val if st.ema_5m_vol <= 0 else (alpha * closed_val + (1.0 - alpha) * st.ema_5m_vol)
            st.cur_min_key = min_key
            st.cur_min_amt = amt

    def _get_effective_v_ref(
        self,
        st: Optional[_StockFlowState],
        v_ref_1m: float,
        prior_5d_1m_amt: Optional[float],
        ts: float,
        is_nxt: bool,
    ) -> Tuple[float, float]:
        """Return `(effective_v_ref_1m, rho_t)` using time profile and Bayesian continuous shrinkage."""
        _, _, _, rho_t = get_session_info(ts, is_nxt=is_nxt)
        if prior_5d_1m_amt is not None and prior_5d_1m_amt > 0:
            v_prior = float(prior_5d_1m_amt) * rho_t
        elif v_ref_1m > 0:
            # 호환 모드: external df_1m 기반 v_ref_1m이 전달된 경우 (단, NXT 확장시간에는 추가 스케일 고려)
            v_prior = float(v_ref_1m)
        else:
            v_prior = 0.0

        if st is None or st.session_1m_count <= 0:
            return v_prior, rho_t

        arr = list(st.recent_20_1m_vols)
        med20 = float(np.median(arr)) if arr else 0.0
        mean20 = float(np.mean(arr)) if arr else 0.0
        avg_sess = st.session_1m_sum / max(1, st.session_1m_count)
        v_obs = max(st.ema_5m_vol, 0.7 * med20 + 0.3 * mean20, 0.5 * avg_sess)

        if v_prior <= 0:
            return v_obs, rho_t

        w_n = min(1.0, float(st.session_1m_count) / 10.0)
        v_eff = (1.0 - w_n) * v_prior + w_n * max(v_obs, 0.25 * v_prior)
        return v_eff, rho_t

    def _decay_to(self, st: _StockFlowState, now_ts: float) -> None:
        if st.last_decay_ts <= 0:
            st.last_decay_ts = now_ts
            return
        dt = now_ts - st.last_decay_ts
        if dt <= 0:
            return
        d60 = math.exp(-LN2_60 * dt)
        d180 = math.exp(-LN2_180 * dt)
        st.b_60 *= d60
        st.s_60 *= d60
        st.b_180 *= d180
        st.s_180 *= d180
        st.last_decay_ts = now_ts

    def _add_bucket(self, st: _StockFlowState, now_ts: float, buy_val: float, sell_val: float) -> None:
        sec = int(now_ts)
        if st.buckets and st.buckets[-1][0] == sec:
            st.buckets[-1][1] += buy_val
            st.buckets[-1][2] += sell_val
        else:
            st.buckets.append([sec, buy_val, sell_val])
        cutoff = sec - 180
        while st.buckets and st.buckets[0][0] < cutoff:
            st.buckets.popleft()

    def on_tick(
        self,
        tick_data: Dict[str, Any],
        v_ref_1m: float = 0.0,
        now_ts: Optional[float] = None,
        is_nxt: bool = False,
        prior_5d_1m_amt: Optional[float] = None,
    ) -> None:
        """Ingest one execution tick (`0B` or `ka10003`) into session-isolated decayed accumulators."""
        cc = clean_code(tick_data.get("code", ""))
        if not cc:
            return
        ts = float(time.time() if now_ts is None else now_ts)

        price = abs(float(tick_data.get("price", 0) or 0))
        qty = abs(int(tick_data.get("qty", 0) or 0))
        if price <= 0 or qty <= 0:
            return

        sess_key, sess_open_ts, _, _ = get_session_info(ts, is_nxt=is_nxt)
        accum_vol = abs(int(tick_data.get("accum_volume", 0) or 0))
        gangdo = abs(float(tick_data.get("gangdo", 0) or 0))
        tick_time = tick_data.get("time", "")

        with self._lock:
            st = self.get_state(cc)
            if st.session_key != sess_key:
                st.reset_for_session(sess_key, sess_open_ts)

            ask1 = float(tick_data.get("ask1", 0) or 0)
            bid1 = float(tick_data.get("bid1", 0) or 0)
            if ask1 > 0 and bid1 > 0 and ask1 >= bid1:
                st.ask1 = ask1
                st.bid1 = bid1
                st.quote_ts = ts
            else:
                if st.quote_ts > 0 and (ts - st.quote_ts) <= 10.0:
                    ask1 = st.ask1
                    bid1 = st.bid1

            if "raw_15" in tick_data:
                is_buy = classify_tick_direction(
                    tick_data.get("raw_15"),
                    price=price,
                    prev_price=st.last_price,
                    ask1=ask1,
                    bid1=bid1,
                    prev_is_buy=st.last_is_buy,
                )
            elif "is_buy" in tick_data:
                is_buy = bool(tick_data["is_buy"])
            else:
                is_buy = classify_tick_direction(
                    None,
                    price=price,
                    prev_price=st.last_price,
                    ask1=ask1,
                    bid1=bid1,
                    prev_is_buy=st.last_is_buy,
                )

            self._decay_to(st, ts)

            eff_v_ref, _ = self._get_effective_v_ref(st, v_ref_1m, prior_5d_1m_amt, ts, is_nxt)
            is_first_tick = not st.has_session_open_tick
            raw_amt = price * float(qty)

            # ① [필수 방어] 동시호가/시초/VI 단일가 틱은 Gap Recovery 보다 먼저 판별해 전액 제외!
            vi_reopen_auction = (
                (not is_nxt)
                and st.last_tick_ts > 0
                and (ts - st.last_tick_ts) >= 90.0
                and eff_v_ref > 0
                and raw_amt >= 3.0 * eff_v_ref
            )
            if vi_reopen_auction or is_auction_tick(
                tick_time, accum_vol, qty, is_nxt=is_nxt, first_session_tick=is_first_tick
            ):
                if accum_vol > 0:
                    st.last_accum_vol = accum_vol
                if gangdo > 0:
                    st.last_gangdo = gangdo
                st.last_price = price
                st.last_is_buy = is_buy
                st.has_session_open_tick = True
                return

            st.has_session_open_tick = True

            # Gap recovery ONLY on post-open same-session ticks (`last_accum_vol > 0` established after auction)
            if accum_vol > 0 and st.last_accum_vol > 0 and accum_vol > st.last_accum_vol + qty:
                gap_qty = accum_vol - st.last_accum_vol - qty
                gap_amt = float(gap_qty) * price
                if eff_v_ref > 0:
                    gap_amt = min(gap_amt, 3.0 * eff_v_ref)
                g = gangdo if gangdo > 0 else st.last_gangdo
                p_buy = max(0.35, min(0.75, g / (g + 100.0))) if g > 0 else 0.5
                gb = gap_amt * p_buy
                gs = gap_amt * (1.0 - p_buy)
                st.b_60 += gb
                st.s_60 += gs
                st.b_180 += gb
                st.s_180 += gs
                self._add_bucket(st, ts, gb, gs)

            if accum_vol > 0:
                st.last_accum_vol = accum_vol
            if gangdo > 0:
                st.last_gangdo = gangdo

            st.last_price = price
            st.last_is_buy = is_buy

            amt_w = min(raw_amt, 3.0 * eff_v_ref) if eff_v_ref > 0 else raw_amt
            self._record_clean_1m_tick(st, ts, raw_amt)

            buy_add = amt_w if is_buy else 0.0
            sell_add = 0.0 if is_buy else amt_w

            st.b_60 += buy_add
            st.s_60 += sell_add
            st.b_180 += buy_add
            st.s_180 += sell_add
            self._add_bucket(st, ts, buy_add, sell_add)

            if st.first_tick_ts <= 0 or ts < st.first_tick_ts:
                st.first_tick_ts = ts
            if ts > st.last_tick_ts:
                st.last_tick_ts = ts
            st.tick_count += 1

    def seed_from_ka10003(
        self,
        code: str,
        ticks: Iterable[Dict[str, Any]],
        v_ref_1m: float = 0.0,
        now_ts: Optional[float] = None,
        is_nxt: bool = False,
        prior_5d_1m_amt: Optional[float] = None,
    ) -> int:
        """
        Cold-start warmup from recent `ka10003` REST execution ticks.
        - Discards previous-day ticks (e.g. yesterday 19:59 at 08:00) instead of clamping to `base_ts`.
        - Discards ticks prior to the current continuous session reset boundary.
        - Passes exact per-tick epoch `YYYY-MM-DD HH:MM:SS` (`tick_ts`) so historical ticks decay accurately.
        """
        cc = clean_code(code)
        if not cc:
            return 0
        base_ts = float(time.time() if now_ts is None else now_ts)
        sess_key, sess_open_ts, sess_reset_ts, _ = get_session_info(base_ts, is_nxt=is_nxt)

        with self._lock:
            st = self.get_state(cc)
            if st.session_key != sess_key:
                st.reset_for_session(sess_key, sess_open_ts)
            if st.ka10003_seeded and st.tick_count >= 5:
                return 0

            raw_list = list(ticks or [])
            if not raw_list:
                return 0

            lt = time.localtime(base_ts)
            today_midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
            parsed = []
            for item in raw_list:
                raw_q = item.get("raw_15", item.get("cntr_trde_qty", item.get("qty", 0)))
                s_q = str(raw_q).strip()
                try:
                    qty = abs(int(float(s_q.lstrip("+-"))))
                except Exception:
                    qty = 0
                raw_p = item.get("price", item.get("cur_prc", 0))
                try:
                    price = abs(float(str(raw_p).strip().lstrip("+-")))
                except Exception:
                    price = 0.0
                if qty <= 0 or price <= 0:
                    continue

                tm_raw = str(item.get("time", item.get("tm", ""))).replace(":", "").strip()
                if len(tm_raw) < 6 or not tm_raw[:6].isdigit():
                    continue
                hh, mm, ss = int(tm_raw[0:2]), int(tm_raw[2:4]), int(tm_raw[4:6])
                if hh > 23 or mm > 59 or ss > 59:
                    continue
                tick_ts = today_midnight + hh * 3600 + mm * 60 + ss

                # ③ 전일 야간(19:59) 틱 등 미래 시각으로 판별되는 구일 틱은 base_ts로 덮어쓰지 않고 즉시 폐기!
                if tick_ts > base_ts + 5.0:
                    continue
                # 이전 세션(08:49 등) 잔재 틱 폐기 & 최근 240초 이내 틱만 수용 (오래된 parsed[-60:] 폴백 금지)
                if tick_ts < sess_reset_ts or (base_ts - tick_ts) > 240.0:
                    continue
                tick_ts = min(tick_ts, base_ts)

                parsed.append({
                    "code": cc,
                    "price": price,
                    "qty": qty,
                    "raw_15": s_q,
                    "time": tm_raw,
                    "gangdo": abs(float(str(item.get("gangdo", item.get("cntr_str", 0)) or 0).lstrip("+-"))),
                    "accum_volume": abs(int(float(str(item.get("accum_volume", item.get("acc_trde_qty", 0)) or 0).lstrip("+-")))),
                    "_ts": tick_ts,
                })

            if not parsed:
                return 0

            # Oldest -> newest chronological decay across exact tick_ts timestamps
            parsed.sort(key=lambda x: x["_ts"])
            inserted = 0
            for row in parsed:
                t_item = float(row.pop("_ts"))
                if st.last_tick_ts > 0 and t_item < st.last_tick_ts:
                    continue
                self.on_tick(
                    row,
                    v_ref_1m=v_ref_1m,
                    now_ts=t_item,
                    is_nxt=is_nxt,
                    prior_5d_1m_amt=prior_5d_1m_amt,
                )
                inserted += 1

            # Decay accumulated balance smoothly from final tick_ts up to current query base_ts
            self._decay_to(st, base_ts)
            if inserted > 0:
                st.ka10003_seeded = True
            return inserted

    def evaluate_entry_strength(
        self,
        code: str,
        df_1m: Optional[pd.DataFrame],
        v_ref_1m: Optional[float] = None,
        big_order_streak: int = 0,
        is_nxt: bool = False,
        now_ts: Optional[float] = None,
        enforce_min_turnover: bool = True,
        prior_5d_1m_amt: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate whether fundamental buying pressure & box breakout energy justify entry.
        Zero upper caps: strong surges / high RVP / wide expansion ranges are NEVER capped.
        """
        cc = clean_code(code)
        ts = float(time.time() if now_ts is None else now_ts)
        computed_v_ref, today_bars = compute_v_ref_1m(df_1m)
        base_v_ref = computed_v_ref if v_ref_1m is None else float(v_ref_1m)

        range_5m, close_pos_5m = compute_5m_box_metrics(df_1m)
        sess_key, sess_open_ts, _, rho_t = get_session_info(ts, is_nxt=is_nxt)

        with self._lock:
            st = self._states.get(cc)
            if st is not None and st.session_key and st.session_key != sess_key:
                st.reset_for_session(sess_key, sess_open_ts)

            v_ref, _ = self._get_effective_v_ref(st, base_v_ref, prior_5d_1m_amt, ts, is_nxt)
            s = 0.2 if is_nxt else min(1.0, rho_t)
            c0 = max(5_000_000.0 * (0.2 if is_nxt else max(0.2, min(1.0, rho_t))), 0.15 * v_ref)

            # T_eff = 연속장 개시 시각(08:00:00, 09:00:35, 15:40:00) 경과초 (시간외 테스트는 first_tick_ts 기준)
            if sess_open_ts > 0.0:
                t_eff = max(0.0, ts - sess_open_ts)
            elif st is not None and st.first_tick_ts > 0:
                t_eff = max(0.0, ts - st.first_tick_ts)
            else:
                t_eff = 300.0

            live_coverage = 0.0
            tick_count = 0
            if st is not None and st.tick_count > 0:
                self._decay_to(st, ts)
                live_coverage = max(0.0, ts - st.first_tick_ts)
                tick_count = st.tick_count

            session_ready = (sess_open_ts <= 0.0) or (t_eff >= 30.0)
            rvp_valid = bool(st is not None and tick_count >= 5 and live_coverage >= 30.0 and session_ready)

            c0_scale = compute_c0_180_scale(t_eff)
            c0_180 = c0_scale * c0

            if rvp_valid and st is not None:
                rvp_60s = ((st.b_60 + c0) / max(st.s_60 + c0, 1e-9)) * 100.0
                rvp_180s = ((st.b_180 + c0_180) / max(st.s_180 + c0_180, 1e-9)) * 100.0
                sec_cutoff = int(ts) - 180
                while st.buckets and st.buckets[0][0] < sec_cutoff:
                    st.buckets.popleft()
                buy_3m = sum(b[1] for b in st.buckets)
                sell_3m = sum(b[2] for b in st.buckets)
                v_3m = buy_3m + sell_3m
                net_buy_3m = buy_3m - sell_3m
                source = "LIVE_WS"
            else:
                clv_flow = compute_clv_warmup_flow(df_1m, v_ref_1m=v_ref, c0=c0)
                rvp_60s = clv_flow["rvp_60s"]
                rvp_180s = clv_flow["rvp_180s"]
                v_3m = clv_flow["v_3m"]
                net_buy_3m = clv_flow["net_buy_3m"]
                source = "CLV_WARMUP"

        eff_win_sec = max(60.0, min(180.0, live_coverage)) if source == "LIVE_WS" else 180.0
        expected_win_turnover = v_ref * (eff_win_sec / 60.0) if v_ref > 0 else 0.0
        activity_3m = (v_3m / expected_win_turnover) if expected_win_turnover > 0 else 1.0

        rvp_60_min = 110.0 if big_order_streak >= 2 else 115.0
        rvp_180_min = 110.0

        rvp60_ok = rvp_60s >= rvp_60_min
        rvp180_ok = rvp_180s >= rvp_180_min
        accel_ok = rvp_60s >= (rvp_180s * 0.98)

        if enforce_min_turnover:
            v_3m_min = 150_000_000.0 * s
            net_buy_min = max(30_000_000.0 * s, 0.15 * expected_win_turnover) if expected_win_turnover > 0 else (30_000_000.0 * s)
            v3m_ok = v_3m >= v_3m_min
            net_buy_ok = net_buy_3m >= net_buy_min
        else:
            v_3m_min = 0.0
            net_buy_min = (0.15 * expected_win_turnover) if expected_win_turnover > 0 else 0.0
            v3m_ok = v_3m > 0
            net_buy_ok = net_buy_3m >= net_buy_min

        activity_ok = True if (today_bars < 5 or v_ref <= 0) else (activity_3m >= 0.80)
        box_ok = (range_5m >= 0.7) and (close_pos_5m >= 0.60)

        passed = bool(rvp_valid and rvp60_ok and rvp180_ok and accel_ok and net_buy_ok and v3m_ok and activity_ok and box_ok)

        reasons = []
        if not rvp_valid:
            reasons.append(f"워밍업미충족({tick_count}/5틱,{live_coverage:.0f}/30s,T_eff:{t_eff:.0f}s)")
        if not rvp60_ok:
            reasons.append(f"RVP60({rvp_60s:.1f}%<{rvp_60_min:.0f}%)")
        if not rvp180_ok:
            reasons.append(f"RVP180({rvp_180s:.1f}%<{rvp_180_min:.0f}%)")
        if not accel_ok:
            reasons.append(f"추세감속({rvp_60s:.1f}<{rvp_180s*0.98:.1f})")
        if not net_buy_ok:
            reasons.append(f"3분순매수({net_buy_3m/1e8:+.2f}억<{net_buy_min/1e8:.2f}억)")
        if not v3m_ok:
            reasons.append(f"3분거래대금({v_3m/1e8:.2f}억<{v_3m_min/1e8:.2f}억)")
        if not activity_ok:
            reasons.append(f"활동성({activity_3m:.2f}<0.80)")
        if not box_ok:
            reasons.append(f"5분박스(폭{range_5m:.2f}%/종가위치{close_pos_5m:.2f})")

        return {
            "passed": passed,
            "rvp_valid": rvp_valid,
            "source": source,
            "rvp_60s": rvp_60s,
            "rvp_180s": rvp_180s,
            "v_3m": v_3m,
            "net_buy_3m": net_buy_3m,
            "activity_3m": activity_3m,
            "v_ref_1m": v_ref,
            "c0": c0,
            "c0_180": c0_180,
            "t_eff": t_eff,
            "range_5m": range_5m,
            "close_pos_5m": close_pos_5m,
            "live_ticks": tick_count,
            "live_coverage_sec": live_coverage,
            "reason": "OK" if passed else ", ".join(reasons),
        }
