"""
trading_bot_holdings_only.py - 키움 실시간 조건검색 전용 1종목 집중 매매 봇

[안전장치 및 운영 규칙]
1. 장운영 시간 안전장치: NXT 프리마켓(08:00~08:50) + KRX 정규장(09:00~15:30) + NXT 애프터마켓(15:40~20:00) 3대 세션 자동 연동 (세션 외 및 주말 주문 원천 차단)
2. 모의/실전 안전 모드: DRY_RUN 플래그로 실제 주문 없이 신호 검증 가능
3. 매수 대상: 키움 실시간 조건검색식 수신 종목만 신규 매수 (계좌 기존 보유/1주 종목은 매수·매도 대상에서 100% 배제)
4. 1차 매수 (100%): 일봉 3-5 골든 M/3 기준선 돌파·첫 5분봉 앵커 또는 120틱 관문선 타점 진입
5. 매도 원칙: 120틱 테마 60-120 데드크로스(정배열 안착 확인 후) 또는 -2.5% 비상 하드 방어선 이탈 시 전량 매도
6. 매도 후 원칙: 20초 쿨다운 후 현금화(IDLE 복귀) 및 1종목 슬롯 개방
"""

import os
import sys
import time
import copy
import asyncio
import threading
import logging
import importlib.util
from datetime import datetime, time as dtime
from typing import Tuple, Dict, Any, Optional
import pandas as pd
import numpy as np

# 경로 설정 (어느 드라이브/폴더나 다른 PC로 옮겨도 100% 자동 인식되도록 상대 경로화)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
PYTHON_WORKSPLACE = PROJECT_ROOT
MOVING_AVERAGE_TRAID = os.path.join(PROJECT_ROOT, "MovingAveragelineTraid", "execution")
REAL_TRADING_PATH = os.path.join(PROJECT_ROOT, "real trading")

for p in [PROJECT_ROOT, CURRENT_DIR, MOVING_AVERAGE_TRAID, REAL_TRADING_PATH]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

# 1) 전략 설정(DEFAULT_CONFIG)을 execution/config.py에서 명시적으로 로드 (이름 충돌 원천 방지)
_exec_cfg_path = os.path.join(CURRENT_DIR, "config.py")
_exec_spec = importlib.util.spec_from_file_location("execution_strategy_config", _exec_cfg_path)
_exec_cfg_mod = importlib.util.module_from_spec(_exec_spec)
_exec_spec.loader.exec_module(_exec_cfg_mod)
DEFAULT_CONFIG = _exec_cfg_mod.DEFAULT_CONFIG

try:
    from execution.indicators import (
        calculate_all_60m_indicators,
        calculate_daily_tema_deadcross,
        calculate_day3_m_line,
        calculate_daily_ma3_5_gc_m3_line,
        check_daily_ma3_5_eligible,
        calculate_pred_volume_ratio,
        calculate_120t_tema_indicators,
    )
    from execution.strategy import ThemeGate60mStrategy, TradeOrder, StrategyState, PositionTracker
    from execution.overnight_market_radar import get_overnight_market_radar, get_stock_theme_alignment_score
except ImportError:
    from indicators import (
        calculate_all_60m_indicators,
        calculate_daily_tema_deadcross,
        calculate_day3_m_line,
        calculate_daily_ma3_5_gc_m3_line,
        check_daily_ma3_5_eligible,
        calculate_pred_volume_ratio,
        calculate_120t_tema_indicators,
    )
    from strategy import ThemeGate60mStrategy, TradeOrder, StrategyState, PositionTracker
    from overnight_market_radar import get_overnight_market_radar, get_stock_theme_alignment_score

# 2) 실전 API(KiwoomRealClient)가 참조하는 real trading/config.py를 sys.modules['config']에 확정 바인딩
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
    logging.error(f"❌ 실전 API 어댑터(RealAPIAdapter) 로드 실패: {e}", exc_info=True)
    HAS_REAL_API = False

try:
    from websocket_client import KiwoomWebSocketClient
    HAS_WS_CLIENT = True
except Exception as e:
    logging.warning(f"⚠️ 실시간 조건검색 웹소켓(KiwoomWebSocketClient) 로드 실패: {e}")
    HAS_WS_CLIENT = False

# 로깅 (콘솔 + 일별 로그 파일 자동 영구 기록 — 선행 모듈의 basicConfig 유무와 무관하게 파일 핸들러 강제 바인딩)
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
DAILY_LOG_PATH = os.path.join(LOG_DIR, f"trading_bot_{datetime.now().strftime('%Y%m%d')}.log")

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
_log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')

if not any(isinstance(h, logging.FileHandler) and os.path.abspath(getattr(h, 'baseFilename', '')) == os.path.abspath(DAILY_LOG_PATH) for h in _root_logger.handlers):
    _fh = logging.FileHandler(DAILY_LOG_PATH, encoding="utf-8")
    _fh.setFormatter(_log_formatter)
    _root_logger.addHandler(_fh)

if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in _root_logger.handlers):
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_log_formatter)
    _root_logger.addHandler(_sh)

logger = logging.getLogger("ThemeGateHoldingsBot")

def get_market_session() -> tuple[bool, str, str]:
    """
    현재 시장 운영 세션 반환: (is_active, session_name, exchange_hint)
    
    세션 정의:
    1. NXT 프리마켓:  평일 08:00 ~ 08:50 (거래소: NXT, 지정가 전용)
    2. KRX 정규장:    평일 09:00 ~ 15:30 (거래소: KRX, 시장가/지정가)
    3. NXT 애프터마켓: 평일 15:40 ~ 20:00 (거래소: NXT, 지정가 전용)
    
    비운영/준비 시간:
    - 08:50 ~ 09:00: 정규장 개장 준비시간 (주문 차단)
    - 15:30 ~ 15:40: 애프터마켓 전환 준비시간 (주문 차단)
    - 20:00 ~ 익일 08:00 및 주말: 야간/휴장 (주문 차단)
    """
    now = datetime.now()
    # 주말(토요일=5, 일요일=6)
    if now.weekday() >= 5:
        return False, "주말(휴장)", "NONE"
        
    cur_t = now.time()
    
    # 1. NXT 프리마켓 (08:00 ~ 08:50)
    if dtime(8, 0, 0) <= cur_t < dtime(8, 50, 0):
        return True, "NXT 프리마켓(08:00~08:50)", "NXT"
        
    # 2. KRX 정규장 (09:00 ~ 15:30)
    if dtime(9, 0, 0) <= cur_t <= dtime(15, 30, 0):
        return True, "KRX 정규장(09:00~15:30)", "KRX"
        
    # 3. NXT 애프터마켓 (15:40 ~ 20:00)
    if dtime(15, 40, 0) <= cur_t < dtime(20, 0, 0):
        return True, "NXT 애프터마켓(15:40~20:00)", "NXT"
        
    # 준비 및 차단 시간대
    if dtime(8, 50, 0) <= cur_t < dtime(9, 0, 0):
        return False, "정규장 개장 준비시간(08:50~09:00)", "NONE"
    elif dtime(15, 30, 0) < cur_t < dtime(15, 40, 0):
        return False, "애프터마켓 전환 준비시간(15:30~15:40)", "NONE"
    else:
        return False, "야간/장마감(주문차단)", "NONE"

def is_market_open() -> bool:
    """시장 운영 여부 (NXT 프리/애프터 및 KRX 정규장 포함)"""
    is_active, _, _ = get_market_session()
    return is_active

def get_session_volume_target() -> tuple[float, str]:
    """
    ⚡ [세션별 차등 거래량 기준]:
    - NXT 프리마켓 (08:00 ~ 08:50): 전일 대비 1.5%
    - KRX 정규장   (09:00 ~ 15:30): 전일 대비 3.0%
    - NXT 애프터마켓 (15:40 ~ 20:00): 전일 대비 1.0%
    """
    cur_t = datetime.now().time()
    if dtime(8, 0, 0) <= cur_t < dtime(8, 50, 0):
        return 1.5, "NXT 프리마켓(1.5%)"
    elif dtime(15, 40, 0) <= cur_t < dtime(20, 0, 0):
        return 1.0, "NXT 애프터마켓(1.0%)"
    else:
        return 3.0, "KRX 정규장(3.0%)"

def get_krx_tick_size(price: float) -> int:
    """한국거래소 호가 단위 반환"""
    if price is None or np.isnan(price) or price <= 0:
        return 1
    if price < 2000: return 1
    elif price < 5000: return 5
    elif price < 20000: return 10
    elif price < 50000: return 50
    elif price < 200000: return 100
    elif price < 500000: return 500
    else: return 1000

