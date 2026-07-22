import asyncio
import logging
import sys
import time
from datetime import datetime, timezone, timedelta

import config
from kiwoom_client import KiwoomClient
from websocket_client import KiwoomWebSocketClient
from theme_manager import ThemeManager
from core_trade_manager import CoreTradeManager
from trend_manager import TrendManager
from tick_acceleration_agent import TickAccelerationEngine
from data_manager import RealtimeDataManager
import strategy_1m_morning
import telegram_bot

# ------------------------------------------
# 1. 설정 및 로깅 초기화
# ------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 거래 제어용 전역 변수
MAX_HOLDING_STOCKS = 3
ORDER_TIMEOUT = 5.0

PORTFOLIO_STATE = {} # {code: {"status": "HOLDING", "qty": int, "buy_price": float}}
TELEGRAM_QUEUE = asyncio.Queue()

# 글로벌 에이전트 및 캐시
g_client = None
g_accel_engine = None
g_ws_client = None
g_core_manager = None

watchlist_codes = set()
DATA_MANAGERS = {}
STOCK_INFO = {}
sold_today = set()

# ------------------------------------------
# 2. 텔레그램 논블로킹 알림 루프
# ------------------------------------------
async def telegram_worker():
    while True:
        try:
            msg = await TELEGRAM_QUEUE.get()
            if telegram_bot.IS_BOT_ACTIVE:
                await telegram_bot.send_message(msg)
            TELEGRAM_QUEUE.task_done()
        except Exception as e:
            logger.error(f"텔레그램 전송 에러: {e}")
        await asyncio.sleep(0.5)

def enqueue_telegram_msg(msg: str):
    logger.info(msg.replace('\n', ' '))
    TELEGRAM_QUEUE.put_nowait(msg)

# ------------------------------------------
# 3. 매수/매도 실행 로직
# ------------------------------------------
async def execute_buy_order(code: str, price: float, accel_ratio: float, reason: str):
    global PORTFOLIO_STATE, g_client
    
    current_holdings = len(PORTFOLIO_STATE)
    if current_holdings >= MAX_HOLDING_STOCKS:
        return
        
    if code in PORTFOLIO_STATE or code in sold_today:
        return
        
    enqueue_telegram_msg(f"🚀 [합의 매수 발송] {code}\n조건: {reason} (가속도 {accel_ratio:.0f}회)")
    
    qty = 1 # [테스트 모드] 예수금 최소화를 위해 무조건 1주만 매수
    PORTFOLIO_STATE[code] = {"status": "PENDING_BUY", "qty": qty, "buy_price": 0.0}
    
    try:
        await asyncio.wait_for(
            asyncio.to_thread(g_client.place_buy_order, code, qty, price=0, order_type="03"),
            timeout=ORDER_TIMEOUT
        )
        enqueue_telegram_msg(f"⏳ [{code}] 시장가 매수 주문 접수 성공")
    except Exception as e:
        logger.error(f"매수 에러: {e}")
        del PORTFOLIO_STATE[code]

async def execute_sell_order(code: str, qty: int, reason: str):
    global PORTFOLIO_STATE, g_client
    
    enqueue_telegram_msg(f"🚨 [매도 발송] {code}\n사유: {reason}")
    PORTFOLIO_STATE[code]["status"] = "PENDING_SELL"
    
    try:
        await asyncio.wait_for(
            asyncio.to_thread(g_client.place_sell_order, code, qty, price=0, order_type="03"),
            timeout=ORDER_TIMEOUT
        )
        enqueue_telegram_msg(f"⏳ [{code}] 시장가 매도 주문 접수 완료")
    except Exception as e:
        logger.error(f"매도 에러: {e}")
        PORTFOLIO_STATE[code]["status"] = "HOLDING"

