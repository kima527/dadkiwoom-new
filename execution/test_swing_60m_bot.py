"""
test_swing_60m_bot.py - 60분봉 TEMA 5-20 전용 스윙 봇 단위/통합 검증 테스트
"""

import os
import sys
import time as _t
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, CURRENT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "real trading"))

from execution.indicators import calculate_daily_seryek_gijun_lines
from execution.order_flow import (
    ExecutionStrengthEngine,
    classify_tick_direction,
    compute_c0_180_scale,
    get_session_info,
    is_auction_tick,
)
from execution.swing_60m_bot import (
    Swing60mBot,
    get_venue_session_state,
    get_open_stabilization_block,
    inject_live_price_60m,
    evaluate_60m_signals,
    evaluate_60m_exit,
    score_60m_entry_candidate,
)


def _warmup_rvp(bot, code: str, now_dt: datetime, is_nxt: bool = False, price: float = 51200.0, qty: int = 300, n_ticks: int = 6):
    now_ts = now_dt.timestamp()
    for i in range(n_ticks):
        t_tick = now_ts - 90.0 + i * (80.0 / max(1, n_ticks - 1))
        tm_s = datetime.fromtimestamp(t_tick).strftime("%H%M%S")
        bot.strength_engine.on_tick(
            {
                "code": code,
                "price": price,
                "qty": qty,
                "raw_15": f"+{qty}",
                "accum_volume": 10000 + i * qty,
                "gangdo": 135.0,
                "time": tm_s,
            },
            v_ref_1m=2_500_000.0,
            now_ts=t_tick,
            is_nxt=is_nxt,
            prior_5d_1m_amt=2_500_000.0,
        )


def _make_daily_df(closes, base_tv_m=1000.0, start_dt=datetime(2026, 9, 13)):
    rows = []
    for i, c in enumerate(closes):
        dt = (start_dt + timedelta(days=i)).strftime("%Y%m%d")
        tv = base_tv_m * (3.5 if i == len(closes) - 1 else 1.0)
        rows.append({
            "date": dt,
            "open": c * 0.99,
            "high": c * 1.02,
            "low": c * 0.98,
            "close": float(c),
            "volume": int((tv * 1_000_000) / max(1.0, c)),
            "trde_prica": tv,
        })
    return pd.DataFrame(rows)


def _make_60m_df(closes, start_dt=datetime(2026, 11, 20, 9, 0)):
    rows = []
    ts = start_dt
    for c in closes:
        rows.append({
            "time": ts,
            "open": float(c) * 0.998,
            "high": float(c) * 1.005,
            "low": float(c) * 0.995,
            "close": float(c),
            "volume": 50000.0,
        })
        ts += timedelta(hours=1)
    return pd.DataFrame(rows).set_index("time")


def test_venue_session_rules():
    wed_0830 = datetime(2026, 11, 25, 8, 30, 0)
    ok_n, _, ex_n = get_venue_session_state("NXT", wed_0830)
    ok_k, _, ex_k = get_venue_session_state("KRX", wed_0830)
    assert ok_n and ex_n == "NXT", f"08:30 NXT failed: {(ok_n, ex_n)}"
    assert (not ok_k) and ex_k == "", f"08:30 KRX must wait until 09:00: {(ok_k, ex_k)}"

    wed_0915 = datetime(2026, 11, 25, 9, 15, 0)
    ok_n2, _, ex_n2 = get_venue_session_state("NXT", wed_0915)
    ok_k2, _, ex_k2 = get_venue_session_state("KRX", wed_0915)
    assert ok_n2 and ex_n2 == "KRX"
    assert ok_k2 and ex_k2 == "KRX"

    wed_1630 = datetime(2026, 11, 25, 16, 30, 0)
    ok_n3, _, ex_n3 = get_venue_session_state("NXT", wed_1630)
    ok_k3, _, ex_k3 = get_venue_session_state("KRX", wed_1630, allow_krx_aftermarket=True)
    ok_k3_off, _, _ = get_venue_session_state("KRX", wed_1630, allow_krx_aftermarket=False)
    assert ok_n3 and ex_n3 == "NXT"
    assert ok_k3 and ex_k3 == "SOR"
    assert not ok_k3_off

    sat = datetime(2026, 11, 28, 10, 0, 0)
    assert not get_venue_session_state("NXT", sat)[0]
    print("PASS test_venue_session_rules")


