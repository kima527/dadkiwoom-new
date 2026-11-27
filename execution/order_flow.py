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
      1. Kiwoom FID 15 (`순간체결량` / `cntr_trde_qty`) explicit '+' or '-' sign.
      2. Lee-Ready best quote rule when ask1 > 0 and bid1 > 0.
      3. Tick rule against previous execution price, then carry `prev_is_buy`.
    """
    if raw_15 is not None:
        if isinstance(raw_15, (int, float)):
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
) -> bool:
    """
    Detect simultaneous auction cross ticks whose huge opening/closing block should not
    distort continuous-session RVP.
    """
    t = str(tick_time_str or "").replace(":", "").strip()
    if len(t) < 6 or not t[:6].isdigit():
        return False
    hhmmss = t[:6]

    # Opening cross at 08:00:00 (NXT) or 09:00:00 (KRX)
    if ("080000" <= hhmmss <= "080003" or "090000" <= hhmmss <= "090003"):
        if accum_vol > 0 and tick_qty > 0 and accum_vol == tick_qty:
            return True

    # KRX closing auction print (~15:30:00) when not NXT continuous session
    if not is_nxt and ("152955" <= hhmmss <= "153005") and tick_qty > 0:
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


class ExecutionStrengthEngine:
    """
    Tracks time-decayed value-weighted execution flow (RVP_60s, RVP_180s, V_3m, NetBuy_3m)
    across all subscribed condition-search & held stocks.
    """

    def __init__(self):
        self._states: Dict[str, _StockFlowState] = {}

    def get_state(self, code: str) -> _StockFlowState:
        cc = clean_code(code)
        st = self._states.get(cc)
        if st is None:
            st = _StockFlowState()
            self._states[cc] = st
        return st

    def on_orderbook(self, code: str, ask1: float, bid1: float, now_ts: Optional[float] = None) -> None:
        cc = clean_code(code)
        if not cc:
            return
        st = self.get_state(cc)
        ts = float(time.time() if now_ts is None else now_ts)
        if ask1 > 0:
            st.ask1 = float(ask1)
            st.quote_ts = ts
        if bid1 > 0:
            st.bid1 = float(bid1)
            st.quote_ts = ts

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
    ) -> None:
        """Ingest one execution tick (`0B` or `ka10003`) into decayed buy/sell accumulators."""
        cc = clean_code(tick_data.get("code", ""))
        if not cc:
            return
        st = self.get_state(cc)
        ts = float(time.time() if now_ts is None else now_ts)

        price = abs(float(tick_data.get("price", 0) or 0))
        qty = abs(int(tick_data.get("qty", 0) or 0))
        if price <= 0 or qty <= 0:
            return

        ask1 = float(tick_data.get("ask1", 0) or 0)
        bid1 = float(tick_data.get("bid1", 0) or 0)
        if ask1 > 0 and bid1 > 0:
            st.ask1 = ask1
            st.bid1 = bid1
            st.quote_ts = ts
        else:
            # Reuse fresh 0D quote if < 10s old
            if st.quote_ts > 0 and (ts - st.quote_ts) <= 10.0:
                ask1 = st.ask1
                bid1 = st.bid1

        accum_vol = abs(int(tick_data.get("accum_volume", 0) or 0))
        gangdo = abs(float(tick_data.get("gangdo", 0) or 0))
        tick_time = tick_data.get("time", "")

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

        # Gap recovery when packet dropped between WS ticks (only on monotonic same-session ticks)
        if accum_vol > 0 and st.last_accum_vol > 0 and accum_vol > st.last_accum_vol + qty:
            gap_qty = accum_vol - st.last_accum_vol - qty
            gap_amt = float(gap_qty) * price
            if v_ref_1m > 0:
                gap_amt = min(gap_amt, 3.0 * v_ref_1m)
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

        if is_auction_tick(tick_time, accum_vol, qty, is_nxt=is_nxt):
            return

        amt = price * float(qty)
        amt_w = min(amt, 3.0 * v_ref_1m) if v_ref_1m > 0 else amt

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
    ) -> int:
        """
        One-shot cold-start warmup from recent `ka10003` REST execution ticks.
        Expects iterable of dicts supporting keys `raw_15` / `cntr_trde_qty`, `price` / `cur_prc`,
        `time` / `tm`, `gangdo` / `cntr_str`.
        """
        cc = clean_code(code)
        if not cc:
            return 0
        st = self.get_state(cc)
        if st.ka10003_seeded and st.tick_count >= 10:
            return 0

        raw_list = list(ticks or [])
        if not raw_list:
            st.ka10003_seeded = True
            return 0

        base_ts = float(time.time() if now_ts is None else now_ts)
        # Convert HHMMSS timestamps into chronological timestamps anchored at base_ts
        parsed = []
        lt = time.localtime(base_ts)
        today_midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
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
            ts_item = base_ts
            if len(tm_raw) >= 6 and tm_raw[:6].isdigit():
                hh = int(tm_raw[0:2])
                mm = int(tm_raw[2:4])
                ss = int(tm_raw[4:6])
                cand_ts = today_midnight + hh * 3600 + mm * 60 + ss
                if cand_ts <= base_ts + 5.0:
                    ts_item = cand_ts
            parsed.append({
                "code": cc,
                "price": price,
                "qty": qty,
                "raw_15": s_q,
                "time": tm_raw,
                "gangdo": abs(float(str(item.get("gangdo", item.get("cntr_str", 0)) or 0).lstrip("+-"))),
                "accum_volume": abs(int(float(str(item.get("accum_volume", item.get("acc_trde_qty", 0)) or 0).lstrip("+-")))),
                "_ts": ts_item,
            })

        # Sort oldest -> newest so exponential decay matches exact timeline
        parsed.sort(key=lambda x: x["_ts"])
        # Filter to recent 240 seconds window if timestamps look historical
        recent = [x for x in parsed if (base_ts - x["_ts"]) <= 240.0]
        if not recent:
            recent = parsed[-60:]

        inserted = 0
        for row in recent:
            ts_item = float(row.pop("_ts"))
            # Prevent seeding past an already newer live tick
            if st.last_tick_ts > 0 and ts_item <= st.last_tick_ts:
                continue
            self.on_tick(row, v_ref_1m=v_ref_1m, now_ts=ts_item, is_nxt=is_nxt)
            inserted += 1

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
    ) -> Dict[str, Any]:
        """
        Evaluate whether fundamental buying pressure & box breakout energy justify a 1m TEMA 60-120 GC entry.
        Zero upper caps: strong surges / high RVP / wide expansion ranges are NEVER capped.
        """
        cc = clean_code(code)
        ts = float(time.time() if now_ts is None else now_ts)
        computed_v_ref, today_bars = compute_v_ref_1m(df_1m)
        v_ref = computed_v_ref if v_ref_1m is None else float(v_ref_1m)

        s = 0.2 if is_nxt else 1.0
        c0 = max(5_000_000.0 * s, 0.15 * v_ref)
        range_5m, close_pos_5m = compute_5m_box_metrics(df_1m)

        st = self._states.get(cc)
        live_coverage = 0.0
        tick_count = 0
        if st is not None and st.tick_count > 0:
            self._decay_to(st, ts)
            live_coverage = max(0.0, ts - st.first_tick_ts)
            tick_count = st.tick_count

        if st is not None and tick_count >= 10 and live_coverage >= 30.0:
            c0_180 = 3.0 * c0
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

        passed = bool(rvp60_ok and rvp180_ok and accel_ok and net_buy_ok and v3m_ok and activity_ok and box_ok)

        reasons = []
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
            "source": source,
            "rvp_60s": rvp_60s,
            "rvp_180s": rvp_180s,
            "v_3m": v_3m,
            "net_buy_3m": net_buy_3m,
            "activity_3m": activity_3m,
            "v_ref_1m": v_ref,
            "c0": c0,
            "range_5m": range_5m,
            "close_pos_5m": close_pos_5m,
            "live_ticks": tick_count,
            "live_coverage_sec": live_coverage,
            "reason": "OK" if passed else ", ".join(reasons),
        }
