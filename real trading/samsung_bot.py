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

TARGET_CODE = "005930"
TARGET_NAME = "삼성전자"

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
                    logger.info(f"💼 [계좌 상태 점검] 삼성전자 현재 보유 수량: {h['quantity']}주")
                    found_target = True
        
        if not found_target:
            logger.info("💼 [계좌 상태 점검] 삼성전자 현재 보유 수량: 0주 (미보유)")
            
    except Exception as e:
        logger.error(f"예수금/보유수량 초기 조회 실패: {e}")
    
    logger.info(f"[{TARGET_NAME}] 실시간 감시 돌입 (08:00 ~ 15:20)")
    
    target_trading_qty = 0 # 매수/매도 사이클에서 기준이 될 보유 수량 기억 변수
    
    last_holdings_check = 0 # TR 조회 횟수 제한 방지용 타이머
    cached_qty = 0
    cached_buy_price = 0
    
    # 당일 매도 이력 확인 부분 제거 (120틱 스캘핑은 다중 매매를 허용하므로 락다운 필요 없음)
        
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            # HTS 셧다운(TR 과부하) 방지: 1시간 1000회(약 3.6초 1회). 실시간성 확보를 위해 4초 주기 폴링.
            try:
                candles = await asyncio.to_thread(client.get_tick_data, TARGET_CODE, "120", 120)
            except Exception as e:
                logger.error(f"120틱 조회 실패: {e}")
                await asyncio.sleep(4)
                continue
                
            if not candles or len(candles) < 70:
                await asyncio.sleep(4)
                continue
                
            closes = [c['close'] for c in candles]
            current_price = closes[-1]
            
            if current_price <= 0:
                await asyncio.sleep(4)
                continue

            # Pandas를 이용한 지표 계산 (수식 반영)
            df = pd.DataFrame({'Close': closes})
            
            # 매수용 지표: SMA40, SMA60
            df['SMA40'] = df['Close'].rolling(window=40).mean()
            df['SMA60'] = df['Close'].rolling(window=60).mean()
            
            p_sma40 = df['SMA40'].iloc[-2]
            p_sma60 = df['SMA60'].iloc[-2]
            
            sma40 = df['SMA40'].iloc[-1]
            sma60 = df['SMA60'].iloc[-1]
            
            # 매도용 지표: a=avg(c,5); b=avg(c,20); d=avg(c,60);
            df['a'] = df['Close'].rolling(window=5).mean()
            df['b'] = df['Close'].rolling(window=20).mean()
            df['d'] = df['Close'].rolling(window=60).mean()
            
            # 정배열 조건 (a>b && b>d && a>d)
            condition1 = (df['a'] > df['b']) & (df['b'] > df['d']) & (df['a'] > df['d'])
            
            # K=valuewhen(1, a>b && b>d && a>d, C)
            df['K'] = df['Close'].where(condition1)
            df['K'] = df['K'].ffill()
            
            # [버그 수정] 최근 120틱 내에 정배열이 단 한 번도 없었다면 K가 모두 NaN이 됩니다.
            # 이 때 continue로 건너뛰면 비상 손절(-0.5%) 로직마저 무시되므로 0으로 채웁니다.
            df['K'] = df['K'].fillna(0)
            
            if pd.isna(df['SMA60'].iloc[-1]):
                await asyncio.sleep(4)
                continue
                
            # 변곡점 판별 로직: valuewhen(1, K(2)<K(1)&&K(1)>K, K(1))
            df['K_prev1'] = df['K'].shift(1)
            df['K_prev2'] = df['K'].shift(2)
            
            # K선 변곡점 (꼭지점) 형성 확인
            is_peak_formed = (df['K_prev2'] < df['K_prev1']) & (df['K_prev1'] > df['K'])
            
            current_date_str = get_kst_now().strftime("%Y-%m-%d")
                
            # 현재 보유 수량 확인 (TR 조회 한도 방지 30초 갱신)
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
            
            qty = cached_qty
            buy_price = cached_buy_price
            
            if qty > 0:
                if target_trading_qty != qty:
                    logger.info(f"✅ [초기 인식 완료] 삼성전자 현재 보유 수량: {qty}주 (해당 수량으로 매매 사이클 진행)")
                target_trading_qty = qty
                    
            buy_signal = False
            sell_signal = False
            signal_msg = ""
            telegram_msg = ""

            # == 매수 신호 판별 (SMA 40/60 크로스 + 횡보장 필터, 기존 로직 복원) ==
            p10_sma60 = df['SMA60'].iloc[-11]
            current_sma60 = df['SMA60'].iloc[-1]
            sma60_slope_diff = abs(current_sma60 - p10_sma60)
            
            # 500원 변동폭 미만이면 횡보로 간주
            is_sideways = sma60_slope_diff < 500
            
            # 이전 캔들에서는 데드크로스/역배열 상태이다가, 현재 캔들에서 40선이 60선을 돌파할 때
            if (p_sma40 <= p_sma60) and (sma40 > sma60):
                if is_sideways:
                    logger.info(f"🚫 [매수 보류] 120틱 골든크로스이나 횡보장으로 판단되어 매매를 쉼 (SMA60 10캔들 변동폭: {sma60_slope_diff:.2f}원)")
                else:
                    buy_signal = True
                    signal_msg = "120틱 SMA 40/60 골든크로스 발생 (추세 초입)"
                    telegram_msg = "AI 120틱 단타 골든크로스 매수"

            # == 매도 로직 (사용자 핵심 요청: K선 변곡점 포착 시 즉시 매도) ==
            if qty > 0:
                is_panic_sell_stop_loss = False
                
                # 1순위: 비상 손절 (-0.5%)
                if buy_price > 0 and current_price <= buy_price * 0.995:
                    sell_signal = True
                    signal_msg = f"비상 스탑로스: 매수가({buy_price:,}원) 대비 0.5% 하락"
                    is_panic_sell_stop_loss = True
                
                # 2순위: K선 변곡점 (최고점 찍고 꺾이는 순간) 매도
                if not sell_signal and is_peak_formed.iloc[-1]:
                    sell_signal = True
                    peak_val = df['K_prev1'].iloc[-1]
                    signal_msg = f"K선 상승 변곡점(Peak: {peak_val:.0f}원) 찍고 꺾임 -> 즉시 익절/손절"
                
                if sell_signal:
                    logger.warning(f"🚨 [매도 신호] {signal_msg}!")
                    
                    if is_panic_sell_stop_loss:
                        sell_price = round_to_tick(current_price * 0.95) if current_price > 0 else current_price
                        logger.info(f"-> [패닉셀 방어] 즉시 체결 유도 지정가 매도 (현재가 -5%: {sell_price}원) x {qty}주")
                        order_type = "00"
                    else:
                        # 변곡점 매도 시 즉각 탈출을 위해 시장가(03) 사용
                        sell_price = 0
                        logger.info(f"-> [변곡점 매도] 즉시 탈출을 위한 시장가(03) 매도 실행 x {qty}주")
                        order_type = "03"
                    
                    await asyncio.to_thread(client.place_sell_order, TARGET_CODE, qty, price=sell_price, order_type=order_type)
                    
                    msg = telegram_bot.format_trade_message(TARGET_NAME, buy_price, current_price)
                    await telegram_bot.send_message(f"🤖 [삼성전자 매도 알림]\n- 사유: {signal_msg}\n{msg}")
                    
                    unfilled = await asyncio.to_thread(client.get_unfilled_orders)
                    if unfilled:
                        for order in unfilled:
                            if order["code"] == TARGET_CODE and "매수" in order.get("side", ""):
                                await asyncio.to_thread(client.cancel_order, order["order_no"], TARGET_CODE, order["unfilled_qty"])
                            
                    last_holdings_check = 0
                    await asyncio.sleep(4)
                    continue

            # 매수 체결 로직
            if buy_signal and qty == 0:
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
                    logger.info(f"-> [일반 매수] 지정가(00) 매수 실행: {price_1st}원 x {buy_qty}주")
                    await asyncio.to_thread(client.place_buy_order, TARGET_CODE, buy_qty, price=price_1st, order_type="00")
                    await telegram_bot.send_message(f"🤖 [삼성전자 매수 알림]\n- {telegram_msg}\n- 매수가: {price_1st:,}원\n- 수량: {buy_qty}주")
                    
                    last_holdings_check = 0
                    await asyncio.sleep(15) # 매수 후 체결 대기시간 부여
                    continue

            # 빠른 대응을 위해 4초 대기 (TR 1시간 1000회 제한 준수)
            await asyncio.sleep(4)
        except Exception as e:
            logger.error(f"메인 매매 루프 실행 중 에러 발생: {e}", exc_info=True)
            await asyncio.sleep(4)

async def async_main():
    logger.info("=========================================")
    logger.info("Samsung Electronics Dedicated Bot Started")
    logger.info("Strategy: 120-tick SMA 40/60 Scalping (Multiple trades/day)")
    logger.info("=========================================")

    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 시작 알림 전송
    await telegram_bot.send_message("🤖 삼성전자 전용 봇이 컴퓨터에서 단독 실행되었습니다.\n(120틱 스캘핑 모드 가동 중: 다중매매 허용, 손절 -0.5%)")

    # 태스크 병렬 실행
    trading_task = asyncio.create_task(main_trading_loop(client))
    cancel_task = asyncio.create_task(cancel_unfilled_buy_orders_loop(client))
    telegram_task = asyncio.create_task(telegram_bot.poll_telegram_updates())

    await asyncio.gather(trading_task, cancel_task, telegram_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