def align_to_tick(price: float) -> int:
    """한국거래소 및 대체거래소 호가 단위 정렬"""
    if price is None or np.isnan(price) or price <= 0:
        return 0
    tick = get_krx_tick_size(price)
    return int((int(price) // tick) * tick)

def get_smart_buy_price(price: float) -> int:
    """
    ⚡ [실전 호가 역선택 방지 스마트 지정가 산출 (+1~2호가 공격적 지정가, 상한 슬리피지 +0.3% 제한)]
    진짜 급등하는 대장주가 돌파 순간 1~2호가 위로 튀어 미체결('Ghost Lock')되는 현상을 원천 방지하고,
    힘없이 밀리는 가짜 돌파만 체결되는 역선택(Adverse Selection)을 차단합니다.
    """
    base_p = align_to_tick(price)
    if base_p <= 0:
        return 0
    tick = get_krx_tick_size(base_p)
    if (tick * 2) / base_p <= 0.003:
        return base_p + (tick * 2)
    elif tick / base_p <= 0.0035:
        return base_p + tick
    return base_p


class BigOrderStreakTracker:
    """
    👑 [대표님 비기]: 실시간 순간체결대금 3,000만 원 이상 매수 연속 체결(세력 입성) 추적기
    - 단일 체결대금 = 체결가 * 순간체결량 >= 30,000,000원 (3천만 원 이상)
    - 매도호가를 위로 긁어먹는 적극적 매수 체결(빨간 체결) 기준
    - 직전 3천만+ 체결 이후 5.0초 이내에 연달아 터지면 streak + 1 연속 카운팅!
    - 5초 초과 시 streak 0 리셋
    """
    def __init__(self, threshold_won: float = 30_000_000.0, streak_window_sec: float = 5.0):
        self.threshold_won = threshold_won
        self.streak_window_sec = streak_window_sec
        self.streaks: dict[str, dict] = {}
        self._lock = threading.Lock()

    def on_tick(self, code: str, current_price: float, tick_qty: int, is_buy_tick: bool = True, chegyul_gangdo: float = 0.0) -> int:
        amt = current_price * tick_qty
        now_ts = time.time()
        
        with self._lock:
            info = self.streaks.setdefault(code, {
                'streak': 0,
                'last_ts': 0.0,
                'last_amt': 0.0,
                'gangdo': 0.0,
                'total_big_amt': 0.0
            })
            
            # 3,000만 원 이상 매수 체결 발생!
            if amt >= self.threshold_won and is_buy_tick:
                if now_ts - info['last_ts'] <= self.streak_window_sec:
                    info['streak'] += 1
                else:
                    info['streak'] = 1  # 신규 연속 체결 시작
                    
                info['last_ts'] = now_ts
                info['last_amt'] = amt
                info['gangdo'] = chegyul_gangdo
                info['total_big_amt'] += amt
                return info['streak']
            else:
                if now_ts - info['last_ts'] > self.streak_window_sec:
                    info['streak'] = 0
                return info['streak']

    def get_streak(self, code: str) -> int:
        now_ts = time.time()
        with self._lock:
            info = self.streaks.get(code)
            if not info:
                return 0
            if now_ts - info.get('last_ts', 0.0) > self.streak_window_sec:
                info['streak'] = 0
            return info['streak']

    def get_info(self, code: str) -> dict:
        now_ts = time.time()
        with self._lock:
            info = self.streaks.get(code, {})
            streak = info.get('streak', 0)
            if now_ts - info.get('last_ts', 0.0) > self.streak_window_sec:
                streak = 0
            return {
                'streak': streak,
                'last_amt': info.get('last_amt', 0.0),
                'gangdo': info.get('gangdo', 0.0),
                'total_big_amt': info.get('total_big_amt', 0.0)
            }


class SafeHoldingsThemeGateBot:
    BOT_ENTRY_MODES = (
        "STAGE1_5M_ANCHOR",
        "STAGE1_M3_BREAKOUT",
        "STAGE2_120T_GATE",
        "120T_SMA",
        "120T_TEMA",
        "120T_ROTATION",
        "10M_TEMA",
        "3M_TEMA",
    )

    def __init__(
        self,
        is_real: bool = True,
        dry_run: bool = False,
        condition_name: str = "Traiding,traiding,Traiding1,trading1",
        enable_ws: bool = True,
        min_overlap: int = 2,
        fixed_qty: int = 2,
        min_cond_stay_sec: float = 30.0
    ):
        """
        is_real: 키움 실전 API 연동 여부
        dry_run: True이면 신호는 계산하되 실제 주문 전송만 건너뜀 (안전 모의 테스트용)
        condition_name: 키움 실시간 조건검색식 이름 (기본값: 'Traiding,traiding,Traiding1,trading1')
        enable_ws: 키움 실시간 조건검색 웹소켓 수신 데몬 활성화 여부
        min_overlap: 신규 매수 허용 최소 조건식 중복 포착 수 (기본 2 = 중복 4·3·2순 Top10 엄선)
        fixed_qty: 고정 매수 수량 (기본값: 2주, 계좌 예수금 조회 TR 생략)
        min_cond_stay_sec: 조건식 최소 연속 체류 인증 시간(초, 기본 30초 — 1~5초 휩소 들락날락 차단)
        """
        self.dry_run = dry_run
        self.condition_name = condition_name
        self.fixed_qty = fixed_qty
        self.min_cond_stay_sec = max(0.0, float(min_cond_stay_sec))
        # 조건식 중복 포착 집계: 4개 조건식 체류 인증 중복 4·3·2 순으로 나열하여 09:30 기준 Top10 엄선
        self.condition_total = max(1, len({n.strip() for n in str(condition_name).split(',') if n.strip()}))
        self.min_overlap = max(1, min(int(min_overlap), self.condition_total))
        self.enable_ws = enable_ws and HAS_WS_CLIENT
        if is_real and not HAS_REAL_API:
            logger.error("❌ [치명적 오류] 실전 계좌 전용 봇(holdings_bot.bat)에서 키움 실전 API(RealAPIAdapter) 로드에 실패했습니다.")
            logger.error("   가상/시뮬레이션 모드로 임의 전환하지 않고 안전 종료합니다. (.env 및 키움 실전 API 설정을 확인하세요)")
            sys.exit(1)

        self.is_real = is_real and HAS_REAL_API

        logger.info("==================================================")
        if self.dry_run:
            logger.info(" 🛡️ [실전 계좌 연동 + 모의 안전 모드(DRY-RUN)] 실계좌 잔고 + 09:30 조건검색 Top10(중복 4·3·2순) 감시 (주문 미전송)")
        elif self.is_real:
            qty_tag = f"고정 {self.fixed_qty}주 실전 매매 (예수금 TR 생략)" if self.fixed_qty > 0 else "예수금 100% 매매"
            logger.info(
                f" 🚀 [키움 실전 계좌 거래 모드] {qty_tag} + 09:30 조건검색({self.condition_name}) "
                f"중복 4·3·2순 Top10 엄선 + 120틱 단순 5-40 GC(1차) · 5-60 GC(2차) 매매"
            )
        else:
            logger.info(" 🧪 [시뮬레이션 모드] 가상 데이터 모드")
        logger.info("==================================================")
        
        if self.is_real:
            self.api = RealAPIAdapter()
        else:
            self.api = None
            
        self.strategies: dict[str, ThemeGate60mStrategy] = {}
        self.active_holdings: dict = {}
        self.condition_picks: dict[str, dict] = {}
        self.condition_lock = threading.Lock()
        self.condition_wakeup_event = threading.Event()
        self.condition_init_event = threading.Event()
        self.top10_cutoff_time: dtime = dtime(9, 30, 0)
        self.top10_locked: bool = False
        self.locked_top10_picks: list[dict] = []
        self.locked_top10_codes: set[str] = set()
        self._bot_start_ts: float = time.time()
        self.ws_client = None
        self.ws_thread: Optional[threading.Thread] = None
        self.pending_buy_orders: dict[str, dict] = {}
        self._last_account_refresh_time: float = 0.0  # 🏛️ 키움 계좌 TR(초당 3회 제한) 방어용 캐시 타임스탬프
        self._cached_real_holdings: dict = {}
        self._cached_cash: float = 0.0
        self._m60_cache: dict[str, tuple[float, int, pd.DataFrame]] = {}   # 60분봉 단기 캐시 (20초 TTL / 시간 경계 갱신)
        self._daily_cache: dict[str, tuple[float, pd.DataFrame]] = {}       # 일봉 단기 캐시 (60초 TTL)
        self._last_idle_scan_ts: float = 0.0                                 # 보유 중 비활성 후보 순환 평가 타임스탬프
        self.sold_cooldowns: dict[str, float] = {}  # 매도 종목 단기 쿨다운 (code -> cooldown_until_ts, 영구 차단 없이 관심종목 지속 유지)
        self.completed_trades_today: int = 0          # 당일 매도 완료(순환매매) 횟수 (0=1차 일봉 3-5 진입, >=1=교체 상승률<=20% 진입)
        self.current_trading_date = datetime.now().date()
        self.m5_anchors: dict[str, dict] = {}        # 🎯 첫 5분봉 앵커 캐시 (open_5m, low_5m, high_5m, locked)
        self._live_tick_prices: dict[str, dict] = {} # ⚡ 웹소켓 0B 실시간 체결 현재가 캐시 (price, ts)
        # 👑 [대표님 비기]: 실시간 순간체결대금 3,000만 원 이상 매수 연속 체결(세력 입성) 추적기 (임계치: 3,000만 원, 윈도우: 5초)
        self.big_order_tracker = BigOrderStreakTracker(threshold_won=30_000_000.0, streak_window_sec=5.0)
        self.dryrun_stats: dict[str, Any] = {
            'initial_seed': 0.0,
            'virtual_cash': 0.0,
            'realized_net_pnl': 0.0,
            'wins': 0,
            'losses': 0,
            'trades': 0,
            'log_path': os.path.join(CURRENT_DIR, "dryrun_trade_history.log")
        }
        self.stock_name_cache: dict[str, str] = {
            '035900': 'JYP Ent.',
            '052260': '현대바이오랜드',
            '138360': '앤로보틱스',
            '263750': '펄어비스',
            '263860': '지니언스',
            '281820': '케이씨텍',
            '386380': '스카이랩스',
            '393210': '토마토시스템',
            '411080': '샌즈랩',
            '425040': '티이엠씨',
            '476830': '알지노믹스',
        }

        if self.is_real and self.enable_ws:
            self._start_condition_ws_daemon()

    @staticmethod
    def _normalize_stock_code(code: str) -> str:
        """종목코드 정규화 (_AL/_NX 및 선행 'A' 1글자만 제거하여 6자리 영문/숫자 코드 보존)"""
        clean_code = str(code or "").replace("_AL", "").replace("_NX", "").strip()
        if clean_code.startswith("A") and len(clean_code) == 7:
            clean_code = clean_code[1:]
        if clean_code.isdigit() and len(clean_code) < 6:
            clean_code = clean_code.zfill(6)
        return clean_code

    def _compute_cond_pick_metrics(self, pick: dict, now_ts: Optional[float] = None) -> dict:
        """
        종목의 조건식별 체류시간·인증중복(confirmed_overlap)·현재유지(active_overlap)·들락날락(churn_count) 동적 산출
        - 연속 min_cond_stay_sec(기본 30초) 이상 또는 누적 1.5배(45초) 이상 유지된 조건만 인증(confirmed)
        - 인증된 조건은 이후 주가 눌림(하락) 중 조건식을 일시 이탈('D')하더라도 confirmed_overlap 유지
        """
        cur_ts = float(now_ts if now_ts is not None else time.time())
        min_stay = max(0.0, float(getattr(self, 'min_cond_stay_sec', 30.0)))
        cum_stay_req = min_stay * 1.5
        cond_stats = pick.get('cond_stats')

        if not isinstance(cond_stats, dict):
            ov = int(pick.get('overlap', len(pick.get('seen_conds', [])) or 0))
            act = int(pick.get('active_overlap', ov))
            return {
                'confirmed_conds': list(pick.get('confirmed_conds', pick.get('seen_conds', []))),
                'confirmed_overlap': ov,
                'active_overlap': act,
                'seen_overlap': len(pick.get('seen_conds', [])) or ov,
                'total_stay_sec': float(pick.get('total_stay_sec', 0.0) or 0.0),
                'churn_count': int(pick.get('churn_count', 0) or 0),
                'durability_score': float(pick.get('durability_score', 0.0) or 0.0),
            }

        confirmed_conds = []
        active_cnt = 0
        total_stay = 0.0
        total_churn = 0
        for cname, st in cond_stats.items():
            is_act = bool(st.get('is_active', False))
            live_sec = max(0.0, cur_ts - float(st.get('active_since', cur_ts) or cur_ts)) if is_act else 0.0
            accum_sec = float(st.get('accum_stay_sec', 0.0) or 0.0)
            c_total = accum_sec + live_sec
            is_conf = bool(st.get('confirmed', False)) or (live_sec >= min_stay) or (c_total >= cum_stay_req)
            if is_act:
                active_cnt += 1
            if is_conf:
                confirmed_conds.append(cname)
            total_stay += c_total
            total_churn += int(st.get('churn_count', 0) or 0)

        confirmed_conds.sort()
        durability = total_stay - (total_churn * 30.0)
        return {
            'confirmed_conds': confirmed_conds,
            'confirmed_overlap': len(confirmed_conds),
            'active_overlap': active_cnt,
            'seen_overlap': len(cond_stats),
            'total_stay_sec': total_stay,
            'churn_count': total_churn,
            'durability_score': durability,
        }

    def _on_condition_insert(self, code: str, cond_name: str = ""):
        """키움 실시간 조건검색(Traiding, traiding, Traiding1, trading1) 편입 콜백 (최소 체류시간 인증 기반 중복 4·3·2순 Top10)"""
        clean_code = self._normalize_stock_code(code)
        if not clean_code.isalnum() or len(clean_code) != 6 or clean_code == "000000":
            return

        # 09:30 정각 이후에는 이미 확정된 Top 10 외 신규 조건검색 유입 차단
        self._maybe_lock_top10()
        if getattr(self, 'top10_locked', False) and clean_code not in getattr(self, 'locked_top10_codes', set()):
            logger.debug(f"🔒 [09:30 Top10 확정 이후 제외] {clean_code} ({cond_name}) 신규 편입 무시")
            return

        effective_cond = cond_name.strip() if cond_name and cond_name.strip() else "Traiding"
        now_ts = time.time()
        min_stay = max(0.0, float(getattr(self, 'min_cond_stay_sec', 30.0)))

        with self.condition_lock:
            is_new_stock = clean_code not in self.condition_picks
            existing = self.condition_picks.get(clean_code, {})
            if not isinstance(existing, dict):
                existing = {}

            cond_stats = {k: dict(v) for k, v in (existing.get('cond_stats') or {}).items()}
            is_new_cond_for_stock = effective_cond not in cond_stats
            st = cond_stats.get(effective_cond)
            is_reentry_bounce = False

            if st is None:
                st = {
                    'is_active': True,
                    'first_seen': now_ts,
                    'active_since': now_ts,
                    'accum_stay_sec': 0.0,
                    'max_cont_sec': 0.0,
                    'confirmed': (min_stay <= 0.0),
                    'churn_count': 0,
                }
            else:
                if not st.get('is_active', False):
                    # 이탈('D') 후 재편입('I') → 들락날락(churn) 카운트 증가
                    st['churn_count'] = int(st.get('churn_count', 0) or 0) + 1
                    st['is_active'] = True
                    st['active_since'] = now_ts
                    is_reentry_bounce = True
                else:
                    live_sec = max(0.0, now_ts - float(st.get('active_since', now_ts) or now_ts))
                    st['max_cont_sec'] = max(float(st.get('max_cont_sec', 0.0) or 0.0), live_sec)
                    if live_sec >= min_stay or (float(st.get('accum_stay_sec', 0.0) or 0.0) + live_sec) >= min_stay * 1.5:
                        st['confirmed'] = True
            cond_stats[effective_cond] = st

            active_conds = sorted(c for c, s in cond_stats.items() if s.get('is_active'))
            seen_conds = sorted(cond_stats.keys())
            pick_obj = {
                'code': clean_code,
                'name': self.stock_name_cache.get(clean_code, existing.get('name', '')),
                'cond_names': active_conds,
                'seen_conds': seen_conds,
                'cond_stats': cond_stats,
                'day_val_eok': float(existing.get('day_val_eok', 0.0) or 0.0),
                'captured_at': existing.get('captured_at', now_ts),
                'last_update': now_ts,
            }
            metrics = self._compute_cond_pick_metrics(pick_obj, now_ts=now_ts)
            pick_obj['confirmed_conds'] = metrics['confirmed_conds']
            pick_obj['confirmed_overlap'] = metrics['confirmed_overlap']
            pick_obj['overlap'] = metrics['confirmed_overlap']
            pick_obj['active_overlap'] = metrics['active_overlap']
            pick_obj['seen_overlap'] = metrics['seen_overlap']
            pick_obj['total_stay_sec'] = metrics['total_stay_sec']
            pick_obj['churn_count'] = metrics['churn_count']
            pick_obj['durability_score'] = metrics['durability_score']
            cond_label = ", ".join(metrics['confirmed_conds'] or seen_conds)
            pick_obj['target_tag'] = (
                f"🔔확정중복{metrics['confirmed_overlap']}/{self.condition_total}"
                f"(활성{metrics['active_overlap']}·{cond_label})"
            )
            self.condition_picks[clean_code] = pick_obj

        cached_nm = self.stock_name_cache.get(clean_code, f"종목_{clean_code}")
        min_ov = int(getattr(self, 'min_overlap', 2))
        seen_ov = len(seen_conds)
        conf_ov = metrics['confirmed_overlap']

        if is_new_stock:
            logger.info(
                f"🔔 [조건검색 포착·체류검증 시작] [{cached_nm}({clean_code})] ({effective_cond}) "
                f"➔ {min_stay:.0f}초 연속 유지 + 중복 {min_ov}개↑ 인증 시 Top10 편입 (포착 즉시 매수 금지)"
            )
        elif is_reentry_bounce:
            logger.debug(
                f"🔁 [조건식 재편입(들락날락 {metrics['churn_count']}회)] [{cached_nm}({clean_code})] "
                f"'{effective_cond}' 재진입 (인증중복 {conf_ov}/{self.condition_total}, 누적체류 {metrics['total_stay_sec']:.0f}초)"
            )
        elif is_new_cond_for_stock and seen_ov >= min_ov:
            logger.info(
                f"🔥 [조건식 다중 포착 관찰(포착 {seen_ov}/{self.condition_total} · 확정 {conf_ov}/{self.condition_total})] "
                f"[{cached_nm}({clean_code})] '{effective_cond}' 추가 ➔ {min_stay:.0f}초 체류 인증 후 4·3·2순 Top10 반영"
            )
        if conf_ov >= min_ov and (is_new_stock or is_new_cond_for_stock):
            self.condition_wakeup_event.set()

    def _on_condition_delete(self, code: str, cond_name: str = ""):
        """키움 실시간 조건검색 이탈('D') 콜백: 해당 조건식 체류시간 정산 및 인증여부 확정 (이미 30초+ 인증된 조건은 하락 보호 유지)"""
        clean_code = self._normalize_stock_code(code)
        effective_cond = cond_name.strip() if cond_name else ""
        now_ts = time.time()
        min_stay = max(0.0, float(getattr(self, 'min_cond_stay_sec', 30.0)))

        with self.condition_lock:
            pick = self.condition_picks.get(clean_code)
            if isinstance(pick, dict) and effective_cond:
                cond_stats = pick.get('cond_stats')
                if isinstance(cond_stats, dict) and effective_cond in cond_stats:
                    st = cond_stats[effective_cond]
                    if st.get('is_active', False):
                        session_sec = max(0.0, now_ts - float(st.get('active_since', now_ts) or now_ts))
                        st['accum_stay_sec'] = float(st.get('accum_stay_sec', 0.0) or 0.0) + session_sec
                        st['max_cont_sec'] = max(float(st.get('max_cont_sec', 0.0) or 0.0), session_sec)
                        if session_sec >= min_stay or st['accum_stay_sec'] >= min_stay * 1.5:
                            st['confirmed'] = True
                        st['is_active'] = False
                        st['active_since'] = 0.0
                    pick['cond_names'] = sorted(c for c, s in cond_stats.items() if s.get('is_active'))
                    metrics = self._compute_cond_pick_metrics(pick, now_ts=now_ts)
                    pick['confirmed_conds'] = metrics['confirmed_conds']
                    pick['confirmed_overlap'] = metrics['confirmed_overlap']
                    pick['overlap'] = metrics['confirmed_overlap']
                    pick['active_overlap'] = metrics['active_overlap']
                    pick['total_stay_sec'] = metrics['total_stay_sec']
                    pick['churn_count'] = metrics['churn_count']
                    pick['durability_score'] = metrics['durability_score']
                    pick['last_update'] = now_ts
                elif effective_cond in pick.get('cond_names', []):
                    remaining = [c for c in pick['cond_names'] if c != effective_cond]
                    pick['cond_names'] = remaining
                    pick['active_overlap'] = len(remaining)
                    pick['last_update'] = now_ts
        logger.debug(f"🔕 [실시간 조건검색 이탈] 종목코드: {clean_code} 조건식: {effective_cond or '-'} (체류시간 정산 완료)")

    def get_condition_overlap(self, code: str) -> int:
        """해당 종목이 4가지 조건검색식 중 최소 체류시간을 통과해 인증된 중복 조건식 수 반환 (0 = 미인증/미포착)"""
        now_ts = time.time()
        with self.condition_lock:
            pick = self.condition_picks.get(code)
            if isinstance(pick, dict):
                return int(self._compute_cond_pick_metrics(pick, now_ts=now_ts)['confirmed_overlap'])
            return len(pick) if pick else 0

    def _select_top10_condition_picks(self) -> list[dict]:
        """
        최소 체류시간 인증 완료 종목 중 아래 우선순위로 정예 Top 10 엄선:
        ① confirmed_overlap (4 → 3 → 2)
        ② 현재 이탈하지 않고 살아있는 active_overlap
        ③ 누적 체류시간 합계(total_stay_sec) - 들락날락(churn_count * 30초) 페널티
        """
        if getattr(self, 'top10_locked', False):
            return [dict(p) for p in getattr(self, 'locked_top10_picks', [])]

        now_ts = time.time()
        min_ov = max(2, int(getattr(self, 'min_overlap', 2)))
        with self.condition_lock:
            raw_picks = [dict(p) for p in self.condition_picks.values() if isinstance(p, dict)]

        eligible = []
        for p in raw_picks:
            m = self._compute_cond_pick_metrics(p, now_ts=now_ts)
            if m['confirmed_overlap'] >= min_ov:
                enriched = dict(p)
                enriched['confirmed_conds'] = m['confirmed_conds']
                enriched['confirmed_overlap'] = m['confirmed_overlap']
                enriched['overlap'] = m['confirmed_overlap']
                enriched['active_overlap'] = m['active_overlap']
                enriched['total_stay_sec'] = m['total_stay_sec']
                enriched['churn_count'] = m['churn_count']
                enriched['durability_score'] = m['durability_score']
                cond_label = ", ".join(m['confirmed_conds'] or p.get('seen_conds', []))
                enriched['target_tag'] = (
                    f"🔔확정중복{m['confirmed_overlap']}/{self.condition_total}"
                    f"(활성{m['active_overlap']}·체류{m['total_stay_sec']:.0f}s·재이탈{m['churn_count']})"
                    f"[{cond_label}]"
                )
                eligible.append(enriched)

        eligible.sort(
            key=lambda x: (
                int(x['confirmed_overlap']),
                int(x['active_overlap']),
                round(float(x['durability_score']), 3),
                float(x.get('day_val_eok', 0.0)),
                -float(x.get('captured_at', 0.0)),
            ),
            reverse=True,
        )
        return eligible[:10]

    def _maybe_lock_top10(self, now_t: Optional[dtime] = None):
        """09:30:00 도달 시 체류 인증 완료된 조건검색 중복 4·3·2순 Top 10 확정 락온 (이후 신규 잡주 편입 차단)"""
        if getattr(self, 'top10_locked', False):
            return
        cur_t = now_t or datetime.now().time()
        cutoff = getattr(self, 'top10_cutoff_time', dtime(9, 30, 0))
        if cur_t < cutoff:
            return

        init_evt = getattr(self, 'condition_init_event', None)
        uptime = time.time() - float(getattr(self, '_bot_start_ts', 0.0) or 0.0)
        if init_evt is not None and not init_evt.is_set() and uptime < 8.5 and not self.condition_picks:
            return

        top10 = self._select_top10_condition_picks()
        min_stay = max(0.0, float(getattr(self, 'min_cond_stay_sec', 30.0)))
        # 장중 늦은 재시작 직후(<35초) 아직 최소 체류 인증 시간이 안 찼다면 잠시 대기해 빈 리스트 오락온 방지
        if not top10 and self.condition_picks and min_stay > 0 and uptime < (min_stay + 5.0):
            return

        self.locked_top10_picks = top10
        self.locked_top10_codes = {p['code'] for p in top10}
        self.top10_locked = True
        summary = ", ".join(
            f"{self.get_stock_name(p['code'])}({p['code']}:확정{p.get('confirmed_overlap', 0)}/활성{p.get('active_overlap', 0)}·체류{p.get('total_stay_sec', 0.0):.0f}s·들락{p.get('churn_count', 0)})"
            for p in top10
        ) or "체류인증 중복2+ 포착종목 없음"
        logger.info(
            f"🔒 [09:30 조건검색 Top10 최종 확정 락온] 체류인증 중복 4·3·2순 {len(top10)}개 엄선 완료 "
            f"(신규 포착 마감 ➔ 120틱 단순 5-40 골든크로스 대기): [{summary}]"
        )

    def get_5m_anchor(self, code: str, df_60m: Optional[pd.DataFrame], df_daily: Optional[pd.DataFrame], tick_close: float) -> dict:
        """
        09:00~09:05 첫 5분봉의 시가(open_5m), 저가(low_5m), 고가(high_5m) 반환 및 캐싱.
        - 09:05 정각 이후에는 고정 앵커로 확정 보존.
        - API 5분봉(get_5m_candles) 조회 시 당일 09:00 첫 5분봉 캔들 추출.
        - 부재 시 당일 일봉 시가(day_open) 및 저가 기반 백업.
        """
        clean_code = str(code).replace("_AL", "").replace("_NX", "").lstrip("A").strip().zfill(6)
        if clean_code in self.m5_anchors:
            cached = self.m5_anchors[clean_code]
            if cached.get('locked', False):
                return cached

        now_t = datetime.now().time()
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_nodash = datetime.now().strftime("%Y%m%d")

        anchor = {'open': 0.0, 'low': 0.0, 'high': 0.0, 'locked': False}

        # 1) API 5분봉 직접 조회 시도 (_convert_raw_candles_to_df가 time을 index로 변환하므로 DatetimeIndex 우선 확인)
        if self.is_real and self.api and hasattr(self.api, 'get_5m_candles'):
            try:
                df_5m = self.api.get_5m_candles(clean_code)
                if df_5m is not None and not df_5m.empty:
                    df_today = pd.DataFrame()
                    if isinstance(df_5m.index, pd.DatetimeIndex):
                        idx_str = df_5m.index.strftime("%Y%m%d")
                        df_today = df_5m[idx_str == today_nodash]
                    else:
                        date_col = 'date' if 'date' in df_5m.columns else ('time' if 'time' in df_5m.columns else None)
                        if date_col:
                            s_date = df_5m[date_col].astype(str)
                            df_today = df_5m[s_date.str.contains(today_str) | s_date.str.contains(today_nodash)]
                    if not df_today.empty:
                        first_bar = df_today.iloc[0]
                        anchor['open'] = float(first_bar.get('open', 0.0) or 0.0)
                        anchor['low'] = float(first_bar.get('low', 0.0) or 0.0)
                        anchor['high'] = float(first_bar.get('high', 0.0) or 0.0)
            except Exception as e:
                logger.debug(f"5분봉 앵커 조회 예외 ({clean_code}): {e}")

        # 2) Fallback: 금일 캔들이 실제로 존재할 때만 당일 일봉/60분봉 활용 (전일 저가 오인 방지!)
        has_today_bar = False
        if anchor['open'] > 0:
            has_today_bar = True
        else:
            day_open = 0.0
            day_low = 0.0
            day_high = 0.0
            if df_daily is not None and not df_daily.empty:
                last_d = df_daily.iloc[-1]
                last_d_dt = str(last_d.get('date', '')).replace('-', '').replace('/', '').strip()[:8]
                if last_d_dt == today_nodash:
                    day_open = float(last_d.get('open', 0.0) or 0.0)
                    day_low = float(last_d.get('low', 0.0) or 0.0)
                    day_high = float(last_d.get('high', 0.0) or 0.0)
                    has_today_bar = True
            if day_open <= 0 and df_60m is not None and not df_60m.empty:
                if isinstance(df_60m.index, pd.DatetimeIndex):
                    df_60_today = df_60m[df_60m.index.strftime("%Y%m%d") == today_nodash]
                    if not df_60_today.empty:
                        first_60 = df_60_today.iloc[0]
                        day_open = float(first_60.get('open', 0.0) or 0.0)
                        day_low = float(first_60.get('low', 0.0) or 0.0)
                        day_high = float(first_60.get('high', 0.0) or 0.0)
                        has_today_bar = True
            if has_today_bar and day_open > 0:
                anchor['open'] = day_open
                anchor['low'] = day_low if day_low > 0 else min(day_open * 0.992, tick_close)
                anchor['high'] = day_high if day_high > 0 else max(day_open * 1.015, tick_close)

        # 09:05 이후 금일 첫 5분봉이 정상 확보된 경우에만 앵커 영구 고정
        if has_today_bar and anchor['open'] > 0 and now_t >= dtime(9, 5, 0):
            anchor['locked'] = True

        self.m5_anchors[clean_code] = anchor
        return anchor

    def _on_real_tick(self, tick_data: dict):
        """
        👑 [대표님 비기]: 실시간 주식체결(0B) 패킷 수신 콜백
        ➔ 순간체결대금 3,000만 원 이상 매수 연속 체결(세력 입성) 실시간 카운팅!
        """
        raw_code = str(tick_data.get('code', '')).strip()
        code = self._normalize_stock_code(raw_code)
        if not code or not code.isalnum() or len(code) != 6 or code == "000000":
            return
        price = float(tick_data.get('price', 0.0) or 0.0)
        qty = int(tick_data.get('qty', 0) or 0)
        is_buy = bool(tick_data.get('is_buy', True))
        gangdo = float(tick_data.get('gangdo', 0.0) or 0.0)
        amt = float(tick_data.get('amount', price * qty) or 0.0)

        if price > 0:
            self._live_tick_prices[code] = {'price': price, 'ts': time.time()}

        is_big_buy_hit = (amt >= self.big_order_tracker.threshold_won) and is_buy
        streak = self.big_order_tracker.on_tick(code, price, qty, is_buy_tick=is_buy, chegyul_gangdo=gangdo)
        if is_big_buy_hit and streak >= 2:
            name = self.get_stock_name(code)
            logger.info(
                f"🔥 [세력 3,000만+ 연속 체결 {streak}연타 포착!] [{name}({code})] "
                f"단가: {price:,.0f}원 | 순간체결: {amt/10000:,.0f}만 원({qty:,}주) (체결강도: {gangdo:.1f}%) "
                f"➔ 세력 수급 확인 (120틱 단순 5-40 GC 1차 / 5-60 GC 2차 타점 평가)"
            )
            self.condition_wakeup_event.set()

    def _start_condition_ws_daemon(self):
        """백그라운드 데몬 스레드에서 KiwoomWebSocketClient 실시간 조건검색 수신 루프 구동"""
        def _ws_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.ws_client = KiwoomWebSocketClient(
                    target_condition_name=self.condition_name,
                    on_insert=self._on_condition_insert,
                    on_delete=self._on_condition_delete,
                    on_real_tick=self._on_real_tick
                )
                self.ws_client.init_sync_event = self.condition_init_event
                logger.info(f"📡 [실시간 조건검색 웹소켓 가동] 목표 조건식: [{self.condition_name}] 실시간 수신 대기 중...")
                loop.run_until_complete(self.ws_client.run())
            except Exception as ws_err:
                logger.error(f"❌ 실시간 조건검색 웹소켓 데몬 예외: {ws_err}")
                self.condition_init_event.set()
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        self.ws_thread = threading.Thread(target=_ws_worker, name="KiwoomConditionWSDaemon", daemon=True)
        self.ws_thread.start()
        # 모든 목표 조건식(CNSRREQ) 초기 포착 응답이 수신될 때까지 최대 8.0초 대기
        self.condition_init_event.wait(timeout=8.0)
        self.condition_wakeup_event.clear()

    def get_stock_name(self, code: str) -> str:
        """종목명 캐시 및 조회 (429 API 제한 방지)"""
        if code in self.stock_name_cache:
            return self.stock_name_cache[code]
        if self.is_real and self.api:
            try:
                name = self.api.get_stock_name(code)
                if name and name.strip():
                    self.stock_name_cache[code] = name.strip()
                    return name.strip()
            except Exception:
                pass
        return f"종목_{code}"

    def get_stock_market_type(self, code: str) -> str:
        """종목의 소속 시장('KOSPI' vs 'KOSDAQ') 조회 및 영구 캐싱"""
        if not hasattr(self, 'stock_market_cache'):
            self.stock_market_cache: dict[str, str] = {
                '005930': 'KOSPI',
                '000660': 'KOSPI',
                '263750': 'KOSDAQ',
            }
        clean_code = str(code).replace("_AL", "").replace("_NX", "").lstrip("A").strip()
        if clean_code in self.stock_market_cache:
            return self.stock_market_cache[clean_code]
        if self.is_real and self.api and hasattr(self.api, 'get_stock_market_type'):
            try:
                m_type = self.api.get_stock_market_type(clean_code)
                if m_type in ("KOSPI", "KOSDAQ"):
                    self.stock_market_cache[clean_code] = m_type
                    return m_type
            except Exception:
                pass
        return "KOSDAQ"

    def get_futures_market_regime(self) -> dict:
        """
        코스피200 선물(F-KOSPI200) 및 코스닥150 선물(F-KOSDAQ150) 실시간 시장 날씨 조회
        - 코스피 종목은 'KOSPI' (코스피200선물), 코스닥 종목은 'KOSDAQ' (코스닥150선물)에 1:1 매칭
        """
        default_regimes = {
            'KOSPI': {
                'label': '코스피200선물',
                'flu_rt': 0.0,
                'intraday_chg_pct': 0.0,
                'drawdown_from_high_pct': 0.0,
                'is_bull_candle': True,
                'regime': 'NORMAL_BULL',
                'badge': '🟢정상(0.00%)',
                'reason': '정상 흐름'
            },
            'KOSDAQ': {
                'label': '코스닥150선물',
                'flu_rt': 0.0,
                'intraday_chg_pct': 0.0,
                'drawdown_from_high_pct': 0.0,
                'is_bull_candle': True,
                'regime': 'NORMAL_BULL',
                'badge': '🟢정상(0.00%)',
                'reason': '정상 흐름'
            }
        }
        if self.is_real and self.api and hasattr(self.api, 'get_futures_market_regime'):
            try:
                return self.api.get_futures_market_regime()
            except Exception as e:
                logger.debug(f"선물지수 시장온도계 조회 예외: {e}")
        return default_regimes

    def _check_and_cleanup_unfilled_orders(self, real_holdings: dict):
        """
        🛡️ [90초 미체결 매수 주문 자동 취소 및 유령 잠금(Ghost Lock) 해제]
        매수 주문 발송 후 90초 내에 체결되지 않고 허공에 떠 있는 미체결 주문은 즉시 취소하고,
        미체결 상태로 1종목 슬롯을 점유하던 전략 상태를 이전 상태(IDLE 등)로 안전 롤백합니다.
        """
        if not (self.is_real and not self.dry_run and self.api and self.pending_buy_orders):
            return

        try:
            unexecuted_list = self.api.get_unexecuted_orders() or []
            unexec_by_code: dict[str, dict] = {}
            for u in unexecuted_list:
                c = str(u.get('stock_code', '')).strip()
                u_qty = int(u.get('unfilled_qty', 0) or 0)
                if c and u_qty > 0:
                    unexec_by_code[c] = u

            now_ts = time.time()
            for code, p_info in list(self.pending_buy_orders.items()):
                name = self.get_stock_name(code)
                acc_qty = int(real_holdings.get(code, {}).get('qty', 0))
                if code not in unexec_by_code:
                    # 미체결 목록에 없으면 전량 체결 완료된 것!
                    logger.info(f"✅ [매수 실체결 확인 완료] [{name}({code})] {p_info.get('action')} 주문 체결 완료 (실계좌 보유: {acc_qty}주)")
                    acc_buy_prc = float(real_holdings.get(code, {}).get('buy_price', 0.0) or 0.0)
                    strat = self.strategies.get(code)
                    if strat and acc_qty > 1 and acc_buy_prc > 0 and strat.position.base_account_qty == 0:
                        strat.position.avg_price = acc_buy_prc
                        if p_info.get('action') == "BUY_1":
                            strat.position.first_buy_price = acc_buy_prc
                        elif p_info.get('action') == "BUY_2":
                            strat.position.second_buy_price = acc_buy_prc
                    self.pending_buy_orders.pop(code, None)
                    continue

                elapsed_sec = now_ts - float(p_info.get('timestamp', now_ts))
                if elapsed_sec >= 90.0:
                    u_item = unexec_by_code[code]
                    ord_no = str(u_item.get('order_no', p_info.get('order_no', '')))
                    u_qty = int(u_item.get('unfilled_qty', p_info.get('qty', 0)))
                    logger.warning(
                        f"⏱️ [미체결 90초 초과 자동 취소] [{name}({code})] 주문번호:{ord_no} 미체결잔량:{u_qty}주 "
                        f"➔ 유령 잠금(Ghost Lock) 방지를 위해 주문을 취소하고 슬롯을 복원합니다."
                    )
                    if ord_no and u_qty > 0:
                        self.api.cancel_order(ord_no, code, u_qty)

                    strat = self.strategies.get(code)
                    if strat:
                        if acc_qty <= 1:
                            # 단 1주도 신규 체결되지 않았으므로 주문 이전 상태로 완벽 롤백 (슬롯 즉시 해제!)
                            self._rollback_strategy_state(strat, p_info.get('order'), p_info.get('prev_pos'), p_info.get('prev_cash'))
                            logger.info(f"   🔓 [{name}({code})] 미체결 전량 취소 완료 ➔ 전략 상태 IDLE 복원 및 1종목 슬롯 개방!")
                        else:
                            # 일부 수량 부분 체결된 경우 실계좌 체결 수량으로 동기화하여 매도 감시 유지
                            strat.position.total_qty = acc_qty
                            logger.info(f"   ➕ [{name}({code})] 부분 체결 수량({acc_qty}주) 실계좌 동기화 완료 (잔여 미체결분 취소)")
                    self.pending_buy_orders.pop(code, None)
        except Exception as e:
            logger.debug(f"미체결 주문 점검 중 예외: {e}")

    def refresh_holdings(self):
        """실전 계좌 보유종목 + 통합 성배 로직 최적합 자동발굴 관심종목 통합 갱신"""
        now_ts = time.time()
        # 🛡️ 키움증권 계좌 조회 TR(1초당 3회 제한) 완벽 보호:
        # 최근 2.5초 이내에 계좌 조회를 완료했고, 대기 중인 미체결 주문이 없다면 캐시된 잔고를 재사용하여 TR 차단을 원천 방지합니다.
        can_use_cache = (
            self.is_real 
            and (now_ts - self._last_account_refresh_time < 2.5)
            and not self.pending_buy_orders
            and bool(self._cached_real_holdings or self._cached_cash > 0)
        )
        if can_use_cache:
            real_holdings = self._cached_real_holdings
            cash = self._cached_cash
        elif self.is_real:
            real_holdings = self.api.get_account_holdings()
            # 🌟 [대표님 지시]: "계좌예수금 조회하지말고 그냥 2주로 매매를 해보자"
            # ➔ 고정 수량 매매 모드(fixed_qty > 0) 시 계좌 예수금 조회 TR(opw00001/kt00001)을 아예 호출하지 않아 1초 3회 제한 완전 방어!
            if self.fixed_qty > 0:
                cash = 10_000_000.0  # 고정 2주 매매용 가상 예수금 (TR 호출 생략)
            else:
                cash = self.api.get_cash_balance()
            self._check_and_cleanup_unfilled_orders(real_holdings)
            self._cached_real_holdings = real_holdings
            self._cached_cash = cash
            self._last_account_refresh_time = now_ts
        else:
            real_holdings = {}
            cash = 10_000_000

        # 💻 [노트북/DRY-RUN 가상매매 감시 모드 시드머니 관리]:
        # 실계좌 예수금이 10만 원 미만이더라도 가상매매 검증이 가능하도록 기본 1,000만 원 시드 보장,
        # 가상 매매 체결 시에는 복리로 누적된 virtual_cash를 유지합니다.
        if self.dry_run:
            if self.dryrun_stats['initial_seed'] <= 0:
                init_seed = float(cash) if float(cash) >= 100_000 else 10_000_000.0
                self.dryrun_stats['initial_seed'] = init_seed
                self.dryrun_stats['virtual_cash'] = init_seed
            cash = self.dryrun_stats['virtual_cash']

        # 1) 우선순위 정렬된 통합 감시 딕셔너리 구성:
        #    [1순위] 봇 당일 진입 운용종목 -> [2순위] 🔔키움 실시간 조건검색 포착 종목
        holdings: dict[str, dict] = {}

        # (A) 봇이 당일 직접 매수한 실계좌 보유 종목만 감시 편입 (기존 계좌 보유·1주 종목은 100% 배제하여 원천 보호)
        for code, h in real_holdings.items():
            if int(h.get('qty', 0)) > 1:
                is_bot_trade = (
                    code in self.strategies
                    and self.strategies[code].position.entry_mode in self.BOT_ENTRY_MODES
                )
                if is_bot_trade:
                    h_copy = dict(h)
                    if code in self.condition_picks:
                        h_copy['is_condition_pick'] = True
                        h_copy['target_tag'] = self.condition_picks[code].get('target_tag', '🔔실시간조건(Traiding)')
                    holdings[code] = h_copy

        # (B) 🔔 키움 실시간 조건검색 중복 4·3·2순 Top10 엄선 풀 (09:30 기준 확정 락온)
        self._maybe_lock_top10()
        cond_added_count = 0
        sorted_cond_picks = self._select_top10_condition_picks()
        for c_pick in sorted_cond_picks:
            code = c_pick['code']
            if code not in real_holdings:
                holdings[code] = {
                    'name': c_pick.get('name', ''),
                    'qty': 0,
                    'buy_price': 0.0,
                    'current_price': 0.0,
                    'is_condition_pick': True,
                    'target_tag': c_pick.get('target_tag', '🔔실시간조건(Traiding)'),
                }
                cond_added_count += 1

        # (C) 지정가 주문 발송 직후 아직 잔고에 미반영된 활성 전략 종목 보호
        for code, st in self.strategies.items():
            if code not in holdings and st.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION]:
                holdings[code] = {
                    'name': self.get_stock_name(code),
                    'qty': st.position.total_qty,
                    'buy_price': st.position.avg_price,
                    'current_price': st.position.avg_price,
                    'is_condition_pick': (code in self.condition_picks),
                }

        self.active_holdings = holdings
        cash_str = f"고정 {self.fixed_qty}주 실전 매매 (예수금 조회 TR 생략)" if self.fixed_qty > 0 else f"가용 예수금: {cash:,.0f}원"
        lock_badge = "🔒09:30락온" if getattr(self, 'top10_locked', False) else "🔄09:30까지수집중"
        logger.info(
            f"💼 [계좌 잔고 & 조건검색 Top10({lock_badge}) 갱신] {cash_str} | "
            f"실계좌 보유: {len(real_holdings)}개 + 🔥Top10(중복 4·3·2순): {cond_added_count}개 (총 감시: {len(holdings)}개)"
        )

        # 우선순위 순서(실보유 -> 🔔실시간조건검색 Top10)에 맞춰 strategies 순서 정렬 유지
        ordered_strategies: dict[str, ThemeGate60mStrategy] = {}

        for code, h in holdings.items():
            if h.get('name'):
                self.stock_name_cache[code] = str(h['name']).strip()
            name = self.get_stock_name(code)
            account_qty = int(h.get('qty', 0))
            buy_prc = float(h.get('buy_price', 0.0))
            is_cond_pick = bool(h.get('is_condition_pick', False))
            target_tag = h.get('target_tag', '')
            
            # 최초 1회만 전략 상태 등록 (이미 있으면 기존 진행 상태 유지)
            if code not in self.strategies:
                strat = ThemeGate60mStrategy(
                    initial_capital=cash,
                    gate_sl_pct=DEFAULT_CONFIG.GATE_STOP_LOSS_PCT,
                    max_reentry=0,
                    fixed_qty=self.fixed_qty
                )
                if is_cond_pick and account_qty == 0:
                    strat.position.state = StrategyState.IDLE
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = 0
                    logger.info(
                        f"   🔔 [{name}({code})] 조건검색 Top10 후보 편입 ({target_tag} | IDLE 대기 ➔ 120틱 단순 5-40 GC 감시)"
                    )
                else:
                    # 🛡️ [기존 계좌 보유 자산 절대 보호 원칙]
                    # 봇이 이번 세션에 직접 매수한 주식이 아닌 계좌 보유분은 감시/매도 대상에서 배제 (IDLE 유지)
                    strat.position.state = StrategyState.IDLE
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = account_qty
                    strat.position.entry_mode = ""
                    logger.info(f"   🛡️ [{name}({code})] 기존 계좌 보유 자산 감지 (보유: {account_qty}주 | 매수가: {buy_prc:,.0f}원) ➔ 봇 자동 매매 대상에서 배제")
                ordered_strategies[code] = strat
            else:
                # 이미 등록된 전략 객체에도 최신 예수금 및 고정 수량 반영
                existing_strat = self.strategies[code]
                existing_strat.fixed_qty = self.fixed_qty
                if self.is_real and not self.dry_run:
                    existing_strat.cash = cash

                # 🛡️ [사자마자 즉시 손절 원천 차단]:
                # 봇이 당일 매수한 포지션(FIRST_BUY_DONE / FULL_POSITION)의 avg_price 및 total_qty를
                # 계좌 전체 합산 평단가(buy_prc)로 덮어쓰지 않고 봇 자체 체결 단가를 100% 보존합니다!
                ordered_strategies[code] = existing_strat

        self.strategies = ordered_strategies

    def get_60m_candles(self, code: str) -> pd.DataFrame:
        """60분봉 데이터 조회 (키움 실전 60분봉 API + 20초 단기 캐시로 120틱 고속 폴링 대역폭 확보)"""
        if self.is_real and self.api:
            now_dt = datetime.now()
            now_ts = time.time()
            cur_hour = now_dt.hour
            if hasattr(self, '_m60_cache') and code in self._m60_cache:
                c_ts, c_hr, c_df = self._m60_cache[code]
                if c_hr == cur_hour and (now_ts - c_ts) < 20.0 and c_df is not None and not c_df.empty:
                    return c_df.copy()
            try:
                if hasattr(self.api, 'get_60m_candles'):
                    df_60m = self.api.get_60m_candles(code)
                    if df_60m is not None and not df_60m.empty and len(df_60m) >= 4:
                        if not hasattr(self, '_m60_cache'):
                            self._m60_cache = {}
                        self._m60_cache[code] = (now_ts, cur_hour, df_60m)
                        return df_60m
                df_30m = self.api.get_30m_candles(code)
                if df_30m is not None and not df_30m.empty and len(df_30m) >= 4:
                    # 60분 단위 리샘플링
                    df_60m = df_30m.resample('60min').agg({
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum'
                    }).dropna().reset_index()
                    if not hasattr(self, '_m60_cache'):
                        self._m60_cache = {}
                    self._m60_cache[code] = (now_ts, cur_hour, df_60m)
                    return df_60m
            except Exception as e:
                logger.error(f"60분봉 조회 에러 ({code}): {e}")
            # 🛡️ 실전 계좌 모드에서는 API 일시 지연 시 절대 가상 샘플 데이터를 섞지 않고 빈 DataFrame 반환
            return pd.DataFrame()

        # Fallback 데이터 (비실전 순수 시뮬레이션 전용)
        try:
            from generate_sample_data import generate_realistic_sample_data
        except ImportError:
            from execution.generate_sample_data import generate_realistic_sample_data
        df_60m, _ = generate_realistic_sample_data(num_days=30)
        return df_60m

    def get_daily_candles(self, code: str) -> pd.DataFrame:
        """일봉 데이터 조회 (60초 단기 캐시로 120틱 고속 조회 여력 확보)"""
        if self.is_real and self.api:
            now_ts = time.time()
            if hasattr(self, '_daily_cache') and code in self._daily_cache:
                c_ts, c_df = self._daily_cache[code]
                if (now_ts - c_ts) < 60.0 and c_df is not None and not c_df.empty:
                    return c_df.copy()
            df_d = self.api.get_daily_candles(code)
            if df_d is not None and not df_d.empty:
                if not hasattr(self, '_daily_cache'):
                    self._daily_cache = {}
                self._daily_cache[code] = (now_ts, df_d)
                return df_d
            # 🛡️ 실전 계좌 모드에서는 API 일시 지연 시 절대 가상 샘플 데이터를 섞지 않고 빈 DataFrame 반환
            return pd.DataFrame()
        try:
            from generate_sample_data import generate_realistic_sample_data
        except ImportError:
            from execution.generate_sample_data import generate_realistic_sample_data
        _, df_d = generate_realistic_sample_data(num_days=40)
        return df_d

    def get_3m_candles(self, code: str) -> pd.DataFrame:
        """실전 3분봉 데이터 조회 (TEMA 60·120·240 실차트 일치용 2400봉 확보)"""
        if self.is_real and self.api:
            try:
                if hasattr(self.api, 'get_3m_candles'):
                    df_3m = self.api.get_3m_candles(code)
                    if df_3m is not None and not df_3m.empty and len(df_3m) >= 10:
                        return df_3m
                elif hasattr(self.api, 'real_client') and hasattr(self.api.real_client, 'get_3min_candles'):
                    try:
                        raw = self.api.real_client.get_3min_candles(code, last_n_days=30, limit=2400)
                    except TypeError:
                        raw = self.api.real_client.get_3min_candles(code, last_n_days=30)
                    if raw:
                        df_raw = pd.DataFrame(raw)
                        df_raw.columns = [c.lower() for c in df_raw.columns]
                        if 'time' in df_raw.columns:
                            t_parsed = pd.to_datetime(df_raw['time'], errors='coerce')
                            if not t_parsed.is_monotonic_increasing and t_parsed.is_monotonic_decreasing:
                                df_raw = df_raw.iloc[::-1]
                            df_raw['time'] = t_parsed
                            df_raw = df_raw.dropna(subset=['time']).set_index('time')
                        return df_raw
            except Exception as e:
                logger.debug(f"3분봉 데이터 조회 에러 ({code}): {e}")
        return pd.DataFrame()

    def get_10m_candles(self, code: str) -> pd.DataFrame:
        """실전 10분봉 데이터 조회 (TEMA 15·30·60·120 실차트 일치용 1500봉 확보)"""
        if self.is_real and self.api:
            try:
                if hasattr(self.api, 'get_10m_candles'):
                    df_10m = self.api.get_10m_candles(code)
                    if df_10m is not None and not df_10m.empty and len(df_10m) >= 10:
                        return df_10m
                elif hasattr(self.api, 'real_client') and hasattr(self.api.real_client, 'get_10min_candles'):
                    raw = self.api.real_client.get_10min_candles(code, last_n_days=60, limit=1500)
                    if raw:
                        df_raw = pd.DataFrame(raw)
                        df_raw.columns = [c.lower() for c in df_raw.columns]
                        if 'time' in df_raw.columns:
                            t_parsed = pd.to_datetime(df_raw['time'], errors='coerce')
                            if not t_parsed.is_monotonic_increasing and t_parsed.is_monotonic_decreasing:
                                df_raw = df_raw.iloc[::-1]
                            df_raw['time'] = t_parsed
                            df_raw = df_raw.dropna(subset=['time']).set_index('time')
                        return df_raw
            except Exception as e:
                logger.debug(f"10분봉 데이터 조회 에러 ({code}): {e}")
        return pd.DataFrame()

    def get_120t_candles(self, code: str) -> pd.DataFrame:
        """실전 120틱 데이터 조회 (TEMA 15·30·60·120 실차트 일치용 1800봉 확보)"""
        if self.is_real and self.api:
            try:
                if hasattr(self.api, 'get_120t_candles'):
                    df_120t = self.api.get_120t_candles(code)
                    if df_120t is not None and not df_120t.empty and len(df_120t) >= 10:
                        return df_120t
                elif hasattr(self.api, 'real_client') and hasattr(self.api.real_client, 'get_tick_data'):
                    raw = self.api.real_client.get_tick_data(code, tick_unit="120", limit=1800)
                    if raw:
                        df_raw = pd.DataFrame(raw)
                        df_raw.columns = [c.lower() for c in df_raw.columns]
                        if 'time' in df_raw.columns:
                            t_parsed = pd.to_datetime(df_raw['time'], errors='coerce')
                            if not t_parsed.is_monotonic_increasing and t_parsed.is_monotonic_decreasing:
                                df_raw = df_raw.iloc[::-1]
                        return df_raw.reset_index(drop=True)
            except Exception as e:
                logger.debug(f"120틱 데이터 조회 에러 ({code}): {e}")
        return pd.DataFrame()

    def _rollback_strategy_state(self, strat: Optional[ThemeGate60mStrategy], order: Optional[TradeOrder],
                                 prev_pos: Optional[PositionTracker], prev_cash: Optional[float]):
        """주문 미발송/API 거절 시 전략 포지션 및 예수금 원자적 롤백(Atomic Rollback)"""
        if not strat:
            return
        if prev_pos is not None:
            strat.position = copy.deepcopy(prev_pos)
        if prev_cash is not None:
            strat.cash = prev_cash
        if order is not None and strat.trade_history and strat.trade_history[-1] == order:
            strat.trade_history.pop()

    def execute_order(
        self,
        code: str,
        name: str,
        order: TradeOrder,
        prev_pos: Optional[PositionTracker] = None,
        prev_cash: Optional[float] = None
    ):
        """실전 주문 전송 (안전 장치 검사 및 실패 시 원자적 롤백 보장)"""
        is_active, session_name, exchange_hint = get_market_session()
        strat = self.strategies.get(code)
        
        # 1. 장운영 시간 안전 검사 (실전 모드 시 장외 주문 원천 차단 및 상태 롤백)
        if not is_active and not self.dry_run:
            logger.warning(
                f"⏸️ [장외/준비 시간 주문 차단] [{name}({code})] {order.action} 신호 감지됨. "
                f"현재 상태는 '{session_name}'이므로 실전 주문을 발송하지 않고 이전 상태로 안전 복원합니다."
            )
            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
            return

        # 2. 매수 집행 (1차 50% 또는 2차 50%)
        if order.action in ["BUY_1", "BUY_2"]:
            if order.qty <= 0:
                logger.warning(f"⚠️ [매수 스킵] [{name}({code})] 매수 수량이 0주 이하({order.qty})이므로 주문을 발송하지 않습니다.")
                self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                return

            # ⚡ 돌파 역선택(Adverse Selection) 및 미체결 방지: +1~2호가 공격적 스마트 지정가 산출 (상한 슬리피지 +0.3% 이내)
            buy_price = get_smart_buy_price(order.price) if order.price > 0 else 0
            if strat and buy_price > 0:
                if order.action == "BUY_1":
                    strat.position.avg_price = buy_price
                    strat.position.first_buy_price = buy_price
                elif order.action == "BUY_2":
                    strat.position.second_buy_price = buy_price
                    p_qty = prev_pos.total_qty if prev_pos else max(0, strat.position.total_qty - order.qty)
                    p_avg = prev_pos.avg_price if (prev_pos and prev_pos.avg_price > 0) else strat.position.first_buy_price
                    tot_q = strat.position.total_qty if strat.position.total_qty > 0 else (p_qty + order.qty)
                    if tot_q > 0 and p_qty > 0 and p_avg > 0:
                        strat.position.avg_price = ((p_qty * p_avg) + (order.qty * buy_price)) / tot_q
                    else:
                        strat.position.avg_price = buy_price

            if self.dry_run:
                buy_msg = (
                    f"💻 [가상매매(DRY-RUN) 매수 체결] [{name}({code})] {order.action} | 세션: {session_name} | "
                    f"수량: {order.qty}주 | 체결가: {buy_price:,.0f}원 | 사유: {order.reason}"
                )
                logger.info(buy_msg)
                try:
                    with open(self.dryrun_stats['log_path'], "a", encoding="utf-8") as lf:
                        lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {buy_msg}\n")
                except Exception:
                    pass
                return

            logger.info(f"🚀 [실전 매수 발송(+1~2호가 스마트지정가)] [{name}({code})] {order.action} | 세션: {session_name} ({exchange_hint}) | 수량: {order.qty}주 | 지정가: {buy_price:,.0f}원")
            if self.is_real and self.api:
                order_no = self.api.place_buy_order(code, order.qty, price=buy_price, order_type="00")
                if not order_no:
                    logger.error(f"   ❌ [매수 주문 실패/거부] [{name}({code})] API 응답 없음 ➔ 전략 상태를 주문 이전으로 안전 롤백합니다.")
                    self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                    return
                logger.info(f"   ✅ [매수 접수 완료] 주문번호: {order_no} (90초 미체결 감시 타이머 가동)")
                self.pending_buy_orders[code] = {
                    'order_no': str(order_no),
                    'action': order.action,
                    'qty': order.qty,
                    'price': buy_price,
                    'timestamp': time.time(),
                    'prev_pos': copy.deepcopy(prev_pos) if prev_pos is not None else None,
                    'prev_cash': prev_cash,
                    'order': order
                }

        # 3. 매도 집행 (봇 진입 수량 한정 매도 및 기존 계좌 자산 절대 보호)
        elif order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]:
            self.pending_buy_orders.pop(code, None)

            # 🛡️ [철통 자산 보호 1단계: 봇 직접 매수 포지션 검증 (매도 시 초기화된 strat.position 대비 prev_pos 병행 참조)]
            entry_mode = (
                strat.position.entry_mode
                if (strat and strat.position.entry_mode)
                else (prev_pos.entry_mode if prev_pos else "")
            )
            if not entry_mode or entry_mode not in self.BOT_ENTRY_MODES:
                logger.error(
                    f"🛑 [기존 계좌 보유 자산 보호 긴급 차단] [{name}({code})] 봇이 당일 매수한 포지션이 아닙니다 (entry_mode: '{entry_mode}'). "
                    f"대표님의 기존 투자 자산(한화에어로스페이스 등) 보호를 위해 매도 주문 발송을 100% 원천 차단합니다!"
                )
                if strat:
                    strat.position = PositionTracker()
                    strat.position.state = StrategyState.IDLE
                return

            account_holding_qty = 0
            if self.is_real and self.api:
                cur_holdings = self.api.get_account_holdings()
                account_holding_qty = cur_holdings.get(code, {}).get('qty', 0)
            else:
                account_holding_qty = self.active_holdings.get(code, {}).get('qty', 0)

            strat_qty = strat.position.total_qty if strat else 0
            prev_qty = prev_pos.total_qty if prev_pos else 0
            order_qty = order.qty if order else 0
            effective_qty = account_holding_qty if (self.is_real and not self.dry_run) else max(account_holding_qty, strat_qty, prev_qty, order_qty)

            # 🛡️ [관종 1주 매도 절대 차단 원칙]
            # 사용자가 관심종목/정찰병으로 1주 매수한 종목은 매수가 실제로 체결되어
            # 계좌 수량이 1주를 초과할 때만 매도 시 함께 정리됩니다.
            # 1주만 남아있는 상태에서는 어떠한 경우에도 매도 주문을 전송하지 않고 보존합니다.
            if effective_qty <= 1:
                logger.warning(
                    f"🛡️ [관종 1주 매도 절대 차단] [{name}({code})] 현재 수량이 {effective_qty}주(관종 마커)입니다. "
                    f"매수가 완료되지 않았으므로 매도 주문 발송을 원천 차단하고 1주를 안전하게 보존합니다."
                )
                if strat:
                    strat.position = PositionTracker()
                    strat.position.state = StrategyState.IDLE
                    strat.position.base_account_qty = effective_qty
                return

            # 실전 매도시 실계좌 보유수량이 0이면 매도 차단 및 상태 동기화
            if self.is_real and not self.dry_run and account_holding_qty <= 0:
                logger.warning(f"⚠️ [매도 스킵] [{name}({code})] 실계좌 보유수량이 0주이므로 매도 주문을 전송하지 않고 상태를 동기화합니다.")
                if strat:
                    strat.position = PositionTracker()
                return

            # 🛡️ [철통 자산 보호 2단계: 매도 수량 1차+2차 봇 매수분 한정 엄격 제한]
            bot_bought_qty = (
                strat.position.total_qty
                if (strat and strat.position.total_qty > 0)
                else (prev_pos.total_qty if (prev_pos and prev_pos.total_qty > 0) else self.fixed_qty)
            )
            max_bot_qty = (self.fixed_qty * 2) if self.fixed_qty > 0 else effective_qty
            final_sell_qty = min(effective_qty, bot_bought_qty, max_bot_qty)
            if final_sell_qty <= 0:
                logger.warning(f"⚠️ [매도 스킵] [{name}({code})] 매도 가능 수량이 0주이므로 주문을 발송하지 않습니다.")
                return

            # 매도가 결정 (포지션 초기화 전 스냅샷 단가까지 안전하게 확보)
            fallback_price = 0.0
            if strat and strat.position.avg_price > 0:
                fallback_price = strat.position.avg_price
            elif prev_pos and prev_pos.avg_price > 0:
                fallback_price = prev_pos.avg_price
            raw_price = order.price if (order.price and order.price > 0) else fallback_price
            sell_price = align_to_tick(raw_price) if raw_price > 0 else 0

            if self.dry_run:
                avg_buy_p = fallback_price if fallback_price > 0 else sell_price
                gross_pnl = (sell_price - avg_buy_p) * final_sell_qty
                fee_tax = (sell_price * final_sell_qty) * 0.0023
                net_pnl = gross_pnl - fee_tax
                net_pnl_pct = ((sell_price - avg_buy_p) / avg_buy_p * 100.0 - 0.23) if avg_buy_p > 0 else 0.0

                self.dryrun_stats['trades'] += 1
                if net_pnl >= 0:
                    self.dryrun_stats['wins'] += 1
                else:
                    self.dryrun_stats['losses'] += 1
                self.dryrun_stats['realized_net_pnl'] += net_pnl
                self.dryrun_stats['virtual_cash'] = self.dryrun_stats['initial_seed'] + self.dryrun_stats['realized_net_pnl']

                tot_t = self.dryrun_stats['trades']
                win_rate = (self.dryrun_stats['wins'] / tot_t * 100.0) if tot_t > 0 else 0.0
                cum_ret = (self.dryrun_stats['realized_net_pnl'] / self.dryrun_stats['initial_seed'] * 100.0) if self.dryrun_stats['initial_seed'] > 0 else 0.0

                sell_msg = (
                    f"💻 [가상매매(DRY-RUN) 전량 매도 체결] [{name}({code})] {order.action} | 수량: {final_sell_qty}주 | "
                    f"매수가: {avg_buy_p:,.0f}원 ➔ 매도가: {sell_price:,.0f}원 | 순수익: {net_pnl:+,.0f}원 ({net_pnl_pct:+.2f}%) | "
                    f"사유: {order.reason} | 📊 누적성적: {self.dryrun_stats['wins']}승 {self.dryrun_stats['losses']}패(승률 {win_rate:.1f}%), "
                    f"누적순손익: {self.dryrun_stats['realized_net_pnl']:+,.0f}원({cum_ret:+.2f}%)"
                )
                logger.info(sell_msg)
                try:
                    with open(self.dryrun_stats['log_path'], "a", encoding="utf-8") as lf:
                        lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {sell_msg}\n")
                except Exception:
                    pass

                if strat:
                    strat.position = PositionTracker()
                # 복리 반영된 가상 시드머니를 대기 중인 모든 전략 객체에 동기화
                for st_obj in self.strategies.values():
                    if st_obj.position.state == StrategyState.IDLE:
                        st_obj.cash = self.dryrun_stats['virtual_cash']
                # 👑 [대표님 지시: 즉시 재매수 및 순환매매 지원]
                # 매도 직후 동일봉 초단타 꼬임 방지용 초단기 쿨다운(20초)만 적용하여,
                # 타점 재발생 시 즉각 '재매수' 또는 '다음 1위 종목 매수'가 가능하도록 보장!
                self.sold_cooldowns[code] = time.time() + 20.0
                self.completed_trades_today += 1
                logger.info(f"   👀 [{name}({code})] 모의 전량 매도 완료 (당일 순환 {self.completed_trades_today}회) ➔ 다음 종목 교체(등락률<=20%) 대기")
                return

            if exchange_hint == "NXT":
                sell_order_type = "00"  # NXT 지정가 필수
                logger.info(f"🚨 [실전 매도 발송(NXT 지정가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (봇 매수분 한정) | 지정가: {sell_price:,.0f}원 | 사유: {order.reason}")
            else:
                sell_order_type = "03"  # KRX 정규장 시장가
                logger.info(f"🚨 [실전 매도 발송(KRX 시장가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (봇 매수분 한정) | 기준가: {sell_price:,.0f}원 | 사유: {order.reason}")

            if self.is_real and self.api:
                order_no = self.api.place_sell_order(code, final_sell_qty, price=sell_price, order_type=sell_order_type)
                if not order_no:
                    logger.error(f"   ❌ [전량 매도 주문 실패/거부] [{name}({code})] API 응답 없음 ➔ 다음 사이클 즉시 재시도를 위해 포지션 상태를 보존합니다.")
                    self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                    return
                logger.info(f"   ✅ [전량 매도 접수 완료] 주문번호: {order_no}")

            if strat:
                # 전량 매도 완료 즉시 포지션 초기화 (IDLE 복귀)
                strat.position = PositionTracker()

            # 👑 [대표님 지시: 즉시 재매수 및 순환매매 지원]
            # 매도 직후 동일봉 초단타 꼬임 방지용 초단기 쿨다운(20초)만 적용하여,
            # 타점 재발생 시 즉각 '재매수' 또는 '다음 1위 종목 매수'가 가능하도록 보장!
            self.sold_cooldowns[code] = time.time() + 20.0
            self.completed_trades_today += 1
            logger.info(f"   👀 [{name}({code})] 전량 매도 완료 (당일 순환 {self.completed_trades_today}회) ➔ 다음 종목 교체(등락률<=20%) 120틱 단순 5-40 타점 대기")

    def get_active_stock_code(self, exclude_codes: Optional[set[str]] = None) -> str | None:
        """
        👑 [대표님 지시]: 로직으로 사지 않은 기존 보유종목은 100% 완전 제외하고,
        '봇이 로직으로 직접 매수한 활성 종목(1종목)'만 반환합니다.
        - 봇 직접 매수 증표:
          1) entry_mode 가 self.BOT_ENTRY_MODES (예: "3M_TEMA") 중 하나여야 함
          2) 전략 상태가 FIRST_BUY_DONE 또는 FULL_POSITION 이어야 함
          3) 봇 매수 수량(total_qty) > 0 이어야 함
        - 로직으로 사지 않은 기존 중장기 보유주식(한화에어로스페이스 등) 및 관심 1주 마커는 슬롯을 점유하지 않습니다!
        """
        for code, strat in self.strategies.items():
            if exclude_codes and code in exclude_codes:
                continue
            
            entry_mode = getattr(strat.position, 'entry_mode', '')
            is_bot_trade = entry_mode in self.BOT_ENTRY_MODES
            is_active_state = strat.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION]
            has_qty = strat.position.total_qty > 0

            if is_bot_trade and is_active_state and has_qty:
                return code
        return None

    @staticmethod
    def _extract_today_rows(df: Optional[pd.DataFrame], today_str: str) -> pd.DataFrame:
        """일중 분봉/120틱 DataFrame에서 당일(today_str: YYYYMMDD) 행만 안전하게 추출합니다."""
        if df is None or df.empty:
            return pd.DataFrame()
        try:
            if isinstance(df.index, pd.DatetimeIndex):
                mask = df.index.strftime('%Y%m%d') == today_str
                return df.loc[mask]
            for col in ('date', 'time', 'dt', 'cntr_tm'):
                if col in df.columns:
                    norm = (
                        df[col].astype(str)
                        .str.replace('-', '', regex=False)
                        .str.replace('/', '', regex=False)
                        .str.strip()
                        .str[:8]
                    )
                    return df.loc[norm == today_str]
            if not isinstance(df.index, pd.RangeIndex):
                idx_norm = (
                    df.index.astype(str)
                    .str.replace('-', '', regex=False)
                    .str.replace('/', '', regex=False)
                    .str.strip()
                    .str[:8]
                )
                return df.loc[idx_norm == today_str]
        except Exception:
            pass
        return pd.DataFrame()

    def _compute_liquidity_metrics(
        self,
        tick_close: float,
        df_daily: Optional[pd.DataFrame] = None,
        df_60m: Optional[pd.DataFrame] = None,
        df_120t: Optional[pd.DataFrame] = None,
        today_str: Optional[str] = None,
        df_10m: Optional[pd.DataFrame] = None,
        df_3m: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """당일 거래량/거래대금(억원), 전일 거래대금(억원), 당일 3분봉(또는 10분/120틱) 형성 봉수를 산출합니다. (NXT 0원 일봉 보정 포함)"""
        today_str = (today_str or datetime.now().strftime('%Y%m%d')).replace('-', '').replace('/', '').strip()[:8]

        def _safe_float(val: Any, default: float = 0.0) -> float:
            try:
                f = float(val)
                return f if np.isfinite(f) else default
            except (TypeError, ValueError):
                return default

        def _row_date_str(row: pd.Series, idx_val: Any = None) -> str:
            raw = row.get('date', '') if hasattr(row, 'get') else ''
            s = str(raw).replace('-', '').replace('/', '').strip()[:8]
            if not s and idx_val is not None:
                s = str(idx_val).replace('-', '').replace('/', '').strip()[:8]
            return s

        vol_daily_today = 0.0
        val_daily_today = 0.0
        prev_day_vol = 0.0
        prev_day_val_eok = 0.0
        day_open_p = 0.0
        has_today_daily = False

        if df_daily is not None and not df_daily.empty:
            last_daily = df_daily.iloc[-1]
            last_daily_dt = _row_date_str(last_daily, df_daily.index[-1])
            has_today_daily = (last_daily_dt == today_str)

            if has_today_daily:
                vol_daily_today = _safe_float(last_daily.get('volume', 0.0))
                raw_tv = _safe_float(last_daily.get('trading_value', 0.0))
                if raw_tv > 0:
                    val_daily_today = raw_tv
                elif vol_daily_today > 0:
                    val_daily_today = vol_daily_today * _safe_float(last_daily.get('close', tick_close), tick_close)
                day_open_p = _safe_float(last_daily.get('open', 0.0))
                prev_row = df_daily.iloc[-2] if len(df_daily) >= 2 else None
            else:
                prev_row = last_daily

            if prev_row is not None:
                prev_close = _safe_float(prev_row.get('close', 0.0))
                prev_day_vol = _safe_float(prev_row.get('volume', 0.0))
                raw_prev_tv = _safe_float(prev_row.get('trading_value', 0.0))
                if raw_prev_tv > 0:
                    prev_day_val_eok = raw_prev_tv / 100_000_000.0
                elif prev_close > 0 and prev_day_vol > 0:
                    prev_day_val_eok = (prev_day_vol * prev_close) / 100_000_000.0

        def _sum_intraday(df: Optional[pd.DataFrame]) -> Tuple[float, float, int, float]:
            today_df = self._extract_today_rows(df, today_str)
            if today_df.empty:
                return 0.0, 0.0, 0, 0.0
            vols = pd.to_numeric(today_df['volume'], errors='coerce').fillna(0.0) if 'volume' in today_df else pd.Series(0.0, index=today_df.index)
            closes = pd.to_numeric(today_df['close'], errors='coerce').fillna(_safe_float(tick_close)) if 'close' in today_df else pd.Series(_safe_float(tick_close), index=today_df.index)
            first_open = _safe_float(today_df.iloc[0].get('open', 0.0)) if 'open' in today_df else 0.0
            return float(vols.sum()), float((vols * closes).sum()), int(len(today_df)), first_open

        df_intraday = df_3m if df_3m is not None else (df_10m if df_10m is not None else df_120t)
        bar_timeframe = "3m" if df_3m is not None else ("10m" if df_10m is not None else "120t")
        vol_60m_today, val_60m_today, bars_60m_today, open_60m_today = _sum_intraday(df_60m)
        vol_120t_today, val_120t_today, t120_today_bars, _ = _sum_intraday(df_intraday)

        if day_open_p <= 0 and open_60m_today > 0:
            day_open_p = open_60m_today

        # NXT 프리마켓(08:00~08:50)에는 일봉 volume이 0이므로 60분봉/3분봉 당일 합산치로 자동 보정
        today_vol = max(vol_daily_today, vol_60m_today, vol_120t_today)
        today_val_won = max(val_daily_today, val_60m_today, val_120t_today)
        if today_val_won <= 0 and today_vol > 0:
            today_val_won = today_vol * float(tick_close or 0.0)
        today_val_eok = today_val_won / 100_000_000.0

        return {
            'today_str': today_str,
            'has_today_daily': has_today_daily,
            'day_open_p': day_open_p,
            'today_vol': today_vol,
            'today_val_eok': today_val_eok,
            'prev_day_vol': prev_day_vol,
            'prev_day_val_eok': prev_day_val_eok,
            'bars_60m_today': bars_60m_today,
            't120_today_bars': t120_today_bars,
            'm10_today_bars': t120_today_bars,
            'm3_today_bars': t120_today_bars,
            'bar_timeframe': bar_timeframe,
        }

    def evaluate_liquidity_activity(
        self,
        tick_close: float,
        df_daily: Optional[pd.DataFrame] = None,
        df_60m: Optional[pd.DataFrame] = None,
        df_120t: Optional[pd.DataFrame] = None,
        metrics: Optional[Dict[str, Any]] = None,
        now_t: Optional[dtime] = None,
        today_str: Optional[str] = None,
        df_10m: Optional[pd.DataFrame] = None,
        df_3m: Optional[pd.DataFrame] = None,
    ) -> Tuple[bool, str]:
        """
        💧 [실시간 유동성·거래대금 및 3분봉(또는 10분/120틱) 체결 활성도 게이트]
        당일 실제 체결량·거래대금이 미미해 지표가 전일 봉에 멈춰있는 초저유동성 종목이
        1/1 회전 슬롯을 선점하여 조건중복 대장주 진입을 막는 현상을 차단합니다.
        """
        m = metrics or self._compute_liquidity_metrics(
            tick_close, df_daily=df_daily, df_60m=df_60m, df_120t=df_120t, today_str=today_str, df_10m=df_10m, df_3m=df_3m
        )
        cur_t = now_t or datetime.now().time()
        today_val_eok = float(m['today_val_eok'])
        prev_val_eok = float(m['prev_day_val_eok'])
        default_tf = '3m' if df_3m is not None else ('10m' if df_10m is not None else '120t')
        bar_tf = str(m.get('bar_timeframe', default_tf))
        intraday_bars = int(m.get('m3_today_bars', m.get('m10_today_bars', m.get('t120_today_bars', 0))))
        tf_short = "3m" if bar_tf == "3m" else ("10m" if bar_tf == "10m" else "120t")
        tf_kr = "3분봉" if bar_tf == "3m" else ("10분봉" if bar_tf == "10m" else "120틱")

        is_premarket = cur_t < dtime(9, 0, 0)
        is_early_nxt = dtime(8, 0, 0) <= cur_t < dtime(8, 3, 0)
        is_early_krx = dtime(9, 0, 0) <= cur_t < dtime(9, 3, 0)

        min_bars_active = 1 if bar_tf in ("3m", "10m") else 3
        min_today_val_active = 3.0 if is_premarket else 10.0

        # 장초반 3분 내더라도 이미 활성 세션 유동성(거래대금·당일 봉수)을 돌파한 주도주는 즉시 허용
        if (
            intraday_bars >= min_bars_active
            and today_val_eok >= min_today_val_active
            and (prev_val_eok >= 10.0 or today_val_eok >= 10.0)
        ):
            return True, f"당일 {today_val_eok:.1f}억 / 전일 {prev_val_eok:.1f}억 / {tf_short} {intraday_bars}봉"

        if is_early_nxt or is_early_krx:
            min_val_early = 0.5 if is_early_nxt else 2.0
            min_prev_early = 50.0
            reasons = []
            if intraday_bars < 1:
                reasons.append(f"당일 {tf_kr} {intraday_bars}봉 < 1봉")
            if today_val_eok < min_val_early:
                reasons.append(f"금일거래대금 {today_val_eok:.2f}억 < {min_val_early:.1f}억")
            if prev_val_eok < min_prev_early:
                reasons.append(f"장초반 전일거래대금 {prev_val_eok:.1f}억 < {min_prev_early:.0f}억")
            if reasons:
                return False, " | ".join(reasons)
            return True, f"장초반 유동성 충족 (당일 {today_val_eok:.1f}억 / 전일 {prev_val_eok:.1f}억 / {tf_short} {intraday_bars}봉)"

        reasons = []
        if intraday_bars < min_bars_active:
            reasons.append(f"당일 {tf_kr} 형성 {intraday_bars}봉 < {min_bars_active}봉(체결 부재)")
        if today_val_eok < min_today_val_active:
            reasons.append(f"금일거래대금 {today_val_eok:.2f}억 < {min_today_val_active:.0f}억")
        if prev_val_eok < 10.0 and today_val_eok < 10.0:
            reasons.append(f"전일({prev_val_eok:.1f}억)·금일({today_val_eok:.2f}억) 모두 10억 미만 초소형주")

        if reasons:
            return False, " | ".join(reasons)
        return True, f"당일 {today_val_eok:.1f}억 / 전일 {prev_val_eok:.1f}억 / {tf_short} {intraday_bars}봉"

    def calculate_priority_score(
        self,
        code: str,
        name: str,
        tick_close: float,
        last_60m: pd.Series,
        last_daily: pd.Series,
        df_60m: pd.DataFrame,
        pre_day_close: Optional[float] = None,
        df_daily: Optional[pd.DataFrame] = None,
        vol_ratio_prev: Optional[float] = None,
        session_target_vol: Optional[float] = None,
        df_120t: Optional[pd.DataFrame] = None,
        today_str: Optional[str] = None,
        df_10m: Optional[pd.DataFrame] = None,
        df_3m: Optional[pd.DataFrame] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        ⚡ [세션별 차등 번개 돌파 + 실제 거래대금 검증 1위 선정 체계 - 100.0점 정규화]
        1. 🥇 세션별 전일 거래량 돌파 속도 및 실제 거래대금 상한 검증 (40점 만점)
           - 금일 거래대금 3억 미만은 % 착시 방지를 위해 속도점수 0점, 10억 미만 15점 상한, 30억 미만 28점 상한
        2. 🥈 시가 무훼손 양봉 순도 (20점 만점, 3억 미만 보합/1호가 캔들은 0점)
        3. 🥉 기준선(M선) 안착 이격도 (20점 만점)
        4. ⚡ 120틱 단순 5-40·5-60 골든크로스 (10점 만점)
        5. 🔥 시초가 모멘텀 (+1.5%, 10점 만점) + 유동성 규모 가산점 (+0~+10점)
        """
        # 세션별 차등 목표 거래량 기준 설정 (프리 1.5%, 정규장 3.0%, 애프터 1.0%)
        if session_target_vol is not None and session_target_vol > 0:
            target_vol = float(session_target_vol)
            target_name = f"지정세션({target_vol:.1f}%)"
        else:
            target_vol, target_name = get_session_volume_target()

        liq = self._compute_liquidity_metrics(
            tick_close, df_daily=df_daily, df_60m=df_60m, df_120t=df_120t, today_str=today_str, df_10m=df_10m, df_3m=df_3m
        )
        today_str = liq['today_str']
        day_val_eok = liq['today_val_eok']
        prev_day_val_eok = liq['prev_day_val_eok']
        t120_today_bars = liq['t120_today_bars']

        # 1. 전일 거래량 돌파 속도 점수 (40점 만점, 실제 거래대금 기반 상한 적용)
        last_daily_dt = str(last_daily.get('date', '')).replace('-', '').replace('/', '').strip()[:8]
        if vol_ratio_prev is None:
            vol_ratio_prev, pre_day_vol = calculate_pred_volume_ratio(df_daily, liq['today_vol'])
        else:
            pre_day_vol = liq['prev_day_vol']

        attainment_ratio = (vol_ratio_prev / target_vol) if target_vol > 0 else 1.0

        if attainment_ratio >= 1.5:
            score_speed = 40.0
        elif attainment_ratio >= 1.0:
            score_speed = 35.0
        elif attainment_ratio >= 0.7:
            score_speed = 25.0
        elif attainment_ratio >= 0.4:
            score_speed = 15.0
        else:
            score_speed = 5.0

        # 극소 거래량 종목의 전일대비 % 착시 원천 차단
        if day_val_eok < 3.0:
            score_speed = 0.0
        elif day_val_eok < 10.0:
            score_speed = min(score_speed, 15.0)
        elif day_val_eok < 30.0:
            score_speed = min(score_speed, 28.0)

        # 2. 당일 시가·60분봉 양봉 순도 및 실시간 3일선(M/3) 안착 점수 (20점 만점)
        day_open_p = liq['day_open_p']
        c_open = float(last_60m.get('open', tick_close))
        c_high = float(last_60m.get('high', tick_close))
        c_low = float(last_60m.get('low', tick_close))
        c_close = float(last_60m.get('close', tick_close))
        c_range = max(c_high - c_low, 1.0)
        c_body = max(c_close - c_open, 0.0)
        body_ratio = c_body / c_range
        upper_shadow = max(c_high - max(c_open, c_close), 0.0)
        upper_shadow_ratio = upper_shadow / c_range

        is_day_yang = (day_open_p > 0 and tick_close >= day_open_p)
        if day_val_eok < 3.0 and c_body <= 0:
            score_shape = 0.0
        elif is_day_yang and tick_close >= c_open and upper_shadow_ratio <= 0.25 and body_ratio >= 0.40:
            score_shape = 20.0
        elif is_day_yang and tick_close >= c_open:
            score_shape = 16.0
        elif is_day_yang:
            score_shape = 12.0
        elif tick_close >= c_open and upper_shadow_ratio <= 0.40:
            score_shape = 10.0
        elif tick_close < c_open:
            score_shape = 0.0
        else:
            score_shape = 5.0

        # 3. 기준선(M선) 및 실시간 3일선(M/3) 안착 이격도 (20점 만점 — NaN 안전 처리)
        raw_gijun = last_60m.get('theme_gijun', np.nan)
        raw_gate = last_60m.get('theme_gate', np.nan)
        if pd.notna(raw_gijun) and float(raw_gijun) > 0:
            gijun_val = float(raw_gijun)
        elif pd.notna(raw_gate) and float(raw_gate) > 0:
            gijun_val = float(raw_gate)
        else:
            gijun_val = tick_close

        gijun_diff_pct = ((tick_close - gijun_val) / gijun_val * 100.0) if gijun_val > 0 else 0.0

        if 0.3 <= gijun_diff_pct <= 3.5:
            score_anchor = 20.0
        elif 3.5 < gijun_diff_pct <= 7.0:
            score_anchor = 15.0
        elif 0.0 <= gijun_diff_pct < 0.3:
            score_anchor = 10.0
        elif gijun_diff_pct > 12.0:
            score_anchor = 4.0
        else:
            score_anchor = 6.0

        if pre_day_close is not None and pre_day_close > 0:
            pre_close = float(pre_day_close)
        elif df_daily is not None and len(df_daily) >= 2 and last_daily_dt == today_str:
            pre_close = float(df_daily['close'].iloc[-2])
        else:
            pre_close = float(last_daily.get('close', tick_close))
        day_ret_pct = ((tick_close - pre_close) / pre_close * 100.0) if pre_close > 0 else 0.0

        df_wave_intraday = df_120t if df_120t is not None else (df_3m if df_3m is not None else df_10m)
        score_120t = 0.0
        if df_wave_intraday is not None and len(df_wave_intraday) >= 40 and 'close' in df_wave_intraday:
            df_120t_calc = calculate_120t_tema_indicators(df_wave_intraday, current_price=tick_close)
            if not df_120t_calc.empty:
                last_120 = df_120t_calc.iloc[-1]
                is_sma5_40_bull = bool(last_120.get('is_sma5_40_bull', False))
                is_sma5_60_bull = bool(last_120.get('is_sma5_60_bull', False))
                is_sma_bull = bool(last_120.get('is_sma40_60_bull', False))
                bs_gc5_40 = float(last_120.get('bars_since_sma5_40_gc', np.nan))
                gc5_40_1bar = (not np.isnan(bs_gc5_40) and 0 <= bs_gc5_40 <= 1)
                sma5_40_gc_recent = bool(df_120t_calc['is_sma5_40_gc'].tail(6).any()) if 'is_sma5_40_gc' in df_120t_calc else False
                sma_gc_recent = bool(df_120t_calc['is_sma40_60_gc'].tail(8).any()) if 'is_sma40_60_gc' in df_120t_calc else False

                if (gc5_40_1bar or sma5_40_gc_recent or is_sma5_40_bull) and is_sma5_60_bull:
                    score_120t = 10.0  # 120틱 단순 5>40 & 5>60 정배열
                elif gc5_40_1bar or sma5_40_gc_recent:
                    score_120t = 9.0   # 120틱 단순 5-40 골든크로스 신규 진입 구간
                elif is_sma5_40_bull:
                    score_120t = 6.0   # 120틱 단순 5>40 정배열 유지
                elif sma_gc_recent or is_sma_bull:
                    score_120t = 4.0   # SMA 40-60 정배열 기반

        # 5. 시초가 모멘텀 락온 점수 (+1.5% 돌파, 10점 만점 - NXT 프리마켓 08:03~08:30 & KRX 정규장 09:00~09:30)
        score_morning = 0.0
        if c_open > 0:
            change_from_open = ((tick_close - c_open) / c_open) * 100.0
            cur_t = datetime.now().time()
            is_early_session = (dtime(8, 3, 0) <= cur_t <= dtime(8, 30, 0)) or (dtime(9, 0, 0) <= cur_t <= dtime(9, 30, 0))
            if is_early_session and change_from_open >= 1.5:
                score_morning = 10.0
            elif change_from_open >= 1.0:
                score_morning = 5.0

        # 6. 🌐 글로벌 선행 지수 주도 섹터(필반지수 강세 시 반도체주 등) 연동 가산점 (+0.0 ~ +5.0점)
        score_global = 0.0
        try:
            score_global = get_stock_theme_alignment_score(code)
        except Exception:
            score_global = 0.0

        # 7. 👑 [대표님 비기]: 실시간 순간체결대금 3,000만 원 이상 매수 연속 체결(세력 입성) 가산점 (+0.0 ~ +15.0점)
        score_big_streak = 0.0
        streak_info = self.big_order_tracker.get_info(code)
        b_streak = streak_info.get('streak', 0)
        if b_streak >= 3:
            score_big_streak = 15.0  # 3연타 이상 슈퍼 세력 시장가 쓸어담기 폭발! (최고 가산점)
        elif b_streak == 2:
            score_big_streak = 10.0  # 2연타 세력 매집 확인
        elif b_streak == 1:
            score_big_streak = 5.0   # 1회 3천만+ 체결 포착

        # 8. 💧 실제 거래대금 규모 유동성 가산점 (+0.0 ~ +10.0점)
        if day_val_eok >= 300.0:
            score_liquidity = 10.0
        elif day_val_eok >= 100.0:
            score_liquidity = 7.0
        elif day_val_eok >= 30.0:
            score_liquidity = 4.0
        elif day_val_eok >= 10.0:
            score_liquidity = 2.0
        else:
            score_liquidity = 0.0

        total_score = min(
            100.0,
            score_speed + score_shape + score_anchor + score_120t
            + score_morning + score_global + score_big_streak + score_liquidity
        )
        details = {
            'total_score': total_score,
            'vol_ratio_prev': vol_ratio_prev,
            'target_vol': target_vol,
            'target_name': target_name,
            'attainment_ratio': attainment_ratio,
            'score_speed': score_speed,
            'gijun_diff_pct': gijun_diff_pct,
            'score_anchor': score_anchor,
            'body_ratio': body_ratio,
            'upper_shadow_ratio': upper_shadow_ratio,
            'score_shape': score_shape,
            'score_120t': score_120t,
            'score_10m': score_120t,
            'score_3m': score_120t,
            'score_morning': score_morning,
            'score_global': score_global,
            'score_big_streak': score_big_streak,
            'score_liquidity': score_liquidity,
            'big_order_streak': b_streak,
            'big_order_last_amt': streak_info.get('last_amt', 0.0),
            'score_candle': score_shape + score_anchor,
            'day_ret_pct': day_ret_pct,
            'day_val_eok': day_val_eok,
            'prev_day_val_eok': prev_day_val_eok,
            't120_today_bars': t120_today_bars,
            'm10_today_bars': liq.get('m10_today_bars', t120_today_bars),
            'm3_today_bars': liq.get('m3_today_bars', t120_today_bars),
        }
        return total_score, details

    def run_cycle(self):
        """1회 감시 사이클"""
        # 🌅 날짜 변경 시 전일 조건검색 및 쿨다운/앵커 자동 초기화
        today_date = datetime.now().date()
        if today_date != self.current_trading_date:
            with self.condition_lock:
                old_cond_count = len(self.condition_picks)
                self.condition_picks.clear()
            self.sold_cooldowns.clear()
            self.completed_trades_today = 0
            self.m5_anchors.clear()
            if hasattr(self, 'top10_locked'):
                self.top10_locked = False
            if hasattr(self, 'locked_top10_picks'):
                self.locked_top10_picks.clear()
            if hasattr(self, 'locked_top10_codes'):
                self.locked_top10_codes.clear()
            logger.info(
                f"🌅 [영업일 변경 감지] {self.current_trading_date} ➔ {today_date} | "
                f"전일 조건검색({old_cond_count}개), Top10 락온, 순환 카운트 초기화 완료 ➔ 09:30까지 신규 조건검색 수집 시작!"
            )
            self.current_trading_date = today_date

        self.refresh_holdings()

        if not self.strategies:
            logger.info("ℹ️ 현재 등록된 감시 종목이 없습니다.")
            return

        is_active, session_name, exchange_hint = get_market_session()
        cur_t = datetime.now().time()
        is_buy_cutoff = (cur_t >= dtime(14, 30, 0))

        cutoff_tag = " | 🕒14:30이후 매수종료(보유매도 집중)" if is_buy_cutoff else ""
        market_status_str = f"🟢 {session_name}{cutoff_tag}" if is_active else f"🔴 {session_name}{cutoff_tag}"
        logger.info(f"⏱️ 감시 루프 실행 중... [현재 시장 상태: {market_status_str}]")

        # 🌐 [글로벌 선행지수 & 증권플러스 코스피/코스닥 야간선물 2612 기상도 실시간 브리핑]
        if cur_t < dtime(9, 30, 0):
            try:
                g_radar = get_overnight_market_radar()
                sox_pct = g_radar.get('sox_pct', 0.0)
                ixic_pct = g_radar.get('ixic_pct', 0.0)
                kp_pct = g_radar.get('kospi_fut', {}).get('flu_pct', 0.0)
                kq_pct = g_radar.get('kosdaq_fut', {}).get('flu_pct', 0.0)
                lead_th = ", ".join(g_radar.get('lead_themes', [])) or "전체"
                logger.info(
                    f"🌐 [증권플러스 연동 2612 야간선물 & 글로벌 기상도] "
                    f"코스피200(2612): {kp_pct:+.2f}% | 코스닥150(2612): {kq_pct:+.2f}% | "
                    f"필반(SOX): {sox_pct:+.2f}% | 나스닥: {ixic_pct:+.2f}% | 주도섹터: [{lead_th}]"
                )
            except Exception as e:
                logger.debug(f"글로벌 기상도 브리핑 예외: {e}")

        # 🌡️ [코스피200선물 & 코스닥150선물 실시간 1:1 시장 온도계 점검]
        futures_regimes = self.get_futures_market_regime()
        kp_fut = futures_regimes.get('KOSPI', {})
        kq_fut = futures_regimes.get('KOSDAQ', {})
        logger.info(
            f"🌡️ [선물지수 1:1 매칭 온도계] "
            f"코스피200선물: {kp_fut.get('badge', '🟢정상')} (시가대비 {kp_fut.get('intraday_chg_pct', 0.0):+.2f}%, 고점대비 -{kp_fut.get('drawdown_from_high_pct', 0.0):.2f}%p) | "
            f"코스닥150선물: {kq_fut.get('badge', '🟢정상')} (시가대비 {kq_fut.get('intraday_chg_pct', 0.0):+.2f}%, 고점대비 -{kq_fut.get('drawdown_from_high_pct', 0.0):.2f}%p)"
        )
        if kp_fut.get('regime') == "CRASH_LOCK":
            logger.warning(f"   🚨 [코스피 서킷브레이커 알림] {kp_fut.get('reason')} (지수 참고 모니터링 — 개별 주도주는 시가지지 기반 독립 매매)")
        if kq_fut.get('regime') == "CRASH_LOCK":
            logger.warning(f"   🚨 [코스닥 서킷브레이커 알림] {kq_fut.get('reason')} (지수 참고 모니터링 — 개별 주도주는 시가지지 기반 독립 매매)")

        active_code = self.get_active_stock_code()
        if active_code:
            act_name = self.get_stock_name(active_code)
            act_state = self.strategies[active_code].position.state.value
            logger.info(
                f"🔒 [1종목 순환매매 슬롯 1/1 점유] 봇 운용 종목: [{act_name}({active_code})] 상태: {act_state} "
                f"➔ 120틱 단순 5-60 GC(2차추가) · 단순 5-60 데드크로스 시 전량 매도 고속 감시 중"
            )
        else:
            lock_note = "09:30 Top10 확정" if getattr(self, 'top10_locked', False) else "09:30까지 4·3·2중복 Top10 엄선 중"
            logger.info(
                f"🔓 [1종목 순환매매 슬롯 0/1 비어있음] 봇 운용 종목 없음 ({lock_note}) "
                "➔ Top10 중 120틱 단순 5-40 골든크로스 발생 시 1위 종목 1차 매수 대기"
            )

        buy_candidates = []
        now_cycle_ts = time.time()
        last_idle_scan = float(getattr(self, '_last_idle_scan_ts', 0.0) or 0.0)
        skip_idle_for_fast_exit = bool(active_code and (now_cycle_ts - last_idle_scan) < 12.0)
        if not active_code or not skip_idle_for_fast_exit:
            self._last_idle_scan_ts = now_cycle_ts

        for code in list(self.strategies.keys()):
            name = self.get_stock_name(code)
            strat = self.strategies.get(code)
            if not strat or strat.position.state == StrategyState.TERMINATED:
                continue

            # 🕒 [14:30 이후 신규 매수 종료]: 미보유(IDLE) 종목 평가 스킵 ➔ 보유 종목 매도에만 API 집중
            if is_buy_cutoff and strat.position.state == StrategyState.IDLE:
                continue

            # ⚡ [보유 종목 초고속 120틱 단순 5-60 DC 매도 감시]: 보유 중에는 비활성 후보 REST 스캔을 12초마다 분산
            if skip_idle_for_fast_exit and code != active_code and strat.position.state == StrategyState.IDLE:
                continue

            # 💡 쿨다운 확인: 매도 직후 단기 쿨다운(20초) 중인지 체크 (종목을 버리지 않고 계속 들여다봄)
            now_ts = time.time()
            cooldown_rem = max(0.0, self.sold_cooldowns.get(code, 0.0) - now_ts)

            # ⏱️ 키움 API 초당 5회(TR 제한) 방어 및 네트워크 부하 분산 딜레이
            time.sleep(0.15)

            try:
                df_60m = self.get_60m_candles(code)
                df_daily = self.get_daily_candles(code)

                if df_60m is None or df_60m.empty or df_daily is None or df_daily.empty:
                    logger.warning(f"⚠️ [{name}({code})] 실전 차트 데이터(60분봉/일봉) 수신 대기 중 ➔ 이번 사이클 평가 스킵")
                    continue

                # ⚡ [120틱 TR 선조회 및 실시간 현재가 시각 동기화]:
                # REST 120틱 조회시각보다 더 최신인 0B 패킷만 덧씌워 구버전 0B가 최신 120틱 종가를 덮어쓰는 현상 원천 차단
                h_info = self.active_holdings.get(code, {})
                acc_price = float(h_info.get('current_price', 0.0) or 0.0)
                is_cond_pick = bool(h_info.get('is_condition_pick', False)) or (code in self.condition_picks)
                need_120t = (
                    strat.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION]
                    or is_cond_pick
                )
                df_120t = self.get_120t_candles(code) if need_120t else pd.DataFrame()
                bar_fetch_ts = 0.0
                if need_120t and self.is_real and self.api:
                    if hasattr(self.api, 'get_last_tick_fetch_ts'):
                        bar_fetch_ts = float(self.api.get_last_tick_fetch_ts(code) or 0.0)
                    elif hasattr(self.api, 'get_last_minute_fetch_ts'):
                        bar_fetch_ts = float(self.api.get_last_minute_fetch_ts(code) or 0.0)

                candle_120t_close = (
                    float(df_120t.iloc[-1]['close'])
                    if (df_120t is not None and not df_120t.empty and 'close' in df_120t.columns)
                    else 0.0
                )
                candle_close = float(df_60m.iloc[-1]['close']) if not df_60m.empty else 0.0
                ws_tick = self._live_tick_prices.get(code)
                ws_ts = float(ws_tick.get('ts', 0.0) or 0.0) if ws_tick else 0.0
                is_ws_fresh = bool(
                    ws_tick
                    and (time.time() - ws_ts) <= 15.0
                    and float(ws_tick.get('price', 0.0) or 0.0) > 0
                    and (bar_fetch_ts <= 0.0 or ws_ts >= bar_fetch_ts)
                )
                if is_ws_fresh:
                    tick_close = float(ws_tick['price'])
                elif candle_120t_close > 0:
                    tick_close = candle_120t_close
                elif exchange_hint == "NXT" and candle_close > 0:
                    tick_close = candle_close
                elif acc_price > 0:
                    tick_close = acc_price
                elif candle_close > 0:
                    tick_close = candle_close
                else:
                    tick_close = acc_price

                # 💡 [실시간 60분봉 캔들 합성]: 장중 진행 중인 마지막 60분봉에 실시간 현재가 즉시 반영
                # ➔ 60분이 끝나기를 기다릴 필요 없이 실시간 기준선 변곡 및 TEMA 지표 즉각 연산
                if df_60m is not None and not df_60m.empty and tick_close > 0:
                    df_60m = df_60m.copy()
                    c_col = df_60m.columns.get_loc('close')
                    h_col = df_60m.columns.get_loc('high')
                    l_col = df_60m.columns.get_loc('low')
                    df_60m.iat[-1, c_col] = tick_close
                    if tick_close > float(df_60m.iat[-1, h_col]):
                        df_60m.iat[-1, h_col] = tick_close
                    if tick_close < float(df_60m.iat[-1, l_col]):
                        df_60m.iat[-1, l_col] = tick_close

                df_60m_calc = calculate_all_60m_indicators(
                    df_60m,
                    p1=DEFAULT_CONFIG.TEMA_FAST,
                    p2=DEFAULT_CONFIG.TEMA_SLOW,
                    p_slow=DEFAULT_CONFIG.SMA_SLOW
                )
                df_daily_calc = calculate_daily_tema_deadcross(
                    df_daily,
                    p1=DEFAULT_CONFIG.TEMA_FAST,
                    p2=DEFAULT_CONFIG.TEMA_SLOW
                )

                last_60m = df_60m_calc.iloc[-1]
                last_daily = df_daily_calc.iloc[-1]

                daily_dead_cross = bool(last_daily.get('daily_dead_cross', False)) if pd.notna(last_daily.get('daily_dead_cross')) else False
                daily_bull = bool(last_daily.get('daily_trend_bull', True)) if pd.notna(last_daily.get('daily_trend_bull')) else True
                close_val = last_60m['close']

                # M/3 수식선 계산: M = 종가 + nPreDayClose(1) + nPreDayClose(2); 수식선 = M / 3.0
                day3_m_line, m_val, pred1, pred2 = calculate_day3_m_line(df_daily, tick_close)
                is_daily_3_5_ok, daily_3_5_label = check_daily_ma3_5_eligible(df_daily, tick_close)

                gate_val = last_60m.get('theme_gate', 0.0)
                high_val = last_60m.get('theme_gate_high', 0.0)
                gijun_val = last_60m.get('theme_gijun', 0.0)
                sma5_val = last_60m.get('sma5', 0.0)
                sma20_val = last_60m.get('sma20', 0.0)
                sma60_val = last_60m.get('sma60', 0.0)

                # 🌡️ [종목 소속 시장(KOSPI vs KOSDAQ) 1:1 선물지수 매칭 & 금일 지수 대비 상대강도(RS Alpha) 산출]
                stock_market = self.get_stock_market_type(code)
                matched_fut = futures_regimes.get(stock_market, {})
                fut_regime = str(matched_fut.get('regime', 'NORMAL_BULL'))
                fut_label = str(matched_fut.get('label', '코스피200선물' if stock_market == 'KOSPI' else '코스닥150선물'))
                fut_badge = str(matched_fut.get('badge', '🟢정상'))
                fut_flu_rt = float(matched_fut.get('flu_rt', 0.0) or 0.0)
                fut_intraday_chg = float(matched_fut.get('intraday_chg_pct', 0.0) or 0.0)

                day_ret_pct = ((tick_close - pred1) / pred1 * 100.0) if pred1 > 0 else 0.0
                day_open = float(last_daily.get('open', last_60m.get('open', tick_close)) or tick_close)
                stock_intraday_chg = ((tick_close - day_open) / day_open * 100.0) if day_open > 0 else 0.0
                day_alpha = day_ret_pct - fut_flu_rt
                intraday_alpha = stock_intraday_chg - fut_intraday_chg

                # 🛡️ evaluate_bar 호출 전 포지션/예수금 원자적 스냅샷 보존
                # (장외/준비시간 상태 변이 방지 및 매도/슬롯차단/주문실패 시 완벽 복원용)
                prev_pos = copy.deepcopy(strat.position)
                prev_cash = strat.cash

                now_t = datetime.now().time()
                is_opening_whipsaw_window = (
                    (dtime(8, 0, 0) <= now_t < dtime(8, 0, 15) and exchange_hint == "NXT")
                    or (dtime(9, 0, 0) <= now_t < dtime(9, 0, 15) and exchange_hint == "KRX")
                )
                is_replacement_mode = (self.completed_trades_today > 0)
                allow_new_buys = (not is_buy_cutoff)
                cur_qty = h_info.get('qty', 0)

                # 🎯 [첫 5분봉 앵커 산출]
                anchor_5m = self.get_5m_anchor(code, df_60m, df_daily, tick_close)
                open_5m = float(anchor_5m.get('open', 0.0) or 0.0)
                low_5m = float(anchor_5m.get('low', 0.0) or 0.0)
                high_5m = float(anchor_5m.get('high', 0.0) or 0.0)

                # 장 운영 시간(또는 DRY-RUN 테스트 모드)에만 전략 상태 전이 평가 실행 (당일 강제청산 없음 — 매도 신호는 상시 평가)
                if is_active or self.dry_run:
                    order = strat.evaluate_bar(
                        last_60m, 
                        daily_dead_cross=daily_dead_cross, 
                        daily_bull=daily_bull,
                        df_daily=df_daily,
                        day3_m_line=day3_m_line,
                        current_price=tick_close,
                        df_120t=df_120t,
                        is_condition_pick=is_cond_pick,
                        day_alpha=day_alpha,
                        open_5m=open_5m,
                        low_5m=low_5m,
                        high_5m=high_5m,
                        day_open=day_open,
                        day_ret_pct=day_ret_pct,
                        is_daily_3_5_eligible=is_daily_3_5_ok,
                        daily_3_5_label=daily_3_5_label,
                        is_replacement_mode=is_replacement_mode,
                        allow_new_buys=allow_new_buys
                    )
                else:
                    order = None

                # 60분봉 정배열/지지 상태 가시화
                if sma5_val > sma20_val > sma60_val:
                    align_str = "🟢완전정배열(5>20>60)"
                elif close_val >= sma20_val * 0.995:
                    align_str = "🟡20선상단지지"
                else:
                    align_str = "🔴역배열/매물저항"

                # 60분봉 기준선 변곡선 상태 실시간 모니터링 가시화
                if gijun_val > 0:
                    gijun_diff_pct = ((tick_close - gijun_val) / gijun_val) * 100.0
                    if tick_close >= gijun_val:
                        gijun_status = f"🟢변곡선돌파(+{gijun_diff_pct:.2f}%)"
                    else:
                        gijun_status = f"🚨변곡선미달매도({gijun_diff_pct:.2f}%)"
                    gijun_str = f"기준선(M): {gijun_val:,.0f} [{gijun_status}]"
                else:
                    gijun_str = f"기준선(M): {gijun_val:,.0f} [산출대기]"

                # M/3 수식선 상태 실시간 모니터링 가시화
                if day3_m_line > 0:
                    m3_diff_pct = ((tick_close - day3_m_line) / day3_m_line) * 100.0
                    if tick_close >= day3_m_line:
                        m3_status = f"🟢M/3선지지({m3_diff_pct:+.2f}%)"
                    else:
                        m3_status = f"🚨M/3선이탈매도({m3_diff_pct:+.2f}%)"
                    m3_str = f"M/3선: {day3_m_line:,.0f} [{m3_status}]"
                else:
                    m3_str = "M/3선: 산출대기"

                # 무위험 본절 락인 및 보유 수익률 가시화 (매수 확정 전 후보 및 매도 직후에도 직전 상태가 정확히 표시되도록 스냅샷 참조)
                ref_pos = prev_pos if (order and order.action in ["BUY_1", "TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]) else strat.position
                bep_tag = " [🔒본절락]" if ref_pos.bep_locked else ""
                profit_tag = ""
                if ref_pos.avg_price > 0 and ref_pos.total_qty > 0:
                    cur_pnl = ((tick_close - ref_pos.avg_price) / ref_pos.avg_price) * 100.0
                    profit_tag = f" [수익률: {cur_pnl:+.2f}%(최고 +{ref_pos.max_profit_pct:.2f}%)]"

                if is_cond_pick:
                    cond_overlap_now = self.get_condition_overlap(code)
                    star = "🔥" if cond_overlap_now >= 3 else "🔔"
                    with self.condition_lock:
                        p_ref = self.condition_picks.get(code)
                        c_met = self._compute_cond_pick_metrics(p_ref) if isinstance(p_ref, dict) else None
                    if c_met:
                        source_badge = (
                            f"{star}[확정중복 {cond_overlap_now}/{self.condition_total}"
                            f"·활성{c_met['active_overlap']}·체류{c_met['total_stay_sec']:.0f}s·들락{c_met['churn_count']}] "
                        )
                    else:
                        source_badge = f"{star}[조건중복 {cond_overlap_now}/{self.condition_total}] "
                else:
                    source_badge = ""
                rs_status = f"🔥지수초과({day_alpha:+.2f}%p)"
                mkt_tag = f"[{stock_market}·{fut_badge}·{rs_status}]"
                if order and order.action == "BUY_1":
                    state_display = "IDLE➔BUY_1후보"
                elif order and order.action == "BUY_2":
                    state_display = "FIRST_BUY➔BUY_2"
                elif ref_pos.state == StrategyState.IDLE and cooldown_rem > 0:
                    state_display = f"IDLE(쿨다운 {cooldown_rem:.0f}초)"
                else:
                    state_display = ref_pos.state.value

                qual_str = f"교체가능(<=20%)" if is_replacement_mode else daily_3_5_label
                gate_120t_str = "산출대기"
                if df_120t is not None and not df_120t.empty and len(df_120t) >= 40 and 'close' in df_120t:
                    try:
                        df120_view = calculate_120t_tema_indicators(df_120t, current_price=tick_close)
                        if not df120_view.empty:
                            l120 = df120_view.iloc[-1]
                            g120 = float(l120.get('theme_gate', np.nan))
                            s5_v = float(l120.get('sma5', np.nan))
                            s40_v = float(l120.get('sma40', np.nan))
                            s60_v = float(l120.get('sma60', np.nan))
                            bull5_40 = bool(l120.get('is_sma5_40_bull', False))
                            bull5_60 = bool(l120.get('is_sma5_60_bull', False))
                            bs_5_40 = float(l120.get('bars_since_sma5_40_gc', np.nan))
                            bs_5_60 = float(l120.get('bars_since_sma5_60_gc', np.nan))
                            gc5_40_badge = f"[5-40GC {int(bs_5_40)}봉]" if (bull5_40 and not np.isnan(bs_5_40)) else ""
                            if not np.isnan(bs_5_60) and bs_5_60 <= 1:
                                tag5_60 = f"5-60GC[{int(bs_5_60)}봉·2차타점]"
                            elif bull5_60:
                                tag5_60 = "5>60"
                            else:
                                tag5_60 = "5<=60(2차대기)"
                            sma_tag = f"단순5>40{gc5_40_badge}·{tag5_60}" if bull5_40 else f"단순5<=40·{tag5_60}"
                            sma_nums = ""
                            if not any(np.isnan(x) for x in (s5_v, s40_v, s60_v)):
                                sma_nums = f" [5:{s5_v:,.0f}/40:{s40_v:,.0f}/60:{s60_v:,.0f}]"
                            if not np.isnan(g120) and g120 > 0:
                                g120_diff = ((tick_close - g120) / g120) * 100.0
                                gate_120t_str = f"{sma_tag} 관문 {g120:,.0f}({g120_diff:+.2f}%){sma_nums}"
                            else:
                                gate_120t_str = f"{sma_tag}{sma_nums}"
                    except Exception:
                        pass

                liq_metrics = self._compute_liquidity_metrics(
                    tick_close, df_daily=df_daily, df_60m=df_60m, df_120t=df_120t
                )
                with self.condition_lock:
                    c_entry = self.condition_picks.get(code)
                    if isinstance(c_entry, dict):
                        c_entry['day_val_eok'] = float(liq_metrics.get('today_val_eok', 0.0) or 0.0)
                liq_tag = (
                    f"거래: {liq_metrics['today_val_eok']:,.1f}억"
                    f"(전일 {liq_metrics['prev_day_val_eok']:,.1f}억·120t {liq_metrics.get('t120_today_bars', 0)}봉)"
                    if need_120t
                    else f"거래: {liq_metrics['today_val_eok']:,.1f}억(전일 {liq_metrics['prev_day_val_eok']:,.1f}억)"
                )

                logger.info(
                    f"📊 {source_badge}[{name}]{mkt_tag} 상태: {state_display}{bep_tag}{profit_tag} | 현재가: {tick_close:,.0f}({day_ret_pct:+.2f}%) | "
                    f"자격: {qual_str} | 120틱: {gate_120t_str} | 60분: {align_str} | {m3_str} | {liq_tag}"
                )

                eff_qty = cur_qty if (self.is_real and not self.dry_run) else max(
                    cur_qty, strat.position.total_qty, prev_pos.total_qty, order.qty if order else 0
                )

                if order:
                    # 1) 매도 주문(익절/손절): 봇이 직접 매수한 포지션에 한해 집행 (기존 계좌 보유 자산 100% 보호)
                    if order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]:
                        # 🛡️ 미체결 매수 주문 대기 중일 때는 사자마자 즉시 매도 원천 차단
                        if code in self.pending_buy_orders:
                            logger.info(f"   ⏳ [{name}({code})] 매수 주문 체결 확인 대기 중 ➔ 조기 매도 평가 보류 (상태 복원)")
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue
                        # 🛡️ [계좌 기존 보유 자산 절대 보호]: 봇이 직접 매수한 포지션(entry_mode != "")이 아니면 매도 신호 차단
                        active_entry_mode = strat.position.entry_mode if strat.position.entry_mode else (prev_pos.entry_mode if prev_pos else "")
                        if not active_entry_mode:
                            logger.info(f"   🛡️ [{name}({code})] 봇 매수 포지션 아님 (계좌 기존 자산) ➔ 매도 주문 발송 차단 및 자산 보존")
                            continue
                        # 🛡️ 관종 1주 종목은 매수가 실제로 체결되기 전에는 매도하지 않음
                        if eff_qty <= 1:
                            logger.info(f"   🛡️ [{name}({code})] 관종 1주 보유 종목 ➔ 매수 미완료 상태 매도 신호 무시 (1주 보존)")
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue
                        self.execute_order(code, name, order, prev_pos=prev_pos, prev_cash=prev_cash)
                    # 2) 2차 관문선 추가 매수: 14:30 이후 중단 및 1차 체결 대기 시 보류
                    elif order.action == "BUY_2":
                        if is_buy_cutoff:
                            logger.info(f"   🕒 [{name}({code})] 14:30 이후 신규·추가 매수 종료 ➔ 2차 매수 보류 및 매도 집중")
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue
                        if code in self.pending_buy_orders:
                            logger.info(f"   ⏳ [{name}({code})] 1차 매수 체결 확인 대기 중 ➔ 2차 매수 보류 (상태 복원)")
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue
                        self.execute_order(code, name, order, prev_pos=prev_pos, prev_cash=prev_cash)
                    # 3) 신규 1차 매수: 14:30 이후 중단 / 쿨다운 / 시초 휩소 방어 / 조건검색 게이트 후 우선순위 수집
                    elif order.action == "BUY_1":
                        if is_buy_cutoff:
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue
                        if cooldown_rem > 0:
                            logger.info(
                                f"   ⏳ [매도 후 재매수 쿨다운 대기] [{name}({code})] 잔여 {cooldown_rem:.0f}초 "
                                f"➔ 체결 안정화 후 즉시 재매수/순환매매 평가 (상태 보존)"
                            )
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue

                        if is_opening_whipsaw_window and not self.dry_run:
                            whipsaw_label = "08:00~08:00:15 프리마켓 시초 15초 호가 안정화" if exchange_hint == "NXT" else "09:00~09:00:15 정규장 시초 15초 호가 안정화"
                            resume_time_str = "08:00:15" if exchange_hint == "NXT" else "09:00:15"
                            logger.info(
                                f"   🛡️ [{whipsaw_label}] [{name}({code})] 시초 동시호가 체결 안정화 대기 중 "
                                f"➔ {resume_time_str} 이후 양봉·지지 유지 확인 시 즉시 진입 (상태 안전 복원)"
                            )
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue

                        # 🔔 [실시간 조건검색 전용 게이트]: 조건검색 모드 가동 시 조건검색식(Traiding/traiding1/Traiding1) 수신 종목만 신규 매수 허용
                        # (1주 계좌 관종 마커나 정적 스캔 종목이 조건식 대장주보다 먼저 슬롯(1/1)을 가로채는 현상 원천 차단!)
                        require_cond_pick = bool(self.condition_name and self.condition_name.strip() and self.enable_ws)
                        if require_cond_pick and not is_cond_pick and strat.position.trade_count_today == 0:
                            logger.info(
                                f"   🚫 [조건검색식 미수신 종목 매수 차단] [{name}({code})] 타점 충족이나 "
                                f"실시간 조건검색({self.condition_name}) 미포착 종목 ➔ 조건검색 대장주 전용 원칙에 따라 매수 보류"
                            )
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue

                        # 🔥 [09:30 Top10 확정 & 조건식 중복(4·3·2순) 게이트]
                        if getattr(self, 'top10_locked', False) and getattr(self, 'locked_top10_codes', None):
                            if code not in self.locked_top10_codes and strat.position.trade_count_today == 0:
                                logger.info(
                                    f"   🚫 [09:30 Top10 확정 외 종목 차단] [{name}({code})] "
                                    f"➔ 09:30 엄선 Top10 외 종목 매수 보류"
                                )
                                self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                                continue

                        cond_overlap = self.get_condition_overlap(code) if is_cond_pick else 0
                        if is_cond_pick and cond_overlap < self.min_overlap:
                            logger.info(
                                f"   ⏸️ [조건 중복 부족 매수 보류] [{name}({code})] 조건식 {cond_overlap}/{self.condition_total}곳 포착 "
                                f"< 최소 {self.min_overlap}곳 (중복 4·3·2순 원칙) ➔ 진입 보류"
                            )
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue

                        # 💧 [실시간 유동성·거래대금 및 120틱 체결 활성도 게이트]: 허수·초저유동성 종목 1/1 슬롯 진입 원천 차단
                        is_liq_ok, liq_reason = self.evaluate_liquidity_activity(
                            tick_close, df_daily=df_daily, df_60m=df_60m, df_120t=df_120t, metrics=liq_metrics
                        )
                        if not is_liq_ok:
                            logger.info(
                                f"   🚫 [유동성·체결량 미달 차단] [{name}({code})] {liq_reason} "
                                f"➔ 120틱 이평 타점이 떠도 거래 미형성 종목 1/1 슬롯 점유 원천 차단"
                            )
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue

                        p_score, p_details = self.calculate_priority_score(
                            code, name, tick_close, last_60m, last_daily, df_60m, pre_day_close=pred1, df_daily=df_daily, df_120t=df_120t
                        )
                        # 🏆 [1) 금일 지수 대비 초과강도(RS Alpha) 가산점 (+4~+10점) & 실시간 조건검색 중복 포착 가산점]
                        rs_alpha_bonus = 0.0
                        if day_alpha >= 3.5 and intraday_alpha >= 1.5:
                            rs_alpha_bonus = 10.0
                        elif day_alpha >= 2.5 and intraday_alpha >= 1.0:
                            rs_alpha_bonus = 7.0
                        elif day_alpha >= 1.5 and intraday_alpha >= 0.5:
                            rs_alpha_bonus = 4.0
                        # 조건식 중복 수 가산점: 1곳 +5 / 2곳 +8 / 3곳 +12 / 4곳 +15
                        cond_bonus = {0: 0.0, 1: 5.0, 2: 8.0, 3: 12.0}.get(cond_overlap, 15.0) if is_cond_pick else 0.0

                        # 🏆 [2) 야간/장중 코스피200선물 vs 코스닥150선물 상대강도 우위 시장 가산점 (+5.0점)]:
                        other_market = "KOSDAQ" if stock_market == "KOSPI" else "KOSPI"
                        other_fut = futures_regimes.get(other_market, {})
                        my_flu = float(matched_fut.get('flu_rt', 0.0) or 0.0)
                        other_flu = float(other_fut.get('flu_rt', 0.0) or 0.0)
                        rel_bonus = 0.0
                        if (
                            my_flu >= 0.30
                            and bool(matched_fut.get('is_bull_candle', True))
                            and (my_flu - other_flu) >= 0.50
                        ):
                            rel_bonus = 5.0

                        p_score = min(100.0, p_score + rs_alpha_bonus + cond_bonus + rel_bonus)
                        p_details['rs_alpha_bonus'] = rs_alpha_bonus
                        p_details['cond_bonus'] = cond_bonus
                        p_details['cond_overlap'] = cond_overlap
                        p_details['day_alpha'] = day_alpha
                        p_details['rel_market_bonus'] = rel_bonus

                        buy_candidates.append({
                            'code': code,
                            'name': name,
                            'market': stock_market,
                            'cond_overlap': cond_overlap,
                            'is_cond_pick': is_cond_pick,
                            'fut_regime': fut_regime,
                            'fut_label': fut_label,
                            'fut_badge': fut_badge,
                            'order': order,
                            'strat': strat,
                            'prev_pos': prev_pos,
                            'prev_cash': prev_cash,
                            'priority_score': p_score,
                            'details': p_details
                        })

            except Exception as stock_err:
                logger.error(f"❌ [{name}({code})] 사이클 처리 중 오류 발생: {stock_err}", exc_info=True)

        # ─────────────────────────────────────────────────────────────
        # 동시 기준선 돌파 종목 우선순위(Priority Score) 1위 선별 및 즉시 매수 집행
        # ─────────────────────────────────────────────────────────────
        if buy_candidates:
            # 👑 [대표님 지시]: 1종목 순환매매 (로직으로 사지 않은 기존 보유종목은 100% 완전 제외!)
            # 1. 봇이 직접 매수한 활성 종목이 이미 1개 운용 중인지 확인 (기존 계좌 잔고는 슬롯 점유에서 완전 배제!)
            candidate_codes = {c['code'] for c in buy_candidates}
            current_active = self.get_active_stock_code(exclude_codes=candidate_codes)

            if current_active:
                cur_act_name = self.get_stock_name(current_active)
                cur_act_state = self.strategies[current_active].position.state.value
                for cand in buy_candidates:
                    logger.info(
                        f"   🔒 [1종목 순환매매 대기] 현재 봇 운용 종목 [{cur_act_name}] 포지션({cur_act_state}) 보유 중 ➔ "
                        f"[{cand['name']}] (점수: {cand['priority_score']:.1f}점) 전량 매도 완료 전까지 신규 매수 대기"
                    )
                    self._rollback_strategy_state(cand['strat'], cand['order'], cand['prev_pos'], cand['prev_cash'])
            else:
                # 2. 봇 운용 슬롯이 비어있음 (0/1): 전략 타점을 통과한 후보 중 [우선순위 1위 단 1종목 즉시 2주 매수 집행]
                # (장초반 거래량/점수 미성숙으로 인해 실제 매수 기회 자체를 차단하던 불필요한 45~50점 하드 커트라인 제거!)
                buy_candidates.sort(
                    key=lambda x: (
                        x.get('cond_overlap', 0),
                        x['priority_score'],
                        x['details'].get('day_val_eok', 0.0),
                    ),
                    reverse=True,
                )
                winner = buy_candidates[0]
                w_code = winner['code']
                w_name = winner['name']
                w_score = winner['priority_score']
                w_order = winner['order']
                w_strat = winner['strat']
                w_fut_label = winner.get('fut_label', '선물지수')
                w_fut_badge = winner.get('fut_badge', '🟢정상')
                w_d = winner['details']

                mode_tag = (
                    f"{w_fut_label} {w_fut_badge} "
                    f"{'순환교체(등락률<=20%) 120틱 단순 5-40 GC 1차' if self.completed_trades_today > 0 else '일봉 3-5 자격 120틱 단순 5-40 GC 1차'}"
                )

                streak_tag = f", 🔥세력3천만+: {w_d.get('big_order_streak')}연타(+{w_d.get('score_big_streak', 0.0):.0f}점)" if w_d.get('big_order_streak', 0) > 0 else ""
                logger.info(
                    f"👑 [1종목 순환매매 1위 매수 집행] [{w_name}({w_code})] [🔥조건중복 {winner.get('cond_overlap', 0)}/{self.condition_total}] "
                    f"점수 1위: {w_score:.1f}점 ({mode_tag}) ➔ {w_order.qty}주 1차 실전 매수 집행! "
                    f"[💧거래대금: {w_d.get('day_val_eok', 0.0):,.1f}억(120t {w_d.get('t120_today_bars', 0)}봉), "
                    f"⚡전일대비 거래량: {w_d.get('vol_ratio_prev', 0.0):.1f}%, "
                    f"시가지지 캔들순도: {w_d.get('score_shape', 0.0):.0f}점, "
                    f"기준선안착: {w_d.get('gijun_diff_pct', 0.0):+.2f}%, 120틱SMA: {w_d.get('score_120t', 0.0):.0f}점{streak_tag}]"
                )
                self.execute_order(
                    w_code,
                    w_name,
                    w_order,
                    prev_pos=winner['prev_pos'],
                    prev_cash=winner['prev_cash']
                )

                # 1위 종목 진입으로 슬롯(1/1) 점유 ➔ 2위 이하 탈락 후보들은 상태 안전 원복 후 대기 (매도 후 다음 순환 때 매수 가능)
                for other in buy_candidates[1:]:
                    logger.info(
                        f"   ⏸️ [{other['name']}({other['code']})] (점수: {other['priority_score']:.1f}점) - "
                        f"1위 [{w_name}] 진입으로 슬롯(1/1) 마감 ➔ 매도 후 다음 순환매매 대기"
                    )
                    self._rollback_strategy_state(other['strat'], other['order'], other['prev_pos'], other['prev_cash'])

    def start_loop(self, interval_sec: int = 5):
        """실시간 반복 감시 시작 (09:30 조건검색 Top10 엄선 및 120틱 단순 5-40 GC · 5-60 GC · 5-60 DC 정밀 감시)"""
        logger.info(
            f"🔄 실시간 조건검색({self.condition_name}) 09:30 중복 4·3·2순 Top10 엄선 & "
            f"120틱 단순 5-40 GC(1차) / 5-60 GC(2차) / 5-60 DC(매도) 감시를 시작합니다 (대기 {interval_sec}초, 보유중 2초)."
        )
        try:
            while True:
                try:
                    self.run_cycle()
                except Exception as cycle_err:
                    logger.error(f"❌ [사이클 에러] 주기 실행 중 예외 발생: {cycle_err}", exc_info=True)
                wait_sec = min(interval_sec, 2) if self.get_active_stock_code() else interval_sec
                woke_early = self.condition_wakeup_event.wait(timeout=wait_sec)
                if woke_early:
                    self.condition_wakeup_event.clear()
                    logger.info("⚡ [실시간 후보/수급 갱신] Top10 후보 등록 및 120틱 단순 5-40·5-60 타점 점검!")
        except KeyboardInterrupt:
            logger.info("🛑 사용자에 의해 감시 루프가 정상 종료되었습니다.")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="키움 실시간 조건검색 전용 1종목 집중 매매 봇")
    parser.add_argument("--once", action="store_true", help="1회 감시만 실행 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="모의 안전 모드(주문 미전송)")
    parser.add_argument("--interval", type=int, default=5, help="루프 감시 주기(초, 기본 5초·보유중 2초)")
    parser.add_argument("--condition", type=str, default="Traiding,traiding,Traiding1,trading1",
                        help="키움 실시간 조건검색식 이름 (기본값: Traiding,traiding,Traiding1,trading1)")
    parser.add_argument("--min-overlap", type=int, default=2,
                        help="신규 매수 허용 최소 조건식 중복 포착 수 (기본 2=중복 4·3·2순 Top10 엄선)")
    parser.add_argument("--min-stay-sec", type=float, default=30.0,
                        help="조건식 최소 연속 체류 인증 시간(초, 기본 30초 — 1~5초 휩소 들락날락 차단)")
    parser.add_argument("--fixed-qty", type=int, default=2,
                        help="고정 매수 수량 (기본값: 2주, 계좌 예수금 조회 TR 생략)")
    parser.add_argument("--no-ws", action="store_true", help="실시간 조건검색 웹소켓 비활성화")

    args = parser.parse_args()

    bot = SafeHoldingsThemeGateBot(
        is_real=True,
        dry_run=args.dry_run,
        condition_name=args.condition,
        enable_ws=(not args.no_ws),
        min_overlap=args.min_overlap,
        fixed_qty=args.fixed_qty,
        min_cond_stay_sec=args.min_stay_sec
    )

    if args.once:
        bot.run_cycle()
    else:
        bot.start_loop(interval_sec=args.interval)

