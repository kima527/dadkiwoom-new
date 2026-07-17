import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import schedule

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from kiwoom_client import KiwoomClient
import telegram_bot
from multi_agent_scanner import ChiefManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

class ThemeEODBot:
    def __init__(self, client: KiwoomClient):
        self.client = client
        self.chief = ChiefManager(client)
        self.target_codes = []
        self.safety_zones = {}
        self.held_stocks = {} # 어제 매수한 종목들 추적용
        
    def calculate_safety_zone(self, stock_code: str) -> float:
        """전문가가 설정한 세이프티존(투매 지지선): 당일 고가 대비 -6%"""
        try:
            # 틱 데이터를 가져와 당일 고가를 계산
            candles = self.client.get_tick_data(stock_code, "120", 300)
            if not candles:
                return 0.0
            
            # 당일 고가 산출 (간단히 틱 데이터의 최근 흐름 중 최고가)
            high_prices = [c['high'] for c in candles]
            if not high_prices:
                return 0.0
                
            daily_high = max(high_prices)
            # 고점 대비 -6% 하락한 가격을 세이프티존으로 설정
            safety_price = daily_high * 0.94
            
            # 호가 단위로 내림 (한국거래소 호가)
            def get_tick_size(price):
                if price < 2000: return 1
                if price < 5000: return 5
                if price < 20000: return 10
                if price < 50000: return 50
                if price < 200000: return 100
                if price < 500000: return 500
                return 1000
                
            tick = get_tick_size(safety_price)
            return (int(safety_price) // tick) * tick
            
        except Exception as e:
            logger.error(f"세이프티 존 계산 중 오류: {e}")
            return 0.0

    def job_afternoon_pickup(self):
        """14:45 ~ 15:15: 대장주 포착 및 세이프티존 그물망 매수"""
        logger.info("🕒 [오후장 픽업] 주도주 종가매매 준비를 시작합니다.")
        
        # 1. 멀티 에이전트 회의를 통한 완벽한 1등 대장주 색출
        best_leader = self.chief.find_ultimate_leader()
        
        if not best_leader:
            msg = "🤖 오늘 시장에 기준을 만족하는 강력한 대장주가 없어 종가매매를 쉽니다."
            logger.info(msg)
            asyncio.run(telegram_bot.send_message(msg))
            return
            
        self.target_codes = [best_leader]
            
        # 2. 투자금 분배
        try:
            cash = self.client.get_cash_balance()
            # 종목당 배정 금액 (예수금의 40%씩 배분)
            alloc_per_stock = cash * 0.4 
        except:
            alloc_per_stock = 1000000 # fallback
            
        # 3. 세이프티존 계산 및 매수 주문(지정가) 실행
        names_dict = self.client.get_stock_names(self.target_codes)
        for code in self.target_codes:
            safety_price = self.calculate_safety_zone(code)
            if safety_price > 0:
                self.safety_zones[code] = safety_price
                qty = int(alloc_per_stock // safety_price)
                if qty > 0:
                    stock_name = names_dict.get(code, code)
                    logger.info(f"👉 [{stock_name}] 세이프티존({safety_price:,.0f}원) 지정가 매수 대기 x {qty}주")
                    self.client.place_buy_order(code, qty, price=safety_price, order_type="00")
                    
                    # 기록 저장
                    self.held_stocks[code] = {"name": stock_name, "buy_price": safety_price, "qty": qty}
                    
                    asyncio.run(telegram_bot.send_message(
                        f"🤖 [종가매매 대장주 포착]\n종목: {stock_name}\n세이프티존 매수대기: {safety_price:,.0f}원\n수량: {qty}주"
                    ))

    def job_cancel_unfilled(self):
        """15:20: 장 마감 동시호가 직전, 안 잡힌 미체결 매수 주문 전부 취소"""
        logger.info("🕒 [동시호가 전] 미체결 매수 주문 일괄 취소")
        try:
            unfilled = self.client.get_unfilled_orders()
            if unfilled:
                for order in unfilled:
                    if "매수" in order.get("side", ""):
                        self.client.cancel_order(order["order_no"], order["code"], order["unfilled_qty"])
            asyncio.run(telegram_bot.send_message("🤖 장 마감이 임박하여 잡히지 않은 세이프티존 대기 물량을 전량 취소했습니다."))
        except Exception as e:
            logger.error(f"미체결 취소 실패: {e}")

    def job_morning_exit(self):
        """09:05: 전일 잡힌 대장주 +4% 익절 또는 본절/손절 탈출"""
        logger.info("🕒 [오전장 탈출] 오버나잇 종목 수익 실현 프로세스 가동")
        try:
            holdings = self.client.get_holdings()
            if not holdings:
                logger.info("보유 중인 종목이 없습니다.")
                return
                
            for h in holdings:
                code = h["code"]
                if code in self.target_codes: # 어제 잡은 대장주인 경우
                    qty = h["quantity"]
                    buy_price = h["buy_price"]
                    current_price = h.get("current_price", buy_price)
                    
                    profit_rate = (current_price - buy_price) / buy_price * 100
                    stock_name = h.get("name", code)
                    
                    # 익절(+4%) 또는 손절(-2%)
                    if profit_rate >= 4.0 or profit_rate <= -2.0:
                        reason = "+4% 목표 달성" if profit_rate > 0 else "-2% 기계적 손절"
                        logger.warning(f"🚨 [{stock_name}] 탈출 조건 충족 ({reason}): 시장가 매도 x {qty}주")
                        self.client.place_sell_order(code, qty, price=0, order_type="03")
                        
                        asyncio.run(telegram_bot.send_message(
                            f"🤖 [종가매매 수익실현]\n종목: {stock_name}\n매도가: {current_price:,.0f}원\n수익률: {profit_rate:,.2f}%\n사유: {reason}"
                        ))
                    else:
                        # 09:10분 경과 시 무조건 시간 청산 (추가 구현 가능)
                        pass
        except Exception as e:
            logger.error(f"오전장 탈출 중 오류: {e}")

    def run(self):
        logger.info("=========================================")
        logger.info("🚀 Theme Leader EOD Bot (종가매매 전용 봇) 가동")
        logger.info("전략: 대장주 스캔 -> 세이프티존(-6%) 매수 -> 익일 +4% 매도")
        logger.info("=========================================")
        
        asyncio.run(telegram_bot.send_message("🤖 주도주 종가매매 봇(Theme EOD Bot)이 실행되었습니다.\n지정된 시간에만 매매를 수행합니다."))
        
        # 시간표 세팅
        schedule.every().day.at("14:45").do(self.job_afternoon_pickup)
        schedule.every().day.at("15:20").do(self.job_cancel_unfilled)
        schedule.every().day.at("09:05").do(self.job_morning_exit)
        
        # 무한 루프
        while True:
            schedule.run_pending()
            time.sleep(1)

if __name__ == "__main__":
    client = KiwoomClient()
    if client.test_connection():
        bot = ThemeEODBot(client)
        bot.run()
