"""
trading_bot_holdings_only.py - 실전 계좌 관심/보유 종목 전용 60분봉 순환 매매 봇

[안전장치 및 운영 규칙]
1. 장운영 시간 안전장치: NXT 프리마켓(08:00~08:50) + KRX 정규장(09:00~15:30) + NXT 애프터마켓(15:40~20:00) 3대 세션 자동 연동 (세션 외 및 주말 주문 원천 차단)
2. 모의/실전 안전 모드: DRY_RUN 플래그로 실제 주문 없이 신호 검증 가능
3. 계좌 보유 1주는 관심종목(Watchlist) 용도: 초기 상태 IDLE(미매수)에서 대기
4. 1차 매수 (50%): 60분봉 테마급등관문선 하락 후 상승변곡 발생 시 진입 (기존 1주 포지션 흡수)
5. 2차 매수 (50%): 급등관문고가선(HH) 상향 돌파 시 추가 매수 (총 100%)
6. 매도시점 일원화: 모든 매도시점은 120틱 테마 5<20 하향 이탈 시 전량 매도로 일원화 (NXT는 지정가, KRX는 시장가)
7. 재매수 진입타점: 120틱 테마 5>20>60>120 완전 정배열 완성 시 동일 수량 재매수 순환
8. 재매수 휩쏘 방어: 재매수 직후에는 -0.5% 이내 손실(-0.5% <= 손실률 < 0%)에서 5<20이 발생해도 매도 차단 홀딩
9. 전략 종료: 일봉 테마 5-20 데드크로스 발생 시 즉시 전량 청산 및 사이클 종료
"""

import os
import sys
import time
import logging
from datetime import datetime, time as dtime
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
    from indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_120t_tema_indicators
    from strategy import ThemeGate60mStrategy, TradeOrder, StrategyState
    from config import DEFAULT_CONFIG