# ------------------------------------------
# 4. 차트 기반 감시 루프 (Trading Agent)
# ------------------------------------------
async def chart_trading_agent():
    """
    3분봉 차트를 주기적으로 확인하여 SMA 크로스를 검사하고, 
    가속도 랭킹과 테마를 팩터로 활용하여 매매를 결정합니다.
    """
    global watchlist_codes, DATA_MANAGERS, PORTFOLIO_STATE, g_accel_engine, g_core_manager
    
    while True:
        try:
            # 1. 매도 감시 (보유 종목)
            for code, state in list(PORTFOLIO_STATE.items()):
                if state["status"] != "HOLDING":
                    continue
                    
                if code in DATA_MANAGERS:
                    dm = DATA_MANAGERS[code]
                    candles_1m = dm.get_completed_and_current_1m_candles()
                    candles_15m = dm.get_completed_and_current_15m_candles()
                    is_sell, reason = g_core_manager.check_sell_condition(code, state["buy_price"], dm.latest_price, candles_1m, candles_15m)
                    
                    if is_sell:
                        await execute_sell_order(code, state["qty"], reason)

            # 2. 매수 감시 (Watchlist 종목)
            for code in list(watchlist_codes):
                if code in sold_today or code not in DATA_MANAGERS or code in PORTFOLIO_STATE:
                    continue
                    
                if len(PORTFOLIO_STATE) >= MAX_HOLDING_STOCKS:
                    break
                    
                dm = DATA_MANAGERS[code]
                
                # [팩터 1] 1분봉 오전장 매수 신호 검증 (눌림목)
                is_buy_candidate, msg = strategy_1m_morning.check_1m_buy_signal(dm)
                
                if is_buy_candidate:
                    # [팩터 2] 가속도 랭킹 확인 (Tick Frequency)
                    accel_ratio = g_accel_engine.rankings.get(code, 0.0)
                    
                    # 랭킹 상위권이거나, 3초당 N회 이상 체결 빈도 발생 시 통과
                    # (여기서는 10회 이상으로 완화하여 골든크로스 신호와 밸런스를 맞춥니다)
                    MIN_BUY_TICK_COUNT = 10 
                    
                    if accel_ratio >= MIN_BUY_TICK_COUNT or code == g_accel_engine.top_code:
                        # [팩터 3] 서포터 마스터(CoreTradeManager) 최종 승인 검증
                        base_reasons = [f"1분봉 눌림목 + 수급폭발({accel_ratio:.0f}회)"]
                        approved, final_reason = g_core_manager.evaluate_buy_candidate(code, dm.latest_price, base_reasons, name=dm.name)
                        
                        if approved:
                            await execute_buy_order(code, dm.latest_price, accel_ratio, final_reason)
                        else:
                            logger.info(f"🛑 [{code}] 서포터 합의 실패 (매수 패스)")
                    else:
                        logger.info(f"🛑 [{code}] 이평선 통과했으나 현재 수급 부족 (체결빈도 {accel_ratio}회 < {MIN_BUY_TICK_COUNT})")
                        
        except Exception as e:
            logger.error(f"Trading Agent 루프 에러: {e}")
            
        await asyncio.sleep(1.0) # 1초마다 차트/랭킹 상태 폴링

# ------------------------------------------
# 5. 실시간 잔고 동기화 에이전트
# ------------------------------------------
async def holdings_sync_agent():
    global PORTFOLIO_STATE, g_client
    while True:
        try:
            if not PORTFOLIO_STATE:
                await asyncio.sleep(2)
                continue
                
            balance_list = await asyncio.to_thread(g_client.get_account_balance)
            if balance_list is not None:
                balance_dict = {item["code"]: item for item in balance_list}
                
                for code, state in list(PORTFOLIO_STATE.items()):
                    if state["status"] == "PENDING_BUY":
                        if code in balance_dict:
                            actual_qty = int(balance_dict[code]["qty"])
                            if actual_qty >= state["qty"]:
                                state["status"] = "HOLDING"
                                state["buy_price"] = float(balance_dict[code]["buy_price"])
                                enqueue_telegram_msg(f"🎉 [{code}] 매수 체결 완료!\n단가: {state['buy_price']:,.0f}원")
                    
                    elif state["status"] == "PENDING_SELL":
                        if code not in balance_dict or int(balance_dict[code]["qty"]) == 0:
                            enqueue_telegram_msg(f"💸 [{code}] 매도 체결 및 포트폴리오 청산 완료!")
                            sold_today.add(code)
                            del PORTFOLIO_STATE[code]
        except Exception as e:
            logger.error(f"잔고 동기화 에러: {e}")
        
        await asyncio.sleep(2)