def test_daily_seryek_gijun_formula():
    # Build >70 bars: uptrend -> peak K -> pullback -> bounce breaking previous gijun M with sma5 > M
    closes = (
        [10000 + i * 100 for i in range(65)]   # up to 16400 (5>20>60정배열)
        + [16800, 17200, 17000, 16200, 15400]  # peak K1=17200, then lower K=17000 -> gijun=17200
        + [15000, 15600, 16400, 17400, 17800, 18100, 18400]  # SMA5 crosses above 17200 -> seryek set
    )
    df = _make_daily_df(closes)
    m = calculate_daily_seryek_gijun_lines(df)
    assert m["gijun"] == 17200.0, f"expected gijun=17200, got {m['gijun']}"
    assert m["seryek"] > 17000.0, f"expected seryek > 17000, got {m['seryek']}"
    assert m["sma3_gt_5"] is True
    assert round(m["tv_ratio_pct"]) == 350, f"expected 350%, got {m['tv_ratio_pct']}"
    print("PASS test_daily_seryek_gijun_formula")


def test_60m_tema_gc_and_live_injection():
    # Steady base (30 bars) -> accelerating drop (TEMA5 < TEMA20) -> sharp turnaround crossing upward on final bar
    closes = [10000.0] * 30 + [9900, 9750, 9550, 9320, 9080, 8860, 8720, 8680, 8760, 8920]
    base_time = datetime(2026, 11, 25, 9, 0)
    df = _make_60m_df(closes, start_dt=base_time)

    last_bar_time = df.index[-1].to_pydatetime()
    same_hour = last_bar_time.replace(minute=30)
    next_hour = last_bar_time + timedelta(hours=1, minutes=10)

    df_same = inject_live_price_60m(df, current_price=9050.0, now_dt=same_hour)
    df_next = inject_live_price_60m(df, current_price=9050.0, now_dt=next_hour)
    assert len(df_same) == len(df), "Same-hour update must not append a bar"
    assert len(df_next) == len(df) + 1, "Next-hour live injection must append a bar"
    assert df_next.iloc[-2]["close"] == 8920.0, "Prior completed bar close must stay preserved"

    sig = evaluate_60m_signals(df, current_price=9050.0, now_dt=next_hour)
    assert sig["valid"] and sig["is_gc_bull"] and sig["is_entry_gc_ready"], f"Expected fresh 60m GC: {sig}"
    sig_chased = evaluate_60m_signals(df, current_price=9250.0, now_dt=next_hour)
    assert sig_chased["is_gc_bull"] and not sig_chased["is_entry_gc_ready"], "Over-chased +3.7% GC must be blocked"
    print("PASS test_60m_tema_gc_and_live_injection")


def test_exit_60m_dc_and_backup_gijun():
    # 1) Backup gijun triggers ONLY if was_above_60m_gijun is True
    sig_bull_above_to_below = {
        "valid": True,
        "price": 9900.0,
        "tema5": 10200.0,
        "tema20": 10100.0,
        "gap_pct": 0.99,
        "gijun_60m": 10000.0,
        "is_gc_bull": True,
        "dc_sell_signal": False,
        "dc_reason": "",
    }
    sell_no, _, above_no = evaluate_60m_exit(sig_bull_above_to_below, 9900.0, was_above_60m_gijun=False, gijun_buffer_pct=0.002)
    assert not sell_no and not above_no, "Must not false-trigger overhead gijun stop if never crossed above"

    sell_yes, reason_yes, above_yes = evaluate_60m_exit(sig_bull_above_to_below, 9900.0, was_above_60m_gijun=True, gijun_buffer_pct=0.002)
    assert sell_yes and above_yes and "기준선" in reason_yes, f"Expected backup gijun stop: {(sell_yes, reason_yes)}"

    # 2) Primary 60m TEMA 5-20 DC always triggers
    sig_dc = dict(sig_bull_above_to_below, dc_sell_signal=True, dc_reason="60분봉 TEMA 5-20 실시간 데드크로스(-0.20%)")
    sell_dc, reason_dc, _ = evaluate_60m_exit(sig_dc, 10050.0, was_above_60m_gijun=True)
    assert sell_dc and "데드크로스" in reason_dc
    print("PASS test_exit_60m_dc_and_backup_gijun")