except ImportError:
    from execution.indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_120t_tema_indicators
    from execution.strategy import ThemeGate60mStrategy, TradeOrder, StrategyState
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
    def __init__(self, is_real: bool = True, dry_run: bool = False, holdings_state: str = "rebuy"):
        """
        is_real: 키움 실전 API 연동 여부
        dry_run: True이면 신호는 계산하되 실제 주문 전송만 건너뜀 (안전 모의 테스트용)
        holdings_state: 'rebuy' (기본값: 장중 1주 매수 종목 및 보유종목을 '120틱 정배열 재매수(RE_BUY)' 대기 모드로 즉시 운용)
                        'idle' (60분봉 관문선 변곡 / 기준선 돌파 1차 50% 매수 대기)
                        'first_buy_done' (1차 매수 보유 상태, 60분봉 기준선 돌파 2차 매수 대기)
                        'full_position' (풀포지션 완료 상태, 120틱 5<20 매도 대기)
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
                    max_reentry=DEFAULT_CONFIG.MAX_REENTRY_COUNT
                )
                # 🎯 장중 1주 매수 종목 또는 holdings_state == "rebuy":
                # 사용자의 수동 마커 매수 종목으로 인식하여 즉시 '120틱 정배열 재매수(RE_BUY)' 대기 모드로 등록
                if self.holdings_state == "rebuy" or account_qty == 1:
                    strat.position.state = StrategyState.PROFIT_TAKEN
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = account_qty
                    strat.position.reentry_qty = 0
                    if buy_prc > 0:
                        strat.position.avg_price = buy_prc
                    logger.info(f"   🎯 [{name}({code})] 1주 수동 매수 종목 등록 ➔ '120틱 정배열 재매수(RE_BUY)' 대기 등록 완료! (보유: {account_qty}주 ➔ 120틱 5>20>60>120 정배열 시 전량 재매수 집행)")
                elif self.holdings_state == "idle":
                    strat.position.state = StrategyState.IDLE
                    strat.position.total_qty = 0
                    strat.position.base_account_qty = account_qty
                    if buy_prc > 0:
                        strat.position.avg_price = buy_prc
                    logger.info(f"   ➔ [{name}({code})] 관심종목 등록 완료 (IDLE 대기) | 기존 계좌 보유 수량: {account_qty}주 (1차 매수 시 자동 합산)")
                elif self.holdings_state == "first_buy_done":
                    strat.position.state = StrategyState.FIRST_BUY_DONE
                    strat.position.total_qty = account_qty
                    strat.position.avg_price = buy_prc
                    strat.position.first_buy_price = buy_prc
                    strat.position.first_buy_qty = account_qty
                    strat.position.base_account_qty = 0
                    strat.position.reentry_qty = account_qty * 2
                    logger.info(f"   ➔ [{name}({code})] 1차 매수 보유 상태 등록 (FIRST_BUY_DONE) | 보유: {account_qty}주 (매수가: {buy_prc:,.0f}원) ➔ 60분봉 기준선(M선) 돌파 2차 매수 대기")
                else:
                    strat.position.state = StrategyState.FULL_POSITION
                    strat.position.total_qty = account_qty
                    strat.position.avg_price = buy_prc
                    strat.position.base_account_qty = 0
                    strat.position.reentry_qty = account_qty
                    logger.info(f"   ➔ [{name}({code})] 실보유 종목 등록 완료 (FULL_POSITION 매도/순환 감시) | 보유: {account_qty}주 | 매수가: {buy_prc:,.0f}원")
                self.strategies[code] = strat
            else:
                # 이미 등록된 전략 객체에도 최신 예수금 반영
                existing_strat = self.strategies[code]
                existing_strat.cash = cash

                # 🎯 [장중 실시간 1주 수동 매수 감지]:
                # 봇 구동 중 사용자가 HTS/MTS에서 1주를 신규 매수하여 IDLE 종목의 수량이 1주 이상으로 확인되면,
                # 즉시 '120틱 정배열 재매수(RE_BUY)' 대기 모드로 동적 전환!
                if existing_strat.position.state == StrategyState.IDLE and account_qty >= 1:
                    existing_strat.position.state = StrategyState.PROFIT_TAKEN
                    existing_strat.position.total_qty = 0
                    existing_strat.position.base_account_qty = account_qty
                    existing_strat.position.reentry_qty = 0
                    if buy_prc > 0:
                        existing_strat.position.avg_price = buy_prc
                    logger.info(f"   🎯 [장중 1주 매수 감지 ➔ 재매수 로직 전환] [{name}({code})] {account_qty}주 확인 ➔ '120틱 정배열 재매수(RE_BUY)' 대기 모드로 즉시 전환!")

                # 실계좌 보유 종목인 경우 보유수량과 매수가 최신 동기화
                if existing_strat.position.state in [StrategyState.FULL_POSITION, StrategyState.REENTRY_HOLDING] and account_qty > 0:
                    existing_strat.position.total_qty = account_qty
                    if buy_prc > 0:
                        existing_strat.position.avg_price = buy_prc




    def get_60m_candles(self, code: str) -> pd.DataFrame:
        """60분봉 데이터 조회 (API 30분봉을 60분봉으로 정확히 리샘플링)"""
        if self.is_real:
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

    def get_120t_candles(self, code: str) -> pd.DataFrame:
        """120틱 데이터 조회 (실전 API 연동 및 fallback 합성)"""
        if self.is_real and self.api:
            try:
                df_120t = self.api.get_120t_candles(code)
                if df_120t is not None and not df_120t.empty and len(df_120t) >= 20:
                    return df_120t
            except Exception as e:
                logger.error(f"120틱 조회 에러 ({code}): {e}")

        # Fallback 데이터 생성 (모의/테스트용)
        return self._generate_fallback_120t(code)

    def _generate_fallback_120t(self, code: str) -> pd.DataFrame:
        """테스트 및 fallback용 120틱 캔들 생성"""
        try:
            df_60m = self.get_60m_candles(code)
            last_close = float(df_60m['close'].iloc[-1]) if not df_60m.empty else 50000.0
        except Exception:
            last_close = 50000.0

        np.random.seed(int(code) % 1000 if code.isdigit() else 42)
        returns = np.random.normal(0.0001, 0.001, 150)
        price_path = last_close * np.cumprod(1 + returns)

        records = []
        now = datetime.now()
        for i, prc in enumerate(price_path):
            records.append({
                'time': now,
                'open': prc * 0.9995,
                'high': prc * 1.001,
                'low': prc * 0.999,
                'close': prc,
                'volume': 1000
            })
        return pd.DataFrame(records)

    def execute_order(self, code: str, name: str, order: TradeOrder):
        """실전 주문 전송 (안전 장치 검사 후 집행)"""
        is_active, session_name, exchange_hint = get_market_session()
        
        # 1. 장운영 시간 안전 검사
        if not is_active:
            logger.warning(
                f"⏸️ [장외/준비 시간 주문 차단] [{name}({code})] {order.action} 신호 감지됨. "
                f"현재 상태는 '{session_name}'이므로 실전 주문을 발송하지 않고 안전 대기합니다."
            )
            return

        # 2. DRY_RUN 안전 검사
        if self.dry_run:
            logger.info(f"🛡️ [DRY-RUN 모의 체결] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {order.qty}주 | 가격: {order.price:,.0f}원")
            return

        strat = self.strategies.get(code)

        # 3. 매수 집행
        if order.action in ["BUY_1", "BUY_2", "RE_BUY"]:
            if order.qty <= 0:
                logger.warning(f"⚠️ [매수 스킵] [{name}({code})] 매수 수량이 0주 이하({order.qty})이므로 주문을 발송하지 않습니다.")
                return

            # 기존 관심용 1주 포지션에 완전 흡수
            if strat and strat.position.base_account_qty > 0:
                strat.position.total_qty += strat.position.base_account_qty
                logger.info(f"   ➕ [수량 흡수] 기존 관심용 1주({strat.position.base_account_qty}주)를 포지션에 합산 ➔ 총 {strat.position.total_qty}주 보유")
                strat.position.base_account_qty = 0

            buy_price = align_to_tick(order.price) if order.price > 0 else 0
            logger.info(f"🚀 [실전 매수 발송] [{name}({code})] {order.action} | 세션: {session_name} ({exchange_hint}) | 수량: {order.qty}주 | 가격: {buy_price:,.0f}원")
            if self.is_real:
                order_no = self.api.place_buy_order(code, order.qty, price=buy_price, order_type="00")
                logger.info(f"   ✅ [매수 접수 완료] 주문번호: {order_no}")

        # 4. 매도 집행 (계좌 전량 100% 매도)
        elif order.action in ["TAKE_PROFIT", "RE_SELL", "STOP_LOSS", "TERMINATE_EXIT"]:
            account_holding_qty = 0
            if self.is_real:
                cur_holdings = self.api.get_account_holdings()
                account_holding_qty = cur_holdings.get(code, {}).get('qty', 0)
            else:
                account_holding_qty = self.active_holdings.get(code, {}).get('qty', 0)

            # 실전 매도시 실계좌 보유수량이 0이면 매도 차단 및 상태 동기화
            if self.is_real and account_holding_qty <= 0:
                logger.warning(f"⚠️ [매도 스킵] [{name}({code})] 실계좌 보유수량이 0주이므로 매도 주문을 전송하지 않고 상태를 동기화합니다.")
                if strat:
                    strat.position.total_qty = 0
                    if strat.position.state in [StrategyState.FULL_POSITION, StrategyState.REENTRY_HOLDING]:
                        strat.position.state = StrategyState.PROFIT_TAKEN
                return

            final_sell_qty = account_holding_qty if self.is_real else max(order.qty, account_holding_qty)
            if final_sell_qty <= 0:
                logger.warning(f"⚠️ [매도 스킵] [{name}({code})] 매도 가능 수량이 0주이므로 주문을 발송하지 않습니다.")
                return


            if strat:
                strat.position.reentry_qty = final_sell_qty
                strat.position.base_account_qty = 0

            # 세션별 매도 주문 타입 분기
            # NXT 프리/애프터마켓은 시장가 불가 -> 호가 단위 맞춘 지정가("00") 필수
            # KRX 정규장은 시장가("03") 기본 발송 (fallback 대비 order.price 지정가 보정 전달)
            raw_price = order.price if (order.price and order.price > 0) else (strat.position.avg_price if strat and strat.position.avg_price > 0 else 0)
            sell_price = align_to_tick(raw_price) if raw_price > 0 else 0

            if exchange_hint == "NXT":
                sell_order_type = "00"  # NXT 지정가 필수
                logger.info(f"🚨 [실전 전량 매도 발송(NXT 지정가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 지정가: {sell_price:,.0f}원 | 사유: {order.reason}")
            else:
                sell_order_type = "03"  # KRX 정규장 시장가
                logger.info(f"🚨 [실전 전량 매도 발송(KRX 시장가)] [{name}({code})] {order.action} | 세션: {session_name} | 수량: {final_sell_qty}주 (계좌 전량 100%) | 기준가: {sell_price:,.0f}원 | 사유: {order.reason}")

            if self.is_real:
                order_no = self.api.place_sell_order(code, final_sell_qty, price=sell_price, order_type=sell_order_type)
                logger.info(f"   ✅ [전량 매도 접수 완료] 주문번호: {order_no}")

    def get_active_stock_code(self) -> str | None:
        """
        현재 활성 포지션을 보유/운용 중인 종목 코드 반환 (1종목 집중 매매 락)
        - 활성 상태: FIRST_BUY_DONE, FULL_POSITION, REENTRY_HOLDING 중 하나이거나 실보유 수량(total_qty) > 0
        """
        for code, strat in self.strategies.items():
            if strat.position.state in [
                StrategyState.FIRST_BUY_DONE,
                StrategyState.FULL_POSITION,
                StrategyState.REENTRY_HOLDING
            ] or strat.position.total_qty > 0:
                return code
        return None

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
            logger.info("🔓 [1종목 집중 매매 슬롯 OPEN] 현재 활성 보유 종목 없음 (슬롯 0/1 비어있음) ➔ 기준선(M선)/관문선 선착순 1위 종목 진입 대기")

        for code in list(self.strategies.keys()):
            name = self.get_stock_name(code)
            strat = self.strategies.get(code)
            if not strat or strat.position.state == StrategyState.TERMINATED:
                continue

            try:
                df_60m = self.get_60m_candles(code)
                df_daily = self.get_daily_candles(code)
                df_120t = self.get_120t_candles(code)

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
                df_120t_calc = calculate_120t_tema_indicators(df_120t)

                last_60m = df_60m_calc.iloc[-1]
                last_daily = df_daily_calc.iloc[-1]
                last_120t = df_120t_calc.iloc[-1] if not df_120t_calc.empty else None

                daily_dead_cross = bool(last_daily.get('daily_dead_cross', False)) if pd.notna(last_daily.get('daily_dead_cross')) else False
                daily_bull = bool(last_daily.get('daily_trend_bull', True)) if pd.notna(last_daily.get('daily_trend_bull')) else True

                # 주문 평가 (120틱 TEMA 정배열 재매수 & 120틱 5<20 매도 일원화 연동)
                order = strat.evaluate_bar(
                    last_60m, 
                    daily_dead_cross=daily_dead_cross, 
                    daily_bull=daily_bull,
                    row_120t=last_120t
                )

                gate_val = last_60m.get('theme_gate', 0.0)
                high_val = last_60m.get('theme_gate_high', 0.0)
                gijun_val = last_60m.get('theme_gijun', 0.0)
                sma5_val = last_60m.get('sma5', 0.0)
                sma20_val = last_60m.get('sma20', 0.0)
                sma60_val = last_60m.get('sma60', 0.0)
                close_val = last_60m['close']

                # 전문가 패널 5대 공통 승률 지표 상태 문자열화
                if sma5_val > sma20_val > sma60_val:
                    align_str = "🟢완전정배열(5>20>60)"
                elif close_val >= sma20_val * 0.995:
                    align_str = "🟡20선상단지지"
                else:
                    align_str = "🔴역배열/매물저항"

                m_dist_pct = ((gijun_val - close_val) / close_val) * 100 if gijun_val and not np.isnan(gijun_val) else 0.0
                if close_val >= gijun_val:
                    m_status = "🚀M선돌파"
                else:
                    m_status = f"M선턱밑({m_dist_pct:+.1f}%)"

                # 120틱 테마 상태 요약 및 휩쏘 방어 여부 실시간 가시화
                is_120t_aligned = False
                is_120t_dead = False
                t5_val = 0.0
                t20_val = 0.0
                if last_120t is not None:
                    dead_v = last_120t.get('is_tema_dead_5_20', False)
                    is_120t_dead = bool(dead_v) if pd.notna(dead_v) else False
                    align_v = last_120t.get('is_tema_aligned_120t', False)
                    is_120t_aligned = bool(align_v) if pd.notna(align_v) else False
                    t5_val = float(last_120t.get('tema5', 0.0)) if pd.notna(last_120t.get('tema5')) else 0.0
                    t20_val = float(last_120t.get('tema20', 0.0)) if pd.notna(last_120t.get('tema20')) else 0.0

                if strat.position.state == StrategyState.REENTRY_HOLDING:
                    base_prc = strat.position.reentry_price if strat.position.reentry_price > 0 else strat.position.avg_price
                    re_pnl = ((close_val - base_prc) / base_prc * 100) if base_prc > 0 else 0.0
                    if is_120t_dead and -0.5 <= re_pnl < 0.0:
                        status_120t = f"🛡️120틱5<20(휩쏘방어홀딩: {re_pnl:+.2f}%)"
                    elif is_120t_dead:
                        status_120t = f"🔴120틱5<20(재매도타점: {re_pnl:+.2f}%)"
                    elif is_120t_aligned:
                        status_120t = f"🟢120틱정배열유지({re_pnl:+.2f}%)"
                    else:
                        status_120t = f"⚪120틱혼조({re_pnl:+.2f}%)"
                else:
                    if is_120t_aligned:
                        status_120t = "🟢120틱정배열(재매수타점)"
                    elif is_120t_dead:
                        status_120t = "🔴120틱5<20(매도타점)"
                    else:
                        status_120t = "⚪120틱혼조"

                logger.info(
                    f"📊 [{name}] 상태: {strat.position.state.value} | 현재가: {close_val:,.0f} | "
                    f"60분: {align_str} | {status_120t} [TEMA 5:{t5_val:,.0f} 20:{t20_val:,.0f}] | 관문선: {gate_val:,.0f} | 기준선(M): {gijun_val:,.0f} [{m_status}]"
                )

                if order:
                    # 🔒 1종목 집중 매매 락(Lock) 검증: 신규 1차 매수 또는 재매수 시 슬롯 점유 여부 확인
                    if order.action in ["BUY_1", "RE_BUY"]:
                        current_active = self.get_active_stock_code()
                        # 이미 다른 종목이 활성 포지션을 점유하고 있는 경우
                        if current_active and current_active != code:
                            cur_act_name = self.get_stock_name(current_active)
                            cur_act_state = self.strategies[current_active].position.state.value
                            logger.info(
                                f"   ⏸️ [1종목 집중 매매 락 차단] 현재 [{cur_act_name}] 포지션({cur_act_state}) 운용 중 ➔ "
                                f"[{name}] {order.action} 신규 진입을 차단하고 안전 대기합니다."
                            )
                            # 주문 차단 및 상태 원복
                            saved_base = strat.position.base_account_qty
                            if order.action == "RE_BUY":
                                # 1주 수동 매수 종목은 재매수 대기 모드(PROFIT_TAKEN) 유지
                                strat.position = PositionTracker()
                                strat.position.state = StrategyState.PROFIT_TAKEN
                                strat.position.base_account_qty = saved_base
                            else:
                                strat.position = PositionTracker()
                                strat.position.base_account_qty = saved_base
                            order = None

                    if order:
                        # 신규 매수 집행 시, 이전에 청산되었던 타 종목의 PROFIT_TAKEN 잔여 상태 중
                        # 1주 수동 매수 종목(base_account_qty > 0)을 제외한 순수 잔여 종목만 IDLE로 리셋
                        if order.action in ["BUY_1", "RE_BUY"]:
                            for other_c, other_s in self.strategies.items():
                                if other_c != code and other_s.position.state == StrategyState.PROFIT_TAKEN:
                                    if other_s.position.base_account_qty == 0:
                                        other_s.position = PositionTracker()
                                        logger.info(f"   🧹 [관심종목 상태 리셋] [{self.get_stock_name(other_c)}] 재매수 대기 종료 ➔ 관심종목(IDLE) 복귀 완료")

                        self.execute_order(code, name, order)
            except Exception as stock_err:
                logger.error(f"❌ [{name}({code})] 사이클 처리 중 오류 발생: {stock_err}", exc_info=True)

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
    parser = argparse.ArgumentParser(description="실전 계좌 관심/보유 종목 전용 60분봉 순환 매매 봇")
    parser.add_argument("--once", action="store_true", help="1회 감시만 실행 후 종료")
    parser.add_argument("--dry-run", action="store_true", help="모의 안전 모드(주문 미전송)")
    parser.add_argument("--interval", type=int, default=30, help="루프 감시 주기(초, 기본 30초)")
    parser.add_argument("--holdings-state", choices=["rebuy", "idle", "first_buy_done", "full_position"], default="rebuy",
                        help="실계좌 보유종목 초기 상태 (기본값: rebuy = 1주 수동 매수 및 보유 종목을 '120틱 정배열 재매수(RE_BUY)' 대기로 즉시 운용)")

    args = parser.parse_args()

    bot = SafeHoldingsThemeGateBot(is_real=True, dry_run=args.dry_run, holdings_state=args.holdings_state)

    if args.once:
        bot.run_cycle()
    else:
        bot.start_loop(interval_sec=args.interval)
