import os
import sys
import time
import logging
import asyncio
from datetime import datetime, timezone, timedelta

# Add local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from kiwoom_client import KiwoomClient
from data_manager import RealtimeDataManager
from data_feeder import HybridDataFeeder
from indicator import calculate_sma
import telegram_bot

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_CODE = "005930"
TARGET_NAME = "삼성전자"

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def is_market_open():
    """장 운영 시간 확인 (08:00 ~ 20:00)"""
    now = get_kst_now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(8, 0) <= current_time <= dt_time(20, 0)

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

async def cancel_unfilled_buy_orders_loop(client: KiwoomClient):
    """미체결된 건을 주기적으로 확인하여 취소 (1분 경과 시)"""
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            unfilled_list = await asyncio.to_thread(client.get_unfilled_orders)
            if unfilled_list:
                now = get_kst_now()
                for order in unfilled_list:
                    if "매수" in order.get("side", "") and order["code"] == TARGET_CODE:
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
            
        await asyncio.sleep(20) # TR 제한 방지를 위해 20초 주기로 변경

async def main_trading_loop(client: KiwoomClient):
    logger.info(f"🤖 [{TARGET_NAME} 전용 로직] 데이터 초기화 및 모니터링 시작...")
    
    # 1. 데이터 강제 초기화 (누락 방지용 넉넉한 데이터 로드)
    dm = RealtimeDataManager(TARGET_CODE, TARGET_NAME, reference_price=0.0)
    
    logger.info(f"[{TARGET_NAME}] 과거 5분봉 및 일봉 데이터 로드 중...")
    past_3m = await asyncio.to_thread(client.get_3min_candles, TARGET_CODE, 2)
    await asyncio.sleep(0.3)
    past_5m = await asyncio.to_thread(client.get_5min_candles, TARGET_CODE, 10) # 10일치 넉넉히
    await asyncio.sleep(0.3)
    past_15m = await asyncio.to_thread(client.get_15min_candles, TARGET_CODE, 7)
    await asyncio.sleep(0.3)
    past_daily = await asyncio.to_thread(client.get_daily_candles, TARGET_CODE, 10)
    
    dm.seed_initial_data(past_3m, past_5m, past_15m, past_daily)
    
    # 2. 실시간 데이터 피더 시작
    feeder = HybridDataFeeder(client, dm, interval=3.0)
    feeder.start()
    
    # 봇 시작 시 예수금을 한 번 강제로 조회해서 화면에 확실히 띄워줍니다!
    try:
        startup_cash = await asyncio.to_thread(client.get_cash_balance)
        logger.info(f"💰 [계좌 상태 점검] 봇 구동 완료! 현재 예수금: {startup_cash:,.0f}원")
        
        # 보유 수량도 명시적으로 한 번 조회해서 띄워줍니다.
        startup_holdings = await asyncio.to_thread(client.get_holdings)
        found_target = False
        if startup_holdings:
            for h in startup_holdings:
                if h["code"] == TARGET_CODE:
                    logger.info(f"💼 [계좌 상태 점검] 삼성전자 현재 보유 수량: {h['quantity']}주")
                    found_target = True
        
        if not found_target:
            logger.info("💼 [계좌 상태 점검] 삼성전자 현재 보유 수량: 0주 (미보유)")
            
    except Exception as e:
        logger.error(f"예수금/보유수량 초기 조회 실패: {e}")
    
    logger.info(f"[{TARGET_NAME}] 실시간 감시 돌입 (08:00 ~ 20:00)")
    
    target_trading_qty = 0 # 매수/매도 사이클에서 기준이 될 보유 수량 기억 변수
    
    last_holdings_check = 0 # TR 조회 횟수 제한 방지용 타이머
    cached_qty = 0
    cached_buy_price = 0
    
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            # 5분봉 데이터 가져오기
            candles = dm.get_completed_and_current_5m_candles()
            if len(candles) < 25:
                await asyncio.sleep(3)
                continue
                
            closes = [c['close'] for c in candles]
            current_price = dm.latest_price
            
            if current_price <= 0:
                await asyncio.sleep(3)
                continue

            # SMA 3, 24 계산
            sma3_list = calculate_sma(closes, 3)
            sma24_list = calculate_sma(closes, 24)
            
            curr_sma3 = sma3_list[-1]
            curr_sma24 = sma24_list[-1]
            prev_sma3 = sma3_list[-2]
            prev_sma24 = sma24_list[-2]
            
            if (curr_sma3 is None or curr_sma24 is None or prev_sma3 is None or prev_sma24 is None):
                await asyncio.sleep(3)
                continue
                
            # 현재 보유 수량 확인 (TR 조회 한도 1000회/시간 방지를 위해 30초마다 갱신)
            import time as time_module
            now_ts = time_module.time()
            if now_ts - last_holdings_check >= 30:
                holdings = await asyncio.to_thread(client.get_holdings)
                last_holdings_check = now_ts
                
                if holdings is not None:
                    temp_qty = 0
                    temp_buy_price = 0
                    for h in holdings:
                        if h["code"] == TARGET_CODE:
                            temp_qty = h["quantity"]
                            temp_buy_price = h.get("buy_price", 0)
                            break
                    cached_qty = temp_qty
                    cached_buy_price = temp_buy_price
                else:
                    pass
            
            qty = cached_qty
            buy_price = cached_buy_price
            
            if qty > 0:
                if target_trading_qty != qty:
                    logger.info(f"✅ [초기 인식 완료] 삼성전자 현재 보유 수량: {qty}주 (해당 수량으로 매매 사이클이 진행됩니다)")
                target_trading_qty = qty # 현재 보유 수량을 기억 (매도 후 다시 매수할 때 사용)
                    
            # == 매수 신호 판별 (3이평-24이평 골든크로스) ==
            buy_signal = False
            signal_msg = ""
            telegram_msg = ""
            
            is_golden_cross_sma3_sma24 = False
            if prev_sma3 is not None and prev_sma24 is not None and curr_sma3 is not None and curr_sma24 is not None:
                is_golden_cross_sma3_sma24 = (prev_sma3 <= prev_sma24) and (curr_sma3 > curr_sma24)
            
            if is_golden_cross_sma3_sma24:
                buy_signal = True
                signal_msg = f"SMA3이 SMA24 골든크로스 (즉시 매수)"
                telegram_msg = "SMA3-SMA24 골든크로스 매수"

            # == 매수 로직 ==
            if buy_signal:
                if qty == 0: # 미보유 상태일 때만 매수
                    logger.warning(f"🚀 [매수 신호] 5분봉 {signal_msg}!")
                    
                    price_1st = round_to_tick(current_price)
                    
                    # 직전 매도시 기억해둔 수량을 그대로 매수
                    buy_qty = target_trading_qty
                    
                    if buy_qty == 0:
                        # 프로그램 시작 후 한 번도 보유/매도한 적이 없어 수량을 모르는 경우 예수금 기반으로 기본 계산
                        cash = await asyncio.to_thread(client.get_cash_balance)
                        buy_amount = min(cash * 0.95, 1000000)
                        buy_qty = int(buy_amount // price_1st) if price_1st > 0 else 0
                        if buy_qty == 0 and buy_amount >= price_1st and price_1st > 0:
                            buy_qty = 1
                        
                    if buy_qty > 0:
                        logger.info(f"-> 전량 지정가 매수 실행: {price_1st}원 x {buy_qty}주")
                        await asyncio.to_thread(client.place_buy_order, TARGET_CODE, buy_qty, price=price_1st, order_type="00")
                        await telegram_bot.send_message(f"🤖 [삼성전자 매수 알림]\n- {telegram_msg} 발생\n- 매수가: {price_1st:,}원\n- 수량: {buy_qty}주")
                        
                        # 매수 후 빠른 수량 갱신을 위해 타이머 리셋
                        last_holdings_check = 0
                        
                        # 중복 주문 방지를 위해 15초 대기
                        await asyncio.sleep(15)
                        continue

            # == 매도 로직 ==
            elif qty > 0: # 보유 상태일 때만 매도 고려
                sell_signal = False
                signal_msg = ""
                
                # 1순위 매도 조건: SMA3이 SMA24를 데드크로스 (하향 돌파)
                is_dead_cross_sma3_sma24 = False
                if prev_sma3 is not None and prev_sma24 is not None and curr_sma3 is not None and curr_sma24 is not None:
                    is_dead_cross_sma3_sma24 = (prev_sma3 >= prev_sma24) and (curr_sma3 < curr_sma24)
                
                if is_dead_cross_sma3_sma24:
                    sell_signal = True
                    signal_msg = f"SMA3-SMA24 데드크로스 (즉시 매도)"
                
                if sell_signal:
                    logger.warning(f"🚨 [매도 신호] {signal_msg}!")
                    
                    sell_price = round_to_tick(current_price * 0.98) if current_price > 0 else current_price
                    logger.info(f"-> 전량 시장가 매도 주문 실행 (장전/장후 지정가 전환 대비: {sell_price}원) x {qty}주")
                    
                    await asyncio.to_thread(client.place_sell_order, TARGET_CODE, qty, price=sell_price, order_type="03")
                    
                    # 텔레그램 매도 알림 전송
                    msg = telegram_bot.format_trade_message(TARGET_NAME, buy_price, current_price)
                    await telegram_bot.send_message(f"🤖 [삼성전자 매도 알림]\n- 사유: {signal_msg}\n{msg}")
                    
                    # 미체결 매수 주문 일괄 취소
                    unfilled = await asyncio.to_thread(client.get_unfilled_orders)
                    for order in unfilled:
                        if order["code"] == TARGET_CODE and "매수" in order.get("side", ""):
                            logger.info("매도 발생에 따른 기존 미체결 매수 주문 취소")
                            await asyncio.to_thread(client.cancel_order, order["order_no"], TARGET_CODE, order["unfilled_qty"])
                            
                    # 매도 후 빠른 수량 갱신을 위해 타이머 리셋
                    last_holdings_check = 0
                    
                    # 중복 주문 방지를 위해 15초 대기
                    await asyncio.sleep(15)
                    continue
                    
        except Exception as e:
            logger.error(f"메인 매매 루프 실행 중 에러 발생: {e}", exc_info=True)
            
        await asyncio.sleep(3) # 3초마다 갱신

async def async_main():
    logger.info("=========================================")
    logger.info("Samsung Electronics Dedicated Bot Started")
    logger.info("Strategy: 5-min SMA 3/24 Golden/Dead Cross")
    logger.info("=========================================")

    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 시작 알림 전송
    await telegram_bot.send_message("🤖 삼성전자 전용 봇이 컴퓨터에서 단독 실행되었습니다.\n(SMA 3/24 교차 매매 전용)")

    # 태스크 병렬 실행
    trading_task = asyncio.create_task(main_trading_loop(client))
    cancel_task = asyncio.create_task(cancel_unfilled_buy_orders_loop(client))
    telegram_task = asyncio.create_task(telegram_bot.poll_telegram_updates())

    await asyncio.gather(trading_task, cancel_task, telegram_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