def test_9stock_leader_ranking():
    leader_daily = {"tv_ratio_pct": 520.0, "today_tv_eok": 450.0, "dist_gijun_pct": 1.2, "dist_seryek_pct": 2.5, "sma3_gt_5": True}
    laggard_daily = {"tv_ratio_pct": 95.0, "today_tv_eok": 40.0, "dist_gijun_pct": -18.0, "dist_seryek_pct": -22.0, "sma3_gt_5": False}
    sig_strong = {"t5_slope": 250.0}
    sig_weak = {"t5_slope": 5.0}
    s1 = score_60m_entry_candidate(18.5, leader_daily, sig_strong, {"rvp_valid": True, "rvp60": 165.0, "rvp180": 140.0})
    s2 = score_60m_entry_candidate(2.5, laggard_daily, sig_weak, {"rvp_valid": True, "rvp60": 95.0, "rvp180": 90.0})
    assert s1["total"] > s2["total"] + 30.0, f"Leader should strongly outscore laggard: {s1} vs {s2}"
    s_unwarmed = score_60m_entry_candidate(18.5, leader_daily, sig_strong, {"rvp_valid": False, "rvp60": 100.0, "rvp180": 100.0})
    assert s_unwarmed["score_flow"] == 5.0, f"Unwarmed rvp_valid=False must get 0 RVP pts (only slope 5): {s_unwarmed}"
    print(f"PASS test_9stock_leader_ranking (leader={s1['total']}, laggard={s2['total']})")


class _FakeAPI:
    def __init__(self):
        self.holdings = {
            "042510": {"name": "라온시큐어", "qty": 1, "buy_price": 19050.0, "current_price": 19200.0},
            "323280": {"name": "태성", "qty": 1, "buy_price": 51300.0, "current_price": 52000.0},
            "181710": {"name": "NHN", "qty": 1, "buy_price": 60200.0, "current_price": 61000.0},
        }
        self.cash_100 = 4_490_000.0
        self.orders = []
        self.unfilled = []
        self.state_mode = "BUY_READY"  # switches to "SELL_READY" on second phase

        base_d = [40000 + i * 100 for i in range(65)] + [48000, 49000, 48500, 47000, 46000] + [45500, 46500, 48000, 50500, 52000]
        self.daily_df = _make_daily_df(base_d)

        # 60m GC turnaround for 태성(323280) and 라온시큐어(042510); accelerating drop DC for NHN
        gc_closes = [55000.0] * 30 + [54500, 53800, 52900, 51900, 50900, 50100, 49600, 49500, 50100, 50900]
        dc_closes = [50000.0] * 30 + [50800, 51900, 53200, 54500, 55000, 54200, 53100, 51800, 50500, 49500]
        self.m60_gc = _make_60m_df(gc_closes, start_dt=datetime(2026, 11, 24, 9, 0))
        self.m60_dc = _make_60m_df(dc_closes, start_dt=datetime(2026, 11, 24, 9, 0))

    def get_account_holdings(self):
        return {k: dict(v) for k, v in self.holdings.items()}

    def get_unexecuted_orders(self):
        return list(self.unfilled)

    def get_orderable_cash_100pct(self):
        return self.cash_100

    def get_daily_candles(self, code):
        return self.daily_df.copy()

    def get_60m_candles(self, code):
        if self.state_mode == "SELL_READY" and code == "323280":
            return self.m60_dc.copy()
        if code in ("323280", "042510"):
            return self.m60_gc.copy()
        return self.m60_dc.copy()

    def place_buy_order(self, code, qty, price, order_type="00", exchange_override=None):
        self.orders.append(("BUY", code, qty, price, order_type, exchange_override))
        return "ORD_BUY_1"

    def place_sell_order(self, code, qty, price, order_type="00", exchange_override=None):
        self.orders.append(("SELL", code, qty, price, order_type, exchange_override))
        return "ORD_SELL_1"


