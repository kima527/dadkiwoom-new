import time
import threading
import logging

logger = logging.getLogger(__name__)

class HybridDataFeeder:
    """
    웹소켓 연결 불확실성을 대비하여, 백그라운드 스레드에서 REST API(get_tick_data)를 주기적으로 호출해
    새로 들어온 틱만 골라내어 RealtimeDataManager에 푸시하는 피더(Feeder)입니다.
    
    메인 루프(main.py)는 API를 직접 호출하지 않고 로컬 큐만 바라보게 되므로 과부하 0%를 달성합니다.
    """
    def __init__(self, kiwoom_client, data_manager, interval=1.0):
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
                # 1. 틱 데이터 수집
                ticks = self.client.get_tick_data(code, "120", limit=10)
                if not ticks:
                    time.sleep(self.interval)
                    continue
                    
                # 2. 새로운 틱만 골라내기
                new_ticks = []
                for t in ticks:
                    t_time = t['time'] # "YYYY-MM-DD HH:MM:SS"
                    if self.last_tick_time is None or t_time > self.last_tick_time:
                        new_ticks.append(t)
                        
                # 3. 데이터 매니저에 밀어넣기 (오름차순이므로 그대로 푸시)
                # get_tick_data는 보통 오름차순 반환 (가장 과거 -> 최신). 만약 내림차순이면 뒤집어야 함.
                # kiwoom_client.py 내부를 보면 sort(key=lambda x: x["time"]) 로 이미 오름차순 정렬됨.
                for t in new_ticks:
                    # process_realtime_tick 인자: current_price, volume, volume_power, time_str
                    # 틱 데이터에는 volume_power가 없으므로, REST 폴링 특성상 임의계산 또는 100.0으로 둠
                    # 이 하이브리드 피더는 임시 대안이며, 완벽한 체결강도는 tick_res에서 처리됨
                    
                    # 시간 변환: "YYYY-MM-DD HH:MM:SS" -> "HHMMSS"
                    time_raw = t['time']
                    hhmmss = time_raw[11:13] + time_raw[14:16] + time_raw[17:19]
                    
                    self.data_manager.process_realtime_tick(
                        current_price=t['close'],
                        volume=t['volume'],
                        volume_power=100.0, # 하이브리드에서는 체결강도 정밀계산 불가하므로 기본값
                        time_str=hhmmss
                    )
                    
                if ticks:
                    self.last_tick_time = ticks[-1]['time']
                    
            except Exception as e:
                logger.error(f"DataFeeder Error: {e}")
                
            time.sleep(self.interval)
