"""
swing_60m_bot.py - 계좌 1주 마커 감시종목(9종목) 전용 60분봉 TEMA 5-20 1종목 풀매수/전량매도 봇

[핵심 매매 규칙]
1. 감시 대상: 계좌에 1주 이상 보유한 감시 종목 자동 인식 + `execution/swing_60m_watchlist.json` 병합
   - KRX 전용(042510 라온시큐어, 281740 레이크머티리얼즈, 340450 지씨지놈):
     * 08:00~08:59 프리마켓 제외, 09:00 정규장부터 매매(15:40~20:00 애프터장은 SOR 자동 라우팅)
   - NXT 가능(181710 NHN, 099320 쎄트렉아이, 323280 태성, 065350 신성델타테크, 056190 SFA, 218410 RFHIC):
     * 08:00 NXT 프리마켓 ~ 15:30 KRX 정규장 ~ 20:00 NXT 애프터마켓 전 세션 매매
2. 매수 진입 (1종목 현금 100% 풀매수):
   - 필수 타점: 60분봉 `TEMA 5-20` 골든크로스(GC 0~2봉 초입, 과추격 <= +2.5%)
   - 동시 다발 GC 시 100점 대장주 스코어로 딱 1종목 선정:
     * 실시간 상승률(35점) + 5일 평균 거래대금 대비 비율/규모(30점) + 일봉 기준선·세력선 돌파/SMA3-5(20점) + RVP체결강도·TEMA5기울기(15점)
   - 매수 수량: 미수 없는 현금 100% 주문가능액(`kt00001 100stk_ord_alow_amt`) 기준 풀매수
   - 기본 `1주` 관종 마커 보존: 진입 전 계좌 보유 수량을 `marker_qty`로 잠금 보존
3. 매도 청산 (전량 시장가 매도 · 기본 1주 마커 제외):
   - 1차 원칙: 60분봉 `TEMA 5-20` 데드크로스(`TEMA5 < TEMA20`) 시 봇 진입 물량 전량 매도
   - 백업 방어: 진입 후 `60분봉 기준선(theme_gijun)` 상단에 안착한 적이 있던 종목이 기준선 하향 이탈 시 즉시 전량 시장가 매도
   - 매도 완료 시 기본 1주 마커만 계좌에 남기고 즉시 슬롯 개방
"""

import os
import sys
import json
import time
import threading
import logging
import importlib.util
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
MOVING_AVERAGE_TRAID = os.path.join(PROJECT_ROOT, "MovingAveragelineTraid", "execution")
REAL_TRADING_PATH = os.path.join(PROJECT_ROOT, "real trading")

for p in [PROJECT_ROOT, CURRENT_DIR, MOVING_AVERAGE_TRAID, REAL_TRADING_PATH]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

from execution.indicators import (
    calculate_all_60m_indicators,
    calculate_daily_seryek_gijun_lines,
)
from execution.order_flow import ExecutionStrengthEngine

# real trading/config.py 를 sys.modules['config']에 바인딩 (어댑터 로드 이전 필수)
_real_cfg_path = os.path.join(REAL_TRADING_PATH, "config.py")
if os.path.exists(_real_cfg_path):
    _real_spec = importlib.util.spec_from_file_location("config", _real_cfg_path)
    _real_cfg_mod = importlib.util.module_from_spec(_real_spec)
    sys.modules["config"] = _real_cfg_mod
    _real_spec.loader.exec_module(_real_cfg_mod)

try:
    from real_api_adapter import RealAPIAdapter
    HAS_REAL_API = True
except Exception as e:
    RealAPIAdapter = None
    HAS_REAL_API = False
    _REAL_API_ERR = e

try:
    from websocket_client import KiwoomWebSocketClient
    HAS_WS_CLIENT = True
except Exception:
    KiwoomWebSocketClient = None
    HAS_WS_CLIENT = False