def test_mocked_full_cycle_marker_preservation():
    fake_api = _FakeAPI()
    bot = Swing60mBot(dry_run=False, enable_ws=False, api=fake_api)
    bot._clear_active_position()

    # 1) At 08:30 Thursday premarket: 라온시큐어(KRX) must be blocked; 태성(NXT) buys 100% cash with NXT limit
    dt_0830 = datetime(2026, 11, 26, 8, 30, 0)
    now_epoch = _t.time()
    bot.live_ticks["323280"] = {"price": 51200.0, "ts": now_epoch}
    bot.live_ticks["042510"] = {"price": 19200.0, "ts": now_epoch}
    bot.live_ticks["181710"] = {"price": 49500.0, "ts": now_epoch}
    for cd in ("323280", "042510", "181710"):
        bot.live_orderbooks[cd] = {"ask1": bot.live_ticks[cd]["price"], "bid1": bot.live_ticks[cd]["price"], "ts": now_epoch}
    _warmup_rvp(bot, "323280", dt_0830, is_nxt=True, price=51200.0)

    bot.run_cycle(now_dt=dt_0830)
    assert len(fake_api.orders) == 1, f"Expected exactly 1 buy order at 08:30, got {fake_api.orders}"
    side, code, qty, px, otype, ex = fake_api.orders[0]
    assert side == "BUY" and code == "323280" and otype == "00" and ex == "NXT"
    assert qty > 50, f"Expected full-buy qty (~85 shares), got {qty}"
    assert bot.state["pending_buy"]["marker_qty"] == 1

    # 2) Simulate fill completion -> active_code=323280, held = 1 + qty
    fake_api.holdings["323280"]["qty"] = 1 + qty
    dt_0915 = dt_0830.replace(hour=9, minute=15)
    bot.run_cycle(now_dt=dt_0915)
    assert bot.state["active_code"] == "323280" and bot.state["bot_qty"] == qty and bot.state["marker_qty"] == 1

    # 3) Switch 태성 60m to DC at 09:25 -> bot sells EXACT `qty` (NOT qty+1!), using KRX market order "03"
    fake_api.state_mode = "SELL_READY"
    bot._m60_cache.clear()
    bot.live_ticks["323280"] = {"price": 49500.0, "ts": _t.time()}
    dt_0925 = dt_0830.replace(hour=9, minute=25)
    bot.run_cycle(now_dt=dt_0925)
    assert len(fake_api.orders) == 2, f"Expected sell order at 09:25, got {fake_api.orders}"
    s_side, s_code, s_qty, _, s_type, s_ex = fake_api.orders[1]
    assert s_side == "SELL" and s_code == "323280" and s_qty == qty, f"Must preserve 1-share marker! sell={s_qty}, bot={qty}"
    assert s_type == "03" and s_ex == "KRX", f"Regular session sell must be market order '03' KRX: {(s_type, s_ex)}"

    # 4) Simulate sell filled leaving 1 share marker -> bot clears slot back to IDLE
    fake_api.holdings["323280"]["qty"] = 1
    bot.run_cycle(now_dt=dt_0925)
    assert bot.state["active_code"] is None and bot.state["bot_qty"] == 0
    bot._clear_active_position()
    if os.path.exists(os.path.join(CURRENT_DIR, "swing_60m_state.json")):
        os.remove(os.path.join(CURRENT_DIR, "swing_60m_state.json"))
    print(f"PASS test_mocked_full_cycle_marker_preservation (bought/sold {qty}주, preserved 1주 marker)")


def test_kiwoom_unfilled_oso_parsing():
    from kiwoom_client import KiwoomRealClient

    class _DummyAcc:
        def unfilled_orders_request_ka10075(self, **kwargs):
            return {
                "oso": [
                    {
                        "ord_no": "0561004",
                        "stk_cd": "088280",
                        "stk_nm": "쏘닉스",
                        "io_tp_nm": "+매수",
                        "oso_qty": "1",
                        "ord_pric": "3645",
                        "tm": "171909",
                        "stex_tp_txt": "SOR",
                    }
                ],
                "return_code": 0,
            }

    client = KiwoomRealClient.__new__(KiwoomRealClient)
    client.account_api = _DummyAcc()
    out = client.get_unfilled_orders()
    assert len(out) == 1 and out[0]["code"] == "088280" and out[0]["unfilled_qty"] == 1 and out[0]["exchange"] == "SOR"
    print("PASS test_kiwoom_unfilled_oso_parsing")


