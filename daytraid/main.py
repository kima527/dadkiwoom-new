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

# 9시 초반 종목 수집용 (종목코드: 포착횟수)
morning_candidates = {}

# 당일 매도 이력 (종목코드 저장)
sold_today = set()
sold_loss_today = set() # 손절로 매도한 종목코드 저장
first_buy_prices_today = {} # [NEW] 종목별 당일 최초 진입가 저장
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
    """전면 매매(매수/매도) 금지 시간 (09:00 이전 장전 시간, 09:00~09:04 변동성 심한 시간)"""
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    if current_time < dt_time(9, 0):
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
    global held_codes, sold_today, sold_loss_today, morning_candidates, first_buy_prices_today
    
    now = get_kst_now()
    current_time = now.time()
    from datetime import time as dt_time
    
    # 09:00:00 ~ 09:04:00 인 경우 후보군에 넣고 매수 보류 (횟수 누적)
    if dt_time(9, 0) <= current_time <= dt_time(9, 4):
        morning_candidates[code] = morning_candidates.get(code, 0) + 1
        logger.info(f"[{code}] 장 초반 수집 시간(09:00~09:04) 포착됨. 현재 누적 포착 횟수: {morning_candidates[code]}회")
        return

    # [수정] 사용자의 요청으로 당일 매도한 종목의 재돌파(재진입) 매수를 허용합니다.
    # if code in sold_today:
    #     logger.info(f"[{code}] 당일 이미 매도한 종목이므로 재진입을 금지합니다.")
    #     return
        
    if code in held_codes:
        logger.info(f"[{code}] 이미 보유 중인 종목이므로 추가 매수(불타기)를 금지합니다.")
        return
        
    if is_buy_prohibited():
        logger.info(f"[{code}] 매수 금지 시간이므로 편입 신호를 무시합니다.")
        return
        
    logger.warning(f"🚀 [매수 신호 발생] 조건검색 편입 도달! ({code})")
    
    # 동기 함수인 client.get_cash_balance 등을 스레드에서 실행
    client = KiwoomClient()
    
    # ---------------------------------------------------------
    # 🛡️ 유통주식수 필터링 (무거운 주식 거르기: 6천만 주 이상 제외)
    # ---------------------------------------------------------
    try:
        stock_info = await asyncio.to_thread(client.stock_info_api.basic_stock_information_request_ka10001, stock_code=code)
        if stock_info and stock_info.get("return_code") == 0:
            dstr_stk_k = int(stock_info.get("dstr_stk", "0")) # API 반환 단위: 천 주(1,000주)
            if dstr_stk_k >= 60000: # 60,000 * 1,000 = 60,000,000 (6천만 주)
                logger.warning(f"[{code}] 유통주식수 {dstr_stk_k * 1000:,}주 초과 (무거운 주식) - 파도타기 단타에 부적합하여 편입을 취소합니다.")
                return
    except Exception as e:
        logger.error(f"[{code}] 유통주식수 조회 중 오류 발생: {e}")
        
    cash = await asyncio.to_thread(client.get_cash_balance)
    buy_amount = min(cash * 0.95, 3000000) # 예수금의 95% 또는 최대 300만원
    
    # 현재가 조회 (틱 데이터 1차 시도, 실패 시 1분봉 2차 시도)
    ticks = await asyncio.to_thread(client.get_tick_data, code, "120", 1)
    latest_price = 0
    if ticks:
        latest_price = ticks[-1]['close']
    else:
        logger.warning(f"[{code}] 틱 데이터 조회 실패. 1분봉 데이터로 대체 조회를 시도합니다.")
        candles_1m = await asyncio.to_thread(client.get_1min_candles, code, 1)
        if candles_1m:
            latest_price = candles_1m[-1]['close']
            
    if latest_price == 0:
        logger.error(f"[{code}] 현재가를 틱/1분봉 모두에서 조회할 수 없어 매수를 취소합니다.")
        return
        
    # (HTS 조건검색식에서 이미 돌파 조건을 검증해서 내려주므로, 봇 내부에서 별도의 K선/L선 돌파 재계산은 생략하고 즉시 진입합니다)
    
    # [수정] 손절 후 재매수 금지, 익절 후 재매수 허용 + 첫 매수가 이하 재진입 금지
    if code in sold_today:
        if code in sold_loss_today:
            logger.info(f"[{code}] 재매수 금지: 당일 손절 이력이 있습니다.")
            return
        else:
            if latest_price <= first_buy_prices_today.get(code, 0):
                logger.info(f"[{code}] 재매수 금지 (안전방패): 현재가({latest_price:,.0f}원)가 당일 최초 진입가({first_buy_prices_today.get(code):,.0f}원) 이하입니다. (속임수 하락 패턴)")
                return
            logger.info(f"[{code}] 재매수 허용: 당일 익절 이력이 있으므로 다시 진입합니다!")
    
    logger.info(f"[{code}] 매수 조건 검사 - 예수금: {cash:,.0f}원, 1종목 할당금액: {buy_amount:,.0f}원, 현재가: {latest_price:,.0f}원")
    
    if buy_amount >= latest_price and latest_price > 0:
        # 비율: 1 : 5 : 25 (총합 31)
        total_ratio = 31
        
        amt_1st = buy_amount * (1 / total_ratio)
        amt_2nd = buy_amount * (5 / total_ratio)
        amt_3rd = buy_amount * (25 / total_ratio)
        
        price_1st = round_to_tick(latest_price)
        price_2nd = round_to_tick(latest_price * 0.997) # -0.3% 하락 시
        price_3rd = round_to_tick(latest_price * 0.994) # -0.6% 하락 시
        
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
            logger.info(f"-> [3차] 지정가 매수: {price_3rd}원 x {qty_3rd}주")
            await asyncio.to_thread(client.place_buy_order, code, qty_3rd, price=price_3rd, order_type="00")
            
        if code not in first_buy_prices_today:
            first_buy_prices_today[code] = latest_price
        
        # 보유 종목 리스트 갱신 (리스트로 관리 중이므로 리스트 append 사용)
        if code not in held_codes:
            held_codes.append(code)
            
        logger.info(f"🎉 [{code}] 분할 매수 주문 전송 완료! 매도 감시 목록에 추가 대기...")

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
            hold_cur_price = 0
            for h in holdings:
                if h["code"] == code:
                    buy_price = h["buy_price"]
                    qty = h["quantity"]
                    hold_cur_price = h["current_price"]
                    break
                    
            if is_trading_prohibited():
                continue
                
            # 가격 정보 보정 (데이터가 아직 수신되지 않아 latest_price가 0일 경우 잔고의 현재가 사용)
            current_price = dm.latest_price if dm.latest_price > 0 else hold_cur_price
            
            if getattr(dm, 'max_price_since_buy', 0) == 0:
                dm.max_price_since_buy = buy_price
                
            if current_price > dm.max_price_since_buy:
                dm.max_price_since_buy = current_price
            
            if current_price > 0 and getattr(dm, 'max_price_since_buy', 0) > 0:
                trailing_drop_rate = (current_price - dm.max_price_since_buy) / dm.max_price_since_buy * 100
                if trailing_drop_rate <= -1.0: # -1.0% 이하일 때 출력 (도배 방지)
                    logger.info(f"[{code}] 매도 감시 중 - 현재가: {current_price}, 최고가: {dm.max_price_since_buy}, 하락률: {trailing_drop_rate:.2f}% (청산기준: -1.5%)")

            # 1. 트레일링 스탑 (-1.5%)
            is_trailing_stop = (dm.max_price_since_buy > 0 and current_price > 0 and current_price <= dm.max_price_since_buy * 0.985)
            
            # 2. 15분봉 데드크로스 또는 L선 이탈
            is_dead_cross = strategy.check_sell_signal(dm) if current_price > 0 else False
            
            if is_trailing_stop or is_dead_cross:
                reason = "트레일링 스탑(최고점대비 -1.5%)" if is_trailing_stop else "15분봉 데드크로스/L선 이탈"
                logger.warning(f"🚨 [매도 신호 발생] {dm.name}({code}) - {reason}! (현재가: {current_price}, 평단가: {buy_price})")
                
                if qty > 0:
                    sell_price = round_to_tick(current_price * 0.98) if current_price > 0 else None
                    if sell_price == 0:
                        sell_price = current_price
                    logger.info(f"-> {qty}주 시장가 매도 주문 실행 (장전/장후 지정가 전환 대비: {sell_price}원)")
                    await asyncio.to_thread(client.place_sell_order, code, qty, price=sell_price, order_type="03")
                    
                    sold_today.add(code)
                    # 손실 매도인지 확인하여 sold_loss_today에 추가
                    profit_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
                    if profit_pct < 0:
                        sold_loss_today.add(code)
                        
                    dm.max_price_since_buy = 0  # 초기화
                        
                    await asyncio.sleep(1)

        await asyncio.sleep(5) # 5초 주기로 매도 감시 

