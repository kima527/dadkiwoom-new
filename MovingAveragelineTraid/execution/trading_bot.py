import os
import sys
import json
import time
import asyncio
import logging
from real_api_adapter import RealAPIAdapter
from utils import TradeState, get_tick_size
from strategy_wma_golden_cross import calculate_wma_breakout_signals
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
        
        self.tracked_orders = {} # { order_no: {'code': code, 'qty': qty, 'time': float, 'order_type': str} }
        
        # 전략 상태 관리
        self.trade_states = {}       # { code: TradeState }
        
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
            
            # 종목이 편입되면 즉시 상태 객체 생성 (다음 run_cycle에서 즉각 매수 가능하도록)
            if code not in self.trade_states:
                self.trade_states[code] = TradeState()

    async def on_delete(self, code: str):
        logger.info(f"🔴 [조건검색 이탈] 종목코드: {code}")
        if code in self.watchlist:
            name = self.watchlist[code]['name']
            del self.watchlist[code]
            logger.info(f"❌ 관심종목 제거 완료: {name} ({code})")

    def load_states(self):
        state_file = os.path.join(os.path.dirname(__file__), "trade_states.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for code, state_dict in data.items():
                        self.trade_states[code] = TradeState.from_dict(state_dict)
                logger.info(f"💾 이전 상태 정보를 로드했습니다. ({len(self.trade_states)}개 종목)")
            except Exception as e:
                logger.error(f"상태 정보 로드 실패: {e}")

    def save_states(self):
        state_file = os.path.join(os.path.dirname(__file__), "trade_states.json")
        try:
            data = {code: state.to_dict() for code, state in self.trade_states.items()}
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"상태 정보 저장 실패: {e}")

    async def manage_unexecuted_orders(self):
        """접수 후 3분(180초)이 경과한 미체결 주문 취소"""
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if current_time - info['time'] > 180:
                logger.info(f"⏳ 3분 경과! 미체결 주문 자동 취소 진행 (종목: {info['code']})")
                async with self.api_lock:
                    await asyncio.to_thread(self.client.cancel_order, order_no, info['code'], info['qty'])
                del self.tracked_orders[order_no]
                
                # 미체결 취소 시 상태 리셋
                state = self.trade_states.get(info['code'])
                if state:
                    order_type = info.get('order_type', 'buy')  # 'buy_1','buy_2','buy_3','buy_re' 또는 'add_buy'
                    if order_type.startswith('buy'):
                        # 분할매수 주문이 취소된 경우: 재매수 가능하도록 상태 리셋
                        state.first_buy_candle_time = None
                        state.first_qty = 0
                    elif order_type == 'add_buy':
                        # 2차 추가매수가 취소된 경우: 추가매수 기회는 소진된 것으로 처리
                        state.added_on = True

    async def run_cycle(self):
        now = datetime.now().time()
        
        # 장 시작 전이면 대기
        if now < dtime(9, 0):
            logger.info("⏰ 장 시작 전입니다. 대기 중...")
            return
        
        logger.info(f"🔄 [전략 감시 사이클] 감시 종목: {len(self.trade_states)}개")
        
        # 1. 미체결 주문 관리
        await self.manage_unexecuted_orders()
        
        # 2. 계좌 상태 조회
        holdings = await asyncio.to_thread(self.client.get_account_holdings)
        unexecuted = await asyncio.to_thread(self.client.get_unexecuted_orders)
        
        # 3. 체결된 주문을 tracked_orders에서 제거 (5초 유예)
        unexecuted_codes = [u.get('stock_code') for u in unexecuted]
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if info['code'] not in unexecuted_codes and (current_time - info['time'] > 5):
                logger.info(f"✅ 주문 체결(또는 취소) 확인됨: 종목 {info['code']}, 주문번호 {order_no}")
                del self.tracked_orders[order_no]
                
        # 4. 잔고에서 사라진 종목 처리 (매도 체결 완료)
        for code, state in list(self.trade_states.items()):
            if state.is_holding and code not in holdings:
                is_sell_unexecuted = any(o['code'] == code and o.get('order_type') == 'sell' for o in self.tracked_orders.values())
                if not is_sell_unexecuted:
                    logger.info(f"✅ 잔고 소진 확인 (매도 체결 완료): {code}")
                    state.is_holding = False
                    
        if now >= dtime(15, 20):
            logger.info("⏰ 15:20 이후 (장 마감/동시호가) - 신규 매수/매도 감시를 중단합니다.")
            return
        
        # ===== 매도 및 추가매수 검사 (보유 종목 중 TradeState가 있는 종목) =====
        for code in list(holdings.keys()):
            state = self.trade_states.get(code)
            if not state:
                logger.info(f"🔄 미등록 보유 종목 발견: {code}, 상태를 복구합니다.")
                state = TradeState()
                self.trade_states[code] = state
            
            if not state.is_holding:
                if state.first_buy_candle_time is not None:
                    logger.info(f"✅ 매수 체결 확인: {code} 보유 상태로 전환합니다.")
                    state.is_holding = True
                else:
                    hold_info_sync = holdings[code]
                    sync_qty = hold_info_sync.get('qty', 1) if isinstance(hold_info_sync, dict) else hold_info_sync
                    logger.info(f"🔄 잔고 동기화: 봇 재시작으로 인해 {code}의 보유 상태를 True로 복구합니다. (수량: {sync_qty})")
                    state.is_holding = True
                    state.first_qty = sync_qty
                    state.added_on = True  # 재시작 후에는 추가매수 기회를 소진된 것으로 처리
                
                # 재시작/신규매수 시 initial_breakout_high가 0이면 120봉 고가로 세팅 (재진입 기준 보호)
                if state.initial_breakout_high == 0.0:
                    try:
                        async with self.api_lock:
                            df_sync = await asyncio.to_thread(self.client.get_15m_candles, code)
                            await asyncio.sleep(0.25)
                        if df_sync is not None and not df_sync.empty:
                            lb = min(len(df_sync), 120)
                            h120 = float(df_sync['high'].tail(lb).max())
                            state.initial_breakout_high = h120
                            state.trailing_high = h120
                            state.reentry_qty = sync_qty
                            logger.info(f"🔄 [{code}] initial_breakout_high={h120:,.0f} 복구 완료")
                    except Exception as e:
                        logger.warning(f"⚠️ [{code}] 120봉 고가 복구 실패: {e}")
            
            async with self.api_lock:
                df = await asyncio.to_thread(self.client.get_15m_candles, code)
                await asyncio.sleep(0.25)
            if df is None or df.empty or len(df) < 5:
                continue
            
            hold_info = holdings[code]
            hold_buy_price = hold_info.get('buy_price', 0) if isinstance(hold_info, dict) else 0.0
            
            if hold_buy_price == 0:
                logger.warning(f"⚠️ [{self.watchlist.get(code, {}).get('name', code)}] 매입단가 정보 없음. -3% 손절은 비활성 상태입니다.")

            # 체결강도 분석을 위한 틱 데이터 조회
            async with self.api_lock:
                tick_data = await asyncio.to_thread(self.client.get_tick_data, code)
                await asyncio.sleep(0.15)
            signals = calculate_wma_breakout_signals(df, state, hold_buy_price, tick_data=tick_data)
            name = self.watchlist.get(code, {}).get('name', code)
            
            # 중복 매도 방지 (현재 처리 중인 매도 주문이 있는지 확인)
            is_sell_unexecuted = any(o['code'] == code and o.get('order_type') == 'sell' for o in self.tracked_orders.values())
            if is_sell_unexecuted:
                continue
                
            # 매도 신호 처리
            if signals.get('sell'):
                sell_reason = signals.get('sell_reason', '매도')
                qty_sell = hold_info if isinstance(hold_info, int) else hold_info.get('qty', 1)
                
                logger.info(f"🔴 [{name}] 매도 신호! 사유: {sell_reason}")
                async with self.api_lock:
                    order_no = await asyncio.to_thread(self.client.place_sell_order, code, qty_sell, price=0, order_type="03")  # 시장가 매도
                if order_no:
                    self.tracked_orders[order_no] = {'code': code, 'qty': qty_sell, 'time': time.time(), 'order_type': 'sell'}
                
                state.sold_once = True
                state.trade_ended = False # 재매수를 위해 감시 유지
            
            # 추가매수 신호 처리
            elif signals.get('add_buy'):
                add_buy_reason = signals.get('add_buy_reason')
                add_buy_price = signals.get('price')
                
                qty = state.first_qty if state.first_qty > 0 else 1
                tick_size = get_tick_size(int(add_buy_price))
                limit_price = int((int(add_buy_price) // tick_size) * tick_size)
                
                logger.info(f"🔵 [{name}] 추가매수 신호! 사유: {add_buy_reason} | 목표가: {limit_price:,}원 x {qty}주")
                
                async with self.api_lock:
                    order_no = await asyncio.to_thread(
                        self.client.place_buy_order, code, qty, price=limit_price, order_type="00"
                    )
                if order_no:
                    self.tracked_orders[order_no] = {
                        'code': code,
                        'qty': qty,
                        'time': time.time(),
                        'order_type': 'add_buy'  # 추가매수 표시
                    }
                    state.added_on = True
                    logger.info(f"✅ [{name}] 추가매수 체결 대기 중 (주문번호: {order_no})")
                else:
                    logger.warning(f"⚠️ [{name}] 추가매수 주문 실패. 추가 시도 금지.")
                    state.added_on = True
        
        # ===== 신규 매수 검사 (감시 종목 전체) =====
        # 보유 종목 수 합산하여 4개 제한 체크
        pending_buy_codes = {o['code'] for o in self.tracked_orders.values() if str(o.get('order_type')).startswith('buy')}
        pending_buy_count = len(pending_buy_codes)
        total_positions = len(holdings) + pending_buy_count
        if total_positions >= 4:
            logger.info(f"⚠️ 최대 보유 종목 수(4개)에 도달. (보유: {len(holdings)}개, 매수대기: {pending_buy_count}개) 신규 매수 탐색 스킵.")
            return
            
        is_after_10am = now >= dtime(10, 0)
        
        for code, state in list(self.trade_states.items()):
            if state.is_holding or state.trade_ended:
                continue
            
            # 10시 이후: 재돌파 대기(sold_once) 종목만 검사, 순수 신규 매수는 금지
            if is_after_10am and not state.sold_once:
                continue
            
            # 관심종목(watchlist)에서 이탈한 종목도, 재돌파 대기 중이면 계속 감시
            if code not in self.watchlist and not state.sold_once:
                continue
            
            if code in holdings:
                continue
                
            is_unexecuted = any(o['code'] == code for o in self.tracked_orders.values())
            if is_unexecuted or any(u.get('stock_code') == code for u in unexecuted):
                continue
            
            info = self.watchlist.get(code, {})
            name = info.get('name', code)
            
            async with self.api_lock:
                df = await asyncio.to_thread(self.client.get_15m_candles, code)
                await asyncio.sleep(0.25)
            if df is None or df.empty or len(df) < 5:
                continue
            
            # 체결강도 분석을 위한 틱 데이터 조회
            async with self.api_lock:
                tick_data = await asyncio.to_thread(self.client.get_tick_data, code)
                await asyncio.sleep(0.15)
            signals = calculate_wma_breakout_signals(df, state, tick_data=tick_data)
            
            if signals.get('buy'):
                buy_reason = signals.get('buy_reason', '매수')
                buy_price = signals.get('price', df.iloc[-1]['close'])
                
                if signals.get('is_reentry'):
                    logger.info(f"🔵 [{name}] 재돌파 전량 매수 신호! 사유: {buy_reason}")
                else:
                    logger.info(f"🟢 [{name}] 신규 진입 전량 매수 신호! 사유: {buy_reason}")
                
                buy_amount = 2500000
                tick = get_tick_size(int(buy_price))
                price_limit = int((int(buy_price) // tick) * tick)
                qty = int(buy_amount // price_limit) if price_limit > 0 else 0
                
                if qty > 0:
                    async with self.api_lock:
                        order_no = await asyncio.to_thread(self.client.place_buy_order, code, qty, price=price_limit, order_type="00")
                    if order_no:
                        self.tracked_orders[order_no] = {'code': code, 'qty': qty, 'time': time.time(), 'order_type': 'buy_1'}
                        logger.info(f"✅ [{name}] 매수 대기: {price_limit}원 x {qty}주 (주문번호: {order_no})")
                        
                        state.first_qty = qty
                        state.first_buy_candle_time = df.iloc[-1].name
                        
                        if signals.get('is_reentry'):
                            state.sold_once = False
                        else:
                            state.initial_breakout_high = df['high'].max()
                            state.reentry_qty = qty
                            
        # 사이클 종료 후 상태 저장
        self.save_states()

    async def start(self):
        """비동기 스케줄러: 즉시 매수 처리를 위해 주기를 10초로 단축"""
        logger.info("="*50)
        logger.info(" 🚀 [WMA 15분봉 골든크로스 지지돌파 봇] 시작")
        logger.info(" 전략: 일봉 WMA50 스캐닝 -> 15분봉 지지/돌파 매수 -> 정배열 전고점 전량 익절")
        logger.info("="*50)
        
        self.load_states()
        
        self.ws_client = KiwoomWebSocketClient(
            target_condition_name=self.condition_name,
            on_insert=self.on_insert,
            on_delete=self.on_delete
        )
        asyncio.create_task(self.ws_client.run())
            
        await self.run_cycle()
        
        while True:
            await asyncio.sleep(10) # 10초 주기로 빠르게 갱신
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"run_cycle 에러: {e}")

async def main():
    bot = TradingBot()
    await bot.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