def test_swing60m_condition_search_regular_and_fallback():
    class _DummyWS:
        target_condition_map = {"12": "Swing60m"}

    class _FakeAPIWithExtGC(_FakeAPI):
        def get_60m_candles(self, code):
            if code == "005930":
                return self.m60_gc.copy()
            return super().get_60m_candles(code)

    fake_api = _FakeAPIWithExtGC()
    bot = Swing60mBot(dry_run=False, enable_ws=False, api=fake_api, condition_name="Swing60m")
    bot._clear_active_position()
    bot.ws_client = _DummyWS()

    dt_0930 = datetime(2026, 11, 26, 9, 30, 0)
    now_epoch = _t.time()
    for cd, px in [("323280", 51200.0), ("042510", 51200.0), ("181710", 49500.0), ("005930", 51200.0)]:
        bot.live_ticks[cd] = {"price": px, "ts": now_epoch}
        bot.live_orderbooks[cd] = {"ask1": px, "bid1": px, "ts": now_epoch}

    # 1) 정규장(09:30)에 Swing60m 등록되어 있지만 323280/042510 모두 아직 미편입 -> 매수 차단(관망)
    bot.run_cycle(now_dt=dt_0930)
    assert len(fake_api.orders) == 0, f"Must wait while Swing60m has 0 active matches: {fake_api.orders}"

    # 2) Swing60m 에 비-마커 0주 외부 종목(005930, 심지어 60m GC)이 편입돼도 감시풀 합류 및 매수 절대 차단!
    bot._on_cond_insert("005930", "Swing60m")
    uni = bot._get_watched_universe(fake_api.get_account_holdings())
    assert "005930" not in uni, f"0-share uncurated stock must NEVER enter watched universe: {list(uni)}"
    bot.run_cycle(now_dt=dt_0930)
    assert len(fake_api.orders) == 0, f"0-share stock from Swing60m must never be bought: {fake_api.orders}"

    # 3) 기존 감시 마커 라온시큐어(042510)가 Swing60m 편입 + 워밍업 완료 시 라온시큐어 즉시 풀매수
    bot._on_cond_insert("042510", "Swing60m")
    _warmup_rvp(bot, "042510", dt_0930, is_nxt=False, price=51200.0)
    bot.run_cycle(now_dt=dt_0930)
    assert len(fake_api.orders) == 1 and fake_api.orders[0][1] == "042510", f"Expected 042510 entry via Swing60m: {fake_api.orders}"

    # 4) 장전/폴백 검증: 08:30에 전일종가 이하(-1.0%) 종목은 폴백 필터에 걸리고, 전일종가 초과+SMA3>5 종목만 매수
    fake_api2 = _FakeAPI()
    bot2 = Swing60mBot(dry_run=False, enable_ws=False, api=fake_api2, condition_name="Swing60m")
    bot2._clear_active_position()
    dt_0830 = datetime(2026, 11, 26, 8, 30, 0)
    _warmup_rvp(bot2, "323280", dt_0830, is_nxt=True, price=51200.0)
    # 323280 live price 50000 < prev_close 50500 (전일종가 이하) -> 폴백 필터 차단
    bot2.live_ticks["323280"] = {"price": 50000.0, "ts": now_epoch}
    bot2.live_orderbooks["323280"] = {"ask1": 50000.0, "bid1": 50000.0, "ts": now_epoch}
    bot2.live_ticks["181710"] = {"price": 49500.0, "ts": now_epoch}
    bot2.live_orderbooks["181710"] = {"ask1": 49500.0, "bid1": 49500.0, "ts": now_epoch}
    bot2.run_cycle(now_dt=dt_0830)
    assert len(fake_api2.orders) == 0, f"Premarket fallback must filter day_ret <= 0: {fake_api2.orders}"

    # 다시 전일종가 초과(51200 > 50500) + SMA3>5 -> NXT 프리마켓 매수 정상 동작
    bot2.live_ticks["323280"] = {"price": 51200.0, "ts": now_epoch}
    bot2.live_orderbooks["323280"] = {"ask1": 51200.0, "bid1": 51200.0, "ts": now_epoch}
    bot2.run_cycle(now_dt=dt_0830)
    assert len(fake_api2.orders) == 1 and fake_api2.orders[0][1] == "323280"

    if os.path.exists(os.path.join(CURRENT_DIR, "swing_60m_state.json")):
        os.remove(os.path.join(CURRENT_DIR, "swing_60m_state.json"))
    print("PASS test_swing60m_condition_search_regular_and_fallback")


