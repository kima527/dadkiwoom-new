import os
import sys
import time
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Add local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from kiwoom_client import KiwoomClient
from data_feeder import HybridDataFeeder
from data_manager import RealtimeDataManager
from scanner import scan_golden_cross_stocks
import strategy

# 전역 상태 관리
DATA_MANAGERS = {}
FEEDERS = {}

def is_market_open():
    """정규장 운영 시간 확인 (09:00 ~ 15:30)"""
    now = datetime.now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(9, 0) <= current_time <= dt_time(15, 30)

def is_trading_prohibited():
    """전면 매매(매수/매도) 금지 시간 (08:00~08:04, 09:00~09:04)"""
    now = datetime.now()
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
    now = datetime.now()
    current_time = now.time()
    from datetime import time as dt_time
    if current_time >= dt_time(14, 0):
        return True
    return False

def main():
    logger.info("=========================================")
    logger.info("Daytraid Bot Started (15m Pullback Strategy)")
    logger.info("=========================================")

    # 1. 클라이언트 초기화
    client = KiwoomClient()

    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 당일 매도 완료 종목 추적 (재진입 금지용)
    sold_today = set()

    # 2. 보유 종목 조회
    holdings = client.get_holdings()
    held_codes = [h["code"] for h in holdings]
    logger.info(f"현재 보유 종목 수: {len(held_codes)}개")

    # 3. 타겟 39종목 스캐닝 (일봉 골든크로스 1~3일전 검색)
    target_stocks = getattr(config, 'HARDCODED_TARGET_STOCKS', [])
    screened_stocks = scan_golden_cross_stocks(client, target_stocks)
    
    # 4. 모니터링 대상 통합 (보유 종목 + 스크리닝 통과 종목)
    monitor_codes = set(held_codes + list(screened_stocks.keys()))
    
    if not monitor_codes:
        logger.info("오늘은 모니터링 대상 종목이 없습니다. 장 종료 시까지 대기합니다.")
    else:
        logger.info(f"실시간 모니터링 시작 종목 수: {len(monitor_codes)}개")

    # API 1시간 호출 제한(1000회)을 피하기 위한 동적 폴링 간격 계산 (여유있게 900회 기준)
    # interval = (종목수 * 3600초) / 900회
    safe_interval = max(3.0, (len(monitor_codes) * 3600) / 900.0)
    logger.info(f"API Rate Limit 보호를 위한 틱 폴링 간격: {safe_interval:.1f}초")

    for code in monitor_codes:
        name = client.get_stock_name(code) or code
        ref_price = screened_stocks.get(code, 0.0) # 보유종목이 스크리닝 통과 안 했으면 0.0
        
        dm = RealtimeDataManager(code, name, ref_price)
        DATA_MANAGERS[code] = dm
        
        # 3분봉, 15분봉, 45분봉, 일봉 초기 시드 데이터 로드
        logger.info(f"[{name}] 초기 분봉/일봉 데이터 로딩 중...")
        past_3m = client.get_3min_candles(code, last_n_days=2)
        time.sleep(0.3)
        past_15m = client.get_15min_candles(code, last_n_days=7)
        time.sleep(0.3)
        past_daily = client.get_daily_candles(code, last_n_days=10)
        time.sleep(0.3)
        dm.seed_initial_data(past_3m, past_15m, past_daily)
        
        feeder = HybridDataFeeder(client, dm, interval=safe_interval)
        FEEDERS[code] = feeder
        feeder.start()

    # 5. 메인 루프 (실시간 감시)
    while True:
        if not getattr(config, 'KIWOOM_IS_MOCK', False) and not is_market_open():
            logger.info("현재 장 시간이 아닙니다. 60초 대기...")
            time.sleep(60)
            continue

        # 잔고 갱신 (잔고 반영 딜레이 고려)
        try:
            holdings = client.get_holdings()
            held_codes = [h["code"] for h in holdings]
        except Exception as e:
            logger.error(f"잔고 조회 중 오류: {e}")
            time.sleep(10)
            continue

        for code, dm in DATA_MANAGERS.items():
            if code in held_codes:
                # 보유 중인 종목 -> 매도 조건 감시
                buy_price = 0
                qty = 0
                for h in holdings:
                    if h["code"] == code:
                        buy_price = h["purchase_price"]
                        qty = h["quantity"]
                        break
                        
                if is_trading_prohibited():
                    continue
                    
                # 1. 기계적 하드 손절 (-1.5%)
                is_hard_stop = (buy_price > 0 and dm.latest_price <= buy_price * 0.985)
                
                # 2. 15분봉 데드크로스 또는 L선 이탈
                is_dead_cross = strategy.check_sell_signal(dm)
                
                # 3. [NEW] 진입 캔들 특수 룰: 진입한 15분봉 내에서 최고가 대비 -1.5% 하락
                is_entry_candle_stop = False
                if getattr(dm, 'entry_candle_time', None) is not None:
                    curr_15m = dm.current_15m_candle
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
                        # 시장가(03) 매도 주문
                        logger.info(f"-> {qty}주 시장가 매도 주문 실행")
                        client.place_sell_order(code, qty, order_type="03")
                        sold_today.add(code) # 매도 후 재진입 금지를 위해 기록
                        time.sleep(1) # 연속 주문 방지 딜레이
            else:
                # 미보유 종목 -> 매수 조건 감시
                if code in sold_today:
                    continue # 당일 이미 매도한 종목은 재진입 금지
                    
                # 매수 금지 시간 체크
                if is_buy_prohibited():
                    continue

                # 스크리닝을 통과하여 기준가(ref_price > 0)가 있는 종목만 검사
                if dm.reference_price > 0 and strategy.check_buy_signal(dm):
                    logger.warning(f"🚀 [매수 신호 발생] {dm.name}({code}) - 15분봉 -3% 눌림목 도달!")
                    
                    cash = client.get_cash_balance()
                    buy_amount = min(cash * 0.95, 1000000) # 예수금의 95% 또는 최대 100만원치
                    
                    if buy_amount >= dm.latest_price and dm.latest_price > 0:
                        qty = int(buy_amount // dm.latest_price)
                        if qty > 0:
                            logger.info(f"-> {qty}주 시장가 매수 주문 실행")
                            client.place_buy_order(code, qty, order_type="03")
                            
                            # [NEW] 매수 진입 시 현재 15분봉 시간 기록
                            if dm.current_15m_candle:
                                dm.entry_candle_time = dm.current_15m_candle['time']
                            else:
                                dm.entry_candle_time = None
                                
                    time.sleep(1)
                    
        time.sleep(1) # 루프 과부하 방지

if __name__ == "__main__":
    main()
