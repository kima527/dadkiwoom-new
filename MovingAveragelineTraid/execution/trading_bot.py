import os
import sys
import json
import time
import asyncio
import logging
from real_api_adapter import RealAPIAdapter
from strategy_sma_breakout import calculate_sma_breakout_signals, TradeState, get_tick_size
from theme_manager import ThemeManager
from datetime import datetime, time as dtime

# real trading 폴더의 websocket_client를 가져오기 위한 경로 추가
real_trading_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'real trading'))
if real_trading_path not in sys.path:
    sys.path.insert(0, real_trading_path)

from websocket_client import KiwoomWebSocketClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self, condition_name="Traiding"):
        self.client = RealAPIAdapter()
        self.condition_name = condition_name
        self.watchlist = {}
        
        # 오프라인 관심종목(watchlist.json) 로드 삭제 - 오직 실시간 조건검색으로만 종목 편입

        self.tracked_orders = {} # { order_no: {'code': code, 'qty': qty, 'time': float} }
        self.theme_manager = ThemeManager()
        self.theme_manager.load_top_themes(limit=30)
        
        # ===== 신규: 돌파 전략 상태 관리 =====
        self.trade_states = {}       # { code: TradeState }
        self.setup_phase_done = False  # 장 초반 5분봉 수집 완료 여부
        
        self.api_lock = asyncio.Lock() # API 동시 호출 방지용 락
    
    async def on_insert(self, code: str):
        logger.info(f"🟢 [조건검색 편입] 종목코드: {code}")
        if code not in self.watchlist:
            name = await asyncio.to_thread(self.client.get_stock_name, code)
            self.watchlist[code] = {
                'name': name,
                'weight': 1.0 # 기본 가중치 부여
            }
            logger.info(f"✅ 관심종목 추가 완료: {name} ({code})")
            
            # 초기 세팅이 끝난 상태라면, 새로 편입된 종목도 즉시 고점/손절선 세팅
            if self.setup_phase_done and code not in self.trade_states:
                try:
                    async with self.api_lock:
                        df = await asyncio.to_thread(self.client.get_1m_candles, code)
                        await asyncio.sleep(0.25)  # API Rate Limit 보호
                    if df is not None and not df.empty and len(df) >= 5:
                        first_5 = df.iloc[:5]
                        max_idx = first_5['high'].idxmax()
                        max_candle = first_5.loc[max_idx]
                        state = TradeState(int(max_candle['high']), int(max_candle['low']))
                        self.trade_states[code] = state
                        logger.info(f"📐 [{name}] 실시간 편입 종목 초기 세팅 완료: 고점 {int(max_candle['high']):,}원")
                except Exception as e:
                    logger.error(f"❌ [{name}] 실시간 편입 종목 세팅 에러: {e}")

    async def on_delete(self, code: str):
        logger.info(f"🔴 [조건검색 이탈] 종목코드: {code}")
        if code in self.watchlist:
            name = self.watchlist[code]['name']
            del self.watchlist[code]
            logger.info(f"❌ 관심종목 제거 완료: {name} ({code})")

    async def manage_unexecuted_orders(self):
        """접수 후 3분(180초)이 경과한 미체결 주문 취소"""
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if current_time - info['time'] > 180:
                logger.info(f"⏳ 3분 경과! 미체결 주문 자동 취소 진행 (종목: {info['code']})")
                await asyncio.to_thread(self.client.cancel_order, order_no, info['code'], info['qty'])
                del self.tracked_orders[order_no]

    async def setup_initial_highs(self):
        """
        장 초반 첫 5개 1분봉을 가져와서 종목별 초기 고점(initial_high)과
        최고점봉의 최저점(stop_loss)을 세팅합니다.
        09:05 이후에 한 번만 실행됩니다.
        """
        logger.info("📐 [초기 세팅] 첫 5분봉 고점 및 손절선을 수집합니다...")
        for code, info in list(self.watchlist.items()):
            try:
                async with self.api_lock:
                    df = await asyncio.to_thread(self.client.get_1m_candles, code)
                    await asyncio.sleep(0.25)  # API Rate Limit 보호
                if df is None or df.empty or len(df) < 5:
                    logger.warning(f"⚠️ [{info['name']}] 1분봉 데이터 부족, 초기 세팅 스킵")
                    continue
                
                # 첫 5개 캔들 추출 (장 시작부터 시간순으로 정렬되어 있다고 가정)
                first_5 = df.iloc[:5]
                max_idx = first_5['high'].idxmax()
                max_candle = first_5.loc[max_idx]
                
                initial_high = int(max_candle['high'])
                stop_loss = int(max_candle['low'])
                
                state = TradeState(initial_high, stop_loss)
                self.trade_states[code] = state
                
                logger.info(f"✅ [{info['name']}] 초기 고점: {initial_high:,}원 | 손절선(최고점봉 저점): {stop_loss:,}원")
            except Exception as e:
                logger.error(f"❌ [{info['name']}] 초기 세팅 에러: {e}")
        
        self.setup_phase_done = True
        logger.info(f"📐 [초기 세팅 완료] {len(self.trade_states)}개 종목 세팅 완료")

    async def run_cycle(self):
        now = datetime.now().time()
        
        # 장 시작 전이면 대기
        if now < dtime(9, 0):
            logger.info("⏰ 장 시작 전입니다. 대기 중...")
            return
        
        # 09:05 이전이면 아직 첫 5분봉이 완성되지 않았으므로 대기
        if now < dtime(9, 5):
            logger.info("⏰ 첫 5분봉 수집 대기 중... (09:05 이후 초기 세팅 시작)")
            return
        
        # 첫 5분봉 고점/손절선 세팅 (한 번만 실행)
        if not self.setup_phase_done:
            await self.setup_initial_highs()
            if not self.trade_states:
                logger.warning("⚠️ 초기 세팅된 종목이 없습니다. 다음 사이클에 재시도합니다.")
                self.setup_phase_done = False
                return
        
        logger.info(f"🔄 [돌파 전략 사이클] 감시 종목: {len(self.trade_states)}개")
        
        # 1. 3분 경과 미체결 주문 관리 (취소)
        await self.manage_unexecuted_orders()
        
        # 2. 계좌 상태 조회
        holdings = await asyncio.to_thread(self.client.get_account_holdings)
        unexecuted = await asyncio.to_thread(self.client.get_unexecuted_orders)
        
        # ===== 매도 검사 (보유 종목 중 TradeState가 있는 종목) =====
        for code in list(holdings.keys()):
            state = self.trade_states.get(code)
            if not state:
                continue  # 이 전략으로 산 종목이 아니면 건드리지 않음
            
            if not state.is_holding:
                continue  # 봇이 매수한 게 아니라면 스킵
            
            async with self.api_lock:
                df_sell = await asyncio.to_thread(self.client.get_1m_candles, code)
                await asyncio.sleep(0.25)  # API Rate Limit 보호
            if df_sell is None or df_sell.empty or len(df_sell) < 10:
                continue
            
            signals = calculate_sma_breakout_signals(df_sell, state)
            
            if signals.get('sell'):
                sell_reason = signals.get('sell_reason', '매도')
                hold_info = holdings[code]
                qty_sell = hold_info if isinstance(hold_info, int) else hold_info.get('qty', 1)
                name = self.watchlist.get(code, {}).get('name', code)
                
                logger.info(f"🔴 [{name}] 매도 신호! 사유: {sell_reason}")
                await asyncio.to_thread(self.client.place_sell_order, code, qty_sell, price=0, order_type="03")  # 시장가 매도
                state.is_holding = False
                # 재매수를 위해 price_dropped_below_high는 리셋하지 않음 (다음 사이클에서 체크)
        
        # ===== 매수 검사 (감시 종목 전체) =====
        if len(holdings) >= 10:
            logger.info("⚠️ 최대 보유 종목 수(10개)에 도달. 신규 매수 탐색 스킵.")
            return
        
        for code, state in list(self.trade_states.items()):
            if state.is_holding:
                continue  # 이미 보유 중
            
            # 이미 보유 중이거나 미체결 대기 중이면 패스
            if code in holdings:
                continue
            is_unexecuted = any(o['code'] == code for o in self.tracked_orders.values())
            if is_unexecuted or any(u.get('stock_code') == code for u in unexecuted):
                continue
            
            info = self.watchlist.get(code, {})
            name = info.get('name', code)
            
            async with self.api_lock:
                df = await asyncio.to_thread(self.client.get_1m_candles, code)
                await asyncio.sleep(0.25)  # API Rate Limit 보호
            if df is None or df.empty or len(df) < 10:
                continue
            
            signals = calculate_sma_breakout_signals(df, state)
            
            if signals.get('buy'):
                buy_reason = signals.get('buy_reason', '매수')
                buy_price = signals.get('price', df.iloc[-1]['close'])
                
                logger.info(f"🟢 [{name}] 매수 신호! 사유: {buy_reason} | 목표가: {int(buy_price):,}원")
                
                # 3초 관망 (추격매수 방지 & API Rate Limit 회피)
                await asyncio.sleep(3)
                
                qty = 1  # 우선 1주 고정
                
                # 지정가 주문 (돌파가 기준)
                tick_size = get_tick_size(int(buy_price))
                limit_price = int((int(buy_price) // tick_size) * tick_size)
                
                logger.info(f"🚀 [{name}] 매수 주문 전송: {limit_price:,}원 x {qty}주")
                order_no = await asyncio.to_thread(
                    self.client.place_buy_order, code, qty, price=limit_price, order_type="00"
                )
                if order_no:
                    self.tracked_orders[order_no] = {
                        'code': code,
                        'qty': qty,
                        'time': time.time()
                    }
                    state.is_holding = True
                    state.has_traded_today = True
                    logger.info(f"✅ [{name}] 매수 체결 대기 중 (주문번호: {order_no})")
                else:
                    logger.warning(f"⚠️ [{name}] 매수 주문 실패. 포지션 유지하지 않음.")            
    async def start(self):
        """비동기 스케줄러: 1분마다 run_cycle을 실행"""
        logger.info("="*50)
        logger.info(" 🚀 [돌파 전략 봇] 시작")
        logger.info(" 전략: 초반 5분봉 고점 돌파 + 3-10 이평선 교차")
        logger.info("="*50)
        
        # 조건검색식 실시간 수신을 위한 웹소켓 클라이언트 시작
        self.ws_client = KiwoomWebSocketClient(
            target_condition_name=self.condition_name,
            on_insert=self.on_insert,
            on_delete=self.on_delete
        )
        asyncio.create_task(self.ws_client.run())
            
        # 최초 1회 실행
        await self.run_cycle()
        
        while True:
            await asyncio.sleep(60)
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"run_cycle 에러: {e}")

async def main():
    bot = TradingBot()
    
    # 웹소켓 조건검색 연동을 포함한 봇의 스케줄러 실행
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