def test_swing60m_cond_delete_does_not_affect_exit():
    class _DummyWS:
        target_condition_map = {"12": "Swing60m"}

    fake_api = _FakeAPI()
    fake_api.holdings["323280"]["qty"] = 86
    bot = Swing60mBot(dry_run=False, enable_ws=False, api=fake_api, condition_name="Swing60m")
    bot._clear_active_position()
    bot.ws_client = _DummyWS()
    bot.state.update({
        "active_code": "323280",
        "active_name": "태성",
        "marker_qty": 1,
        "bot_qty": 85,
        "entry_price": 51200.0,
        "was_above_60m_gijun": False,
    })
    bot._save_state()

    # 1) 보유 중 Swing60m 조건식 이탈('D') 발생해도 60m GC 유지 중이면 조기 청산 금지 & 슬롯 유지
    bot._on_cond_insert("323280", "Swing60m")
    bot._on_cond_delete("323280", "Swing60m")
    assert bot.cond_picks["323280"]["active"] is False

    dt_1015 = datetime(2026, 11, 26, 10, 15, 0)
    bot.live_ticks["323280"] = {"price": 51300.0, "ts": _t.time()}
    bot.live_orderbooks["323280"] = {"ask1": 51300.0, "bid1": 51300.0, "ts": _t.time()}
    bot.run_cycle(now_dt=dt_1015)
    assert len(fake_api.orders) == 0 and bot.state["active_code"] == "323280"

    # 2) 이후 실제 60m TEMA 5-20 데드크로스 발생 시 마커 1주 남기고 85주 정상 전량 매도
    fake_api.state_mode = "SELL_READY"
    bot._m60_cache.clear()
    bot.live_ticks["323280"] = {"price": 49500.0, "ts": _t.time()}
    bot.run_cycle(now_dt=datetime(2026, 11, 26, 10, 25, 0))
    assert len(fake_api.orders) == 1
    s_side, s_code, s_qty, _, _, _ = fake_api.orders[0]
    assert s_side == "SELL" and s_code == "323280" and s_qty == 85

    if os.path.exists(os.path.join(CURRENT_DIR, "swing_60m_state.json")):
        os.remove(os.path.join(CURRENT_DIR, "swing_60m_state.json"))
    print("PASS test_swing60m_cond_delete_does_not_affect_exit")