async def evaluate_morning_candidates_loop(client: KiwoomClient):
    """9시 4분이 되면 장 초반 수집된 종목들 중 포착 횟수 2회 이상인 종목을 모두 선정하여 매수합니다."""
    global morning_candidates, morning_evaluated
    
    while True:
        now = get_kst_now()
        current_time = now.time()
        from datetime import time as dt_time
        
        # 09:04:01 ~ 09:04:30 사이에 한 번만 실행
        if dt_time(9, 4, 1) <= current_time <= dt_time(9, 4, 30) and not morning_evaluated:
            morning_evaluated = True
            
            # 1회 이하 포착된 종목 제외 (가짜 돌파 필터링)
            valid_candidates = {code: count for code, count in morning_candidates.items() if count >= 2}
            
            if valid_candidates:
                logger.info(f"🕒 9시 4분 도달! 장 초반 수집 종목 중 2회 이상 포착된 {len(valid_candidates)}개 종목 평가 시작...")
                eval_results = []
                for code, count in valid_candidates.items():
                    # 일봉 2일치 조회하여 어제 종가와 오늘 현재가로 등락률 계산
                    candles = await asyncio.to_thread(client.get_daily_candles, code, 2)
                    rate = 0.0
                    if len(candles) == 2:
                        y_close = candles[0]['close']
                        t_close = candles[1]['close']
                        if y_close > 0:
                            rate = (t_close - y_close) / y_close * 100
                    elif len(candles) == 1:
                        t_open = candles[0]['open']
                        t_close = candles[0]['close']
                        if t_open > 0:
                            rate = (t_close - t_open) / t_open * 100
                    
                    eval_results.append({'code': code, 'count': count, 'rate': rate})
                    await asyncio.sleep(0.2) # API 호출 제한 방지
                
                # 1순위: 포착횟수 내림차순, 2순위: 등락률 내림차순 정렬
                eval_results.sort(key=lambda x: (x['count'], x['rate']), reverse=True)
                
                logger.info(f"📊 장 초반 수집 종목 순위 (2회 이상 포착된 모든 종목 매수 진행):")
                for res in eval_results:
                    logger.info(f" - [{res['code']}] 포착 {res['count']}회, 상승률 {res['rate']:.2f}%")
                
                for res in eval_results:
                    logger.info(f"🚀 [{res['code']}] 검증 통과(포착 {res['count']}회)! 실전 매수 진입을 시도합니다.")
                    # 선정된 종목을 모두 기존 매수 로직에 통과시킴 (무제한 매수)
                    await on_condition_insert(res['code'])
                    await asyncio.sleep(0.5)
                
                # 평가가 끝난 후보군은 비워서 초기화
                morning_candidates.clear()
            else:
                if morning_candidates:
                    logger.info(f"🕒 9시 4분 도달! 장 초반 수집 종목이 {len(morning_candidates)}개 있었으나 모두 1회 포착이어서 매수를 패스합니다.")
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
