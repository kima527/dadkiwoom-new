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

import pandas as pd

def load_my_pick_codes():
    file_path = config.WATCHLIST_FILE
    if not os.path.exists(file_path):
        logger.warning(f"나의픽 파일이 없습니다: {file_path}")
        return []
    try:
        if file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path, encoding='cp949')
            
        if not df.empty:
            last_col = df.columns[-1]
            codes = []
            for val in df[last_col].dropna():
                val_str = str(val).strip()
                if val_str.startswith("'"):
                    val_str = val_str[1:]
                if val_str.isdigit():
                    codes.append(val_str.zfill(6))
            return codes
    except Exception as e:
        logger.error(f"나의픽 파싱 에러: {e}")
    return []

async def preload_seed_data(client):
    global DATA_MANAGERS
    codes = load_my_pick_codes()
    if not codes:
        logger.info("프리로드할 나의픽 종목이 없습니다.")
        return

    logger.info(f"총 {len(codes)}개 나의픽 종목에 대한 장전 시드 데이터 프리로드를 시작합니다...")
    for idx, code in enumerate(codes):
        if code in DATA_MANAGERS:
            continue
            
        name = client.get_stock_name(code) or code
        logger.info(f"[{idx+1}/{len(codes)}] [{name}] 프리패치 중...")
        from data_manager import RealtimeDataManager
        dm = RealtimeDataManager(code, name, reference_price=0.0)
        
        try:
            # 1분봉 장전(어제까지의) 데이터 로드 (1일치만 로드해도 380개)
            past_1m = await asyncio.to_thread(client.get_1min_candles, code, 1)
            await asyncio.sleep(0.3)
            past_daily = await asyncio.to_thread(client.get_daily_candles, code, 10)
            await asyncio.sleep(0.3)
            
            dm.seed_initial_data(past_1m, [], [], past_daily)
            
            DATA_MANAGERS[code] = dm
        except Exception as e:
            logger.error(f"[{name}] 프리패치 실패: {e}")
            
    logger.info("모든 나의픽 타겟 종목의 프리로드가 완료되었습니다.")


# Add local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from kiwoom_client import KiwoomClient
from data_feeder import HybridDataFeeder
from data_manager import RealtimeDataManager
import strategy
from websocket_client import KiwoomWebSocketClient
import telegram_bot  # 신규 텔레그램 봇 모듈

# 전역 상태 관리
DATA_MANAGERS = {}
FEEDERS = {}
held_codes = []
sold_today = set()
first_buy_prices_today = {}
watchlist_codes = set()
MARKET_CRASH_FLAG = False

MAX_HOLDING_STOCKS = 3
MAX_BUY_AMOUNT = 3000000

def is_market_open():
    """장 운영 시간 확인 (08:00 ~ 20:00)"""
    now = get_kst_now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(8, 0) <= current_time <= dt_time(20, 0)

def is_trading_prohibited():
    """전면 매매 금지 시간 (제한 없음)"""
    return False

