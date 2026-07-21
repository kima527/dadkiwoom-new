import os
import json
import time
import logging
from kiwoom_api import KiwoomRESTClient
from strategy_sma import calculate_sma_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self):
        self.client = KiwoomRESTClient()
        self.watchlist = self.load_watchlist()
        self.tracked_orders = {} # { order_no: {'code': code, 'qty': qty, 'time': float} }
    
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
        """접수 후 3분(180초)이 경과한 미체결 주문 취소"""
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if current_time - info['time'] > 180:
                logger.info(f"⏳ 3분 경과! 미체결 주문 자동 취소 진행 (종목: {info['code']})")
                self.client.cancel_order(order_no, info['code'], info['qty'])
                del self.tracked_orders[order_no]

    def run_cycle(self):
        logger.info("Starting 15-minute cycle evaluation...")
        
        # 1. 3분 경과 미체결 주문 관리 (취소)
        self.manage_unexecuted_orders()
        
        # 2. 계좌 상태 조회 (중복 매수 방지)
        holdings = self.client.get_account_holdings()
        unexecuted = self.client.get_unexecuted_orders()
        
        buy_candidates = []
        
        for code, info in self.watchlist.items():
            # 1종목 1회 매수 제한 (이미 보유 중이거나, 미체결 대기 중이면 패스)
            if code in holdings:
                logger.info(f"⚠️ 이미 보유 중인 종목입니다. 매수 패스: {info['name']} ({code})")
                continue
                
            is_unexecuted = any(o['code'] == code for o in self.tracked_orders.values())
            if is_unexecuted or any(u.get('stock_code') == code for u in unexecuted):
                logger.info(f"⚠️ 이미 미체결 매수 주문이 있습니다. 매수 패스: {info['name']} ({code})")
                continue
            df = self.client.get_15m_candles(code)
            signals = calculate_sma_signals(df)
            
            if signals['buy']:
                logger.info(f"Signal found for {info['name']} ({code})")
                
                # Fetch momentum score (1 API call per signal)
                momentum = self.client.calculate_momentum(code)
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
        
        # 2. Observation (관망) & Rate Limit Solution
        logger.info("Entering 3-second observation to avoid 추격매수 and Rate Limit...")
        time.sleep(3)
        
        # 3. Calculate Safety Zone (Limit Order Price)
        # This makes 1 API call after the 3 seconds to find the best entry point
        safety_price = self.client.calculate_safety_zone(top_candidate['code'], top_candidate['sma20'])
        
        # 4. Calculate 95% of available cash
        cash = self.client.get_cash_balance()
        alloc_cash = cash * 0.95
        qty = int(alloc_cash // safety_price)
        
        # 5. Execute Limit Order
        if qty > 0:
            logger.info(f"Executing Buy Order for {top_candidate['name']} at {safety_price:,.0f} x {qty}주 (95% cash alloc)")
            order_no = self.client.place_buy_order(top_candidate['code'], qty, price=safety_price, order_type="00") # 00 = 지정가
            if order_no:
                self.tracked_orders[order_no] = {
                    'code': top_candidate['code'],
                    'qty': qty,
                    'time': time.time()
                }
        else:
            logger.warning("Insufficient funds to execute order.")

if __name__ == "__main__":
    bot = TradingBot()
    bot.run_cycle()
