import os
import sys
import time
import logging
import asyncio
from datetime import datetime, timezone, timedelta

# Add local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from kiwoom_client import KiwoomClient
import telegram_bot
import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_CODE = None
TARGET_NAME = None

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def is_market_open():
    """장 운영 시간 확인 (08:00 ~ 15:20)"""
    now = get_kst_now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(8, 0) <= current_time <= dt_time(15, 20)

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


async def find_todays_target_stock(client: KiwoomClient):
    global TARGET_CODE, TARGET_NAME
    logger.info("🔍 [주도주 자동 검색] 09:03까지 대기합니다...")
    while True:
        now = get_kst_now()
        from datetime import time as dt_time
        # 장중이 아니면 주말 등 예외처리
        if not is_market_open() and now.time() > dt_time(15, 20):
            logger.info("장이 열려있지 않아 임시로 005930 셋팅")
            TARGET_CODE = "005930"
            TARGET_NAME = "삼성전자"
            return
            
        if now.time() >= dt_time(9, 3) and now.time() <= dt_time(15, 20):
            break
        await asyncio.sleep(1)
        
    logger.info("🔍 [주도주 자동 검색] 조건검색 시작 (거래대금 상위 + 등락률 상위)")
    
    top_value_codes = await asyncio.to_thread(client.get_top_trading_value_stocks, "000", 50)
    top_fluct_dict = await asyncio.to_thread(client.get_top_fluctuation_stocks_with_rates, "000", 50)
    
    if not top_value_codes or not top_fluct_dict:
        logger.error("API 호출 실패로 대안 종목 설정")
        TARGET_CODE = "005930"
        TARGET_NAME = "삼성전자"
        return
        
    blacklist = ["005930", "000660", "373220", "207940"]
    
    best_code = None
    best_name = None
    
    for code in top_value_codes:
        if code in blacklist: continue
        if code in top_fluct_dict:
            info = top_fluct_dict[code]
            if 5.0 <= info["rate"] <= 20.0:
                name = info["name"]
                # ETF, ETN, 스팩, 우선주 등 제외 필터
                exclude_keywords = ["KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO", "ACE", "ETN", "스팩"]
                if any(kw in name for kw in exclude_keywords) or name.endswith("우") or name.endswith("우B"):
                    continue
                    
                best_code = code
                best_name = name
                break
                
    if best_code:
        TARGET_CODE = best_code
        TARGET_NAME = best_name
        logger.info(f"🎯 [오늘의 타겟 확정] {TARGET_NAME} ({TARGET_CODE}) - 거래대금 상위 & 등락률 {top_fluct_dict[best_code]['rate']}%")
        await telegram_bot.send_message(f"🎯 [오늘의 주도주 타겟 확정]\n- 종목명: {TARGET_NAME} ({TARGET_CODE})\n- 지금부터 120틱 스캘핑 감시를 시작합니다!")
    else:
        logger.error("조건에 맞는 종목이 없어 기본 종목으로 시작")
        TARGET_CODE = "005930"
        TARGET_NAME = "삼성전자"

