import time
import threading
import logging

logger = logging.getLogger(__name__)

class HybridDataFeeder:
    """
    웹소켓 연결 불확실성을 대비하여, 백그라운드 스레드에서 REST API(ka10001)를 주기적으로 호출해
    현재가만 빠르게 갱신합니다 (키움증권 HTS 셧다운 방지 - 차트 TR 과부하 회피 로직).
    """
    def __init__(self, kiwoom_client, data_manager, interval=2.0):
        self.client = kiwoom_client
        self.data_manager = data_manager
        self.interval = interval
        self.is_running = False
        self.last_tick_time = None
        
        self.thread = threading.Thread(target=self._feed_loop, daemon=True)

    def start(self):
        self.is_running = True
        self.thread.start()
        logger.info(f"[{self.data_manager.stock_code}] 백그라운드 데이터 피더 가동 시작 (간격: {self.interval}초)")

    def stop(self):
        self.is_running = False

    def _feed_loop(self):
        import random
        time.sleep(random.uniform(0.1, min(10.0, self.interval)))
        code = self.data_manager.stock_code
        
        while self.is_running:
            try:
                # 1. 차트 API(get_tick_data, opt10079)는 잦은 호출 시 HTS 셧다운/차단을 유발하므로 금지
                # 2. 대신 가장 가벼운 단일 종목 기본 정보(ka10001) API를 호출하여 현재가만 즉각적으로 업데이트
                info = self.client.stock_info_api.basic_stock_information_request_ka10001(stock_code=code)
                if not info or "cur_prc" not in info:
                    time.sleep(self.interval)
                    continue
                    
                current_price = abs(float(info["cur_prc"]))
                self.data_manager.latest_price = current_price
                
                # 시간은 현재 시간 사용
                import datetime
                now_time = datetime.datetime.now().strftime("%H%M%S")
                
                # 분봉/일봉 업데이트용 틱 푸시
                self.data_manager.process_realtime_tick(
                    current_price=current_price,
                    volume=1,
                    volume_power=100.0,
                    time_str=now_time
                )
                    
            except Exception as e:
                logger.error(f"HybridDataFeeder Error: {e}")
                
            time.sleep(self.interval)

class GlobalDataFeeder:
    """
    조건검색식에서 포착된 모든 종목을 하나의 백그라운드 스레드에서 순차적으로 폴링합니다.
    (키움 API 초당 TR 조회 한도를 방어하기 위함)
    """
    def __init__(self, kiwoom_client, data_managers_dict):
        self.client = kiwoom_client
        self.data_managers = data_managers_dict
        self.is_running = False
        self.thread = threading.Thread(target=self._feed_loop, daemon=True)
        self.last_tick_times = {}

    def start(self):
        self.is_running = True
        self.thread.start()
        logger.info("글로벌 통합 데이터 피더 가동 시작 (과부하 방지용 0.3초 순차 폴링)")

    def stop(self):
        self.is_running = False

    def _feed_loop(self):
        while self.is_running:
            try:
                codes = list(self.data_managers.keys())
                if not codes:
                    time.sleep(1.0)
                    continue

                for code in codes:
                    if not self.is_running:
                        break
                        
                    dm = self.data_managers.get(code)
                    if not dm:
                        continue
                        
                    # TR 제한 방지를 위해 순차적으로 0.3초 간격 강제 (초당 최대 3~4회)
                    time.sleep(0.3)
                    
                    try:
                        # get_tick_data(ka10079)는 특정 시간대나 시장에서 빈 리스트를 반환하여 매수 판단을 마비시킵니다.
                        # 따라서 가장 안정적인 단일 종목 기본 정보(ka10001) API를 호출하여 현재가만 즉각적으로 업데이트합니다.
                        info = self.client.stock_info_api.basic_stock_information_request_ka10001(stock_code=code)
                        if not info or "cur_prc" not in info:
                            continue
                            
                        current_price = abs(float(info["cur_prc"]))
                        
                        # 무조건 가장 최신 조회된 현재가를 즉시 반영 (매수 로직 반응 속도 극대화)
                        dm.latest_price = current_price
                        
                        # 실시간으로 1분봉의 현재 캔들 종가/고가/저가를 임시로 업데이트
                        if dm.current_1m_candle:
                            dm.current_1m_candle['close'] = current_price
                            dm.current_1m_candle['high'] = max(dm.current_1m_candle['high'], current_price)
                            dm.current_1m_candle['low'] = min(dm.current_1m_candle['low'], current_price)
                        else:
                            # 만약 현재 1분 캔들이 없으면 하나 강제 생성
                            import datetime
                            time_key = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:00")
                            dm.current_1m_candle = {
                                'time': time_key,
                                'open': current_price,
                                'high': current_price,
                                'low': current_price,
                                'close': current_price,
                                'volume': 1
                            }
                            
                    except Exception as e:
                        logger.error(f"[{code}] GlobalDataFeeder Error: {e}")
                        
            except Exception as e:
                logger.error(f"GlobalDataFeeder Loop Error: {e}")
                time.sleep(1.0)

