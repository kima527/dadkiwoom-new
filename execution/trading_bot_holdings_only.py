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
import logging
from datetime import datetime, time as dtime
from typing import Tuple, Dict, Any, Optional
import pandas as pd
import numpy as np

# 경로 설정
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
PYTHON_WORKSPLACE = r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
MOVING_AVERAGE_TRAID = os.path.join(PYTHON_WORKSPLACE, "MovingAveragelineTraid", "execution")
REAL_TRADING_PATH = os.path.join(PYTHON_WORKSPLACE, "real trading")

for p in [CURRENT_DIR, PROJECT_ROOT, MOVING_AVERAGE_TRAID, REAL_TRADING_PATH]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_day3_m_line, calculate_pred_volume_ratio
    from strategy import ThemeGate60mStrategy, TradeOrder, StrategyState, PositionTracker
    from config import DEFAULT_CONFIG
except ImportError:
    from execution.indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_day3_m_line, calculate_pred_volume_ratio
    from execution.strategy import ThemeGate60mStrategy, TradeOrder, StrategyState, PositionTracker
    from execution.config import DEFAULT_CONFIG

try:
    from real_api_adapter import RealAPIAdapter
    HAS_REAL_API = True
except Exception as e:
    HAS_REAL_API = False

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

def align_to_tick(price: float) -> int:
    """한국거래소 및 대체거래소 호가 단위 정렬"""
    if price is None or np.isnan(price) or price <= 0:
        return 0
    if price < 2000: tick = 1
    elif price < 5000: tick = 5
    elif price < 20000: tick = 10
    elif price < 50000: tick = 50
    elif price < 200000: tick = 100
    elif price < 500000: tick = 500
    else: tick = 1000
    return int((int(price) // tick) * tick)


class SafeHoldingsThemeGateBot:
    def __init__(self, is_real: bool = True, dry_run: bool = False, holdings_state: str = "idle"):
        """
        is_real: 키움 실전 API 연동 여부
        dry_run: True이면 신호는 계산하되 실제 주문 전송만 건너뜀 (안전 모의 테스트용)
        holdings_state: 'idle' (기본값: 관심종목/1주 수동 매수 종목을 IDLE 상태로 등록, 1차 50% 매수 대기)
                        'first_buy_done' (1차 매수 보유 상태, 60분봉 기준선 돌파 2차 매수 대기)
                        'full_position' (풀포지션 완료 상태, M/3선 및 기준선 변곡선 매도 대기)
        """
        self.dry_run = dry_run
        self.is_real = is_real and HAS_REAL_API
        self.holdings_state = holdings_state

        logger.info("==================================================")
        if self.dry_run:
            logger.info(" 🛡️ [모의 안전 모드(DRY-RUN)] 신호 감시만 수행 (실제 주문 차단)")
        elif self.is_real:
            logger.info(" 🚀 [실전 거래 모드] 장중 신호 발생 시 실제 주문 전송")
        else:
            logger.info(" 🧪 [시뮬레이션 모드] 가상 데이터 모드")
        logger.info("==================================================")
        
        if self.is_real:
            self.api = RealAPIAdapter()
        else:
            self.api = None
            
        self.strategies: dict[str, ThemeGate60mStrategy] = {}
        self.active_holdings: dict = {}
        self.sold_today_stocks: set[str] = set()
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

    def refresh_holdings(self):
        """실전 계좌에서 관심종목(보유 목록) 가져오기"""
        if self.is_real:
            holdings = self.api.get_account_holdings()
            cash = self.api.get_cash_balance()
        else:
            holdings = {
                '005930': {'qty': 1, 'buy_price': 70000, 'current_price': 71000},
                '263750': {'qty': 1, 'buy_price': 34650, 'current_price': 34650}
            }
            cash = 10_000_000

        self.active_holdings = holdings
        logger.info(f"💼 [계좌 잔고 갱신] 가용 예수금: {cash:,.0f}원 | 감시 대상 종목 수: {len(holdings)}개")

        for code, h in holdings.items():
            name = self.get_stock_name(code)
            account_qty = int(h.get('qty', 0))
            buy_prc = float(h.get('buy_price', 0.0))
            
            # 최초 1회만 전략 상태 등록 (이미 있으면 기존 진행 상태 유지)
            if code not in self.strategies:
                strat = ThemeGate60mStrategy(
                    initial_capital=cash,
                    gate_sl_pct=DEFAULT_CONFIG.GATE_STOP_LOSS_PCT,
                    max_reentry=0
                )
                # 🎯 장중 1주 매수 종목: 일봉 1>3>5 단순이평선 기반 수동 1주 매수 관심종목 (IDLE 등록)
                if account_qty <= 1 or self.holdings_state == "idle":
                    strat.position.state = StrategyState.IDLE
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = account_qty
                    if buy_prc > 0:
                        strat.position.avg_price = buy_prc
                    logger.info(f"   🎯 [{name}({code})] 관심종목(1주 마커) 등록 완료 (IDLE 대기 | 기존 수량: {account_qty}주 ➔ 1차/기준선 돌파 매수 시 흡수 합산)")
                elif self.holdings_state == "first_buy_done":
                    strat.position.state = StrategyState.FIRST_BUY_DONE
                    strat.position.total_qty = account_qty
                    strat.position.avg_price = buy_prc
                    strat.position.first_buy_price = buy_prc
                    strat.position.first_buy_qty = account_qty
                    strat.position.base_account_qty = 0
                    logger.info(f"   ➔ [{name}({code})] 1차 매수 보유 상태 등록 (FIRST_BUY_DONE) | 보유: {account_qty}주 (매수가: {buy_prc:,.0f}원) ➔ M선 돌파 2차 매수 대기")
                else:
                    # 실보유 종목 (account_qty > 1 또는 full_position) -> M/3 수식선 및 기준선 변곡선 이탈 매도 감시
                    strat.position.state = StrategyState.FULL_POSITION
                    strat.position.total_qty = account_qty
                    strat.position.avg_price = buy_prc
                    strat.position.base_account_qty = 0
                    logger.info(f"   ➔ [{name}({code})] 실보유 종목 등록 완료 (FULL_POSITION | M/3 수식선 & 기준선 변곡선 매도 감시) | 보유: {account_qty}주 | 매수가: {buy_prc:,.0f}원")
                self.strategies[code] = strat
            else:
                # 이미 등록된 전략 객체에도 최신 예수금 반영
                existing_strat = self.strategies[code]
                existing_strat.cash = cash

                # 🎯 [장중 실시간 1주 수동 매수 동기화]: IDLE 상태에서 수동 1주 매수 확인 시 기본 수량 업데이트
                if existing_strat.position.state == StrategyState.IDLE and account_qty >= 1:
                    existing_strat.position.base_account_qty = account_qty
                    if buy_prc > 0:
                        existing_strat.position.avg_price = buy_prc

                # 실계좌 보유 종목인 경우 보유수량과 매수가 최신 동기화 (FIRST_BUY_DONE, FULL_POSITION 모두)
                if existing_strat.position.state in [StrategyState.FIRST_BUY_DONE, StrategyState.FULL_POSITION] and account_qty > 0:
                    existing_strat.position.total_qty = account_qty
                    if buy_prc > 0:
                        existing_strat.position.avg_price = buy_prc

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

        # Fallback 데이터
        try:
            from generate_sample_data import generate_realistic_sample_data
        except ImportError:
            from execution.generate_sample_data import generate_realistic_sample_data
        df_60m, _ = generate_realistic_sample_data(num_days=30)
        return df_60m

    def get_daily_candles(self, code: str) -> pd.DataFrame:
        """일봉 데이터 조회"""
        if self.is_real:
            df_d = self.api.get_daily_candles(code)
            if df_d is not None and not df_d.empty:
                return df_d
        try:
            from generate_sample_data import generate_realistic_sample_data
        except ImportError:
            from execution.generate_sample_data import generate_realistic_sample_data
        _, df_d = generate_realistic_sample_data(num_days=40)
        return df_d

    def execute_order(self, code: str, name: str, order: TradeOrder):
        """실전 주문 전송 (안전 장치 검사 후 집행)"""
        is_active, session_name, exchange_hint = get_market_session()
        strat = self.strategies.get(code)
        
        # 1. 장운영 시간 안전 검사 (실전 모드 시 장외 주문 원천 차단)
        if not is_active and not self.dry_run:
            logger.warning(
                f"⏸️ [장외/준비 시간 주문 차단] [{name}({code})] {order.action} 신호 감지됨. "
                f"현재 상태는 '{session_name}'이므로 실전 주문을 발송하지 않고 안전 대기합니다."
            )
            return

        # 2. 매수 집행 (1차 50% 또는 2차 50%)
        if order.action in ["BUY_1", "BUY_2"]:
            if order.qty <= 0:
                logger.warning(f"⚠️ [매수 스킵] [{name}({code})] 매수 수량이 0주 이하({order.qty})이므로 주문을 발송하지 않습니다.")
                return

            # 기존 관심용 1주 포지션에 완전 흡수
            if strat and strat.position.base_account_qty > 0:
                strat.position.total_qty += strat.position.base_account_qty
                logger.info(f"   ➕ [수량 흡수] 기존 관심용 1주({strat.position.base_account_qty}주)를 포지션에 합산 ➔ 총 {strat.position.total_qty}주 보유")
                strat.position.base_account_qty = 0

            buy_price = align_to_tick(order.price) if order.price > 0 else 0

            if self.dry_run:
                logger.info(f"🛡️ [DRY-RUN 모의 체결] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {order.qty}주 | 가격: {buy_price:,.0f}원 (실제 주문 미전송)")
                return

            logger.info(f"🚀 [실전 매수 발송] [{name}({code})] {order.action} | 세션: {session_name} ({exchange_hint}) | 수량: {order.qty}주 | 가격: {buy_price:,.0f}원")
            if self.is_real and self.api:
                order_no = self.api.place_buy_order(code, order.qty, price=buy_price, order_type="00")
                logger.info(f"   ✅ [매수 접수 완료] 주문번호: {order_no}")

        # 3. 매도 집행 (계좌 전량 100% 매도)
        elif order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]:
            account_holding_qty = 0
            if self.is_real and self.api:
                cur_holdings = self.api.get_account_holdings()
                account_holding_qty = cur_holdings.get(code, {}).get('qty', 0)
            else:
                account_holding_qty = self.active_holdings.get(code, {}).get('qty', 0)

            # 실전 매도시 실계좌 보유수량이 0이면 매도 차단 및 상태 동기화
            if self.is_real and not self.dry_run and account_holding_qty <= 0:
                logger.warning(f"⚠️ [매도 스킵] [{name}({code})] 실계좌 보유수량이 0주이므로 매도 주문을 전송하지 않고 상태를 동기화합니다.")
                if strat:
                    strat.position = PositionTracker()
                return

            final_sell_qty = account_holding_qty if (self.is_real and not self.dry_run) else max(order.qty, account_holding_qty)
            if final_sell_qty <= 0:
                logger.warning(f"⚠️ [매도 스킵] [{name}({code})] 매도 가능 수량이 0주이므로 주문을 발송하지 않습니다.")
                return

            if strat:
                # 전량 매도 완료 즉시 포지션 초기화 (IDLE 복귀, 재매수 없음)
                strat.position = PositionTracker()

            # 당일 매도 완료 종목으로 등록하여 당일 재매수 원천 차단
            self.sold_today_stocks.add(code)
            logger.info(f"   🚫 [{name}({code})] 당일 매도 완료 처리 ➔ 당일 재매수 영구 차단 목록에 등록되었습니다.")

            raw_price = order.price if (order.price and order.price > 0) else (strat.position.avg_price if strat and strat.position.avg_price > 0 else 0)
            sell_price = align_to_tick(raw_price) if raw_price > 0 else 0

            if self.dry_run:
                logger.info(f"🛡️ [DRY-RUN 모의 체결] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 지정가: {sell_price:,.0f}원 (실제 주문 미전송)")
                return

            if exchange_hint == "NXT":
                sell_order_type = "00"  # NXT 지정가 필수
                logger.info(f"🚨 [실전 전량 매도 발송(NXT 지정가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 지정가: {sell_price:,.0f}원 | 사유: {order.reason}")
            else:
                sell_order_type = "03"  # KRX 정규장 시장가
                logger.info(f"🚨 [실전 전량 매도 발송(KRX 시장가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 기준가: {sell_price:,.0f}원 | 사유: {order.reason}")

            if self.is_real and self.api:
                order_no = self.api.place_sell_order(code, final_sell_qty, price=sell_price, order_type=sell_order_type)
                logger.info(f"   ✅ [전량 매도 접수 완료] 주문번호: {order_no}")

    def get_active_stock_code(self) -> str | None:
        """
        현재 활성 포지션을 보유/운용 중인 종목 코드 반환 (1종목 집중 매매 락)
        - 활성 상태: FIRST_BUY_DONE, FULL_POSITION 중 하나이거나 실보유 수량(total_qty) > 0
        """
        for code, strat in self.strategies.items():
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
        session_target_vol: Optional[float] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        ⚡ [세션별 차등 번개 돌파 스나이핑 1위 선정 체계 - 100점 만점]
        1. 🥇 세션별 전일 거래량 돌파 속도 및 잠식률 (50점 만점, 최우선 엔진!)
           - 🎯 세션별 기준치: [NXT 프리마켓: 1.5%] / [KRX 정규장: 3.0%] / [NXT 애프터마켓: 1.0%]
           - 목표치 대비 달성률(attainment_ratio = vol_ratio_prev / target_vol):
             * 달성률 >= 1.5배 (정규장 4.5%+, 프리 2.25%+, 애프터 1.5%+): 50점 만점!
             * 달성률 >= 1.0배 (정규장 3.0%+, 프리 1.5%+, 애프터 1.0%+): 45점 (목표 돌파 완료)
             * 달성률 >= 0.7배: 35점
             * 달성률 >= 0.4배: 20점
             * 달성률 < 0.4배: 5점
        2. 🥈 시가 무훼손 양봉 순도 (25점 만점)
           - 당일 시가(Open)를 단 1호가도 깨지 않고 지키는 강력한 붉은 양봉
           - 시가 위 양봉 유지 (tick_close >= c_open) + 윗꼬리 25% 이하: 25점 만점
           - 양봉 유지 + 윗꼬리 40% 이하: 18점
           - 음봉 (tick_close < c_open): 0점 (시가 훼손 감점)
        3. 🥉 기준선(M선) 안착 이격도 (25점 만점)
           - 시가 갭돌파든 장중 돌파든 기준선 위 +0.3% ~ +3.5% 최적 안착: 25점 만점
           - 기준선 위 +3.5% ~ +7.0%: 20점
           - 기준선 위 0.0% ~ +0.3%: 12점
           - 기준선 대비 +12% 이상 과열: 5점 (추격 매수 방지)
        """
        # 세션별 차등 목표 거래량 기준 설정 (프리 1.5%, 정규장 3.0%, 애프터 1.0%)
        if session_target_vol is not None and session_target_vol > 0:
            target_vol = float(session_target_vol)
            target_name = f"지정세션({target_vol:.1f}%)"
        else:
            target_vol, target_name = get_session_volume_target()

        # 1. 전일 거래량 돌파 속도 점수 (50점 만점)
        if vol_ratio_prev is None:
            curr_vol = float(last_daily.get('volume', 0.0))
            if curr_vol <= 0:
                curr_vol = float(last_60m.get('volume', 0.0))
            vol_ratio_prev, pre_day_vol = calculate_pred_volume_ratio(df_daily, curr_vol)
        else:
            pre_day_vol = 0.0

        attainment_ratio = (vol_ratio_prev / target_vol) if target_vol > 0 else 1.0

        if attainment_ratio >= 1.5:
            score_speed = 50.0
        elif attainment_ratio >= 1.0:
            score_speed = 45.0
        elif attainment_ratio >= 0.7:
            score_speed = 35.0
        elif attainment_ratio >= 0.4:
            score_speed = 20.0
        else:
            score_speed = 5.0

        # 2. 시가 무훼손 양봉 순도 점수 (25점 만점)
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
            score_shape = 25.0
        elif tick_close >= c_open and upper_shadow_ratio <= 0.40:
            score_shape = 18.0
        elif tick_close < c_open:
            score_shape = 0.0
        else:
            score_shape = 10.0

        # 3. 기준선(M선) 안착 이격도 (25점 만점)
        gijun_val = float(last_60m.get('theme_gijun', 0.0))
        if gijun_val <= 0:
            gijun_val = float(last_60m.get('theme_gate', tick_close))

        gijun_diff_pct = ((tick_close - gijun_val) / gijun_val * 100.0) if gijun_val > 0 else 0.0

        if 0.3 <= gijun_diff_pct <= 3.5:
            score_anchor = 25.0
        elif 3.5 < gijun_diff_pct <= 7.0:
            score_anchor = 20.0
        elif 0.0 <= gijun_diff_pct < 0.3:
            score_anchor = 12.0
        elif gijun_diff_pct > 12.0:
            score_anchor = 5.0
        else:
            score_anchor = 8.0

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

        total_score = score_speed + score_shape + score_anchor
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
            'score_candle': score_shape + score_anchor,
            'day_ret_pct': day_ret_pct,
            'day_val_eok': day_val_eok
        }
        return total_score, details

    def run_cycle(self):
        """1회 감시 사이클"""
        self.refresh_holdings()

        if not self.strategies:
            logger.info("ℹ️ 현재 등록된 감시 종목이 없습니다.")
            return

        is_active, session_name, _ = get_market_session()
        market_status_str = f"🟢 {session_name}" if is_active else f"🔴 {session_name}"
        logger.info(f"⏱️ 감시 루프 실행 중... [현재 시장 상태: {market_status_str}]")

        active_code = self.get_active_stock_code()
        if active_code:
            act_name = self.get_stock_name(active_code)
            act_state = self.strategies[active_code].position.state.value
            logger.info(f"🔒 [1종목 집중 매매 락 ON] 현재 운용 종목: [{act_name}({active_code})] 상태: {act_state} (슬롯 1/1 점유) | 기타 관심종목 신규 매수 차단 대기")
        else:
            logger.info("🔓 [1종목 집중 매매 슬롯 OPEN] 현재 활성 보유 종목 없음 (슬롯 0/1 비어있음) ➔ 기준선(M선)/관문선 옥석 가리기 1위 종목 진입 대기")

        buy_candidates = []

        for code in list(self.strategies.keys()):
            name = self.get_stock_name(code)
            strat = self.strategies.get(code)
            if not strat or strat.position.state == StrategyState.TERMINATED:
                continue

            # 🚫 당일 매도 완료 종목: 신규 매수 감시 원천 제외 (No-Rebuy 원칙)
            if code in self.sold_today_stocks and strat.position.state == StrategyState.IDLE:
                continue

            try:
                df_60m = self.get_60m_candles(code)
                df_daily = self.get_daily_candles(code)

                # 실시간 현재가 최우선 확보: 1순위 계좌 잔고 TR 수신가 -> 2순위 API 조회 -> 3순위 60분봉 종가
                acc_price = self.active_holdings.get(code, {}).get('current_price', 0.0)
                if acc_price and acc_price > 0:
                    tick_close = float(acc_price)
                else:
                    tick_close = 0.0
                    if self.is_real and self.api:
                        try:
                            real_prc = self.api.get_current_price(code)
                            if real_prc and real_prc > 0:
                                tick_close = float(real_prc)
                        except Exception:
                            pass

                if tick_close <= 0 and df_60m is not None and not df_60m.empty:
                    tick_close = float(df_60m.iloc[-1]['close'])

                # 💡 [실시간 60분봉 캔들 합성]: 장중 진행 중인 마지막 60분봉에 실시간 현재가 즉시 반영
                # ➔ 60분이 끝나기를 기다릴 필요 없이 실시간 기준선 변곡 및 TEMA 지표 즉각 연산
                if df_60m is not None and not df_60m.empty and tick_close > 0:
                    df_60m = df_60m.copy()
                    last_idx = df_60m.index[-1]
                    df_60m.loc[last_idx, 'close'] = tick_close
                    if tick_close > df_60m.loc[last_idx, 'high']:
                        df_60m.loc[last_idx, 'high'] = tick_close
                    if tick_close < df_60m.loc[last_idx, 'low']:
                        df_60m.loc[last_idx, 'low'] = tick_close

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

                # 주문 평가 (M/3 수식선 이탈 즉시 매도 & 60분봉 기준선 변곡선 미돌파 매도 연동)
                order = strat.evaluate_bar(
                    last_60m, 
                    daily_dead_cross=daily_dead_cross, 
                    daily_bull=daily_bull,
                    df_daily=df_daily,
                    day3_m_line=day3_m_line,
                    current_price=tick_close
                )

                gate_val = last_60m.get('theme_gate', 0.0)
                high_val = last_60m.get('theme_gate_high', 0.0)
                gijun_val = last_60m.get('theme_gijun', 0.0)
                sma5_val = last_60m.get('sma5', 0.0)
                sma20_val = last_60m.get('sma20', 0.0)
                sma60_val = last_60m.get('sma60', 0.0)

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

                logger.info(
                    f"📊 [{name}] 상태: {strat.position.state.value} | 현재가: {tick_close:,.0f} | "
                    f"60분: {align_str} | {m3_str} | 관문선: {gate_val:,.0f} | {gijun_str}"
                )

                if order:
                    # 1) 매도 주문(전량 익절/손절/이탈): 즉시 집행하여 슬롯 및 예수금 확보
                    if order.action in ["TAKE_PROFIT", "STOP_LOSS", "TERMINATE_EXIT"]:
                        self.execute_order(code, name, order)
                    # 2) 2차 불타기 매수: 이미 활성 운용 중인 종목이므로 즉시 집행
                    elif order.action == "BUY_2":
                        self.execute_order(code, name, order)
                    # 3) 신규 1차 매수: 동시 돌파 우선순위 스코어링 평가 리스트에 수집
                    elif order.action == "BUY_1":
                        p_score, p_details = self.calculate_priority_score(
                            code, name, tick_close, last_60m, last_daily, df_60m, pre_day_close=pred1, df_daily=df_daily
                        )
                        buy_candidates.append({
                            'code': code,
                            'name': name,
                            'order': order,
                            'strat': strat,
                            'priority_score': p_score,
                            'details': p_details
                        })

            except Exception as stock_err:
                logger.error(f"❌ [{name}({code})] 사이클 처리 중 오류 발생: {stock_err}", exc_info=True)

        # ─────────────────────────────────────────────────────────────
        # 동시 기준선 돌파 종목 우선순위(Priority Score) 옥석 가리기 및 최우선주 매수 집행
        # ─────────────────────────────────────────────────────────────
        if buy_candidates:
            current_active = self.get_active_stock_code()
            if current_active:
                cur_act_name = self.get_stock_name(current_active)
                cur_act_state = self.strategies[current_active].position.state.value
                for cand in buy_candidates:
                    if cand['code'] != current_active:
                        logger.info(
                            f"   ⏸️ [1종목 집중 매매 락 차단] 현재 [{cur_act_name}] 포지션({cur_act_state}) 운용 중 ➔ "
                            f"[{cand['name']}] (우선순위: {cand['priority_score']:.1f}점) 신규 매수 차단 대기"
                        )
                        # 상태 안전 원복 (계좌 원본 잔고 수량 유지 및 예수금/거래내역 복구)
                        s = cand['strat']
                        s.cash += cand['order'].amount
                        if s.trade_history and s.trade_history[-1] == cand['order']:
                            s.trade_history.pop()
                        orig_qty = self.active_holdings.get(cand['code'], {}).get('qty', 1)
                        s.position = PositionTracker()
                        s.position.state = StrategyState.IDLE
                        s.position.base_account_qty = orig_qty
            else:
                # 슬롯 0/1 비어있음! 최고 우선순위 점수 종목 선정
                buy_candidates.sort(key=lambda x: x['priority_score'], reverse=True)
                winner = buy_candidates[0]
                w_d = winner['details']
                logger.info(
                    f"👑 [동시 기준선 돌파 1픽 선정] 총 {len(buy_candidates)}개 돌파 후보 중 [{winner['name']}({winner['code']})] "
                    f"우선순위 1위 ({winner['priority_score']:.1f}점) 선정 및 매수 집행! "
                    f"[⚡전일대비 거래량: {w_d.get('vol_ratio_prev', 0.0):.1f}% 돌파({w_d.get('score_speed', 0.0):.0f}점), "
                    f"시가지지 캔들순도: {w_d.get('score_shape', 0.0):.0f}점, "
                    f"기준선안착: +{w_d.get('gijun_diff_pct', 0.0):.2f}%({w_d.get('score_anchor', 0.0):.0f}점)]"
                )

                self.execute_order(winner['code'], winner['name'], winner['order'])

                # 2위 이하 탈락 후보들은 슬롯 마감 대기 및 상태 원복 (IDLE 복귀, 1주 마커 보존, 예수금/거래내역 복구)
                for other in buy_candidates[1:]:
                    logger.info(
                        f"   ⏸️ [{other['name']}({other['code']})] (우선순위: {other['priority_score']:.1f}점) - "
                        f"1위 [{winner['name']}] 진입으로 슬롯 마감 ➔ 다음 회차 대기"
                    )
                    s = other['strat']
                    s.cash += other['order'].amount
                    if s.trade_history and s.trade_history[-1] == other['order']:
                        s.trade_history.pop()
                    orig_qty = self.active_holdings.get(other['code'], {}).get('qty', 1)
                    s.position = PositionTracker()
                    s.position.state = StrategyState.IDLE
                    s.position.base_account_qty = orig_qty

    def start_loop(self, interval_sec: int = 30):
        """실시간 반복 감시 시작"""
        logger.info(f"🔄 60분봉 실시간 감시를 시작합니다 (갱신 주기: {interval_sec}초).")
        try:
            while True:
                try:
                    self.run_cycle()
                except Exception as cycle_err:
                    logger.error(f"❌ [사이클 에러] 주기 실행 중 예외 발생: {cycle_err}", exc_info=True)
                time.sleep(interval_sec)
        except KeyboardInterrupt:
            logger.info("🛑 사용자에 의해 감시 루프가 정상 종료되었습니다.")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="실전 계좌 관심/보유 종목 전용 60분봉 집중 매매 봇")
    parser.add_argument("--once", action="store_true", help="1회 감시만 실행 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="모의 안전 모드(주문 미전송)")
    parser.add_argument("--interval", type=int, default=30, help="루프 감시 주기(초, 기본 30초)")
    parser.add_argument("--holdings-state", choices=["idle", "first_buy_done", "full_position"], default="idle",
                        help="실계좌 보유종목 초기 상태 (기본값: idle = 1주 수동 매수 관심종목 대기)")

    args = parser.parse_args()

    bot = SafeHoldingsThemeGateBot(is_real=True, dry_run=args.dry_run, holdings_state=args.holdings_state)

    if args.once:
        bot.run_cycle()
    else:
        bot.start_loop(interval_sec=args.interval)

