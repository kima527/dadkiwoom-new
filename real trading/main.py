import os
import sys
import time
import logging
import asyncio
from datetime import datetime, timezone, timedelta

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Add local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from kiwoom_client import KiwoomClient
from data_feeder import HybridDataFeeder
from data_manager import RealtimeDataManager
import strategy
from websocket_client import KiwoomWebSocketClient

# 전역 상태 관리
DATA_MANAGERS = {}
FEEDERS = {}
held_codes = []
sold_today = set()
first_buy_prices_today = {}
last_l_lines = {}  # L선 변경 추적용

def is_market_open():
    """장 운영 시간 확인 (09:00 ~ 20:00)"""
    now = get_kst_now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(9, 0) <= current_time <= dt_time(20, 0)

def is_trading_prohibited():
    """전면 매매 금지 시간 (제한 없음)"""
    return False

def is_buy_prohibited():
    """매수 금지 시간 (09:00 이전 및 14:00 이후 신규 진입 금지)"""
    if is_trading_prohibited():
        return True
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    if current_time < dt_time(9, 0) or current_time >= dt_time(14, 0):
        return True
    return False

def get_tick_size(price):
    """한국거래소 호가 단위 산출 (주식)"""
    if price < 2000: return 1
    if price < 5000: return 5
    if price < 20000: return 10
    if price < 50000: return 50
    if price < 200000: return 100
    if price < 500000: return 500
    return 1000