WATCHLIST_PATH = os.path.join(CURRENT_DIR, "swing_60m_watchlist.json")
STATE_PATH = os.path.join(CURRENT_DIR, "swing_60m_state.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
SWING_LOG_PATH = os.path.join(LOG_DIR, f"swing_60m_bot_{datetime.now().strftime('%Y%m%d')}.log")

logger = logging.getLogger("Swing60mBot")


def configure_swing_logger() -> None:
    """전용 60분봉 봇 로거 파일/콘솔 핸들러 설정"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    if not any(
        isinstance(h, logging.FileHandler)
        and os.path.abspath(getattr(h, "baseFilename", "")) == os.path.abspath(SWING_LOG_PATH)
        for h in root_logger.handlers
    ):
        fh = logging.FileHandler(SWING_LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root_logger.addHandler(sh)


DEFAULT_KRX_ONLY_CODES: Dict[str, str] = {
    "042510": "라온시큐어",
    "281740": "레이크머티리얼즈",
    "340450": "지씨지놈",
}

DEFAULT_NXT_CODES: Dict[str, str] = {
    "181710": "NHN",
    "099320": "쎄트렉아이",
    "323280": "태성",
    "065350": "신성델타테크",
    "056190": "SFA",
    "218410": "RFHIC",
}


def normalize_code(code: Any) -> str:
    """종목코드 6자리 정규화 (_AL/_NX 및 선행 'A' 제거)"""
    clean = str(code or "").replace("_AL", "").replace("_NX", "").strip()
    if clean.startswith("A") and len(clean) == 7:
        clean = clean[1:]
    if clean.isdigit() and len(clean) < 6:
        clean = clean.zfill(6)
    return clean


def load_watchlist_config(path: str = WATCHLIST_PATH) -> Tuple[Dict[str, str], Dict[str, str]]:
    """swing_60m_watchlist.json 로드 (미존재 시 기본 9종목 반환)"""
    krx_map = dict(DEFAULT_KRX_ONLY_CODES)
    nxt_map = dict(DEFAULT_NXT_CODES)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if isinstance(data.get("krx_only_codes"), dict):
                    krx_map = {normalize_code(k): str(v) for k, v in data["krx_only_codes"].items() if normalize_code(k)}
                if isinstance(data.get("nxt_codes"), dict):
                    nxt_map = {normalize_code(k): str(v) for k, v in data["nxt_codes"].items() if normalize_code(k)}
        except Exception as e:
            logger.warning(f"watchlist 설정 로드 실패(기본값 사용): {e}")
    return krx_map, nxt_map


def get_krx_tick_size(price: float) -> int:
    """한국거래소 호가 단위 반환"""
    if price is None or (isinstance(price, float) and np.isnan(price)) or price <= 0:
        return 1
    if price < 2000:
        return 1
    if price < 5000:
        return 5
    if price < 20000:
        return 10
    if price < 50000:
        return 50
    if price < 200000:
        return 100
    if price < 500000:
        return 500
    return 1000


def align_to_tick(price: float) -> int:
    if price is None or (isinstance(price, float) and np.isnan(price)) or price <= 0:
        return 0
    tick = get_krx_tick_size(price)
    return int((int(price) // tick) * tick)


def get_smart_buy_price(price: float) -> int:
    """+1~2호가 공격적 지정가 (슬리피지 +0.35% 이내)"""
    base_p = align_to_tick(price)
    if base_p <= 0:
        return 0
    tick = get_krx_tick_size(base_p)
    if (tick * 2) / base_p <= 0.003:
        return base_p + (tick * 2)
    if tick / base_p <= 0.0035:
        return base_p + tick
    return base_p


def get_smart_sell_price(price: float, best_bid: float = 0.0) -> int:
    """시간외 지정가 매도 체결률 확보용 -1~2호가 지정가 (슬리피지 -0.35% 이내)"""
    ref_p = best_bid if best_bid and best_bid > 0 else price
    base_p = align_to_tick(ref_p)
    if base_p <= 0:
        return 0
    tick = get_krx_tick_size(max(1, base_p - 1))
    if (tick * 2) / base_p <= 0.003:
        return max(tick, base_p - (tick * 2))
    if tick / base_p <= 0.0035:
        return max(tick, base_p - tick)
    return base_p


def get_venue_session_state(
    venue: str,
    now_dt: Optional[datetime] = None,
    allow_krx_aftermarket: bool = True,
) -> Tuple[bool, str, str]:
    """
    종목 구분(NXT vs KRX)별 현재 매매 가능 여부 및 주문 거래소 반환:
    - NXT: 08:00~08:50(NXT), 09:00~15:30(KRX), 15:40~20:00(NXT)
    - KRX: 08:00~08:59 대기(매매불가), 09:00~15:30(KRX), 15:40~20:00(SOR 애프터장)
    """
    dt = now_dt or datetime.now()
    if dt.weekday() >= 5:
        return False, "주말휴장", ""

    now_t = dt.time()
    v = "KRX" if str(venue).upper() == "KRX" else "NXT"

    if dtime(8, 0, 0) <= now_t < dtime(8, 50, 0):
        if v == "NXT":
            return True, "NXT 프리마켓(08:00~08:50)", "NXT"
        return False, "KRX 정규장 대기(09:00개시)", ""

    if dtime(8, 50, 0) <= now_t < dtime(9, 0, 0):
        return False, "정규장 동시호가(08:50~09:00)", ""

    if dtime(9, 0, 0) <= now_t < dtime(15, 30, 0):
        return True, "KRX 정규장(09:00~15:30)", "KRX"

    if dtime(15, 30, 0) <= now_t < dtime(15, 40, 0):
        return False, "장후 동시호가 전환(15:30~15:40)", ""

    if dtime(15, 40, 0) <= now_t < dtime(20, 0, 0):
        if v == "NXT":
            return True, "NXT 애프터마켓(15:40~20:00)", "NXT"
        if allow_krx_aftermarket:
            return True, "SOR 애프터마켓(15:40~20:00)", "SOR"
        return False, "KRX 장마감", ""

    return False, "장운영 시간외", ""


def inject_live_price_60m(
    df_60m: Optional[pd.DataFrame],
    current_price: Optional[float] = None,
    now_dt: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    60분봉 DataFrame에 실시간 현재가 반영:
    - 현재 시(HH:00)의 봉이 이미 존재하면 종가/고가/저가 실시간 갱신
    - 현재 시가 직전 완성봉보다 뒤라면 직전 완성봉을 덮어쓰지 않고 새 실시간 봉 추가
    """
    if df_60m is None or df_60m.empty:
        return pd.DataFrame()

    df = df_60m.copy()
    has_dt_index = isinstance(df.index, pd.DatetimeIndex)
    if not has_dt_index and "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).set_index("time")
        has_dt_index = isinstance(df.index, pd.DatetimeIndex)

    if has_dt_index:
        df = df.sort_index()

    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").ffill().astype(float)
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).astype(float)
    else:
        df["volume"] = 0.0

    if current_price is None or float(current_price) <= 0 or len(df) == 0:
        return df

    cp = float(current_price)
    if has_dt_index and now_dt is not None:
        cur_hour_ts = pd.Timestamp(now_dt.replace(minute=0, second=0, microsecond=0))
        last_ts = pd.Timestamp(df.index[-1])
        if cur_hour_ts > last_ts:
            new_row = pd.DataFrame(
                {"open": [cp], "high": [cp], "low": [cp], "close": [cp], "volume": [0.0]},
                index=[cur_hour_ts],
            )
            df = pd.concat([df, new_row])
            return df

    last_idx = df.index[-1]
    df.at[last_idx, "close"] = cp
    if cp > float(df.at[last_idx, "high"]):
        df.at[last_idx, "high"] = cp
    if cp < float(df.at[last_idx, "low"]):
        df.at[last_idx, "low"] = cp
    return df


