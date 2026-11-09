"""
trading_bot_holdings_only.py - 실전 계좌 관심/보유 종목 전용 60분봉 집중 매매 봇

[안전장치 및 운영 규칙]
1. 장운영 시간 안전장치: NXT 프리마켓(08:00~08:50) + KRX 정규장(09:00~15:30) + NXT 애프터마켓(15:40~20:00) 3대 세션 자동 연동 (세션 외 및 주말 주문 원천 차단)
2. 모의/실전 안전 모드: DRY_RUN 플래그로 실제 주문 없이 신호 검증 가능
3. 계좌 보유 1주는 관심종목(Watchlist) 마커: 초기 상태 IDLE(대기)에서 1차 매수 신호 대기
4. 1차 매수 (50%): 60분봉 테마급등관문선 하락 후 상승변곡/지지 또는 기준선 돌파 시 진입 (기존 1주 포지션 흡수)
5. 2차 매수 (50%): 60분봉 테마기준선(M선) 상향 돌파 시 추가 매수 (총 100% FULL_POSITION)
6. 매도 2대 원칙: 
   1) M = 종가 + nPreDayClose(1) + nPreDayClose(2); M/3 실시간 3일선 수식선 이탈 즉시 전량 매도
   2) 60분봉 기준선 변곡선(M선) 넘지 못할 경우 즉시 전량 매도
7. 매도 후 원칙: 재매수 없이 즉시 100% 현금화(IDLE 복귀) 및 1종목 락 해제 (다음 1순위 주도주 진입 대기)
8. 전략 종료: 일봉 테마 5-20 데드크로스 발생 시 즉시 전량 청산 및 사이클 종료
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
    from execution.indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_day3_m_line, calculate_pred_volume_ratio
    from execution.strategy import ThemeGate60mStrategy, TradeOrder, StrategyState, PositionTracker, calculate_wma
    from execution.watchlist_scanner import scan_and_save_holy_grail_watchlist, load_saved_watchlist
except ImportError:
    from indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_day3_m_line, calculate_pred_volume_ratio
    from strategy import ThemeGate60mStrategy, TradeOrder, StrategyState, PositionTracker, calculate_wma
    from watchlist_scanner import scan_and_save_holy_grail_watchlist, load_saved_watchlist

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

# 로깅
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
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


class SafeHoldingsThemeGateBot:
    def __init__(
        self,
        is_real: bool = True,
        dry_run: bool = False,
        holdings_state: str = "idle",
        auto_scan: bool = True,
        condition_name: str = "Traiding,traiding,Traiding1,trading1",
        enable_ws: bool = True
    ):
        """
        is_real: 키움 실전 API 연동 여부
        dry_run: True이면 신호는 계산하되 실제 주문 전송만 건너뜀 (안전 모의 테스트용)
        holdings_state: 'idle' (기본값: 관심종목/1주 수동 매수 종목을 IDLE 상태로 등록, 1차 50% 매수 대기)
                        'first_buy_done' (1차 매수 보유 상태, 60분봉 기준선 돌파 2차 매수 대기)
                        'full_position' (풀포지션 완료 상태, M/3선 및 기준선 변곡선 매도 대기)
        auto_scan: 지수 조정/폭락 시에도 현재 성배 로직(60분 정배열/20선지지 + 관문/기준선 타점 + M/3선 지지)에
                   가장 부합하는 주도주를 자동 발굴하여 관심종목에 추가 및 매매 수행
        condition_name: 키움 실시간 조건검색식 이름 (기본값: 'Traiding,traiding,Traiding1')
        enable_ws: 키움 실시간 조건검색 웹소켓 수신 데몬 활성화 여부
        """
        self.dry_run = dry_run
        self.auto_scan = auto_scan
        self.condition_name = condition_name
        self.enable_ws = enable_ws and HAS_WS_CLIENT
        if is_real and not HAS_REAL_API:
            logger.error("❌ [치명적 오류] 실전 계좌 전용 봇(holdings_bot.bat)에서 키움 실전 API(RealAPIAdapter) 로드에 실패했습니다.")
            logger.error("   가상/시뮬레이션 모드로 임의 전환하지 않고 안전 종료합니다. (.env 및 키움 실전 API 설정을 확인하세요)")
            sys.exit(1)

        self.is_real = is_real and HAS_REAL_API
        self.holdings_state = holdings_state

        logger.info("==================================================")
        if self.dry_run:
            logger.info(" 🛡️ [실전 계좌 연동 + 모의 안전 모드(DRY-RUN)] 실계좌 잔고/차트 감시만 수행 (실제 주문 미전송)")
        elif self.is_real:
            logger.info(f" 🚀 [키움 실전 계좌 거래 모드] 실계좌 잔고 + 실시간 조건검색({self.condition_name}) + 지수초과강도·120틱 매매 즉시 전송")
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
        self.ws_client = None
        self.ws_thread: Optional[threading.Thread] = None
        self.auto_watchlist_picks: dict[str, dict] = {}
        self.pending_buy_orders: dict[str, dict] = {}
        self.last_watchlist_scan_time: float = 0.0
        self.sold_today_stocks: set[str] = set()
        self.current_trading_date = datetime.now().date()
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
            '052260': '현대바이오랜드',
            '138360': '앤로보틱스',
            '263750': '펄어비스',
            '281820': '케이씨텍',
            '386380': '스카이랩스',
            '393210': '토마토시스템',
            '411080': '샌즈랩',
            '425040': '티이엠씨',
            '476830': '알지노믹스',
        }

        if self.is_real and self.enable_ws:
            self._start_condition_ws_daemon()

    def _on_condition_insert(self, code: str):
        """키움 실시간 조건검색(Traiding, traiding, Traiding1) 종목 편입 콜백"""
        clean_code = str(code).replace("_AL", "").replace("_NX", "").lstrip("A").strip().zfill(6)
        if not clean_code.isdigit() or len(clean_code) != 6:
            return
        if clean_code in self.sold_today_stocks:
            return

        with self.condition_lock:
            is_new = clean_code not in self.condition_picks
            self.condition_picks[clean_code] = {
                'code': clean_code,
                'name': self.stock_name_cache.get(clean_code, ''),
                'target_tag': f'🔔실시간조건({self.condition_name})',
                'captured_at': time.time()
            }

        if is_new:
            cached_nm = self.stock_name_cache.get(clean_code, f"종목_{clean_code}")
            logger.info(
                f"🔔 [실시간 조건검색 포착] [{cached_nm}({clean_code})] (조건식: {self.condition_name}) "
                f"➔ 지수 상대강도 & 120틱 매수 타점 즉시 검증 깨우기!"
            )
            self.condition_wakeup_event.set()

    def _on_condition_delete(self, code: str):
        """키움 실시간 조건검색 종목 이탈 콜백 (보유 중이거나 파동 살아있는 종목 보호를 위해 즉시 삭제하지 않고 메인 루프에서 상대강도로 정밀 관리)"""
        clean_code = str(code).replace("_AL", "").replace("_NX", "").lstrip("A").strip().zfill(6)
        logger.debug(f"🔕 [실시간 조건검색 이탈 신호] 종목코드: {clean_code} (지수 상대강도 및 120틱 추세 유지 여부로 감시 지속 판단)")

    def _start_condition_ws_daemon(self):
        """백그라운드 데몬 스레드에서 KiwoomWebSocketClient 실시간 조건검색 수신 루프 구동"""
        def _ws_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.ws_client = KiwoomWebSocketClient(
                    target_condition_name=self.condition_name,
                    on_insert=self._on_condition_insert,
                    on_delete=self._on_condition_delete
                )
                logger.info(f"📡 [실시간 조건검색 웹소켓 가동] 목표 조건식: [{self.condition_name}] 실시간 수신 대기 중...")
                loop.run_until_complete(self.ws_client.run())
            except Exception as ws_err:
                logger.error(f"❌ 실시간 조건검색 웹소켓 데몬 예외: {ws_err}")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        self.ws_thread = threading.Thread(target=_ws_worker, name="KiwoomConditionWSDaemon", daemon=True)
        self.ws_thread.start()
        # 초기 조건검색(CNSRREQ) 포착 종목이 첫 사이클부터 즉시 반영되도록 최대 2.5초 대기
        self.condition_wakeup_event.wait(timeout=2.5)
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
        if self.is_real:
            real_holdings = self.api.get_account_holdings()
            cash = self.api.get_cash_balance()
            self._check_and_cleanup_unfilled_orders(real_holdings)
        else:
            real_holdings = {
                '005930': {'qty': 1, 'buy_price': 70000, 'current_price': 71000},
                '263750': {'qty': 1, 'buy_price': 34650, 'current_price': 34650}
            }
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

        # 🔍 [성배 타점 종목 사전 등록분 즉시 로드 & 장중 30분 주기 자동 갱신]:
        # 1) 최초 기동 시 이미 사전 스캔·등록된 holy_grail_watchlist.json(최근 12시간 이내)이 있으면 0.01초 만에 즉시 장착!
        # 2) 파일이 없거나 30분(1800초) 경과 시(활성 매매 포지션이 없을 때) 실시간 재스캔 수행
        if self.auto_scan and self.is_real and self.api:
            now_ts = time.time()
            if self.last_watchlist_scan_time == 0.0:
                saved_wl = load_saved_watchlist()
                wl_path = os.path.join(CURRENT_DIR, "holy_grail_watchlist.json")
                is_recent_file = os.path.exists(wl_path) and ((now_ts - os.path.getmtime(wl_path)) < 43200.0)
                if saved_wl and is_recent_file:
                    self.auto_watchlist_picks = saved_wl
                    self.last_watchlist_scan_time = now_ts
                    logger.info(f"📂 [사전 등록 관심종목 로드 완료] holy_grail_watchlist.json에서 성배 타점 {len(saved_wl)}종목 즉시 장착!")
                else:
                    exclude_set = set(real_holdings.keys()) | self.sold_today_stocks
                    self.auto_watchlist_picks = scan_and_save_holy_grail_watchlist(
                        self.api, max_picks=12, exclude_codes=exclude_set
                    )
                    self.last_watchlist_scan_time = now_ts
            elif (now_ts - self.last_watchlist_scan_time >= 1800.0) and not self.get_active_stock_code():
                try:
                    exclude_set = set(real_holdings.keys()) | self.sold_today_stocks
                    self.auto_watchlist_picks = scan_and_save_holy_grail_watchlist(
                        self.api, max_picks=12, exclude_codes=exclude_set
                    )
                except Exception as scan_err:
                    logger.warning(f"⚠️ 성배 타점 자동 스캔 중 예외 발생 (기존 목록 유지): {scan_err}")
                self.last_watchlist_scan_time = now_ts

        # 1) 우선순위 정렬된 통합 감시 딕셔너리 구성:
        #    [1순위] 실계좌 다수 보유종목(qty > 1) -> [2순위] 🔔키움 실시간 조건검색(Traiding) 포착 종목 -> [3순위] 🌟성배타점 자동발굴 관종 -> [4순위] 실계좌 1주 관종 마커
        holdings: dict[str, dict] = {}

        # (A) 실계좌 실보유 종목 (qty > 1) 최우선 배치
        for code, h in real_holdings.items():
            if int(h.get('qty', 0)) > 1:
                holdings[code] = h

        # (B-1) 🔔 키움 실시간 조건검색(Traiding, traiding, Traiding1) 포착 종목 최우선 편입 (최신 포착순 최대 15종목)
        cond_added_count = 0
        with self.condition_lock:
            sorted_cond_picks = sorted(
                self.condition_picks.values(),
                key=lambda x: float(x.get('captured_at', 0.0)),
                reverse=True
            )[:15]
        for c_pick in sorted_cond_picks:
            code = c_pick['code']
            if code not in real_holdings and code not in self.sold_today_stocks:
                holdings[code] = {
                    'name': c_pick.get('name', ''),
                    'qty': 0,
                    'buy_price': 0.0,
                    'current_price': 0.0,
                    'is_auto_watchlist': True,
                    'is_condition_pick': True,
                    'target_tag': c_pick.get('target_tag', '🔔실시간조건(Traiding)'),
                    'fit_score': 95.0
                }
                cond_added_count += 1

        # (B-2) 🌟 성배 로직 최적합 자동 발굴 관심종목 편입 (실계좌 미보유 & 당일 미매도 종목)
        auto_added_count = 0
        for code, pick in self.auto_watchlist_picks.items():
            if code not in holdings and code not in real_holdings and code not in self.sold_today_stocks:
                holdings[code] = {
                    'name': pick.get('name', ''),
                    'qty': 0,
                    'buy_price': 0.0,
                    'current_price': float(pick.get('price', 0.0)),
                    'is_auto_watchlist': True,
                    'is_condition_pick': False,
                    'target_tag': pick.get('target_tag', '🌟성배타점관종'),
                    'fit_score': pick.get('fit_score', 0.0)
                }
                auto_added_count += 1

        # (C) 실계좌 1주 보유 관심종목 마커 배치
        for code, h in real_holdings.items():
            if code not in holdings:
                holdings[code] = h

        # (D) 지정가 주문 발송 직후 아직 잔고에 미반영된 활성 전략 종목 보호
        for code, st in self.strategies.items():
            if code not in holdings and st.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION]:
                holdings[code] = {
                    'name': self.get_stock_name(code),
                    'qty': st.position.total_qty,
                    'buy_price': st.position.avg_price,
                    'current_price': st.position.avg_price,
                    'is_auto_watchlist': True
                }

        self.active_holdings = holdings
        logger.info(
            f"💼 [계좌 잔고 & 실시간 조건검색·타점관종 갱신] 가용 예수금: {cash:,.0f}원 | "
            f"실계좌 보유: {len(real_holdings)}개 + 🔔실시간조건검색({self.condition_name}): {cond_added_count}개 + 🌟성배타점관종: {auto_added_count}개 (총 감시: {len(holdings)}개)"
        )

        # 새로운 우선순위 순서(실보유 -> 🌟성배타점관종 -> 기존 1주 관종)에 맞춰 strategies 순서도 정렬 유지
        ordered_strategies: dict[str, ThemeGate60mStrategy] = {}

        for code, h in holdings.items():
            if h.get('name'):
                self.stock_name_cache[code] = str(h['name']).strip()
            name = self.get_stock_name(code)
            account_qty = int(h.get('qty', 0))
            buy_prc = float(h.get('buy_price', 0.0))
            is_auto_wl = bool(h.get('is_auto_watchlist', False))
            target_tag = h.get('target_tag', '')
            fit_score = h.get('fit_score', 0.0)
            
            # 최초 1회만 전략 상태 등록 (이미 있으면 기존 진행 상태 유지)
            if code not in self.strategies:
                strat = ThemeGate60mStrategy(
                    initial_capital=cash,
                    gate_sl_pct=DEFAULT_CONFIG.GATE_STOP_LOSS_PCT,
                    max_reentry=0
                )
                if is_auto_wl and account_qty == 0:
                    strat.position.state = StrategyState.IDLE
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = 0
                    logger.info(
                        f"   🌟 [{name}({code})] 성배 로직 최적합 관심종목 자동 등록 (IDLE 대기 | 적합도 {fit_score}점 · {target_tag})"
                    )
                elif account_qty <= 1:
                    strat.position.state = StrategyState.IDLE
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = account_qty
                    if buy_prc > 0:
                        strat.position.avg_price = buy_prc
                    logger.info(f"   🎯 [{name}({code})] 계좌 관심종목(1주 마커) 등록 완료 (IDLE 대기 | 기존 수량: {account_qty}주 ➔ 1차/기준선 돌파 매수 시 흡수 합산)")
                elif self.holdings_state == "first_buy_done":
                    strat.position.state = StrategyState.FIRST_BUY_DONE
                    strat.position.total_qty = account_qty
                    strat.position.avg_price = buy_prc
                    strat.position.first_buy_price = buy_prc
                    strat.position.first_buy_qty = account_qty
                    strat.position.base_account_qty = 0
                    strat.position.entry_time = time.time()
                    logger.info(f"   ➔ [{name}({code})] 1차 매수 보유 상태 등록 (FIRST_BUY_DONE) | 보유: {account_qty}주 (매수가: {buy_prc:,.0f}원) ➔ M선 돌파 2차 매수 대기")
                else:
                    # 실보유 종목 (account_qty > 1) -> M/3 수식선 및 기준선 변곡선 이탈 매도 감시 (FULL_POSITION)
                    strat.position.state = StrategyState.FULL_POSITION
                    strat.position.total_qty = account_qty
                    strat.position.avg_price = buy_prc
                    strat.position.base_account_qty = 0
                    strat.position.entry_time = time.time()
                    logger.info(f"   ➔ [{name}({code})] 실보유 종목 등록 완료 (FULL_POSITION | M/3 수식선 & 기준선 변곡선 매도 감시) | 보유: {account_qty}주 | 매수가: {buy_prc:,.0f}원")
                ordered_strategies[code] = strat
            else:
                # 이미 등록된 전략 객체에도 최신 예수금 반영 (단, 모의/DRY-RUN 중 가상 차감된 예수금 보존을 위해 실전 모드에서만 덮어씀)
                existing_strat = self.strategies[code]
                if self.is_real and not self.dry_run:
                    existing_strat.cash = cash

                # 🎯 [장중 실시간 1주 수동 매수 동기화]: IDLE 상태에서 수동 1주 매수 확인 시 기본 수량 업데이트
                if existing_strat.position.state == StrategyState.IDLE and account_qty >= 1:
                    existing_strat.position.base_account_qty = account_qty
                    if buy_prc > 0:
                        existing_strat.position.avg_price = buy_prc

                # 실전 모드(not dry_run)에서 실체결 수량이 1주를 초과한 경우에만 실계좌 수량/단가 동기화
                # (DRY-RUN이나 지정가 미체결 상태에서 가상 포지션 total_qty가 덮어써지는 현상 원천 차단)
                if self.is_real and not self.dry_run and existing_strat.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION] and account_qty > 1:
                    existing_strat.position.total_qty = account_qty
                    if buy_prc > 0:
                        existing_strat.position.avg_price = buy_prc
                ordered_strategies[code] = existing_strat

        self.strategies = ordered_strategies

    def get_60m_candles(self, code: str) -> pd.DataFrame:
        """60분봉 데이터 조회 (키움 실전 60분봉 API 직접 수신, 부재 시 30분봉 리샘플링)"""
        if self.is_real and self.api:
            try:
                if hasattr(self.api, 'get_60m_candles'):
                    df_60m = self.api.get_60m_candles(code)
                    if df_60m is not None and not df_60m.empty and len(df_60m) >= 4:
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
        """일봉 데이터 조회"""
        if self.is_real and self.api:
            df_d = self.api.get_daily_candles(code)
            if df_d is not None and not df_d.empty:
                return df_d
            # 🛡️ 실전 계좌 모드에서는 API 일시 지연 시 절대 가상 샘플 데이터를 섞지 않고 빈 DataFrame 반환
            return pd.DataFrame()
        try:
            from generate_sample_data import generate_realistic_sample_data
        except ImportError:
            from execution.generate_sample_data import generate_realistic_sample_data
        _, df_d = generate_realistic_sample_data(num_days=40)
        return df_d

    def get_120t_candles(self, code: str) -> pd.DataFrame:
        """실전 120틱 데이터 조회 (WMA 20-40-60 순차돌파 및 피크 반전 감지용)"""
        if self.is_real and self.api:
            try:
                if hasattr(self.api, 'get_120t_candles'):
                    df_120t = self.api.get_120t_candles(code)
                    if df_120t is not None and not df_120t.empty and len(df_120t) >= 10:
                        return df_120t
                elif hasattr(self.api, 'real_client') and hasattr(self.api.real_client, 'get_tick_data'):
                    raw = self.api.real_client.get_tick_data(code, tick_unit="120", limit=300)
                    if raw:
                        df_raw = pd.DataFrame(raw)
                        df_raw.columns = [c.lower() for c in df_raw.columns]
                        return df_raw.iloc[::-1].reset_index(drop=True)
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

            if self.dry_run:
                if strat and strat.position.base_account_qty > 0:
                    strat.position.total_qty += strat.position.base_account_qty
                    logger.info(f"   ➕ [수량 흡수] 기존 관심용 1주({strat.position.base_account_qty}주)를 포지션에 합산 ➔ 총 {strat.position.total_qty}주 보유")
                    strat.position.base_account_qty = 0
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

            # 주문 성공 확인 후 기존 관심용 1주 포지션 흡수
            if strat and strat.position.base_account_qty > 0:
                strat.position.total_qty += strat.position.base_account_qty
                logger.info(f"   ➕ [수량 흡수] 기존 관심용 1주({strat.position.base_account_qty}주)를 포지션에 합산 ➔ 총 {strat.position.total_qty}주 보유")
                strat.position.base_account_qty = 0

        # 3. 매도 집행 (계좌 전량 100% 매도)
        elif order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]:
            self.pending_buy_orders.pop(code, None)
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

            final_sell_qty = effective_qty
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
                self.sold_today_stocks.add(code)
                return

            if exchange_hint == "NXT":
                sell_order_type = "00"  # NXT 지정가 필수
                logger.info(f"🚨 [실전 전량 매도 발송(NXT 지정가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 지정가: {sell_price:,.0f}원 | 사유: {order.reason}")
            else:
                sell_order_type = "03"  # KRX 정규장 시장가
                logger.info(f"🚨 [실전 전량 매도 발송(KRX 시장가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 기준가: {sell_price:,.0f}원 | 사유: {order.reason}")

            if self.is_real and self.api:
                order_no = self.api.place_sell_order(code, final_sell_qty, price=sell_price, order_type=sell_order_type)
                if not order_no:
                    logger.error(f"   ❌ [전량 매도 주문 실패/거부] [{name}({code})] API 응답 없음 ➔ 다음 사이클 즉시 재시도를 위해 포지션 상태를 보존합니다.")
                    self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                    return
                logger.info(f"   ✅ [전량 매도 접수 완료] 주문번호: {order_no}")

            if strat:
                # 전량 매도 완료 즉시 포지션 초기화 (IDLE 복귀, 재매수 없음)
                strat.position = PositionTracker()

            # 당일 매도 완료 종목으로 등록하여 당일 재매수 원천 차단
            self.sold_today_stocks.add(code)
            logger.info(f"   🚫 [{name}({code})] 당일 매도 완료 처리 ➔ 당일 재매수 영구 차단 목록에 등록되었습니다.")

    def get_active_stock_code(self, exclude_codes: Optional[set[str]] = None) -> str | None:
        """
        현재 활성 포지션을 보유/운용 중인 종목 코드 반환 (1종목 집중 매매 락)
        - 활성 상태: FIRST_BUY_DONE, FULL_POSITION 중 하나이거나 실보유 수량(total_qty) > 0
        - exclude_codes: 이번 사이클에 막 신규 매수 후보(buy_candidates)로 올라온 종목들을 제외하고 기존 활성 종목만 조회할 때 사용
        """
        for code, strat in self.strategies.items():
            if exclude_codes and code in exclude_codes:
                continue
            if strat.position.state in [
                StrategyState.FIRST_BUY_DONE,
                StrategyState.FULL_POSITION
            ] or strat.position.total_qty > 0:
                return code
        return None

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
        df_120t: Optional[pd.DataFrame] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        ⚡ [세션별 차등 번개 돌파 스나이핑 1위 선정 체계 - 100.0점 만점 정규화]
        1. 🥇 세션별 전일 거래량 돌파 속도 및 잠식률 (40점 만점, 최우선 엔진!)
           - 🎯 세션별 기준치: [NXT 프리마켓: 1.5%] / [KRX 정규장: 3.0%] / [NXT 애프터마켓: 1.0%]
           - 목표치 대비 달성률(attainment_ratio = vol_ratio_prev / target_vol):
             * 달성률 >= 1.5배 (정규장 4.5%+, 프리 2.25%+, 애프터 1.5%+): 40점 만점!
             * 달성률 >= 1.0배 (정규장 3.0%+, 프리 1.5%+, 애프터 1.0%+): 35점 (목표 돌파 완료)
             * 달성률 >= 0.7배: 25점
             * 달성률 >= 0.4배: 15점
             * 달성률 < 0.4배: 5점
        2. 🥈 시가 무훼손 양봉 순도 (20점 만점)
           - 당일 시가(Open)를 단 1호가도 깨지 않고 지키는 강력한 붉은 양봉
           - 시가 위 양봉 유지 (tick_close >= c_open) + 윗꼬리 25% 이하: 20점 만점
           - 양봉 유지 + 윗꼬리 40% 이하: 15점
           - 음봉 (tick_close < c_open): 0점 (시가 훼손 감점)
        3. 🥉 기준선(M선) 안착 이격도 (20점 만점)
           - 시가 갭돌파든 장중 돌파든 기준선 위 +0.3% ~ +3.5% 최적 안착: 20점 만점
           - 기준선 위 +3.5% ~ +7.0%: 15점
           - 기준선 위 0.0% ~ +0.3%: 10점
           - 기준선 대비 +12% 이상 과열: 4점 (추격 매수 방지)
        4. ⚡ 120틱 WMA 20-40-60 순차돌파 가속도 (10점 만점)
        5. 🔥 시초가 모멘텀 락온 (+1.5% 돌파, 10점 만점)
        """
        # 세션별 차등 목표 거래량 기준 설정 (프리 1.5%, 정규장 3.0%, 애프터 1.0%)
        if session_target_vol is not None and session_target_vol > 0:
            target_vol = float(session_target_vol)
            target_name = f"지정세션({target_vol:.1f}%)"
        else:
            target_vol, target_name = get_session_volume_target()

        # 1. 전일 거래량 돌파 속도 점수 (40점 만점)
        if vol_ratio_prev is None:
            curr_vol = float(last_daily.get('volume', 0.0))
            if curr_vol <= 0:
                curr_vol = float(last_60m.get('volume', 0.0))
            vol_ratio_prev, pre_day_vol = calculate_pred_volume_ratio(df_daily, curr_vol)
        else:
            pre_day_vol = 0.0

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

        # 2. 시가 무훼손 양봉 순도 점수 (20점 만점)
        c_open = float(last_60m.get('open', tick_close))
        c_high = float(last_60m.get('high', tick_close))
        c_low = float(last_60m.get('low', tick_close))
        c_close = float(last_60m.get('close', tick_close))
        c_range = max(c_high - c_low, 1.0)
        c_body = max(c_close - c_open, 0.0)
        body_ratio = c_body / c_range
        upper_shadow = max(c_high - max(c_open, c_close), 0.0)
        upper_shadow_ratio = upper_shadow / c_range

        if tick_close >= c_open and upper_shadow_ratio <= 0.25 and body_ratio >= 0.40:
            score_shape = 20.0
        elif tick_close >= c_open and upper_shadow_ratio <= 0.40:
            score_shape = 15.0
        elif tick_close < c_open:
            score_shape = 0.0
        else:
            score_shape = 8.0

        # 3. 기준선(M선) 안착 이격도 (20점 만점)
        gijun_val = float(last_60m.get('theme_gijun', 0.0))
        if gijun_val <= 0:
            gijun_val = float(last_60m.get('theme_gate', tick_close))

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

        # 참고 모니터링용 지표
        day_val = float(last_daily.get('trading_value', 0.0)) if pd.notna(last_daily.get('trading_value')) else 0.0
        if day_val <= 0:
            day_val = float(last_daily.get('close', tick_close)) * float(last_daily.get('volume', 0.0))
        day_val_eok = day_val / 100_000_000.0

        if pre_day_close is not None and pre_day_close > 0:
            pre_close = float(pre_day_close)
        else:
            pre_close = float(last_daily.get('close', tick_close))
        day_ret_pct = ((tick_close - pre_close) / pre_close * 100.0) if pre_close > 0 else 0.0

        # 4. 120틱 WMA 20-40-60 순차돌파 가속도 점수 (10점 만점 - 실시간 tick_close 주입 반영)
        score_120t = 0.0
        if df_120t is not None and len(df_120t) >= 65 and 'close' in df_120t:
            s_120t = df_120t['close'].astype(float).copy()
            if tick_close > 0:
                s_120t.iloc[-1] = tick_close
            w1 = float(s_120t.iloc[-1])
            w20 = float(calculate_wma(s_120t, 20).iloc[-1])
            w40 = float(calculate_wma(s_120t, 40).iloc[-1])
            w60 = float(calculate_wma(s_120t, 60).iloc[-1])
            if not np.isnan(w20) and not np.isnan(w40) and not np.isnan(w60):
                if w1 >= w60 * 0.998 and w1 >= w40 * 0.998 and w1 >= w20 * 0.998:
                    score_120t = 10.0
                elif w1 >= w20:
                    score_120t = 5.0

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

        total_score = score_speed + score_shape + score_anchor + score_120t + score_morning
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
            'score_morning': score_morning,
            'score_candle': score_shape + score_anchor,
            'day_ret_pct': day_ret_pct,
            'day_val_eok': day_val_eok
        }
        return total_score, details

    def run_cycle(self):
        """1회 감시 사이클"""
        # 🌅 날짜 변경 시 당일 매도 완료(No-Rebuy) 목록 자동 초기화
        today_date = datetime.now().date()
        if today_date != self.current_trading_date:
            logger.info(f"🌅 [영업일 변경 감지] {self.current_trading_date} ➔ {today_date} | 당일 매도 차단 목록({len(self.sold_today_stocks)}종목) 초기화 완료")
            self.sold_today_stocks.clear()
            self.current_trading_date = today_date

        self.refresh_holdings()

        if not self.strategies:
            logger.info("ℹ️ 현재 등록된 감시 종목이 없습니다.")
            return

        is_active, session_name, exchange_hint = get_market_session()
        market_status_str = f"🟢 {session_name}" if is_active else f"🔴 {session_name}"
        logger.info(f"⏱️ 감시 루프 실행 중... [현재 시장 상태: {market_status_str}]")

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
            logger.warning(f"   🚨 [코스피 서킷브레이커 발동] {kp_fut.get('reason')} (코스피 종목 신규매수 자동 잠금)")
        if kq_fut.get('regime') == "CRASH_LOCK":
            logger.warning(f"   🚨 [코스닥 서킷브레이커 발동] {kq_fut.get('reason')} (코스닥 종목 신규매수 자동 잠금)")

        active_code = self.get_active_stock_code()
        if active_code:
            act_name = self.get_stock_name(active_code)
            act_state = self.strategies[active_code].position.state.value
            logger.info(f"🔒 [1종목 집중 매매 락 ON] 현재 운용 종목: [{act_name}({active_code})] 상태: {act_state} (슬롯 1/1 점유) | 기타 관심종목 신규 매수 차단 대기")
        else:
            logger.info("🔓 [1종목 집중 매매 슬롯 OPEN] 현재 활성 보유 종목 없음 (슬롯 0/1 비어있음) ➔ 기준선(M선)/관문선 옥석 가리기 1위 종목 진입 대기")

        buy_candidates = []
        total_eval_count = 0
        bear_align_count = 0

        for code in list(self.strategies.keys()):
            name = self.get_stock_name(code)
            strat = self.strategies.get(code)
            if not strat or strat.position.state == StrategyState.TERMINATED:
                continue

            # 🚫 당일 매도 완료 종목: 신규 매수 감시 원천 제외 (No-Rebuy 원칙)
            if code in self.sold_today_stocks and strat.position.state == StrategyState.IDLE:
                continue

            # ⏱️ 키움 API 초당 5회(TR 제한) 방어 및 네트워크 부하 분산 딜레이
            time.sleep(0.15)

            try:
                df_60m = self.get_60m_candles(code)
                df_daily = self.get_daily_candles(code)

                if df_60m is None or df_60m.empty or df_daily is None or df_daily.empty:
                    logger.warning(f"⚠️ [{name}({code})] 실전 차트 데이터(60분봉/일봉) 수신 대기 중 ➔ 이번 사이클 평가 스킵")
                    continue

                # 실시간 현재가 최우선 확보:
                # - NXT 프리마켓/애프터마켓 세션에서는 _AL 통합 차트 현재가(candle_close)가 실시간 NXT 체결가를 반영하므로 최우선 적용!
                # - KRX 정규장에서는 실계좌 수신가(acc_price) 또는 실시간 60분봉 현재가(candle_close) 적용
                h_info = self.active_holdings.get(code, {})
                is_auto_wl = bool(h_info.get('is_auto_watchlist', False))
                acc_price = float(h_info.get('current_price', 0.0) or 0.0)

                candle_close = float(df_60m.iloc[-1]['close']) if not df_60m.empty else 0.0
                if exchange_hint == "NXT" and candle_close > 0:
                    tick_close = candle_close
                elif not is_auto_wl and acc_price > 0:
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

                is_cond_pick = bool(h_info.get('is_condition_pick', False)) or (code in self.condition_picks)
                day_ret_pct = ((tick_close - pred1) / pred1 * 100.0) if pred1 > 0 else 0.0
                day_open = float(last_daily.get('open', last_60m.get('open', tick_close)) or tick_close)
                stock_intraday_chg = ((tick_close - day_open) / day_open * 100.0) if day_open > 0 else 0.0
                day_alpha = day_ret_pct - fut_flu_rt
                intraday_alpha = stock_intraday_chg - fut_intraday_chg

                # 🏆 [금일 시장 지수보다 강하게 움직이는 종목 판정 (RS Alpha Gate)]:
                # 전일대비 등락률이 소속 시장 지수보다 +1.5%p 이상 강하고, 당일 시가 위 양봉(시가대비 초과탄력 +0.5%p 이상) 유지!
                is_outperforming_index = (day_alpha >= 1.5) and (intraday_alpha >= 0.5) and (tick_close >= day_open * 0.999)

                # 🧹 [조건검색 편입 종목 중 지수 대비 약세/시가 훼손 종목 자동 정리 (Pruning)]:
                if is_cond_pick and strat.position.state == StrategyState.IDLE and (day_alpha < 0.0 or tick_close < day_open * 0.990):
                    with self.condition_lock:
                        self.condition_picks.pop(code, None)

                # ⚡ [스마트 120틱 TR 호출 최적화]:
                # 활성 보유 중(FIRST_BUY_DONE / FULL_POSITION)이거나,
                # IDLE 상태에서 선물 서킷브레이커가 아니고 + 지수 초과강세(is_outperforming_index) + 일봉 상승추세 + M/3선 지지 + 60분봉 20선 지지 종목은 120틱 즉시 조회!
                need_120t = (
                    strat.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION]
                    or (
                        fut_regime != "CRASH_LOCK"
                        and daily_bull
                        and is_outperforming_index
                        and (day3_m_line <= 0 or tick_close >= day3_m_line * 0.995)
                        and close_val >= sma20_val * 0.990
                    )
                )
                df_120t = self.get_120t_candles(code) if need_120t else pd.DataFrame()

                # 🛡️ evaluate_bar 호출 전 포지션/예수금 원자적 스냅샷 보존
                # (장외/준비시간 상태 변이 방지 및 매도/슬롯차단/주문실패 시 완벽 복원용)
                prev_pos = copy.deepcopy(strat.position)
                prev_cash = strat.cash

                now_t = datetime.now().time()
                is_eod_window = (dtime(15, 15, 0) <= now_t <= dtime(15, 30, 0) and exchange_hint == "KRX")
                is_opening_whipsaw_window = (
                    (dtime(8, 0, 0) <= now_t < dtime(8, 3, 0) and exchange_hint == "NXT")
                    or (dtime(9, 0, 0) <= now_t < dtime(9, 3, 0) and exchange_hint == "KRX")
                )
                is_premarket_bridge_window = (dtime(8, 45, 0) <= now_t < dtime(8, 50, 0) and exchange_hint == "NXT")
                cur_qty = h_info.get('qty', 0)
                pre_holding_qty = cur_qty if (self.is_real and not self.dry_run) else max(cur_qty, prev_pos.total_qty)

                # 장 운영 시간(또는 DRY-RUN 테스트 모드)에만 전략 상태 전이 평가 실행
                # (단, 15:15~15:30 정규장 마감 동시호가 구간에서는 신규 매수 원천 차단 및 보유분 일괄 청산 우선)
                if (is_active or self.dry_run) and not is_eod_window:
                    order = strat.evaluate_bar(
                        last_60m, 
                        daily_dead_cross=daily_dead_cross, 
                        daily_bull=daily_bull,
                        df_daily=df_daily,
                        day3_m_line=day3_m_line,
                        current_price=tick_close,
                        df_120t=df_120t,
                        futures_regime=fut_regime,
                        futures_label=fut_label,
                        is_premarket_bridge_window=is_premarket_bridge_window,
                        is_outperforming_index=is_outperforming_index,
                        is_condition_pick=is_cond_pick,
                        day_alpha=day_alpha
                    )
                else:
                    order = None

                # 60분봉 정배열/지지 상태 가시화 및 폭락장(역배열 비율) 브레드스 집계
                total_eval_count += 1
                if sma5_val > sma20_val > sma60_val:
                    align_str = "🟢완전정배열(5>20>60)"
                elif close_val >= sma20_val * 0.995:
                    align_str = "🟡20선상단지지"
                else:
                    align_str = "🔴역배열/매물저항"
                    bear_align_count += 1

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

                # 무위험 본절 락인 및 보유 수익률 가시화 (매도 발생 시에도 직전 보유 수익률이 로그에 정확히 표시되도록 스냅샷 병행 참조)
                ref_pos = prev_pos if (order and order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]) else strat.position
                bep_tag = " [🔒본절락]" if ref_pos.bep_locked else ""
                profit_tag = ""
                if ref_pos.avg_price > 0 and ref_pos.total_qty > 0:
                    cur_pnl = ((tick_close - ref_pos.avg_price) / ref_pos.avg_price) * 100.0
                    profit_tag = f" [수익률: {cur_pnl:+.2f}%(최고 +{ref_pos.max_profit_pct:.2f}%)]"

                if is_cond_pick:
                    source_badge = "🔔[실시간조건(Traiding)] "
                elif is_auto_wl:
                    source_badge = "🌟[타점관종] "
                else:
                    source_badge = ""
                rs_status = f"🔥지수초과({day_alpha:+.2f}%p)" if is_outperforming_index else f"⚪지수대비({day_alpha:+.2f}%p)"
                mkt_tag = f"[{stock_market}·{fut_badge}·{rs_status}]"
                logger.info(
                    f"📊 {source_badge}[{name}]{mkt_tag} 상태: {strat.position.state.value}{bep_tag}{profit_tag} | 현재가: {tick_close:,.0f}({day_ret_pct:+.2f}%) | "
                    f"60분: {align_str} | {m3_str} | 관문선: {gate_val:,.0f} | {gijun_str}"
                )

                # 🕒 [15:15~15:30 정규장 마감 청산 - 데이트레이딩 오버나이트 리스크 원천 차단]
                if is_eod_window and pre_holding_qty > 1:
                    logger.info(f"🕒 [장마감 동시호가 전량 청산] [{name}({code})] 당일 청산 원칙에 따라 전량 매도 집행 ({pre_holding_qty}주)")
                    eod_order = TradeOrder(
                        timestamp=last_60m.name if hasattr(last_60m, 'name') else str(datetime.now()),
                        action="TERMINATE_EXIT",
                        price=tick_close,
                        qty=pre_holding_qty,
                        amount=pre_holding_qty * tick_close,
                        reason="15:15 정규장 마감 동시호가 당일 청산(오버나이트 리스크 방지)",
                        stage="IDLE"
                    )
                    self.execute_order(code, name, eod_order, prev_pos=prev_pos, prev_cash=prev_cash)
                    continue

                eff_qty = cur_qty if (self.is_real and not self.dry_run) else max(
                    cur_qty, strat.position.total_qty, prev_pos.total_qty, order.qty if order else 0
                )

                if order:
                    # 1) 매도 주문(전량 익절/손절/이탈): 실보유 물량에 한해 전량 집행
                    if order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]:
                        # 🛡️ 관종 1주 종목은 매수가 실제로 체결되기 전에는 매도하지 않음
                        if eff_qty <= 1:
                            logger.info(f"   🛡️ [{name}({code})] 관종 1주 보유 종목 ➔ 매수 미완료 상태 매도 신호 무시 (1주 보존)")
                            continue
                        self.execute_order(code, name, order, prev_pos=prev_pos, prev_cash=prev_cash)
                    # 2) 2차 불타기 매수: 이미 활성 운용 중인 종목이므로 즉시 집행
                    elif order.action == "BUY_2":
                        self.execute_order(code, name, order, prev_pos=prev_pos, prev_cash=prev_cash)
                    # 3) 신규 1차 매수: 시초 3분(08:00~08:03 프리마켓 / 09:00~09:03 정규장) 휩소 방어 검사 후 우선순위 스코어링 수집
                    elif order.action == "BUY_1":
                        if is_opening_whipsaw_window and not self.dry_run:
                            whipsaw_label = "08:00~08:03 프리마켓 시초 3분 호가 휩소 방어" if exchange_hint == "NXT" else "09:00~09:03 정규장 시초가 휩소 방어"
                            resume_time_str = "08:03:00" if exchange_hint == "NXT" else "09:03:00"
                            logger.info(
                                f"   🛡️ [{whipsaw_label}] [{name}({code})] 시초 얇은 호가창/차익 매물 소화 대기 중 "
                                f"➔ {resume_time_str} 이후 양봉·지지 유지 확인 시 진입 (상태 안전 복원)"
                            )
                            self._rollback_strategy_state(strat, order, prev_pos, prev_cash)
                            continue

                        p_score, p_details = self.calculate_priority_score(
                            code, name, tick_close, last_60m, last_daily, df_60m, pre_day_close=pred1, df_daily=df_daily, df_120t=df_120t
                        )
                        # 🏆 [1) 금일 지수 대비 초과강도(RS Alpha) 가산점 (+4~+10점) & 실시간 조건검색(Traiding) 포착 우선권 (+5점)]
                        rs_alpha_bonus = 0.0
                        if day_alpha >= 3.5 and intraday_alpha >= 1.5:
                            rs_alpha_bonus = 10.0
                        elif day_alpha >= 2.5 and intraday_alpha >= 1.0:
                            rs_alpha_bonus = 7.0
                        elif day_alpha >= 1.5 and intraday_alpha >= 0.5:
                            rs_alpha_bonus = 4.0
                        cond_bonus = 5.0 if is_cond_pick else 0.0

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
                        p_details['day_alpha'] = day_alpha
                        p_details['rel_market_bonus'] = rel_bonus

                        buy_candidates.append({
                            'code': code,
                            'name': name,
                            'market': stock_market,
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
        # 동시 기준선 돌파 종목 우선순위(Priority Score) 옥석 가리기 및 최우선주 매수 집행
        # ─────────────────────────────────────────────────────────────
        if buy_candidates:
            # 🚨 핵심 결함 수정: 이번 루프에서 막 BUY_1 후보가 되어 FIRST_BUY_DONE으로 임시 전이된 종목들은
            # 기존 활성 종목 조회 대상에서 제외해야 1위 후보(winner) 주문이 정상 발송됨!
            candidate_codes = {c['code'] for c in buy_candidates}
            current_active = self.get_active_stock_code(exclude_codes=candidate_codes)
            if current_active:
                cur_act_name = self.get_stock_name(current_active)
                cur_act_state = self.strategies[current_active].position.state.value
                for cand in buy_candidates:
                    logger.info(
                        f"   ⏸️ [1종목 집중 매매 락 차단] 현재 [{cur_act_name}] 포지션({cur_act_state}) 운용 중 ➔ "
                        f"[{cand['name']}] (우선순위: {cand['priority_score']:.1f}점) 신규 매수 차단 대기"
                    )
                    # 상태 안전 원복 (스냅샷 기반 포지션/예수금/거래내역 완벽 복구)
                    self._rollback_strategy_state(cand['strat'], cand['order'], cand['prev_pos'], cand['prev_cash'])
            else:
                # 슬롯 0/1 비어있음! 최고 우선순위 점수 종목 선정 및 소속 시장 선물지수 연동 커트라인 검증
                buy_candidates.sort(key=lambda x: x['priority_score'], reverse=True)
                winner = buy_candidates[0]
                w_d = winner['details']
                w_fut_regime = winner.get('fut_regime', 'NORMAL_BULL')
                w_fut_label = winner.get('fut_label', '선물지수')
                w_fut_badge = winner.get('fut_badge', '🟢정상')

                bear_ratio = (bear_align_count / total_eval_count) if total_eval_count > 0 else 0.0
                is_market_slump = (total_eval_count >= 4 and bear_ratio >= 0.60)

                if w_fut_regime == "CRASH_LOCK":
                    min_required_score = 999.0  # 선물투매 서킷브레이커 발동 시 전면 차단
                    market_mode_tag = f"{w_fut_label} {w_fut_badge} 서킷브레이커 잠금"
                elif w_fut_regime == "CAUTION_DEFENSE" or is_market_slump:
                    min_required_score = 78.0
                    market_mode_tag = f"{w_fut_label} {w_fut_badge} 하락방어모드(대장주 78점+ 엄선)"
                elif w_fut_regime == "STRONG_BULL":
                    min_required_score = 62.0
                    market_mode_tag = f"{w_fut_label} {w_fut_badge} 강세공격모드(62점+)"
                else:
                    min_required_score = 65.0
                    market_mode_tag = f"{w_fut_label} {w_fut_badge} 정상/강세모드(65점+)"

                if winner['priority_score'] < min_required_score:
                    logger.info(
                        f"🛡️ [선물지수 연동 커트라인 미달 매수 보류] 1위 후보 [{winner['name']}({winner['code']})] "
                        f"점수 {winner['priority_score']:.1f}점 < 최소 커트라인 {min_required_score:.1f}점 ({market_mode_tag}) "
                        f"➔ 선물 약세/변동성 구간에서 억지 매매를 차단하고 현금을 100% 보존합니다."
                    )
                    for cand in buy_candidates:
                        self._rollback_strategy_state(cand['strat'], cand['order'], cand['prev_pos'], cand['prev_cash'])
                else:
                    logger.info(
                        f"👑 [동시 기준선 돌파 1픽 선정] 총 {len(buy_candidates)}개 돌파 후보 중 [{winner['name']}({winner['code']})] "
                        f"우선순위 1위 ({winner['priority_score']:.1f}점/100점 | {market_mode_tag} 커트라인 {min_required_score:.0f}점 통과) 선정 및 매수 집행! "
                        f"[⚡전일대비 거래량: {w_d.get('vol_ratio_prev', 0.0):.1f}% 돌파({w_d.get('score_speed', 0.0):.0f}점), "
                        f"시가지지 캔들순도: {w_d.get('score_shape', 0.0):.0f}점, "
                        f"기준선안착: +{w_d.get('gijun_diff_pct', 0.0):.2f}%({w_d.get('score_anchor', 0.0):.0f}점), "
                        f"120틱WMA: {w_d.get('score_120t', 0.0):.0f}점, 모멘텀: {w_d.get('score_morning', 0.0):.0f}점]"
                    )

                    self.execute_order(
                        winner['code'],
                        winner['name'],
                        winner['order'],
                        prev_pos=winner['prev_pos'],
                        prev_cash=winner['prev_cash']
                    )

                    # 2위 이하 탈락 후보들은 슬롯 마감 대기 및 상태 원복 (스냅샷 기반 완벽 복구)
                    for other in buy_candidates[1:]:
                        logger.info(
                            f"   ⏸️ [{other['name']}({other['code']})] (우선순위: {other['priority_score']:.1f}점) - "
                            f"1위 [{winner['name']}] 진입으로 슬롯 마감 ➔ 다음 회차 대기"
                        )
                        self._rollback_strategy_state(other['strat'], other['order'], other['prev_pos'], other['prev_cash'])

    def start_loop(self, interval_sec: int = 30):
        """실시간 반복 감시 시작 (키움 실시간 조건검색 포착 시 대기 시간 없이 0.1초 즉시 깨어나 스나이핑!)"""
        logger.info(
            f"🔄 실시간 조건검색({self.condition_name}) + 지수초과강도·120틱 감시를 시작합니다 (기본 주기: {interval_sec}초, 조건검색 포착 시 즉시 가동)."
        )
        try:
            while True:
                try:
                    self.run_cycle()
                except Exception as cycle_err:
                    logger.error(f"❌ [사이클 에러] 주기 실행 중 예외 발생: {cycle_err}", exc_info=True)
                woke_early = self.condition_wakeup_event.wait(timeout=interval_sec)
                if woke_early:
                    self.condition_wakeup_event.clear()
                    logger.info("⚡ [실시간 조건검색 포착 즉시 스나이핑] 대기 주기를 생략하고 즉시 지수 상대강도 & 120틱 타점 검증을 시작합니다!")
        except KeyboardInterrupt:
            logger.info("🛑 사용자에 의해 감시 루프가 정상 종료되었습니다.")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="실전 계좌 관심/보유 종목 + 키움 실시간 조건검색 120틱 집중 매매 봇")
    parser.add_argument("--once", action="store_true", help="1회 감시만 실행 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="모의 안전 모드(주문 미전송)")
    parser.add_argument("--interval", type=int, default=30, help="루프 감시 주기(초, 기본 30초)")
    parser.add_argument("--holdings-state", choices=["idle", "first_buy_done", "full_position"], default="idle",
                        help="실계좌 보유종목 초기 상태 (기본값: idle = 1주 수동 매수 관심종목 대기)")
    parser.add_argument("--condition", type=str, default="Traiding,traiding,Traiding1,trading1",
                        help="키움 실시간 조건검색식 이름 (기본값: Traiding,traiding,Traiding1,trading1)")
    parser.add_argument("--no-ws", action="store_true", help="실시간 조건검색 웹소켓 비활성화")

    args = parser.parse_args()

    bot = SafeHoldingsThemeGateBot(
        is_real=True,
        dry_run=args.dry_run,
        holdings_state=args.holdings_state,
        condition_name=args.condition,
        enable_ws=(not args.no_ws)
    )

    if args.once:
        bot.run_cycle()
    else:
        bot.start_loop(interval_sec=args.interval)