# ------------------------------------------
# 6. 웹소켓 (조건검색 / 실시간 틱) 콜백 핸들러
# ------------------------------------------
async def on_condition_insert(code: str):
    """Real_Traiding 조건식에 종목 포착 시"""
    global watchlist_codes, STOCK_INFO, DATA_MANAGERS, g_client
    
    if code in watchlist_codes or code in sold_today:
        return
        
    logger.info(f"👀 [조건검색 포착] {code} - 감시망 편입 준비")
    
    name = g_client.get_stock_name(code) or code
    STOCK_INFO[code] = {'name': name}
    watchlist_codes.add(code)
    
    if code not in DATA_MANAGERS:
        dm = RealtimeDataManager(code, name, reference_price=0.0)
        # 과거 데이터 로드 (1분, 3분)
        past_1m = await asyncio.to_thread(g_client.get_1min_candles, code, 1)
        await asyncio.sleep(0.3) # API 과부하 방지
        past_3m = await asyncio.to_thread(g_client.get_3min_candles, code, 1)
        
        dm.seed_initial_data(past_1m, past_3m, [], [])
        DATA_MANAGERS[code] = dm
        
        # 추세 서포터 사전 학습 (비동기 스레드로 실행하여 블로킹 방지)
        await asyncio.to_thread(g_core_manager.trend_manager.pre_learn, [code])
        
        logger.info(f"✅ [{name}] 실시간 틱 구독, 캔들 및 일봉 추세 세팅 완료")

async def on_condition_delete(code: str):
    """Real_Traiding 조건식 이탈 시"""
    logger.info(f"👀 [조건검색 이탈] {code} - 차트/가속도 감시는 일단 유지합니다.")

async def on_real_tick(tick_data: dict):
    """REALREQ 주식체결 데이터 수신 시"""
    global g_accel_engine, DATA_MANAGERS, PORTFOLIO_STATE
    
    code = tick_data['code']
    
    # 1. 차트 매니저 캔들 업데이트
    if code in DATA_MANAGERS:
        DATA_MANAGERS[code].update_realtime_data(
            current_price=tick_data['price'],
            accum_volume=tick_data['accum_volume'],
            time_str=tick_data['time']
        )
    
    # 2. 가속도 엔진 랭킹 보드 업데이트
    if code not in PORTFOLIO_STATE and g_accel_engine:
        await g_accel_engine.process_tick(tick_data)

# ------------------------------------------
# 7. 메인 루프 (Main)
# ------------------------------------------
async def main():
    global g_client, g_accel_engine, g_ws_client, g_core_manager
    
    logger.info("=========================================")
    logger.info("🚀 [Real_Traiding] 순위 + 테마 + SMA 멀티팩터 봇 시작")
    logger.info("=========================================")
    
    telegram_bot.IS_BOT_ACTIVE = True
    asyncio.create_task(telegram_worker())
    enqueue_telegram_msg("🚀 [Real_Traiding] 하이브리드 봇 가동\n(조건검색 -> 가속도 랭킹/테마 검증 -> 1분봉 눌림목 타점)")
    
    # 1. 코어 인스턴스 생성
    g_client = KiwoomClient()
    theme_manager = ThemeManager()
    trend_manager = TrendManager(g_client)
    g_core_manager = CoreTradeManager(theme_manager=theme_manager, trend_manager=trend_manager, max_holdings=MAX_HOLDING_STOCKS)
    
    # 2. 가속도 랭킹 엔진 생성
    g_accel_engine = TickAccelerationEngine(g_client, {})
    
    # 3. 비동기 백그라운드 태스크 구동
    asyncio.create_task(chart_trading_agent())
    asyncio.create_task(holdings_sync_agent())
    
    # 4. 실시간 웹소켓(조건검색 및 호가) 연결
    g_ws_client = KiwoomWebSocketClient(
        target_condition_name="Real_Traiding",
        on_insert=on_condition_insert,
        on_delete=on_condition_delete,
        on_real_tick=on_real_tick
    )
    
    await g_ws_client.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("봇을 종료합니다.")
        sys.exit(0)
