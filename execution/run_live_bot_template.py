"""
실전/모의투자 실시간 연동 봇 템플릿
Theme Gate 60-Minute Real-time Trading Bot Template

키움증권 Open API+ 또는 REST API 연동 시 실시간 60분봉 및 일봉을 수신하여
테마급등관문선 분할매수 -> 급등관문고가선 2차매수 -> 테마기준선 익절 -> 재매수 순환을 집행합니다.
"""

import os
import sys
import time
import logging
from datetime import datetime
import pandas as pd
import numpy as np

# 경로 설정
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from execution.indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross
    from execution.strategy import ThemeGate60mStrategy, TradeOrder, StrategyState
    from execution.config import DEFAULT_CONFIG
except ImportError:
    from indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross
    from strategy import ThemeGate60mStrategy, TradeOrder, StrategyState
    from config import DEFAULT_CONFIG

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ThemeGateBot")

class LiveThemeGateBot:
    def __init__(self, stock_code: str, stock_name: str, account_no: str = "", is_mock: bool = True):
        self.stock_code = stock_code
        self.stock_name = stock_name
        self.account_no = account_no
        self.is_mock = is_mock
        
        self.strategy = ThemeGate60mStrategy(
            initial_capital=10_000_000,
            gate_sl_pct=DEFAULT_CONFIG.GATE_STOP_LOSS_PCT,
            max_reentry=DEFAULT_CONFIG.MAX_REENTRY_COUNT
        )
        
        self.df_60m = pd.DataFrame()
        self.df_daily = pd.DataFrame()
        self.is_running = True
        
    def fetch_historical_candles(self):
        """
        초기 캔들 데이터 로드 (60분봉 최소 100개, 일봉 최소 40개 필요)
        실제 환경에서는 kiwoom_api.get_candle_data_60m(), get_candle_data_daily() 연동
        """
        logger.info(f"[{self.stock_name}({self.stock_code})] 과거 캔들 데이터 조회 중...")
        # 템플릿용: 실제 환경에서는 API 호출로 대체
        try:
            from generate_sample_data import generate_realistic_sample_data
        except ImportError:
            from execution.generate_sample_data import generate_realistic_sample_data
            
        self.df_60m, self.df_daily = generate_realistic_sample_data(num_days=30)
        logger.info(f"데이터 로드 완료: 60분봉 {len(self.df_60m)}개, 일봉 {len(self.df_daily)}개")

    def execute_real_order(self, order: TradeOrder):
        """
        실제 증권사 주문 API 호출 함수 (키움 API 연동 위치)
        """
        order_type_str = "모의투자" if self.is_mock else "실전매매"
        logger.info(f"[{order_type_str} 주문 집행] {order.action} | 가격: {order.price:,.0f} | 수량: {order.qty}주 | 사유: {order.reason}")
        
        # TODO: 실제 키움증권 주문 함수 호출
        # if order.action in ["BUY_1", "BUY_2", "RE_BUY"]:
        #     kiwoom_api.send_order(order_type=1, code=self.stock_code, qty=order.qty, price=order.price)
        # elif order.action in ["TAKE_PROFIT", "RE_SELL", "STOP_LOSS", "TERMINATE_EXIT"]:
        #     kiwoom_api.send_order(order_type=2, code=self.stock_code, qty=order.qty, price=0) # 시장가 매도

    def on_60m_candle_closed(self, new_candle: dict):
        """
        60분봉 캔들 마감 시 트리거되는 이벤트 핸들러
        """
        # 1. 새 캔들 추가
        new_row = pd.DataFrame([new_candle])
        self.df_60m = pd.concat([self.df_60m, new_row], ignore_index=True)
        
        # 2. 지표 재계산
        df_calc = calculate_all_60m_indicators(
            self.df_60m,
            p1=DEFAULT_CONFIG.TEMA_FAST,
            p2=DEFAULT_CONFIG.TEMA_SLOW,
            p_slow=DEFAULT_CONFIG.SMA_SLOW
        )
        
        df_daily_calc = calculate_daily_tema_deadcross(
            self.df_daily,
            p1=DEFAULT_CONFIG.TEMA_FAST,
            p2=DEFAULT_CONFIG.TEMA_SLOW
        )
        
        last_row = df_calc.iloc[-1]
        daily_last = df_daily_calc.iloc[-1]
        
        daily_dead_cross = daily_last.get('daily_dead_cross', False)
        daily_bull = daily_last.get('daily_trend_bull', True)
        
        # 3. 전략 평가
        order = self.strategy.evaluate_bar(last_row, daily_dead_cross=daily_dead_cross, daily_bull=daily_bull)
        
        if order:
            self.execute_real_order(order)
            
        logger.info(f"[{self.stock_name}] 상태: {self.strategy.position.state.value} | 보유수량: {self.strategy.position.total_qty}주 | 현재가: {last_row['close']:,.0f}")
        
        if self.strategy.position.state == StrategyState.TERMINATED:
            logger.warning(f"[{self.stock_name}] 일봉 테마 5-20 데드크로스로 전략 사이클이 종료되었습니다.")
            self.is_running = False

    def run(self):
        """실시간 감시 루프"""
        self.fetch_historical_candles()
        logger.info(f"[{self.stock_name}] 실시간 60분봉 감시 모니터링을 시작합니다.")
        
        # 데모 실행: 최근 캔들 하나를 시뮬레이션
        sample_candle = {
            'timestamp': datetime.now(),
            'open': self.df_60m['close'].iloc[-1],
            'high': self.df_60m['close'].iloc[-1] * 1.01,
            'low': self.df_60m['close'].iloc[-1] * 0.99,
            'close': self.df_60m['close'].iloc[-1] * 1.005,
            'volume': 50000
        }
        self.on_60m_candle_closed(sample_candle)

if __name__ == '__main__':
    bot = LiveThemeGateBot(stock_code="005930", stock_name="삼성전자", is_mock=True)
    bot.run()
