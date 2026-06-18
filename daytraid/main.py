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

# 9시 초반 종목 수집용
morning_candidates = set()
morning_evaluated = False

def is_market_open():
    """장 운영 시간 확인 (08:00 ~ 20:00)"""
    now = get_kst_now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(8, 0) <= current_time <= dt_time(20, 0)

def is_trading_prohibited():
    """전면 매매(매수/매도) 금지 시간 (08:00~08:04, 09:00~09:04)"""
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    if dt_time(8, 0) <= current_time <= dt_time(8, 4):
        return True
    if dt_time(9, 0) <= current_time <= dt_time(9, 4):
        return True
    return False

def is_buy_prohibited():
    """매수 금지 시간 (전면 매매 금지 시간 + 14:00 이후 신규 진입 금지)"""
    if is_trading_prohibited():
        return True
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    if current_time >= dt_time(14, 0):
        return True
    return False

# 백그라운드 매도 루프를 위한 전역 변수
sold_today = set()
held_codes = []

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

async def on_condition_insert(code: str):
    """조건검색 편입(매수) 신호 수신 시 호출되는 콜백"""
    global held_codes, sold_today, morning_candidates
    
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    
    # 09:00:00 ~ 09:04:00 인 경우 후보군에 넣고 매수 보류
    if dt_time(9, 0) <= current_time <= dt_time(9, 4):
        if code not in morning_candidates:
            morning_candidates.add(code)
            logger.info(f"[{code}] 장 초반 수집 시간(09:00~09:04) 포착됨. 09:04 일괄 평가 후보군에 추가합니다.")
        return

    if code in sold_today:
        logger.info(f"[{code}] 당일 이미 매도한 종목이므로 재진입을 금지합니다.")
        return
        
    if is_buy_prohibited():
        logger.info(f"[{code}] 매수 금지 시간이므로 편입 신호를 무시합니다.")
        return
        
    if len(held_codes) >= 2:
        logger.info(f"[{code}] 최대 보유 종목 수(2종목) 초과! 편입 신호를 무시합니다.")
        return
        
    logger.warning(f"🚀 [매수 신호 발생] 조건검색 편입 도달! ({code})")
    
    # 동기 함수인 client.get_cash_balance 등을 스레드에서 실행
    client = KiwoomClient()
    cash = await asyncio.to_thread(client.get_cash_balance)
    buy_amount = min(cash * 0.95, 3000000) # 예수금의 95% 또는 최대 300만원
    
    # 현재가 조회 (REST API 틱 데이터나 일봉을 가져오는 대신 호가 잔량/틱 사용)
    ticks = await asyncio.to_thread(client.get_tick_data, code, "120", 1)
    if not ticks:
        logger.error(f"[{code}] 현재가를 조회할 수 없어 매수를 취소합니다.")
        return
        
    latest_price = ticks[-1]['close']
    
    if buy_amount >= latest_price and latest_price > 0:
        # 비율: 1 : 5 : 25 (총합 31)
        total_ratio = 31
        
        amt_1st = buy_amount * (1 / total_ratio)
        amt_2nd = buy_amount * (5 / total_ratio)
        amt_3rd = buy_amount * (25 / total_ratio)
        
        price_1st = round_to_tick(latest_price)
        price_2nd = round_to_tick(latest_price * 0.995)
        price_3rd = round_to_tick(latest_price * 0.990)
        
        qty_1st = int(amt_1st // price_1st) if price_1st > 0 else 0
        qty_2nd = int(amt_2nd // price_2nd) if price_2nd > 0 else 0
        qty_3rd = int(amt_3rd // price_3rd) if price_3rd > 0 else 0
        
        # 지정가(00) 분할 매수 발송
        if qty_1st > 0:
            logger.info(f"-> [1차] 지정가 매수: {price_1st}원 x {qty_1st}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_1st, price=price_1st, order_type="00")
            await asyncio.sleep(0.2)
            
        if qty_2nd > 0:
            logger.info(f"-> [2차] 지정가 매수(-0.5%): {price_2nd}원 x {qty_2nd}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_2nd, price=price_2nd, order_type="00")
            await asyncio.sleep(0.2)
            
        if qty_3rd > 0:
            logger.info(f"-> [3차] 지정가 매수(-1.0%): {price_3rd}원 x {qty_3rd}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_3rd, price=price_3rd, order_type="00")
            
        logger.info("분할 매수 주문 전송 완료. 매도 감시 목록에 추가 대기...")

async def on_condition_delete(code: str):
    """조건검색 이탈 신호 수신 시 호출되는 콜백"""
    logger.info(f"📉 [이탈 신호] 조건검색 이탈됨 ({code}) - 매도는 기존 15분봉/손절 로직에 맡깁니다.")

async def check_sell_logic_loop(client: KiwoomClient):
    """주기적으로 보유 종목을 체크하여 매도 로직(15분 데드크로스, -1.5% 하드 손절)을 수행합니다."""
    global held_codes, sold_today
    
    while True:
        if not is_market_open():
            await asyncio.sleep(60)
            continue
            
        try:
            holdings = await asyncio.to_thread(client.get_holdings)
            held_codes_new = [h["code"] for h in holdings]
            held_codes = held_codes_new
        except Exception as e:
            logger.error(f"잔고 조회 중 오류: {e}")
            await asyncio.sleep(10)
            continue
            
        # 신규 편입된 종목이 있다면 DataManager 및 Feeder 생성
        for code in held_codes:
            if code not in DATA_MANAGERS:
                name = client.get_stock_name(code) or code
                logger.info(f"신규 보유 종목 감지 [{name}]. 매도 감시용 15분봉 로딩 중...")
                dm = RealtimeDataManager(code, name, reference_price=0.0)
                
                past_3m = await asyncio.to_thread(client.get_3min_candles, code, 2)
                await asyncio.sleep(0.3)
                past_15m = await asyncio.to_thread(client.get_15min_candles, code, 7)
                await asyncio.sleep(0.3)
                past_daily = await asyncio.to_thread(client.get_daily_candles, code, 10)
                await asyncio.sleep(0.3)
                
                dm.seed_initial_data(past_3m, past_15m, past_daily)
                DATA_MANAGERS[code] = dm
                
                # 안전한 간격(3초)으로 Feeder 구동
                feeder = HybridDataFeeder(client, dm, interval=3.0)
                FEEDERS[code] = feeder
                feeder.start()
                
        # 보유하지 않게 된 종목의 Feeder 정리
        removed = []
        for code in list(DATA_MANAGERS.keys()):
            if code not in held_codes:
                logger.info(f"보유 종목에서 제외됨 [{code}]. 매도 감시 중단.")
                if code in FEEDERS:
                    FEEDERS[code].stop()
                    del FEEDERS[code]
                removed.append(code)
        for code in removed:
            del DATA_MANAGERS[code]
            
        # 매도 감시 실행
        for code, dm in DATA_MANAGERS.items():
            buy_price = 0
            qty = 0
            for h in holdings:
                if h["code"] == code:
                    buy_price = h["buy_price"]
                    qty = h["quantity"]
                    break
                    
            if is_trading_prohibited():
                continue
                
            # 1. 기계적 하드 손절 (-1.5%)
            is_hard_stop = (buy_price > 0 and dm.latest_price <= buy_price * 0.985)
            
            # 2. 15분봉 데드크로스 또는 L선 이탈
            is_dead_cross = strategy.check_sell_signal(dm)
            
            # 3. 진입 캔들 내 하락 제한
            is_entry_candle_stop = False
            if getattr(dm, 'entry_candle_time', None) is not None:
                curr_15m = getattr(dm, 'current_15m_candle', None)
                if curr_15m and curr_15m['time'] == dm.entry_candle_time:
                    if dm.latest_price <= curr_15m['high'] * 0.985:
                        is_entry_candle_stop = True
                        
            if is_hard_stop or is_dead_cross or is_entry_candle_stop:
                if is_entry_candle_stop:
                    reason = "진입 캔들 내 고가대비 -1.5% 하락"
                else:
                    reason = "기계적 하드 손절(-1.5%)" if is_hard_stop else "15분봉 데드크로스/L선 이탈"
                logger.warning(f"🚨 [매도 신호 발생] {dm.name}({code}) - {reason}!")
                
                if qty > 0:
                    logger.info(f"-> {qty}주 시장가 매도 주문 실행")
                    await asyncio.to_thread(client.place_sell_order, code, qty, order_type="03")
                    sold_today.add(code)
                    await asyncio.sleep(1)

        await asyncio.sleep(5) # 5초 주기로 매도 감시 

async def evaluate_morning_candidates_loop(client: KiwoomClient):
    """9시 4분이 되면 장 초반 수집된 종목들 중 상승률 상위 2종목을 선정하여 매수합니다."""
    global morning_candidates, morning_evaluated
    
    while True:
        now = get_kst_now()
        current_time = now.time()
        from datetime import time as dt_time
        
        # 09:04:01 ~ 09:04:30 사이에 한 번만 실행
        if dt_time(9, 4, 1) <= current_time <= dt_time(9, 4, 30) and not morning_evaluated:
            morning_evaluated = True
            
            if morning_candidates:
                logger.info(f"🕒 9시 4분 도달! 장 초반 수집된 {len(morning_candidates)}개 종목 평가 시작...")
                rates = []
                for code in list(morning_candidates):
                    # 일봉 2일치 조회하여 어제 종가와 오늘 현재가로 등락률 계산
                    candles = await asyncio.to_thread(client.get_daily_candles, code, 2)
                    if len(candles) == 2:
                        y_close = candles[0]['close']
                        t_close = candles[1]['close']
                        if y_close > 0:
                            rate = (t_close - y_close) / y_close * 100
                            rates.append((code, rate))
                    elif len(candles) == 1:
                        t_open = candles[0]['open']
                        t_close = candles[0]['close']
                        if t_open > 0:
                            rate = (t_close - t_open) / t_open * 100
                            rates.append((code, rate))
                            
                    await asyncio.sleep(0.2) # API 호출 제한 방지
                
                # 등락률 순으로 내림차순 정렬
                rates.sort(key=lambda x: x[1], reverse=True)
                top_2 = rates[:2]
                
                logger.info(f"📊 장 초반 수집 종목 상승률 순위: {[(c, f'{r:.2f}%') for c, r in rates]}")
                logger.info(f"🏆 최종 선정된 상위 2종목: {[(c, f'{r:.2f}%') for c, r in top_2]}")
                
                for code, rate in top_2:
                    logger.info(f"🚀 [{code}] 상승률 {rate:.2f}% 상위 종목으로 선정되어 매수 진입을 시도합니다.")
                    # 선정된 종목을 기존 매수 로직에 통과시킴
                    await on_condition_insert(code)
                    await asyncio.sleep(0.5)
                
                # 평가가 끝난 후보군은 비워서 초기화
                morning_candidates.clear()
            
        # 08:59에 초기화 (다음날을 위해)
        if dt_time(8, 59, 0) <= current_time <= dt_time(8, 59, 59):
            morning_evaluated = False
            morning_candidates.clear()
            
        await asyncio.sleep(1)

async def async_main():
    logger.info("=========================================")
    logger.info("Daytraid Bot Started (WebSocket HTS Condition Search)")
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
    morning_eval_task = asyncio.create_task(evaluate_morning_candidates_loop(client))

    await asyncio.gather(ws_task, sell_logic_task, morning_eval_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