def evaluate_60m_signals(
    df_60m: Optional[pd.DataFrame],
    current_price: Optional[float] = None,
    now_dt: Optional[datetime] = None,
    max_gc_bars_ago: int = 2,
    max_chase_pct: float = 2.5,
) -> Dict[str, Any]:
    """
    60분봉 TEMA 5-20 골든크로스/데드크로스 및 60분봉 기준선(theme_gijun) 산출
    """
    empty = {
        "valid": False,
        "price": 0.0,
        "tema5": 0.0,
        "tema20": 0.0,
        "tema5_prev": 0.0,
        "tema20_prev": 0.0,
        "t5_slope": 0.0,
        "gap_pct": 0.0,
        "gijun_60m": 0.0,
        "is_gc_bull": False,
        "gc_bars_ago": None,
        "gc_close": 0.0,
        "price_vs_gc_pct": 0.0,
        "is_entry_gc_ready": False,
        "dc_sell_signal": False,
        "dc_reason": "",
    }
    if df_60m is None or len(df_60m) < 25:
        return empty

    df_live = inject_live_price_60m(df_60m, current_price=current_price, now_dt=now_dt)
    if df_live.empty or len(df_live) < 25:
        return empty

    df_ind = calculate_all_60m_indicators(df_live, p1=5, p2=20, p_slow=60)
    t5 = df_ind["tema_fast"]
    t20 = df_ind["tema_slow"]
    closes = df_ind["close"]

    t5_cur = float(t5.iloc[-1])
    t20_cur = float(t20.iloc[-1])
    t5_prev = float(t5.iloc[-2])
    t20_prev = float(t20.iloc[-2])
    price_cur = float(closes.iloc[-1])

    if any(np.isnan(v) for v in (t5_cur, t20_cur, t5_prev, t20_prev, price_cur)) or t20_cur <= 0:
        return empty

    gijun_val = 0.0
    if "theme_gijun" in df_ind.columns and pd.notna(df_ind["theme_gijun"].iloc[-1]):
        gijun_val = float(df_ind["theme_gijun"].iloc[-1])

    gap_pct = (t5_cur - t20_cur) / t20_cur * 100.0
    t5_slope = t5_cur - t5_prev
    is_gc_bull = t5_cur > t20_cur

    cross_up_s = (t5.shift(1) <= t20.shift(1)) & (t5 > t20)
    cross_dn_s = (t5.shift(1) >= t20.shift(1)) & (t5 < t20)

    gc_bars_ago = None
    gc_close = 0.0
    if is_gc_bull:
        for idx in range(len(df_ind) - 1, 0, -1):
            if bool(cross_up_s.iloc[idx]):
                gc_bars_ago = (len(df_ind) - 1) - idx
                gc_close = float(closes.iloc[idx])
                break

    price_vs_gc_pct = ((price_cur - gc_close) / gc_close * 100.0) if gc_close > 0 else 0.0
    is_entry_gc_ready = bool(
        is_gc_bull
        and gc_bars_ago is not None
        and gc_bars_ago <= max_gc_bars_ago
        and price_vs_gc_pct <= max_chase_pct
    )

    dc_sell_signal = False
    dc_reason = ""
    if not is_gc_bull:
        if bool(cross_dn_s.iloc[-1]) and gap_pct <= -0.10:
            dc_sell_signal = True
            dc_reason = f"60분봉 TEMA 5-20 실시간 데드크로스(이격 {gap_pct:+.2f}%)"
        elif len(df_ind) >= 3 and bool(cross_dn_s.iloc[-2]):
            dc_sell_signal = True
            dc_reason = f"60분봉 TEMA 5-20 직전완성봉 확정 데드크로스(이격 {gap_pct:+.2f}%)"
        elif gap_pct <= -0.15:
            dc_sell_signal = True
            dc_reason = f"60분봉 TEMA 5-20 하향 이탈({gap_pct:+.2f}%)"

    return {
        "valid": True,
        "price": price_cur,
        "tema5": t5_cur,
        "tema20": t20_cur,
        "tema5_prev": t5_prev,
        "tema20_prev": t20_prev,
        "t5_slope": t5_slope,
        "gap_pct": gap_pct,
        "gijun_60m": gijun_val,
        "is_gc_bull": is_gc_bull,
        "gc_bars_ago": gc_bars_ago,
        "gc_close": gc_close,
        "price_vs_gc_pct": price_vs_gc_pct,
        "is_entry_gc_ready": is_entry_gc_ready,
        "dc_sell_signal": dc_sell_signal,
        "dc_reason": dc_reason,
    }


def evaluate_60m_exit(
    sig_60m: Dict[str, Any],
    live_price: float,
    was_above_60m_gijun: bool,
    gijun_buffer_pct: float = 0.0,
) -> Tuple[bool, str, bool]:
    """
    60분봉 보유 청산 판정:
      1) 60분봉 TEMA 5-20 데드크로스 시 즉시 전량 시장가 매도
      2) 백업: 60분봉 기준선(theme_gijun) 위에 안착했던 종목이 기준선 하향 이탈 시 즉시 전량 시장가 매도
    """
    gijun_60m = float(sig_60m.get("gijun_60m", 0.0) or 0.0)
    updated_above = bool(was_above_60m_gijun or (gijun_60m > 0 and live_price >= gijun_60m * 1.001))

    if sig_60m.get("dc_sell_signal"):
        return True, sig_60m.get("dc_reason") or "60분봉 TEMA 5-20 데드크로스", updated_above

    if was_above_60m_gijun and gijun_60m > 0 and live_price > 0:
        cutoff = gijun_60m * (1.0 - max(0.0, float(gijun_buffer_pct)))
        if live_price < cutoff:
            diff_pct = (live_price - gijun_60m) / gijun_60m * 100.0
            return True, f"60분봉 기준선({gijun_60m:,.0f}원) 하향 이탈({diff_pct:+.2f}%) 백업 전량매도", updated_above

    return False, "", updated_above