async def cancel_unfilled_buy_orders_loop(client: KiwoomClient):
    """미체결된 건을 주기적으로 확인하여 취소 (1분 경과 시)"""
    while True:
        if TARGET_CODE is None or not is_market_open():
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
    global TARGET_CODE, TARGET_NAME
    if TARGET_CODE is None:
        await find_todays_target_stock(client)
        
    logger.info(f"🤖 [{TARGET_NAME} 전용 로직] 데이터 초기화 및 모니터링 시작...")
    
    logger.info(f"[{TARGET_NAME}] 120틱 데이터 감시 전 계좌 상태 점검 중...")
    
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
                    logger.info(f"💼 [계좌 상태 점검] {TARGET_NAME} 현재 보유 수량: {h['quantity']}주")
                    found_target = True
        
        if not found_target:
            logger.info("💼 [계좌 상태 점검] {TARGET_NAME} 현재 보유 수량: 0주 (미보유)")
            
    except Exception as e:
        logger.error(f"예수금/보유수량 초기 조회 실패: {e}")
    
    logger.info(f"[{TARGET_NAME}] 실시간 감시 돌입 (08:00 ~ 15:20)")
    
    target_trading_qty = 0 # 매수/매도 사이클에서 기준이 될 보유 수량 기억 변수
    
    last_holdings_check = 0 # TR 조회 횟수 제한 방지용 타이머
    cached_qty = 0
    cached_buy_price = 0
    
    # 당일 매도 이력 확인 부분 제거 (120틱 스캘핑은 다중 매매를 허용하므로 락다운 필요 없음)
        
    while True:
        if TARGET_CODE is None or not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            # HTS 셧다운(TR 과부하) 방지를 위해 15초 주기로 120틱 차트 조회 (서버 직접 호출)
            try:
                candles = await asyncio.to_thread(client.get_tick_data, TARGET_CODE, "120", 75)
            except Exception as e:
                logger.error(f"120틱 조회 실패: {e}")
                await asyncio.sleep(15)
                continue
                
            if not candles or len(candles) < 75: # SMA 60 계산 + 기울기 비교를 위해 넉넉히 대기
                await asyncio.sleep(15)
                continue
                
            closes = [c['close'] for c in candles]
            current_price = closes[-1]
            
            if current_price <= 0:
                await asyncio.sleep(3)
                continue

            # Pandas를 이용한 이동평균 지표 계산 (SMA 20, 40, 60)
            df = pd.DataFrame({'Close': closes})
            
            df['SMA20'] = df['Close'].rolling(window=20).mean()
            df['SMA40'] = df['Close'].rolling(window=40).mean()
            df['SMA60'] = df['Close'].rolling(window=60).mean()
            
            p_sma40 = df['SMA40'].iloc[-2]
            p_sma60 = df['SMA60'].iloc[-2]
            
            sma40 = df['SMA40'].iloc[-1]
            sma60 = df['SMA60'].iloc[-1]
            
            if pd.isna(df['SMA60'].iloc[-1]):
                await asyncio.sleep(3)
                continue
                
            current_date_str = get_kst_now().strftime("%Y-%m-%d")
                
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
                    logger.info(f"✅ [초기 인식 완료] {TARGET_NAME} 현재 보유 수량: {qty}주 (해당 수량으로 매매 사이클이 진행됩니다)")
                target_trading_qty = qty # 현재 보유 수량을 기억 (매도 후 다시 매수할 때 사용)
                    
            # == 매수 신호 판별 (SMA 40/60 크로스 + 횡보장 필터, 다중매매 허용) ==
            buy_signal = False
            signal_msg = ""
            telegram_msg = ""
            
            # 횡보장 감지 (SMA 60 기울기 활용)
            # 120틱 기준 10캔들 전과 비교
            p10_sma60 = df['SMA60'].iloc[-11]
            current_sma60 = df['SMA60'].iloc[-1]
            sma60_slope_diff = abs(current_sma60 - p10_sma60)
            
            # 500원(요청하신 기준) 변동폭 미만이면 횡보로 간주
            is_sideways = sma60_slope_diff < 500
            
            # 이전 캔들에서는 데드크로스/역배열 상태이다가, 현재 캔들에서 40선이 60선을 돌파할 때
            if (p_sma40 <= p_sma60) and (sma40 > sma60):
                if is_sideways:
                    logger.info(f"🚫 [매수 보류] 120틱 골든크로스이나 횡보장으로 판단되어 매매를 쉼 (SMA60 10캔들 변동폭: {sma60_slope_diff:.2f}원)")
                else:
                    buy_signal = True
                    signal_msg = "120틱 SMA 40/60 골든크로스 발생 (추세 초입)"
                    telegram_msg = "AI 120틱 단타 골든크로스 매수"

            # == 매수 로직 ==
            if buy_signal:
                if qty == 0: # 미보유 상태일 때만 매수
                    logger.warning(f"🚀 [매수 신호] {signal_msg}!")
                    
                    price_1st = round_to_tick(current_price)
                    buy_qty = target_trading_qty
                    
                    if buy_qty == 0:
                        cash = await asyncio.to_thread(client.get_cash_balance)
                        buy_amount = min(cash * 0.95, 10000000) # 최대 천만원 기본 설정
                        buy_qty = int(buy_amount // price_1st) if price_1st > 0 else 0
                        if buy_qty == 0 and buy_amount >= price_1st and price_1st > 0:
                            buy_qty = 1
                        
                    if buy_qty > 0:
                        logger.info(f"-> 전량 지정가 매수 실행: {price_1st}원 x {buy_qty}주")
                        await asyncio.to_thread(client.place_buy_order, TARGET_CODE, buy_qty, price=price_1st, order_type="00")
                        await telegram_bot.send_message(f"🤖 [{TARGET_NAME} 매수 알림]\n- {telegram_msg}\n- 매수가: {price_1st:,}원\n- 수량: {buy_qty}주")
                        
                        last_holdings_check = 0
                        await asyncio.sleep(15)
                        continue

            # == 매도 로직 ==
            if qty > 0:
                sell_signal = False
                signal_msg = ""
                is_panic_sell_stop_loss = False
                
                # 1순위: 비상 손절 (-0.5%)
                if buy_price > 0 and current_price <= buy_price * 0.995:
                    sell_signal = True
                    signal_msg = f"비상 스탑로스: 매수가({buy_price:,}원) 대비 0.5% 하락"
                    is_panic_sell_stop_loss = True
                
                # 2순위: 120틱 데드크로스 익절/손절
                if not sell_signal:
                    if (p_sma40 >= p_sma60) and (sma40 < sma60):
                        sell_signal = True
                        signal_msg = "120틱 SMA 40/60 데드크로스 발생 (추세 이탈)"
                
                if sell_signal:
                    logger.warning(f"🚨 [매도 신호] {signal_msg}!")
                    
                    if is_panic_sell_stop_loss:
                        sell_price = round_to_tick(current_price * 0.95) if current_price > 0 else current_price
                        logger.info(f"-> [패닉셀 방어] 즉시 체결 유도 지정가 매도 (현재가 -5%: {sell_price}원) x {qty}주")
                    else:
                        tick_size = get_tick_size(current_price)
                        sell_price = current_price - (tick_size * 2) if current_price > 0 else current_price
                        logger.info(f"-> [일반 매도] 지정가 매도 주문 실행 (현재가 -2호가: {sell_price}원) x {qty}주")
                    
                    await asyncio.to_thread(client.place_sell_order, TARGET_CODE, qty, price=sell_price, order_type="00")
                    
                    # 텔레그램 매도 알림 전송
                    msg = telegram_bot.format_trade_message(TARGET_NAME, buy_price, current_price)
                    await telegram_bot.send_message(f"🤖 [{TARGET_NAME} 매도 알림]\n- 사유: {signal_msg}\n{msg}")
                    
                    # 미체결 매수 주문 일괄 취소
                    unfilled = await asyncio.to_thread(client.get_unfilled_orders)
                    if unfilled:
                        for order in unfilled:
                            if order["code"] == TARGET_CODE and "매수" in order.get("side", ""):
                                logger.info("매도 발생에 따른 기존 미체결 매수 주문 취소")
                                await asyncio.to_thread(client.cancel_order, order["order_no"], TARGET_CODE, order["unfilled_qty"])
                            
                    # 다중 매매 허용이므로 last_sell_date_str 락다운 제거됨
                    
                    # 매도 후 빠른 수량 갱신을 위해 타이머 리셋
                    last_holdings_check = 0
                    
                    # 중복 주문 방지 및 TR 제한 방어를 위해 15초 대기
                    await asyncio.sleep(15)
                    continue
            
            # 다음 루프 대기 (HTS 셧다운 방지를 위해 15초 대기)
            await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"메인 매매 루프 실행 중 에러 발생: {e}", exc_info=True)
            await asyncio.sleep(15)

async def async_main():
    logger.info("=========================================")
    logger.info("Auto Momentum Scalper Bot Started")
    logger.info("Strategy: 120-tick SMA 40/60 Scalping (Multiple trades/day)")
    logger.info("=========================================")

    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 시작 알림 전송
    await telegram_bot.send_message("🤖 자동 주도주 사냥 스캘핑 봇이 시작되었습니다.\n(120틱 스캘핑 모드 가동 중: 다중매매 허용, 손절 -0.5%)")

    # 태스크 병렬 실행
    trading_task = asyncio.create_task(main_trading_loop(client))
    cancel_task = asyncio.create_task(cancel_unfilled_buy_orders_loop(client))
    telegram_task = asyncio.create_task(telegram_bot.poll_telegram_updates())

    await asyncio.gather(trading_task, cancel_task, telegram_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