def is_buy_prohibited():
    """매수 금지 시간 (08:00 이전 및 14:00 이후 신규 진입 금지)"""
    if is_trading_prohibited():
        return True
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    if current_time < dt_time(8, 0) or current_time >= dt_time(14, 0):
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
    global held_codes, first_buy_prices_today, watchlist_codes, MARKET_CRASH_FLAG
    
    if MARKET_CRASH_FLAG:
        logger.warning(f"🚨 [비상 차단] 코스피 폭락 모드 가동 중으로 신규 매수({code})가 차단되었습니다.")
        return
        
    cash = await asyncio.to_thread(client.get_cash_balance)
    buy_amount = min(cash * 0.95, MAX_BUY_AMOUNT)
    
    logger.info(f"[{code}] 매수 준비 - 예수금: {cash:,.0f}원, 할당금액: {buy_amount:,.0f}원, 현재가: {latest_price:,.0f}원")
    
    if buy_amount >= latest_price and latest_price > 0:
        price_1st = round_to_tick(latest_price)
        qty_1st = int(buy_amount // price_1st) if price_1st > 0 else 0
        
        if qty_1st == 0 and buy_amount >= price_1st and price_1st > 0:
            qty_1st = 1
            
        if qty_1st > 0:
            logger.info(f"-> [돌파 매수] 전량 지정가 매수: {price_1st}원 x {qty_1st}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_1st, price=price_1st, order_type="00")
            
            if code not in first_buy_prices_today:
                first_buy_prices_today[code] = latest_price
                
            if code not in held_codes:
                held_codes.append(code)
                
            if code in watchlist_codes:
                watchlist_codes.remove(code)
                
            name = await asyncio.to_thread(client.get_stock_name, code)
            logger.info(f"🎉 [{name}({code})] 전량 매수 주문 전송 완료! 보유 종목으로 전환됩니다.")
            msg = f"✅ [매수 주문 완료]\n종목명: {name}({code})\n주문단가: {price_1st:,.0f}원\n수량: {qty_1st}주\n금액: {price_1st * qty_1st:,.0f}원"
            await telegram_bot.send_message(msg)

async def on_condition_insert(code: str):
    """조건검색 편입 신호 수신 시 콜백"""
    global held_codes, sold_today, watchlist_codes, DATA_MANAGERS, FEEDERS, MARKET_CRASH_FLAG
    
    if not telegram_bot.IS_BOT_ACTIVE:
        return
        
    if MARKET_CRASH_FLAG:
        return
        
    if code in held_codes or code in sold_today or code in watchlist_codes:
        return
        
    if is_buy_prohibited():
        return
        
    if len(held_codes) >= MAX_HOLDING_STOCKS:
        logger.info(f"[{code}] 최대 보유 종목({MAX_HOLDING_STOCKS}개) 초과로 감시망 편입 보류")
        return
        
    logger.info(f"👀 [조건검색 포착] {code} - 감시망(Watchlist) 편입 및 1분봉 데이터 추적 시작")
    watchlist_codes.add(code)
    
    client = KiwoomClient()
    if code not in DATA_MANAGERS:
        name = client.get_stock_name(code) or code
        dm = RealtimeDataManager(code, name, reference_price=0.0)
        
        # 1분봉 데이터 로드 (넉넉히 2페이지)
        past_1m = await asyncio.to_thread(client.get_1min_candles, code, 2)
        await asyncio.sleep(0.3)
        dm.seed_initial_data(past_1m, [], [], [])
        
        DATA_MANAGERS[code] = dm
        feeder = HybridDataFeeder(client, dm, interval=3.0)
        FEEDERS[code] = feeder
        feeder.start()

async def on_condition_delete(code: str):
    """조건검색 이탈 신호 수신 시 콜백"""
    global watchlist_codes, DATA_MANAGERS, FEEDERS
    
    if code in watchlist_codes:
        logger.info(f"🗑️ [조건검색 이탈] {code} - 매수 전 조건 이탈로 감시망에서 삭제 및 자원 회수")
        watchlist_codes.remove(code)
        if code in FEEDERS:
            FEEDERS[code].stop()
            del FEEDERS[code]
        if code in DATA_MANAGERS:
            del DATA_MANAGERS[code]
    else:
        logger.info(f"📉 [이탈 신호] 이미 보유/매도된 종목 이탈됨 ({code})")

last_holdings_sync_time = 0

async def monitor_logic_loop(client: KiwoomClient):
    """주기적으로 감시망(Watchlist) 및 보유 종목(Held)을 체크하여 매수/매도 로직을 수행합니다."""
    global held_codes, sold_today, watchlist_codes, last_holdings_sync_time
    holdings = []
    
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        now_ts = time.time()
        # TR 한도 초과(조회제한) 방지를 위해 계좌 잔고 동기화는 20초에 한 번만 실행
        if now_ts - last_holdings_sync_time >= 20:
            try:
                holdings = await asyncio.to_thread(client.get_holdings)
                # 주문 직후 미체결 상태일 때 held_codes에서 사라지지 않도록 합집합 유지 (일부 보호)
                held_codes_new = [h["code"] for h in holdings]
                for hc in held_codes:
                    if hc not in held_codes_new and hc not in sold_today:
                        # 체결 대기 중일 가능성이 있으므로 유지
                        held_codes_new.append(hc)
                held_codes = held_codes_new
                last_holdings_sync_time = now_ts
            except Exception as e:
                logger.error(f"잔고 조회 중 오류: {e}")
                last_holdings_sync_time = now_ts - 10  # 에러 시 10초 후 재시도
            
        # 미보유/미감시 종목 리소스 정리
        removed = []
        for code in list(DATA_MANAGERS.keys()):
            # 감시망(watchlist)에도 없고 보유(held) 중도 아닌 종목 제거
            if code not in held_codes and code not in watchlist_codes:
                if code in FEEDERS:
                    FEEDERS[code].stop()
                    del FEEDERS[code]
                removed.append(code)
        for code in removed:
            del DATA_MANAGERS[code]
            
        # 감시 실행 (매수 감시 / 매도 감시)
        for code, dm in DATA_MANAGERS.items():
            current_price = dm.latest_price
            if current_price <= 0:
                continue
                
            # --- [1] 매도 감시 (보유 종목) ---
            if code in held_codes:
                # 당일 매도 완료 종목은 중복 주문 방지를 위해 패스
                if code in sold_today:
                    continue
                    
                buy_price = 0
                qty = 0
                for h in holdings:
                    if h["code"] == code:
                        buy_price = h["buy_price"] if "buy_price" in h else h.get("purchase_price", 0)
                        qty = h["quantity"]
                        break
                        
                if is_trading_prohibited() or qty == 0:
                    continue
                
                # 매도 로직 분기 (평상시 vs 코스피 폭락 비상시)
                if MARKET_CRASH_FLAG:
                    is_line_sell, sell_reason = strategy.check_emergency_sell_signal(dm, buy_price)
                else:
                    is_line_sell, sell_reason = strategy.check_1m_dead_cross(dm)
                
                # 안전망: 진입가 대비 -1.5% 하락 시 강제 청산
                is_emergency_stop = (buy_price > 0 and current_price <= buy_price * 0.985)
                
                if is_line_sell or is_emergency_stop:
                    if is_emergency_stop and not is_line_sell:
                        reason = f"긴급 안전망 발동 (진입가 대비 -1.5%) [현재가:{current_price:,.0f}, 평단가:{buy_price:,.0f}]"
                    else:
                        reason = sell_reason
                    logger.warning(f"🚨 [매도 신호 발생] {dm.name}({code}) - {reason}!")
                    
                    sell_price = round_to_tick(current_price * 0.98) if current_price > 0 else current_price
                    logger.info(f"-> {qty}주 시장가 매도 주문 실행 (장전/장후 지정가 전환 대비: {sell_price}원)")
                    
                    # 03 = 시장가
                    await asyncio.to_thread(client.place_sell_order, code, qty, price=sell_price, order_type="03")
                    sold_today.add(code)
                    
                    # 텔레그램 매도 알림 전송
                    msg = telegram_bot.format_trade_message(dm.name, buy_price, current_price)
                    await telegram_bot.send_message(msg)
                    
                    # 미체결 매수 주문이 남아있을 수 있으므로 전량 취소 시도
                    unfilled = await asyncio.to_thread(client.get_unfilled_orders)
                    for order in unfilled:
                        if order["code"] == code and "매수" in order.get("side", ""):
                            logger.info(f"[{code}] 매도 발생에 따른 미체결 매수 주문 일괄 취소")
                            await asyncio.to_thread(client.cancel_order, order["order_no"], code, order["unfilled_qty"])
                            
                    await asyncio.sleep(1)
                    
            # --- [2] 매수 감시 (Watchlist 종목) ---
            elif code in watchlist_codes and code not in sold_today:
                if len(held_codes) < MAX_HOLDING_STOCKS:
                    is_buy_signal = strategy.check_1m_golden_cross(dm)
                    if is_buy_signal:
                        await execute_buy_order(client, code, current_price)
                        await asyncio.sleep(1)

        await asyncio.sleep(3)

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

async def schedule_preload(client):
    """8시 50분에 프리로드를 자동으로 실행하는 스케줄러"""
    while True:
        now = get_kst_now()
        current_time = now.time()
        from datetime import time as dt_time
        
        if getattr(schedule_preload, "done_today", None) == now.date():
            await asyncio.sleep(60)
            continue
            
        target_start = dt_time(8, 50)
        target_end = dt_time(9, 0)
        
        if target_start <= current_time < target_end:
            logger.info("🕒 [스케줄러] 지정된 시간(8:50~9:00)입니다. 시드 데이터 프리로드를 시작합니다.")
            await preload_seed_data(client)
            schedule_preload.done_today = now.date()
        elif current_time < target_start:
            await asyncio.sleep(10)
        else:
            # 9시 이후면 당일은 스킵
            schedule_preload.done_today = now.date()
            await asyncio.sleep(60)

async def market_crash_monitor_loop(client):
    """
    1분 단위로 코스피 지수를 모니터링하여, 1분 안에 -1% 이상 폭락할 경우
    비상 모드를 발동시켜 매수를 중단시킵니다.
    """
    global MARKET_CRASH_FLAG
    logger.info("🚨 KOSPI 1분봉 폭락 감지기(Market Crash Detector) 가동 시작...")
    
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            # 업종 분봉 조회 (001: 코스피, tic_scope: 1분)
            res = await asyncio.to_thread(client.chart_api.industry_minute_chart_request_ka20005, inds_cd='001', tic_scope='1')
            minutes = res.get('inds_min_pole_qry', [])
            
            if len(minutes) >= 2:
                # 최신 1분봉 데이터
                current = minutes[0]
                prev = minutes[1]
                
                cur_price = float(current.get('cur_prc', '0').replace('+', '').replace('-', ''))
                open_price = float(current.get('open_pric', '0').replace('+', '').replace('-', ''))
                
                # 시가 대비 현재가 변동률 계산 (단일 1분봉 내 하락률)
                if open_price > 0:
                    drop_rate = (cur_price - open_price) / open_price * 100.0
                    
                    if drop_rate <= -1.0 and not MARKET_CRASH_FLAG:
                        MARKET_CRASH_FLAG = True
                        msg = f"🚨 [비상] 코스피 1분 만에 {drop_rate:.2f}% 폭락 감지!\n비상 모드를 가동하여 신규 매수를 전면 차단하고 5이평선 초정밀 손절 체제로 전환합니다!"
                        logger.error(msg)
                        await telegram_bot.send_message(msg)
                        
        except Exception as e:
            logger.error(f"Market Crash Monitor Error: {e}")
            
        await asyncio.sleep(60)

async def async_main():
    logger.info("=========================================")
    logger.info("Daytraid Bot Started (WebSocket HTS Condition Search & 1-Min SMA Cross)")
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

    # 당일 매도 완료 종목 재매수 방지 설정
    global sold_today
    filled_orders = client.get_today_filled_orders()
    for order in filled_orders:
        if "매도" in order.get("side", ""):
            sold_today.add(order["code"])
    logger.info(f"당일 매도 완료 종목 초기화: {len(sold_today)}개 종목 재매수 방지")

    # 웹소켓 클라이언트 생성 (타겟 조건식: Real_Traiding)
    ws_client = KiwoomWebSocketClient(
        target_condition_name="Real_Traiding",
        on_insert=on_condition_insert,
        on_delete=on_condition_delete
    )

    # 태스크 병렬 실행
    ws_task = asyncio.create_task(ws_client.run())
    sell_logic_task = asyncio.create_task(monitor_logic_loop(client))
    cancel_task = asyncio.create_task(cancel_unfilled_buy_orders_loop(client))
    telegram_task = asyncio.create_task(telegram_bot.poll_telegram_updates())
    preload_task = asyncio.create_task(schedule_preload(client))
    crash_monitor_task = asyncio.create_task(market_crash_monitor_loop(client))

    # 시작 알림 전송
    await telegram_bot.send_message("🤖 주식 자동매매 봇이 컴퓨터에서 실행되었습니다.\n\n제어 권한을 얻으려면 <b>/auth hani1302</b> 를 입력해주세요.")

    await asyncio.gather(ws_task, sell_logic_task, cancel_task, telegram_task, preload_task, crash_monitor_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