def score_60m_entry_candidate(
    day_ret_pct: float,
    daily_metrics: Dict[str, Any],
    sig_60m: Dict[str, Any],
    rvp_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """
    9종목 풀 중 1종목 풀매수 우선순위 100점 스코어링:
      1) 당일 상승률(힘)         : 35점
      2) 5일평균 거래대금 비율/규모: 30점 (비율 22 + 절대대금 8)
      3) 일봉 기준·세력선 & 3-5 GC : 20점
      4) 실시간 체결강도(RVP)·각도  : 15점
    """
    # 1) 상승률 (35점)
    score_ret = min(35.0, max(0.0, (float(day_ret_pct) + 1.0) / 21.0 * 35.0))

    # 2) 거래대금 비율 + 규모 (30점)
    tv_ratio = float(daily_metrics.get("tv_ratio_pct", 0.0) or 0.0)
    today_tv_eok = float(daily_metrics.get("today_tv_eok", 0.0) or 0.0)
    score_tv_ratio = min(22.0, max(0.0, (tv_ratio - 50.0) / 350.0 * 22.0))
    if today_tv_eok >= 300.0:
        score_tv_size = 8.0
    elif today_tv_eok >= 150.0:
        score_tv_size = 6.0
    elif today_tv_eok >= 70.0:
        score_tv_size = 4.0
    elif today_tv_eok >= 25.0:
        score_tv_size = 2.0
    else:
        score_tv_size = 1.0
    score_tv = score_tv_ratio + score_tv_size

    # 3) 일봉 기준선/세력선 & SMA 3-5 (20점)
    line_scores = []
    for key in ("dist_gijun_pct", "dist_seryek_pct"):
        d = float(daily_metrics.get(key, 999.0) or 999.0)
        if abs(d) > 200.0:
            continue
        if 0.0 <= d <= 8.0:
            line_scores.append(16.0)
        elif -3.5 <= d < 0.0:
            line_scores.append(12.5)
        elif (8.0 < d <= 16.0) or (-10.0 <= d < -3.5):
            line_scores.append(7.0)
        else:
            line_scores.append(2.0)
    score_line = max(line_scores) if line_scores else 2.0
    score_sma35 = 4.0 if daily_metrics.get("sma3_gt_5") else 0.0
    score_daily = min(20.0, score_line + score_sma35)

    # 4) 60m TEMA5 상승 기울기 & RVP 체결강도 (15점)
    score_slope = 5.0 if float(sig_60m.get("t5_slope", 0.0) or 0.0) > 0 else 0.0
    rvp_info = rvp_info or {}
    rvp_valid = bool(rvp_info.get("rvp_valid", False))
    rvp_val = max(float(rvp_info.get("rvp60", 0.0) or 0.0), float(rvp_info.get("rvp180", 0.0) or 0.0))
    if not rvp_valid:
        score_rvp = 5.0  # 장초반/워밍업 전 중립 점수 (진입 차단 안 함)
    elif rvp_val >= 140.0:
        score_rvp = 10.0
    elif rvp_val >= 110.0:
        score_rvp = 7.0
    elif rvp_val >= 85.0:
        score_rvp = 4.0
    else:
        score_rvp = 0.0
    score_flow = score_slope + score_rvp

    total = round(score_ret + score_tv + score_daily + score_flow, 2)
    return {
        "total": total,
        "score_ret": round(score_ret, 1),
        "score_tv": round(score_tv, 1),
        "score_daily": round(score_daily, 1),
        "score_flow": round(score_flow, 1),
    }


class Swing60mBot:
    """계좌 보유 마커(1주) 종목 전용 60분봉 TEMA 5-20 1종목 풀매수·전량매도 봇"""

    def __init__(
        self,
        dry_run: bool = False,
        enable_ws: bool = True,
        max_budget_pct: float = 99.2,
        allow_krx_aftermarket: bool = True,
        gijun_buffer_pct: float = 0.002,
        api: Optional[Any] = None,
    ):
        if not HAS_REAL_API and api is None:
            raise RuntimeError(f"RealAPIAdapter 로드 실패: {_REAL_API_ERR}")

        self.dry_run = dry_run
        self.enable_ws = enable_ws and HAS_WS_CLIENT and (api is None)
        self.max_budget_pct = max(10.0, min(99.8, float(max_budget_pct)))
        self.allow_krx_aftermarket = allow_krx_aftermarket
        self.gijun_buffer_pct = max(0.0, float(gijun_buffer_pct))

        self.api = api if api is not None else RealAPIAdapter()
        self.krx_map, self.nxt_map = load_watchlist_config()
        self.strength_engine = ExecutionStrengthEngine()
        self.live_ticks: Dict[str, Dict[str, float]] = {}
        self.live_orderbooks: Dict[str, Dict[str, float]] = {}
        self._v_ref_cache: Dict[str, float] = {}
        self._daily_cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
        self._m60_cache: Dict[str, Tuple[float, int, pd.DataFrame]] = {}
        self._ka10003_seeded: set[str] = set()
        self.ws_client = None
        self.ws_thread: Optional[threading.Thread] = None

        self.state = self._load_state()
        if self.enable_ws:
            self._start_ws_daemon()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "active_code": None,
            "active_name": "",
            "marker_qty": 0,
            "bot_qty": 0,
            "entry_price": 0.0,
            "entry_time": "",
            "entry_venue": "",
            "was_above_60m_gijun": False,
            "pending_buy": None,
            "pending_sell": None,
            "venue_overrides": {},
        }

    def _load_state(self) -> Dict[str, Any]:
        st = self._default_state()
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    st.update(loaded)
            except Exception as e:
                logger.warning(f"상태 파일 로드 실패(초기 상태 사용): {e}")
        return st

    def _save_state(self) -> None:
        if self.dry_run:
            return
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"상태 파일 저장 에러: {e}")

    def _start_ws_daemon(self) -> None:
        def _on_tick(tick_data: dict):
            try:
                code = normalize_code(tick_data.get("code", ""))
                px = float(tick_data.get("price", 0) or 0)
                if not code or px <= 0:
                    return
                self.live_ticks[code] = {"price": px, "ts": time.time()}
                v_ref = self._v_ref_cache.get(code, 5_000_000.0)
                now_t = datetime.now().time()
                is_nxt_sess = (dtime(8, 0, 0) <= now_t < dtime(8, 50, 0)) or (dtime(15, 40, 0) <= now_t < dtime(20, 0, 0))
                is_nxt_code = self.get_venue(code) == "NXT" and is_nxt_sess
                self.strength_engine.on_tick(tick_data, v_ref_1m=v_ref, is_nxt=is_nxt_code)
            except Exception:
                pass

        def _on_ob(ob_data: dict):
            try:
                code = normalize_code(ob_data.get("code", ""))
                if code:
                    self.live_orderbooks[code] = {
                        "ask1": float(ob_data.get("ask1", 0) or 0),
                        "bid1": float(ob_data.get("bid1", 0) or 0),
                        "ts": time.time(),
                    }
            except Exception:
                pass

        self.ws_client = KiwoomWebSocketClient(
            target_condition_name="",
            on_insert=lambda *a: None,
            on_delete=lambda *a: None,
            on_real_tick=_on_tick,
            on_orderbook=_on_ob,
        )

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.ws_client.run())
            except Exception as e:
                logger.error(f"웹소켓 스레드 예외: {e}")

        self.ws_thread = threading.Thread(target=_runner, daemon=True, name="Swing60mWS")
        self.ws_thread.start()

    def get_venue(self, code: str) -> str:
        """종목의 시장 구분('KRX' vs 'NXT') 판별"""
        cc = normalize_code(code)
        if cc in self.krx_map:
            return "KRX"
        if cc in self.nxt_map:
            return "NXT"
        overrides = self.state.get("venue_overrides") or {}
        if cc in overrides:
            return str(overrides[cc])

        # 미등록 계좌 보유 종목이면 1회 NXT 호가 유무 조회
        try:
            rc = getattr(self.api, "real_client", None)
            if rc and hasattr(rc, "get_nxt_hoga"):
                nxt = rc.get_nxt_hoga(cc)
                venue = "NXT" if nxt and (nxt.get("best_ask", 0) > 0 or nxt.get("best_bid", 0) > 0) else "KRX"
                overrides[cc] = venue
                self.state["venue_overrides"] = overrides
                self._save_state()
                return venue
        except Exception:
            pass
        return "KRX"

    def _get_watched_universe(self, holdings: Dict[str, dict]) -> Dict[str, dict]:
        """계좌 보유 마커 종목 + 설정 9종목 통합 감시 풀 구성"""
        universe: Dict[str, dict] = {}
        for code, name in self.nxt_map.items():
            universe[code] = {"code": code, "name": name, "venue": "NXT", "held_qty": 0, "current_price": 0.0}
        for code, name in self.krx_map.items():
            universe[code] = {"code": code, "name": name, "venue": "KRX", "held_qty": 0, "current_price": 0.0}

        for raw_c, h in (holdings or {}).items():
            cc = normalize_code(raw_c)
            qty = int(h.get("qty", 0) or 0)
            if qty <= 0:
                continue
            venue = self.get_venue(cc)
            if cc in universe:
                universe[cc]["held_qty"] = qty
                universe[cc]["current_price"] = float(h.get("current_price", 0) or 0)
                if h.get("name"):
                    universe[cc]["name"] = str(h["name"])
            else:
                universe[cc] = {
                    "code": cc,
                    "name": str(h.get("name") or cc),
                    "venue": venue,
                    "held_qty": qty,
                    "current_price": float(h.get("current_price", 0) or 0),
                }
        return universe

    def _sync_ws_stream(self, universe: Dict[str, dict], now_dt: datetime) -> None:
        if not self.ws_client or not getattr(self.ws_client, "connected", False):
            return
        now_t = now_dt.time()
        is_ext = (dtime(8, 0, 0) <= now_t < dtime(8, 50, 0)) or (dtime(15, 40, 0) <= now_t < dtime(20, 0, 0))
        items = []
        for code, info in universe.items():
            if info["venue"] == "NXT" and is_ext:
                items.append(f"{code}_NX")
            else:
                items.append(code)
        self.ws_client.sync_custom_stream_sync(items)

    def _seed_ka10003_if_needed(self, code: str) -> None:
        if code in self._ka10003_seeded or not hasattr(self.api, "get_recent_ticks_ka10003"):
            return
        try:
            ticks = self.api.get_recent_ticks_ka10003(code, limit=60)
            if ticks:
                v_ref = self._v_ref_cache.get(code, 5_000_000.0)
                self.strength_engine.seed_from_ka10003(code, ticks, v_ref_1m=v_ref, is_nxt=(self.get_venue(code) == "NXT"))
            self._ka10003_seeded.add(code)
        except Exception:
            pass

    def _get_daily_df(self, code: str) -> pd.DataFrame:
        now_ts = time.time()
        cached = self._daily_cache.get(code)
        if cached and (now_ts - cached[0]) < 120.0:
            return cached[1]
        df = None
        rc = getattr(self.api, "real_client", None)
        if rc and hasattr(rc, "get_daily_candles"):
            raw_d = rc.get_daily_candles(code, last_n_days=600)
            if raw_d:
                df = pd.DataFrame(raw_d)
        if df is None or df.empty:
            df = self.api.get_daily_candles(code)
        if df is not None and not df.empty:
            self._daily_cache[code] = (now_ts, df)
        return df if df is not None else pd.DataFrame()

    def _get_60m_df(self, code: str) -> pd.DataFrame:
        now_dt = datetime.now()
        now_ts = time.time()
        cached = self._m60_cache.get(code)
        if cached and cached[1] == now_dt.hour and (now_ts - cached[0]) < 20.0:
            return cached[2]
        df = self.api.get_60m_candles(code)
        if df is not None and not df.empty:
            self._m60_cache[code] = (now_ts, now_dt.hour, df)
        return df if df is not None else pd.DataFrame()

    def _get_live_quote(self, code: str, venue: str, exchange_hint: str, fallback_price: float = 0.0) -> Tuple[float, float, float]:
        """(cur_price, best_ask, best_bid) 조회"""
        lt = self.live_ticks.get(code)
        ws_px = float(lt["price"]) if lt and (time.time() - lt["ts"]) <= 20.0 else 0.0
        ob = self.live_orderbooks.get(code)
        ws_ask = float(ob["ask1"]) if ob and (time.time() - ob["ts"]) <= 20.0 else 0.0
        ws_bid = float(ob["bid1"]) if ob and (time.time() - ob["ts"]) <= 20.0 else 0.0

        if ws_px > 0 and ws_ask > 0 and ws_bid > 0:
            return ws_px, ws_ask, ws_bid

        rc = getattr(self.api, "real_client", None)
        if rc:
            try:
                from kiwoom_rest_api.koreanstock.market_condition import MarketCondition
                mc = MarketCondition(base_url=rc.base_url, token_manager=rc.token_manager)
                q_code = (code + "_NX") if (venue == "NXT" and exchange_hint == "NXT") else code
                q = mc.stock_quote_request_ka10004(stock_code=q_code)
                if (not q or not q.get("sel_fpr_bid")) and q_code != code:
                    q = mc.stock_quote_request_ka10004(stock_code=code)
                if q and q.get("return_code", 0) == 0:
                    ask = abs(float(str(q.get("sel_fpr_bid", "0")).replace("+", "").replace("-", "").strip() or 0))
                    bid = abs(float(str(q.get("buy_fpr_bid", "0")).replace("+", "").replace("-", "").strip() or 0))
                    px = ws_px or ask or bid or fallback_price
                    return px, (ask or px), (bid or px)
            except Exception:
                pass
        px = ws_px or fallback_price
        return px, px, px

    def _place_buy_with_fallback(self, code: str, qty: int, price: int, preferred_ex: str) -> Tuple[Optional[str], str]:
        ord_no = self.api.place_buy_order(code, qty, price=price, order_type="00", exchange_override=preferred_ex)
        if ord_no:
            return ord_no, preferred_ex
        if preferred_ex == "NXT":
            logger.warning(f"🔄 [{code}] NXT 매수 거절 ➔ SOR 자동 폴백 재시도")
            time.sleep(0.35)
            ord_no = self.api.place_buy_order(code, qty, price=price, order_type="00", exchange_override="SOR")
            if ord_no:
                return ord_no, "SOR"
        return None, preferred_ex

    def _place_sell_with_fallback(
        self, code: str, qty: int, cur_price: float, best_bid: float, preferred_ex: str
    ) -> Tuple[Optional[str], str, float]:
        if preferred_ex == "KRX":
            ord_no = self.api.place_sell_order(code, qty, price=cur_price, order_type="03", exchange_override="KRX")
            return ord_no, "KRX", cur_price

        sell_px = get_smart_sell_price(cur_price, best_bid=best_bid)
        ord_no = self.api.place_sell_order(code, qty, price=sell_px, order_type="00", exchange_override=preferred_ex)
        if ord_no:
            return ord_no, preferred_ex, sell_px
        if preferred_ex == "NXT":
            logger.warning(f"🔄 [{code}] NXT 매도 거절 ➔ SOR 자동 폴백 재시도")
            time.sleep(0.35)
            ord_no = self.api.place_sell_order(code, qty, price=sell_px, order_type="00", exchange_override="SOR")
            if ord_no:
                return ord_no, "SOR", sell_px
        return None, preferred_ex, sell_px

    def _reconcile_pending_orders(self, holdings: Dict[str, dict], now_dt: datetime) -> bool:
        """미체결 매수/매도 주문 감시 (매수 20초 초과 취소, 매도 10초 초과 호가 정정). 작업 있으면 True 반환."""
        pb = self.state.get("pending_buy")
        ps = self.state.get("pending_sell")
        if not pb and not ps:
            return False

        unfilled_list = self.api.get_unexecuted_orders() if hasattr(self.api, "get_unexecuted_orders") else []
        unfilled_by_no = {str(u.get("order_no", "")): u for u in unfilled_list}
        time.sleep(0.35)

        if pb:
            code = pb["code"]
            ord_no = str(pb["order_no"])
            u = unfilled_by_no.get(ord_no)
            held_qty = int(holdings.get(code, {}).get("qty", 0) or 0)
            marker_qty = int(pb.get("marker_qty", 0) or 0)
            filled_bot_qty = max(0, held_qty - marker_qty)

            if u is None:
                # 주문 완료(전량 체결 또는 취소)
                if filled_bot_qty > 0:
                    self.state["active_code"] = code
                    self.state["active_name"] = pb.get("name", code)
                    self.state["marker_qty"] = marker_qty
                    self.state["bot_qty"] = filled_bot_qty
                    self.state["entry_price"] = float(holdings.get(code, {}).get("buy_price") or pb.get("price", 0.0))
                    self.state["entry_time"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                    self.state["entry_venue"] = pb.get("venue", "NXT")
                    self.state["was_above_60m_gijun"] = bool(pb.get("init_above_60m_gijun", False))
                    logger.info(f"✅ [풀매수 실체결 확정] [{self.state['active_name']}({code})] 봇진입 {filled_bot_qty}주 (마커 {marker_qty}주 보존)")
                else:
                    logger.info(f"ℹ️ [매수 미체결 종료] [{pb.get('name', code)}({code})] 체결 수량 없음 ➔ IDLE 복귀")
                self.state["pending_buy"] = None
                self._save_state()
                return True

            elapsed = time.time() - float(pb.get("timestamp", 0.0))
            if elapsed >= 20.0:
                u_qty = int(u.get("unfilled_qty", 0) or 0)
                logger.warning(f"⏰ [매수 20초 미체결 취소] [{pb.get('name', code)}({code})] 주문번호:{ord_no} 미체결:{u_qty}주")
                if not self.dry_run and u_qty > 0:
                    self.api.cancel_order(ord_no, code, u_qty, exchange_override=pb.get("exchange"))
                    time.sleep(0.6)
                    holdings = self.api.get_account_holdings() or {}
                    held_qty = int(holdings.get(code, {}).get("qty", 0) or 0)
                    filled_bot_qty = max(0, held_qty - marker_qty)
                if filled_bot_qty > 0:
                    self.state["active_code"] = code
                    self.state["active_name"] = pb.get("name", code)
                    self.state["marker_qty"] = marker_qty
                    self.state["bot_qty"] = filled_bot_qty
                    self.state["entry_price"] = float(holdings.get(code, {}).get("buy_price") or pb.get("price", 0.0))
                    self.state["entry_time"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                    self.state["entry_venue"] = pb.get("venue", "NXT")
                    self.state["was_above_60m_gijun"] = bool(pb.get("init_above_60m_gijun", False))
                    logger.info(f"✅ [부분체결 확정] [{self.state['active_name']}({code})] 봇진입 {filled_bot_qty}주 유지")
                self.state["pending_buy"] = None
                self._save_state()
            return True

        if ps:
            code = ps["code"]
            ord_no = str(ps["order_no"])
            u = unfilled_by_no.get(ord_no)
            held_qty = int(holdings.get(code, {}).get("qty", 0) or 0)
            marker_qty = int(self.state.get("marker_qty", 1) or 1)
            rem_bot_qty = max(0, held_qty - marker_qty)

            if u is None and rem_bot_qty == 0:
                logger.info(f"🎉 [전량 매도 완료 · 슬롯 개방] [{ps.get('name', code)}({code})] 기본 {marker_qty}주 마커 보존 완료!")
                self._clear_active_position()
                return True

            elapsed = time.time() - float(ps.get("timestamp", 0.0))
            if u is not None and elapsed >= 10.0 and not self.dry_run:
                u_qty = int(u.get("unfilled_qty", 0) or 0)
                ex_used = ps.get("exchange", "NXT")
                logger.warning(f"🔄 [매도 10초 미체결 호가 재정정] [{ps.get('name', code)}({code})] {u_qty}주 취소 후 재전송")
                self.api.cancel_order(ord_no, code, u_qty, exchange_override=ex_used)
                time.sleep(0.6)
                venue = self.get_venue(code)
                tradable, _, pref_ex = get_venue_session_state(venue, now_dt, self.allow_krx_aftermarket)
                if tradable:
                    cur_px, _, best_bid = self._get_live_quote(code, venue, pref_ex, ps.get("price", 0.0))
                    new_no, used_ex, new_px = self._place_sell_with_fallback(code, u_qty, cur_px, best_bid, pref_ex)
                    if new_no:
                        self.state["pending_sell"] = {
                            "order_no": str(new_no),
                            "code": code,
                            "name": ps.get("name", code),
                            "qty": u_qty,
                            "price": new_px,
                            "exchange": used_ex,
                            "timestamp": time.time(),
                        }
                        self._save_state()
                else:
                    self.state["pending_sell"] = None
                    self._save_state()
            elif u is None and rem_bot_qty > 0:
                # 주문번호는 종결됐으나 봇 수량이 남아있으면 pending_sell만 해제해 다음 틱에 마저 매도
                self.state["bot_qty"] = rem_bot_qty
                self.state["pending_sell"] = None
                self._save_state()
            return True

        return False

    def _clear_active_position(self) -> None:
        self.state["active_code"] = None
        self.state["active_name"] = ""
        self.state["marker_qty"] = 0
        self.state["bot_qty"] = 0
        self.state["entry_price"] = 0.0
        self.state["entry_time"] = ""
        self.state["entry_venue"] = ""
        self.state["was_above_60m_gijun"] = False
        self.state["pending_buy"] = None
        self.state["pending_sell"] = None
        self._save_state()

    def run_cycle(self, now_dt: Optional[datetime] = None) -> None:
        now = now_dt or datetime.now()
        holdings = self.api.get_account_holdings() or {}
        time.sleep(0.35)

        universe = self._get_watched_universe(holdings)
        self._sync_ws_stream(universe, now)

        if self._reconcile_pending_orders(holdings, now):
            return

        # ── [CASE 1] 현재 1종목 풀매수 포지션 보유 중 ➔ 60분봉 TEMA 5-20 DC / 기준선 이탈 전량 매도 감시 ──
        active_code = self.state.get("active_code")
        if active_code:
            info = universe.get(active_code, {"code": active_code, "name": self.state.get("active_name", active_code), "venue": self.get_venue(active_code), "held_qty": 0, "current_price": 0.0})
            held_qty = int(holdings.get(active_code, {}).get("qty", 0) or 0)
            marker_qty = int(self.state.get("marker_qty", 1) or 1)
            avail_sell = max(0, held_qty - marker_qty)
            bot_qty = min(int(self.state.get("bot_qty", avail_sell) or avail_sell), avail_sell)

            if bot_qty <= 0 and not self.dry_run:
                logger.info(f"ℹ️ [포지션 자동 정리] [{info['name']}({active_code})] 계좌 보유({held_qty}주) <= 마커({marker_qty}주) ➔ 슬롯 개방")
                self._clear_active_position()
                return

            tradable, sess_label, pref_ex = get_venue_session_state(info["venue"], now, self.allow_krx_aftermarket)
            cur_px, _, best_bid = self._get_live_quote(active_code, info["venue"], pref_ex or info["venue"], info.get("current_price", 0.0))
            df_60m = self._get_60m_df(active_code)
            sig60 = evaluate_60m_signals(df_60m, current_price=cur_px, now_dt=now)

            if not sig60["valid"]:
                logger.warning(f"⚠️ [{info['name']}({active_code})] 60분봉 데이터 부족으로 청산 판단 보류")
                return

            should_sell, reason, updated_above = evaluate_60m_exit(
                sig60,
                live_price=sig60["price"],
                was_above_60m_gijun=bool(self.state.get("was_above_60m_gijun", False)),
                gijun_buffer_pct=self.gijun_buffer_pct,
            )
            if updated_above != bool(self.state.get("was_above_60m_gijun", False)):
                self.state["was_above_60m_gijun"] = updated_above
                self._save_state()

            entry_px = float(self.state.get("entry_price", 0.0) or 0.0)
            pnl_pct = ((sig60["price"] - entry_px) / entry_px * 100.0) if entry_px > 0 else 0.0
            logger.info(
                f"🔒 [보유 감시] [{info['name']}({active_code})][{info['venue']}·{sess_label}] "
                f"봇수량:{bot_qty}주(마커:{marker_qty}주) | 현재:{sig60['price']:,.0f}({pnl_pct:+.2f}%) | "
                f"60m T5:{sig60['tema5']:,.0f} vs T20:{sig60['tema20']:,.0f}({sig60['gap_pct']:+.2f}%) | "
                f"60m기준선:{sig60['gijun_60m']:,.0f}(안착:{updated_above})"
            )

            if should_sell:
                if not tradable:
                    logger.info(f"⏳ [매도 신호 대기] [{info['name']}({active_code})] {reason} ➔ 현재 {sess_label} (개시 즉시 전량 매도)")
                    return
                if self.dry_run:
                    logger.info(f"💻 [DRY-RUN 전량 매도] [{info['name']}({active_code})] {bot_qty}주(마커 {marker_qty}주 보존) | 사유: {reason}")
                    self._clear_active_position()
                    return

                ord_no, used_ex, exec_px = self._place_sell_with_fallback(
                    active_code, bot_qty, sig60["price"], best_bid, pref_ex
                )
                if ord_no:
                    logger.warning(f"🚨 [전량 매도 발송] [{info['name']}({active_code})] {bot_qty}주 @ {exec_px:,.0f}원 ({used_ex}) | 사유: {reason}")
                    self.state["pending_sell"] = {
                        "order_no": str(ord_no),
                        "code": active_code,
                        "name": info["name"],
                        "qty": bot_qty,
                        "price": exec_px,
                        "exchange": used_ex,
                        "timestamp": time.time(),
                    }
                    self._save_state()
            return

        # ── [CASE 2] IDLE 슬롯 비어 있음 ➔ 9종목 전수 평가 후 60m TEMA 5-20 GC 1위 종목 풀매수 ──
        logger.info("===============================================================================")
        logger.info(f" 🔎 [60분봉 스윙 스캔] 감시 {len(universe)}종목 ({now.strftime('%H:%M:%S')}) — 60분봉 TEMA 5-20 GC 1등 탐색")
        logger.info("===============================================================================")

        gc_candidates = []
        for code, info in universe.items():
            name = info["name"]
            venue = info["venue"]
            tradable, sess_label, pref_ex = get_venue_session_state(venue, now, self.allow_krx_aftermarket)

            self._seed_ka10003_if_needed(code)
            df_daily = self._get_daily_df(code)
            df_60m = self._get_60m_df(code)

            cur_px, best_ask, _ = self._get_live_quote(code, venue, pref_ex or venue, info.get("current_price", 0.0))
            if cur_px <= 0 and not df_60m.empty:
                cur_px = float(df_60m["close"].iloc[-1])

            d_metrics = calculate_daily_seryek_gijun_lines(df_daily, current_price=cur_px)
            sig60 = evaluate_60m_signals(df_60m, current_price=cur_px, now_dt=now)
            if not sig60["valid"]:
                continue

            if d_metrics["prev5_tv_eok"] > 0:
                self._v_ref_cache[code] = (d_metrics["prev5_tv_eok"] * 1e8) / 390.0

            prev_close = float(df_daily["close"].iloc[-2]) if len(df_daily) >= 2 else float(d_metrics["close"] or 0.0)
            day_ret_pct = ((sig60["price"] - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
            rvp_raw = self.strength_engine.evaluate_entry_strength(
                code,
                df_1m=None,
                v_ref_1m=self._v_ref_cache.get(code, 5_000_000.0),
                is_nxt=(venue == "NXT" and pref_ex == "NXT"),
                now_ts=time.time(),
            )
            rvp_info = {
                "rvp_valid": (rvp_raw.get("source") == "LIVE_WS"),
                "rvp60": float(rvp_raw.get("rvp_60s", 100.0) or 100.0),
                "rvp180": float(rvp_raw.get("rvp_180s", 100.0) or 100.0),
            }
            scores = score_60m_entry_candidate(day_ret_pct, d_metrics, sig60, rvp_info=rvp_info)

            gc_tag = (
                f"🔥60m GC({sig60['gc_bars_ago']}봉·+{sig60['price_vs_gc_pct']:.2f}%)"
                if sig60["is_entry_gc_ready"]
                else (f"GC지남({sig60['gc_bars_ago']}봉)" if sig60["is_gc_bull"] else f"60m DC({sig60['gap_pct']:+.2f}%)")
            )
            rvp_str = f"RVP:{rvp_info.get('rvp60', 0):.0f}%" if rvp_info.get("rvp_valid") else "RVP:대기"
            logger.info(
                f"  · [{name}({code})][{venue}{'(거래가능)' if tradable else '(대기:'+sess_label+')'}] "
                f"총점:{scores['total']:5.1f} [상승{scores['score_ret']:.0f}·대금{scores['score_tv']:.0f}·일봉{scores['score_daily']:.0f}·수급{scores['score_flow']:.0f}] | "
                f"현재:{sig60['price']:,.0f}({day_ret_pct:+.2f}%) | 거래비율:{d_metrics['tv_ratio_pct']:.0f}%({d_metrics['today_tv_eok']:.0f}억) | "
                f"기준:{d_metrics['gijun']:,.0f}({d_metrics['dist_gijun_pct']:+.1f}%) 세력:{d_metrics['seryek']:,.0f}({d_metrics['dist_seryek_pct']:+.1f}%) | "
                f"{gc_tag} | {rvp_str}"
            )

            # 매수 자격: 현재 세션 거래 가능 + 60m TEMA 5-20 신규 GC + 명백한 매도 투매(RVP < 70%) 아님
            if not tradable or not sig60["is_entry_gc_ready"]:
                continue
            if rvp_info.get("rvp_valid") and max(rvp_info.get("rvp60", 0), rvp_info.get("rvp180", 0)) < 70.0:
                logger.info(f"    ⏭️ [{name}] 60m GC 발생했으나 체결강도 약세(RVP < 70%)로 관망")
                continue

            gc_candidates.append({
                "code": code,
                "name": name,
                "venue": venue,
                "exchange": pref_ex,
                "sess_label": sess_label,
                "held_qty": int(info.get("held_qty", 0) or 0),
                "price": sig60["price"],
                "best_ask": best_ask or sig60["price"],
                "sig60": sig60,
                "scores": scores,
                "day_ret_pct": day_ret_pct,
            })

        if not gc_candidates:
            return

        gc_candidates.sort(key=lambda x: x["scores"]["total"], reverse=True)
        winner = gc_candidates[0]
        w_code = winner["code"]
        w_name = winner["name"]
        buy_price = get_smart_buy_price(winner["best_ask"] or winner["price"])
        if buy_price <= 0:
            return

        cash_100 = self.api.get_orderable_cash_100pct() if hasattr(self.api, "get_orderable_cash_100pct") else 0.0
        if cash_100 <= 0 and hasattr(self.api, "get_cash_balance"):
            # Fallback 시 계좌 보유 평가금액 제외 안전 예산 추정
            est_tot = float(self.api.get_cash_balance() or 0.0)
            held_val = sum(float(v.get("qty", 0)) * float(v.get("current_price", 0)) for v in (holdings or {}).values())
            cash_100 = max(0.0, est_tot - held_val)

        order_budget = cash_100 * (self.max_budget_pct / 100.0)
        buy_qty = int(order_budget // buy_price)
        if buy_qty <= 0:
            logger.warning(f"⚠️ [{w_name}({w_code})] 1등 선정되었으나 현금 100% 주문가능액({cash_100:,.0f}원) < 매수가({buy_price:,}원)")
            return

        marker_qty = int(winner["held_qty"])
        gijun_60m = float(winner["sig60"].get("gijun_60m", 0.0) or 0.0)
        init_above_gijun = bool(gijun_60m > 0 and buy_price >= gijun_60m)

        logger.info(
            f"👑 [1등 풀매수 선정] [{w_name}({w_code})] 총점:{winner['scores']['total']:.1f}점 | "
            f"{winner['sess_label']} ({winner['exchange']}) | 수량:{buy_qty}주 @ {buy_price:,}원 (예산:{order_budget:,.0f}원, 기존마커:{marker_qty}주)"
        )

        if self.dry_run:
            logger.info(f"💻 [DRY-RUN 풀매수 가상체결] [{w_name}({w_code})] {buy_qty}주 @ {buy_price:,}원")
            return

        ord_no, used_ex = self._place_buy_with_fallback(w_code, buy_qty, buy_price, winner["exchange"])
        if not ord_no:
            logger.error(f"❌ [풀매수 주문 실패] [{w_name}({w_code})]")
            return

        self.state["pending_buy"] = {
            "order_no": str(ord_no),
            "code": w_code,
            "name": w_name,
            "venue": winner["venue"],
            "exchange": used_ex,
            "qty": buy_qty,
            "marker_qty": marker_qty,
            "price": buy_price,
            "init_above_60m_gijun": init_above_gijun,
            "timestamp": time.time(),
        }
        self._save_state()

    def start_loop(self, interval_sec: int = 10) -> None:
        logger.info(
            f"🚀 [60분봉 TEMA 5-20 전용 스윙 봇 가동] 주기: {interval_sec}초 | "
            f"NXT(08:00~20:00) / KRX(09:00~15:30 + 애프터 SOR) | 1종목 현금 {self.max_budget_pct:.1f}% 풀매수"
        )
        try:
            while True:
                t0 = time.time()
                try:
                    self.run_cycle()
                except Exception as e:
                    logger.error(f"감시 루프 예외: {e}", exc_info=True)
                sleep_sec = max(2.0, float(interval_sec) - (time.time() - t0))
                time.sleep(sleep_sec)
        except KeyboardInterrupt:
            logger.info("🛑 사용자 요청으로 60분봉 스윙 봇을 종료합니다.")


if __name__ == "__main__":
    import argparse

    configure_swing_logger()
    parser = argparse.ArgumentParser(description="9종목 마커 기반 60분봉 TEMA 5-20 1종목 풀매수 전용 봇")
    parser.add_argument("--once", action="store_true", help="1회 스캔/평가 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="모의 검증 모드(주문 미전송)")
    parser.add_argument("--interval", type=int, default=10, help="감시 주기(초, 기본 10초)")
    parser.add_argument("--max-budget-pct", type=float, default=99.2, help="주문가능현금 대비 투자 비중(%%, 기본 99.2)")
    parser.add_argument("--no-ws", action="store_true", help="실시간 웹소켓 비활성화")
    parser.add_argument("--no-aftermarket-krx", action="store_true", help="15:40~20:00 KRX 종목 SOR 매매 비활성화")
    args = parser.parse_args()

    _lock_fp = None
    if not args.once:
        try:
            lock_path = os.path.join(LOG_DIR, "swing_60m_bot.lock")
            _lock_fp = open(lock_path, "a+", encoding="utf-8")
            if sys.platform.startswith("win"):
                import msvcrt
                _lock_fp.seek(0)
                msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(_lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_fp.seek(0)
            _lock_fp.truncate()
            _lock_fp.write(f"pid={os.getpid()} started={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            _lock_fp.flush()
        except Exception as lock_err:
            logger.error(f"⛔ 이미 다른 swing_60m_bot 인스턴스가 실행 중입니다: {lock_err}")
            sys.exit(1)

    bot = Swing60mBot(
        dry_run=args.dry_run,
        enable_ws=(not args.no_ws),
        max_budget_pct=args.max_budget_pct,
        allow_krx_aftermarket=(not args.no_aftermarket_krx),
    )
    if args.once:
        bot.run_cycle()
    else:
        bot.start_loop(interval_sec=args.interval)
