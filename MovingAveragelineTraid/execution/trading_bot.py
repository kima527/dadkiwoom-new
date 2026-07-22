import os
import json
import time
import logging
import sys
import pandas as pd

real_trading_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'real trading'))
if real_trading_path not in sys.path:
    sys.path.insert(0, real_trading_path)

from kiwoom_client import KiwoomRealClient
from strategy_sma import calculate_sma_signals
from core_trade_manager import CoreTradeManager
from theme_manager import ThemeManager
from trend_manager import TrendManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self):
        self.client = KiwoomRealClient()
        if not self.client.test_connection():
            logger.error("API Connection Failed")
            sys.exit(1)
        self.watchlist = self.load_watchlist()
        self.tracked_orders = {} 
        
        # 통합 코어 매니저 초기화
        theme_mgr = ThemeManager()
        trend_mgr = TrendManager(self.client)
        self.core_manager = CoreTradeManager(
            theme_manager=theme_mgr,
            trend_manager=trend_mgr,
            max_holdings=5,
            alloc_ratio=0.05
        )
        
        # 추세 서포터 사전 학습 실행
        watchlist_codes = list(self.watchlist.keys())
        if watchlist_codes:
            logger.info(f"사전 학습(Pre-learn)을 위해 {len(watchlist_codes)}개 종목의 추세 데이터를 가져옵니다.")
            trend_mgr.pre_learn(watchlist_codes)
    
    def load_watchlist(self):
        # 우선 조건검색식으로 생성된 sub_watchlist.json 확인
        sub_path = os.path.join(os.path.dirname(__file__), '..', 'sub_watchlist.json')
        if os.path.exists(sub_path):
            logger.info("sub_watchlist.json (조건검색 결과)를 불러옵니다.")
            with open(sub_path, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        # 없으면 기본 watchlist.json 확인
        main_path = os.path.join(os.path.dirname(__file__), '..', 'watchlist.json')
        logger.info("watchlist.json (기본 관심종목)을 불러옵니다.")
        with open(main_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    def manage_unexecuted_orders(self):
        pass # 시장가 매수/매도를 사용하므로 미체결 관리 생략

    def run_cycle(self):
        logger.info("Starting 1-minute cycle evaluation...")
        
        # 1. 3분 경과 미체결 주문 관리 (취소)
        self.manage_unexecuted_orders()
        
        # 2. 계좌 상태 및 잔고 조회
        holdings_list = self.client.get_holdings()
        if holdings_list is None:
            holdings_list = []
        holdings = {h['code']: h for h in holdings_list}
        
        cash = self.client.get_cash_balance()
        # Calculate total balance (cash + stock value)
        stock_value = sum(h['quantity'] * h['current_price'] for h in holdings_list)
        total_balance = cash + stock_value
        
        # ==================================================
        # [매도 로직 (Sell Logic)]
        # ==================================================
        for code, h in list(holdings.items()):
            qty = h['quantity']
            buy_price = h['buy_price']
            current_price = h['current_price']
            name = h['name']
            
            score = self.core_manager.trend_manager.get_trend_score(code)
            candles_15m = None
            # 스윙 전환 조건(80점 이상)일 때만 15분봉 데이터를 요청하여 API 부하를 최소화
            if score >= 80:
                candles_15m = self.client.get_15min_candles(code, last_n_days=5)
                
            candles_1m = self.client.get_1min_candles(code, last_n_days=1)
            
            # CoreTradeManager에게 매도 판단 위임 (다이나믹 스위칭)
            should_sell, reason = self.core_manager.check_sell_condition(code, buy_price, current_price, candles_1m, candles_15m)
            
            if should_sell:
                logger.info(f"📉 매도 신호 발생 [{name}]: {reason}")
                self.client.place_sell_order(code, qty, order_type="03")
                del holdings[code]  # 방금 매도한 종목을 이번 사이클에서 제외
        
        # ==================================================
        # [매수 로직 (Buy Logic)]
        # ==================================================
        
        buy_candidates = []
        
        for code, info in self.watchlist.items():
            # 1. 1종목 1회 매수 및 최대 보유 제한
            qty_to_buy = self.core_manager.calculate_buy_quantity(len(holdings), total_balance, 1) # target price is placeholder
            if qty_to_buy <= 0:
                break
                
            if code in holdings:
                continue
                
            # 2. 이평선 봇 고유의 1차 필터링 (정배열 등)
            candles = self.client.get_1min_candles(code, last_n_days=1)
            if not candles or len(candles) < 20:
                continue
                
            df = pd.DataFrame(candles)
            signals = calculate_sma_signals(df)
            
            if signals['buy']:
                # 3. CoreTradeManager 서포터 평가 (테마, 추세)
                base_reasons = ["SMA 정배열"]
                approved, reason = self.core_manager.evaluate_buy_candidate(code, float(df.iloc[-1]['close']), base_reasons, name=name)
                
                if approved:
                    logger.info(f"Signal found and approved for {info['name']} ({code})")
                
                # Fetch momentum score (Mocked as 1.0 since calculate_momentum may not exist in KiwoomRealClient)
                momentum = 1.0
                score = info['weight'] * momentum
                
                buy_candidates.append({
                    'code': code,
                    'name': info['name'],
                    'score': score,
                    'sma20': signals['sma20']
                })
                
        if not buy_candidates:
            logger.info("No buy signals in this cycle.")
            return
            
        # 1. Priority Filtering: Sort by Theme Weight * Momentum Score
        buy_candidates.sort(key=lambda x: x['score'], reverse=True)
        top_candidate = buy_candidates[0]
        
        logger.info(f"Top candidate selected: {top_candidate['name']} with priority score {top_candidate['score']:.2f}")
        
        # 3. Calculate Limit Order Price (Optional) & Qty
        target_price = top_candidate['sma20'] # 예상 진입가
        
        # 코어 매니저를 통한 최종 비중(수량) 계산
        qty = self.core_manager.calculate_buy_quantity(len(holdings), total_balance, target_price)
        
        # 4. Execute Market Order
        if qty > 0:
            logger.info(f"Executing Buy Order for {top_candidate['name']} (Market Order) x {qty}주 (5% account alloc)")
            result = self.client.place_buy_order(top_candidate['code'], qty, order_type="03") # 03 = 시장가
            if result and result.get('return_code') == 0:
                logger.info(f"Buy Order successful for {top_candidate['code']}")
        else:
            logger.warning("Insufficient funds to execute order.")

if __name__ == "__main__":
    bot = TradingBot()
    bot.run_cycle()