def test_order_flow_auction_gap_ka10003_and_c0_180():
    # 1) k(T_eff) 0/0 guard & monotonic scaling
    assert compute_c0_180_scale(0.0) == 1.0
    assert compute_c0_180_scale(0.05) == 1.0
    assert compute_c0_180_scale(0.1) == 1.0
    k60 = compute_c0_180_scale(60.0)
    k180 = compute_c0_180_scale(180.0)
    assert 1.20 < k60 < 1.28 and 1.65 < k180 < 1.78, f"Unexpected k(T_eff): {k60}, {k180}"

    # classify_tick_direction signed integer symmetry
    assert classify_tick_direction(100, price=1000, prev_price=1000) is True
    assert classify_tick_direction(-100, price=1000, prev_price=1000) is False

    # NXT 08:00:01 continuous open must NOT be rejected; KRX 09:00:15 first tick MUST be rejected
    assert is_auction_tick("080001", accum_vol=100, tick_qty=100, is_nxt=True, first_session_tick=True) is False
    assert is_auction_tick("090015", accum_vol=50000, tick_qty=49000, is_nxt=False, first_session_tick=True) is True

    # 2) Bug ①: Gap Recovery must NOT swallow 09:00:15 opening auction block after premarket!
    eng = ExecutionStrengthEngine()
    t_0848 = datetime(2026, 11, 26, 8, 48, 0).timestamp()
    eng.on_tick({"code": "323280", "price": 50000, "qty": 10, "raw_15": "+10", "accum_volume": 100, "time": "084800"}, v_ref_1m=10_000_000, now_ts=t_0848, is_nxt=True)
    # KRX 09:00:15 opening print jumps accum_volume 100 -> 50000 (auction)
    t_090015 = datetime(2026, 11, 26, 9, 0, 15).timestamp()
    eng.on_tick({"code": "323280", "price": 52000, "qty": 49000, "raw_15": "+49000", "accum_volume": 50000, "gangdo": 180.0, "time": "090015"}, v_ref_1m=100_000_000, now_ts=t_090015, is_nxt=False, prior_5d_1m_amt=100_000_000)
    st = eng.get_state("323280")
    assert st.tick_count == 0 and st.b_60 == 0.0 and st.s_60 == 0.0, f"Opening auction leaked into RVP! {st.tick_count}, {st.b_60}"

    # Now continuous KRX ticks from 09:00:40..09:01:20 (t_eff = 45s >= 30s)
    for i in range(6):
        ti = (datetime(2026, 11, 26, 9, 0, 40) + timedelta(seconds=i * 8)).timestamp()
        eng.on_tick({"code": "323280", "price": 52100, "qty": 100, "raw_15": "+100", "accum_volume": 50000 + (i + 1) * 100, "time": datetime.fromtimestamp(ti).strftime("%H%M%S")}, v_ref_1m=100_000_000, now_ts=ti, is_nxt=False, prior_5d_1m_amt=100_000_000)
    m_open = eng.evaluate_entry_strength("323280", df_1m=None, v_ref_1m=100_000_000, now_ts=datetime(2026, 11, 26, 9, 1, 20).timestamp(), is_nxt=False, prior_5d_1m_amt=100_000_000)
    assert m_open["rvp_valid"] is True and m_open["live_ticks"] == 6
    assert abs(m_open["c0_180"] / m_open["c0"] - compute_c0_180_scale(45.0)) < 1e-6

    # 3) Bug ③ & Detail #2: ka10003 at 08:03 rejects yesterday 19:59 & uses tick_ts decay
    eng2 = ExecutionStrengthEngine()
    t_0803 = datetime(2026, 11, 26, 8, 3, 0).timestamp()
    sample_ticks = [
        {"price": 50000, "qty": 500, "raw_15": "+500", "time": "195950", "accum_volume": 90000},   # 전일 애프터 -> 반드시 폐기!
        {"price": 50000, "qty": 200, "raw_15": "+200", "time": "080010", "accum_volume": 200},     # 170초 전 매수 (감쇠됨)
        {"price": 50000, "qty": 200, "raw_15": "-200", "time": "080255", "accum_volume": 400},     # 5초 전 매도 (신선함)
    ]
    cnt = eng2.seed_from_ka10003("181710", sample_ticks, v_ref_1m=20_000_000, now_ts=t_0803, is_nxt=True, prior_5d_1m_amt=20_000_000)
    assert cnt == 2, f"Yesterday 19:59 tick must be rejected (expected 2, got {cnt})"
    st2 = eng2.get_state("181710")
    assert st2.s_60 > st2.b_60 * 5.0, f"08:02:55 sell must heavily outweigh decayed 08:00:10 buy: s60={st2.s_60}, b60={st2.b_60}"

    # Verify 08:20 smooth Bayesian v_ref blend eliminates step cliff
    eng3 = ExecutionStrengthEngine()
    for m_idx in range(19):
        eng3.on_1m_bar_closed("099320", 3_000_000.0, now_ts=datetime(2026, 11, 26, 8, m_idx + 1, 0).timestamp())
    v_19 = eng3._get_effective_v_ref(eng3.get_state("099320"), 0.0, 20_000_000.0, datetime(2026, 11, 26, 8, 19, 30).timestamp(), is_nxt=True)[0]
    eng3.on_1m_bar_closed("099320", 3_000_000.0, now_ts=datetime(2026, 11, 26, 8, 20, 0).timestamp())
    v_20 = eng3._get_effective_v_ref(eng3.get_state("099320"), 0.0, 20_000_000.0, datetime(2026, 11, 26, 8, 20, 30).timestamp(), is_nxt=True)[0]
    assert abs(v_20 - v_19) / max(1.0, v_19) < 0.05, f"v_ref must not cliff jump at bar 20: {v_19} -> {v_20}"
    print("PASS test_order_flow_auction_gap_ka10003_and_c0_180")