def round_to_tick(price):
    """지정된 가격을 호가 단위에 맞게 내림 처리"""
    tick = get_tick_size(price)
    return (int(price) // tick) * tick

async def execute_buy_order(client, code: str, latest_price: float):
    global held_codes, first_buy_prices_today, DATA_MANAGERS, FEEDERS
    
    cash = await asyncio.to_thread(client.get_cash_balance)
    buy_amount = min(cash * 0.95, 1000000) # 예수금 95% 또는 최대 100만원
    
    logger.info(f"[{code}] 매수 준비 - 예수금: {cash:,.0f}원, 할당금액: {buy_amount:,.0f}원, 현재가: {latest_price:,.0f}원")
    
    if buy_amount >= latest_price and latest_price > 0:
        # 매수 진입 전, DataManager를 미리 생성하여 entry_candle_time 기록
        if code not in DATA_MANAGERS:
            name = client.get_stock_name(code) or code
            logger.info(f"[{name}] 매수 진입 전 15분봉 초기 데이터 로딩 중...")
            dm = RealtimeDataManager(code, name, reference_price=0.0)
            
            past_3m = await asyncio.to_thread(client.get_3min_candles, code, 2)
            await asyncio.sleep(0.3)
            past_5m = await asyncio.to_thread(client.get_5min_candles, code, 3)
            await asyncio.sleep(0.3)
            past_15m = await asyncio.to_thread(client.get_15min_candles, code, 7)
            await asyncio.sleep(0.3)
            past_daily = await asyncio.to_thread(client.get_daily_candles, code, 10)
            
            dm.seed_initial_data(past_3m, past_5m, past_15m, past_daily)
            
            feeder = HybridDataFeeder(client, dm, interval=3.0)
            FEEDERS[code] = feeder
            feeder.start()
            DATA_MANAGERS[code] = dm
            
        dm = DATA_MANAGERS[code]
        if dm.current_15m_candle:
            dm.entry_candle_time = dm.current_15m_candle['time']
        else:
            dm.entry_candle_time = None
            
        # 3분할 매수 (비율 1:5:25)
        total_ratio = 31
        amt_1st = buy_amount * (1 / total_ratio)
        amt_2nd = buy_amount * (5 / total_ratio)
        amt_3rd = buy_amount * (25 / total_ratio)
        
        price_1st = round_to_tick(latest_price)
        price_2nd = round_to_tick(latest_price * 0.997) # -0.3%
        price_3rd = round_to_tick(latest_price * 0.994) # -0.6%
        
        qty_1st = int(amt_1st // price_1st) if price_1st > 0 else 0
        qty_2nd = int(amt_2nd // price_2nd) if price_2nd > 0 else 0
        qty_3rd = int(amt_3rd // price_3rd) if price_3rd > 0 else 0
        
        # 지정가(00) 분할 매수 발송
        if qty_1st > 0:
            logger.info(f"-> [1차] 지정가 매수: {price_1st}원 x {qty_1st}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_1st, price=price_1st, order_type="00")
            await asyncio.sleep(0.2)
            
        if qty_2nd > 0:
            logger.info(f"-> [2차] 지정가 매수(-0.3%): {price_2nd}원 x {qty_2nd}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_2nd, price=price_2nd, order_type="00")
            await asyncio.sleep(0.2)
            
        if qty_3rd > 0:
            logger.info(f"-> [3차] 지정가 매수(-0.6%): {price_3rd}원 x {qty_3rd}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_3rd, price=price_3rd, order_type="00")
            
        if code not in first_buy_prices_today:
            first_buy_prices_today[code] = latest_price
            
        if code not in held_codes:
            held_codes.append(code)
            
        logger.info(f"🎉 [{code}] 3분할 매수 주문 전송 완료! 매도 감시 목록에 추가 대기...")

async def on_condition_insert(code: str):
    """조건검색 편입(매수) 신호 수신 시 호출되는 콜백"""
    global held_codes, sold_today, first_buy_prices_today
    
    if code in held_codes:
        logger.info(f"[{code}] 이미 보유 중인 종목이므로 추가 매수를 금지합니다.")
        return
        
    if is_buy_prohibited():
        logger.info(f"[{code}] 매수 금지 시간이므로 편입 신호를 무시합니다.")
        return
        
    if code in sold_today:
        logger.info(f"[{code}] 당일 이미 매도한 종목이므로 재진입을 금지합니다.")
        return
        
    client = KiwoomClient()
    
    # 1분봉 데이터 조회 (시가 > 종가 확인용)
    candles_1m = await asyncio.to_thread(client.get_1min_candles, code, 2)
    if not candles_1m:
        logger.warning(f"[{code}] 1분봉 데이터 조회 실패로 매수를 취소합니다.")
        return
        
    latest_candle = candles_1m[-1]
    latest_price = latest_candle['close']
    open_price = latest_candle['open']
    
    # [조건 확인] 1분봉 종가 >= 시가 (양봉 또는 보합) 확인
    if latest_price < open_price:
        logger.info(f"[{code}] 조건 미충족: 1분봉 종가({latest_price}) < 시가({open_price}) (음봉). 매수하지 않습니다.")
        return
        
    logger.warning(f"🚀 [매수 신호 발생] 조건검색 편입 & 1분봉 종가 >= 시가 (양봉/보합) 조건 충족! ({code})")
    
    await execute_buy_order(client, code, latest_price)

async def on_condition_delete(code: str):
    """조건검색 이탈 신호 수신 시 콜백"""
    logger.info(f"📉 [이탈 신호] 조건검색 이탈됨 ({code}) - 매도는 기존 손절 로직에 맡깁니다.")

async def check_sell_logic_loop(client: KiwoomClient):
    """주기적으로 보유 종목을 체크하여 매도 로직을 수행합니다."""
    global held_codes, sold_today
    
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            holdings = await asyncio.to_thread(client.get_holdings)
            # 주문 직후 미체결 상태일 때 held_codes에서 사라지지 않도록 합집합 유지 (일부 보호)
            held_codes_new = [h["code"] for h in holdings]
            for hc in held_codes:
                if hc not in held_codes_new and hc not in sold_today:
                    # 체결 대기 중일 가능성이 있으므로 유지
                    held_codes_new.append(hc)
            held_codes = held_codes_new
        except Exception as e:
            logger.error(f"잔고 조회 중 오류: {e}")
            await asyncio.sleep(10)
            continue
            
        # 신규 편입된 종목 DM/Feeder 생성
        for code in held_codes:
            if code not in DATA_MANAGERS:
                name = client.get_stock_name(code) or code
                logger.info(f"신규 보유 종목 감지 [{name}]. 매도 감시용 데이터 로딩 중...")
                dm = RealtimeDataManager(code, name, reference_price=0.0)
                
                past_3m = await asyncio.to_thread(client.get_3min_candles, code, 2)
                await asyncio.sleep(0.3)
                past_5m = await asyncio.to_thread(client.get_5min_candles, code, 3)
                await asyncio.sleep(0.3)
                past_15m = await asyncio.to_thread(client.get_15min_candles, code, 7)
                await asyncio.sleep(0.3)
                past_daily = await asyncio.to_thread(client.get_daily_candles, code, 10)
                
                dm.seed_initial_data(past_3m, past_5m, past_15m, past_daily)
                DATA_MANAGERS[code] = dm
                
                feeder = HybridDataFeeder(client, dm, interval=3.0)
                FEEDERS[code] = feeder
                feeder.start()
                
        # 보유하지 않게 된 종목 정리 (재매수 감시를 위해 당일 매도 종목은 삭제하지 않음)
        removed = []
        for code in list(DATA_MANAGERS.keys()):
            # 당일 매도 이력이 없는 완전 미보유 종목만 제거 (sold_today가 아닌 경우)
            if code not in held_codes and code not in sold_today:
                logger.info(f"완전 미보유 종목 제외됨 [{code}]. 매도 감시 중단.")
                if code in FEEDERS:
                    FEEDERS[code].stop()
                    del FEEDERS[code]
                removed.append(code)
        for code in removed:
            del DATA_MANAGERS[code]
            
        # 매도 및 재매수 감시 실행
        for code, dm in DATA_MANAGERS.items():
            if code in sold_today and code not in held_codes:
                # 재매수 신호 감시
                if strategy.check_rebuy_signal(dm):
                    logger.warning(f"🚀 [재매수 진입] 조건 충족! 당일 매도 종목 재매수 ({code})")
                    # 재매수 진행을 위해 sold_today에서 제거
                    sold_today.remove(code)
                    await execute_buy_order(client, code, dm.latest_price)
                continue
            
            buy_price = 0
            qty = 0
            hold_cur_price = 0
            for h in holdings:
                if h["code"] == code:
                    buy_price = h["buy_price"] if "buy_price" in h else h.get("purchase_price", 0)
                    qty = h["quantity"]
                    hold_cur_price = h["current_price"]
                    break
                    
            if is_trading_prohibited() or qty == 0:
                continue
                
            current_price = dm.latest_price if dm.latest_price > 0 else hold_cur_price
            
            # 보유 중일 경우 L선 변곡(변경) 감지 및 로그 출력
            if qty > 0:
                current_l = strategy.get_current_l_line(list(dm.candles_15m))
                prev_l = last_l_lines.get(code)
                if current_l is not None and current_l != prev_l:
                    logger.info(f"💡 [{dm.name}] 현재 15분봉 L선 변곡점 확인! (L선 목표 매도라인: {current_l:,.0f}원)")
                    last_l_lines[code] = current_l
                    
            # 1. 기계적 하드 손절 (-1.5%)
            is_hard_stop = (buy_price > 0 and current_price <= buy_price * 0.985)
            
            # 2. 15분봉 데드크로스 또는 L선 이탈
            is_dead_cross = strategy.check_sell_signal(dm) if current_price > 0 else False
            
            # 3. 5분봉 L선 이탈 (선제 방어)
            is_5m_early_sell = strategy.check_5m_early_sell_signal(dm) if current_price > 0 else False
            
            # 4. 진입 캔들 특수 룰: 진입한 15분봉 내에서 최고가 대비 -1.5% 하락
            is_entry_candle_stop = False
            if getattr(dm, 'entry_candle_time', None) is not None:
                curr_15m = dm.current_15m_candle
                if curr_15m and curr_15m['time'] == dm.entry_candle_time:
                    if current_price <= curr_15m['high'] * 0.985:
                        is_entry_candle_stop = True

            if is_hard_stop or is_dead_cross or is_5m_early_sell or is_entry_candle_stop:
                if is_entry_candle_stop:
                    reason = "진입 캔들 내 고가대비 -1.5% 하락"
                elif is_5m_early_sell:
                    reason = "5분봉 L선 하향 이탈 (선제 방어)"
                else:
                    reason = "기계적 하드 손절(-1.5%)" if is_hard_stop else "15분봉 데드크로스/L선 이탈"
                logger.warning(f"🚨 [매도 신호 발생] {dm.name}({code}) - {reason}! (현재가: {current_price}, 평단가: {buy_price})")
                
                if qty > 0:
                    sell_price = round_to_tick(current_price * 0.98) if current_price > 0 else None
                    if sell_price == 0: sell_price = current_price
                    logger.info(f"-> {qty}주 시장가 매도 주문 실행 (장전/장후 지정가 전환 대비: {sell_price}원)")
                    
                    # 03 = 시장가
                    await asyncio.to_thread(client.place_sell_order, code, qty, price=sell_price, order_type="03")
                    sold_today.add(code)
                    
                    # 미체결 매수 주문이 남아있을 수 있으므로 전량 취소 시도
                    unfilled = await asyncio.to_thread(client.get_unfilled_orders)
                    for order in unfilled:
                        if order["code"] == code and "매수" in order.get("side", ""):
                            logger.info(f"[{code}] 매도 발생에 따른 미체결 매수 주문(물타기) 일괄 취소")
                            await asyncio.to_thread(client.cancel_order, order["order_no"], code, order["unfilled_qty"])
                            
                    await asyncio.sleep(1)

        await asyncio.sleep(3)

async def cancel_unfilled_buy_orders_loop(client: KiwoomClient):
    """매수 주문 후 1분이 지나도 미체결된 건을 주기적으로 확인하여 취소합니다."""
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            unfilled_list = await asyncio.to_thread(client.get_unfilled_orders)
            if unfilled_list:
                now = get_kst_now()
                for order in unfilled_list:
                    if "매수" in order.get("side", ""):
                        order_time_str = order.get("order_time", "").strip()
                        if len(order_time_str) >= 6:
                            try:
                                from datetime import time as dt_time
                                o_time = dt_time(int(order_time_str[:2]), int(order_time_str[2:4]), int(order_time_str[4:6]))
                                order_dt = datetime.combine(now.date(), o_time).replace(tzinfo=timezone(timedelta(hours=9)))
                                elapsed_seconds = (now - order_dt).total_seconds()
                                
                                if elapsed_seconds >= 60:
                                    logger.warning(f"🕒 [미체결 취소] 매수 주문 1분 경과 취소: {order['name']}({order['code']}), 수량: {order['unfilled_qty']}")
                                    await asyncio.to_thread(client.cancel_order, order["order_no"], order["code"], order["unfilled_qty"])
                                    await asyncio.sleep(0.5)
                            except Exception as e:
                                logger.error(f"주문 시간 파싱 오류: {e}")
        except Exception as e:
            logger.error(f"미체결 주문 조회/취소 루프 중 오류: {e}")
            
        await asyncio.sleep(10)

async def async_main():
    logger.info("=========================================")
    logger.info("Daytraid Bot Started (WebSocket HTS Condition Search & 3-Split Buy)")
    logger.info("=========================================")

    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 기존 보유 종목 초기화
    holdings = client.get_holdings()
    global held_codes
    held_codes = [h["code"] for h in holdings]
    logger.info(f"시작 시점 보유 종목 수: {len(held_codes)}개")

    # 웹소켓 클라이언트 생성 (타겟 조건식: Real_traiding)
    ws_client = KiwoomWebSocketClient(
        target_condition_name="Real_traiding",
        on_insert=on_condition_insert,
        on_delete=on_condition_delete
    )

    # 태스크 병렬 실행
    ws_task = asyncio.create_task(ws_client.run())
    sell_logic_task = asyncio.create_task(check_sell_logic_loop(client))
    cancel_task = asyncio.create_task(cancel_unfilled_buy_orders_loop(client))

    await asyncio.gather(ws_task, sell_logic_task, cancel_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