def test_gc_zero_chase_and_hard_gate_blackout():
    # 1) Bug ②: gc_bars_ago == 0 spike (+8.8%) must NOT bypass max_chase_pct as 0.0%
    base_closes = [10000.0] * 35 + [9800, 9600, 9400, 9200, 9100]  # still TEMA5 < TEMA20 up to iloc[-1]
    df_60 = _make_60m_df(base_closes, start_dt=datetime(2026, 11, 24, 9, 0))
    next_hr = df_60.index[-1].to_pydatetime() + timedelta(hours=1, minutes=5)
    sig_spike = evaluate_60m_signals(df_60, current_price=9900.0, now_dt=next_hr)
    assert sig_spike["is_gc_bull"] and sig_spike["gc_bars_ago"] == 0
    assert sig_spike["price_vs_gc_pct"] > 7.0 and not sig_spike["is_entry_gc_ready"], (
        f"gc_bars_ago==0 +8.8% spike must be blocked by max_chase_pct! {sig_spike}"
    )

    # 2) Opening stabilization blackout (08:01 NXT, 09:01 KRX)
    assert get_open_stabilization_block(datetime(2026, 11, 26, 8, 1, 0), "NXT")[0] is True
    assert get_open_stabilization_block(datetime(2026, 11, 26, 9, 1, 0), "KRX")[0] is True
    assert get_open_stabilization_block(datetime(2026, 11, 26, 8, 4, 0), "NXT")[0] is False

    # 3) Detail #3 Hard Gate: unwarmed (3 ticks < 5) must block even with 60m GC; warmed & 08:01 blackout also blocked
    fake_api = _FakeAPI()
    bot = Swing60mBot(dry_run=False, enable_ws=False, api=fake_api)
    bot._clear_active_position()
    dt_0830 = datetime(2026, 11, 26, 8, 30, 0)
    now_epoch = _t.time()
    bot.live_ticks["323280"] = {"price": 51200.0, "ts": now_epoch}
    bot.live_ticks["042510"] = {"price": 19200.0, "ts": now_epoch}
    bot.live_ticks["181710"] = {"price": 49500.0, "ts": now_epoch}
    for cd in ("323280", "042510", "181710"):
        bot.live_orderbooks[cd] = {"ask1": bot.live_ticks[cd]["price"], "bid1": bot.live_ticks[cd]["price"], "ts": now_epoch}

    # Only 3 ticks -> Hard Gate must block
    _warmup_rvp(bot, "323280", dt_0830, is_nxt=True, n_ticks=3)
    bot.run_cycle(now_dt=dt_0830)
    assert len(fake_api.orders) == 0, f"Hard Gate must block < 5 ticks unwarmed stock: {fake_api.orders}"

    # Fully warmed at 08:01 -> blocked by opening stabilization blackout
    dt_0801 = datetime(2026, 11, 26, 8, 1, 0)
    _warmup_rvp(bot, "323280", dt_0801, is_nxt=True, n_ticks=6)
    bot.run_cycle(now_dt=dt_0801)
    assert len(fake_api.orders) == 0, f"Must block 08:01 opening blackout: {fake_api.orders}"

    # Decelerating sell shock (buy early then sudden big sell -> RVP60 < 75%) -> blocked even when warmed
    fake_api_dump = _FakeAPI()
    bot_dump = Swing60mBot(dry_run=False, enable_ws=False, api=fake_api_dump)
    bot_dump._clear_active_position()
    for cd, px in [("323280", 51200.0), ("042510", 19200.0), ("181710", 49500.0)]:
        bot_dump.live_ticks[cd] = {"price": px, "ts": now_epoch}
        bot_dump.live_orderbooks[cd] = {"ask1": px, "bid1": px, "ts": now_epoch}
    base_t = dt_0830.timestamp()
    for i in range(4):
        bot_dump.strength_engine.on_tick({"code": "323280", "price": 51200, "qty": 50, "raw_15": "+50", "accum_volume": 1000 + i * 50, "time": "082800"}, v_ref_1m=2_500_000, now_ts=base_t - 100.0 + i * 10.0, is_nxt=True, prior_5d_1m_amt=2_500_000)
    for j in range(3):
        bot_dump.strength_engine.on_tick({"code": "323280", "price": 51200, "qty": 300, "raw_15": "-300", "accum_volume": 1300 + j * 300, "time": "082955"}, v_ref_1m=2_500_000, now_ts=base_t - 5.0 + j, is_nxt=True, prior_5d_1m_amt=2_500_000)
    bot_dump.run_cycle(now_dt=dt_0830)
    assert len(fake_api_dump.orders) == 0, f"Deceleration/dump RVP filter must block entry: {fake_api_dump.orders}"

    if os.path.exists(os.path.join(CURRENT_DIR, "swing_60m_state.json")):
        os.remove(os.path.join(CURRENT_DIR, "swing_60m_state.json"))
    print("PASS test_gc_zero_chase_and_hard_gate_blackout")


if __name__ == "__main__":
    test_venue_session_rules()
    test_daily_seryek_gijun_formula()
    test_60m_tema_gc_and_live_injection()
    test_exit_60m_dc_and_backup_gijun()
    test_9stock_leader_ranking()
    test_mocked_full_cycle_marker_preservation()
    test_kiwoom_unfilled_oso_parsing()
    test_swing60m_condition_search_regular_and_fallback()
    test_swing60m_cond_delete_does_not_affect_exit()
    test_order_flow_auction_gap_ka10003_and_c0_180()
    test_gc_zero_chase_and_hard_gate_blackout()
    print("\nALL 11 SWING_60M TESTS PASSED!")
