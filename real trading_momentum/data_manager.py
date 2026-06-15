

# 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
# ── RealtimeDataManager (과부하 0% 실시간 캔들 조립 공장) ──
# 이 모듈은 웹소켓 또는 하이브리드 피더에서 수신한 실시간 틱을 바탕으로
# 메모리 상에서 120틱 및 1분봉 캔들을 초고속으로 조립하는 봇의 핵심 엔진입니다.
# 사용자의 명시적 승인 없이 큐(Deque) 구조나 처리 방식을 임의로 변경하지 마십시오.
# ────────────────────────────────────────────────────────────

from collections import deque
import logging

logger = logging.getLogger(__name__)

class RealtimeDataManager:
    def __init__(self, stock_code: str, max_len: int = 120, cumulative_limit: int = 100000000):
        self.stock_code = stock_code
        self.max_len = max_len
        self.cumulative_limit = cumulative_limit
        
        # 원시 틱 체결 데이터 임시 저장소 (120틱 및 1분봉 생성용)
        self.raw_tick_buffer = []
        
        # 로컬에 적립할 최종 캔들 큐 (속도 향상을 위해 deque 사용)
        self.ticks_120_deque = deque(maxlen=max_len)
        self.candles_1m_deque = deque(maxlen=max_len)
        self.candles_3m_deque = deque(maxlen=max_len)
        self.candles_5m_deque = deque(maxlen=max_len)
        self.candles_15m_deque = deque(maxlen=max_len)
        self.daily_candles_deque = deque(maxlen=250)
        
        # 1분봉 경계면 체크를 위한 변수 (HHMM)
        self.last_processed_minute = ""
        
        logger.info(f"[{stock_code}] RealtimeDataManager 다중 타임프레임 모드 초기화 완료 (max_len={max_len})")

        self.sugeub_history = deque()
        self.last_tick_price = 0.0
        import time
        import threading
        self.tick_timestamps = deque(maxlen=20)

    @staticmethod
    def fill_void_gaps(candles: list, freq_minutes: int) -> list:
        """
        이빨 빠진 차트(거래량 0 구간)를 이전 종가로 복제(ffill)하여 수학적 무결성을 보장합니다.
        Numpy/Pandas 없이 순수 파이썬(Pure Python)으로만 작동하여 충돌을 원천 방지합니다.
        """
        if not candles:
            return []
        import datetime
        
        try:
            sorted_candles = sorted(candles, key=lambda x: x['time'])
        except Exception:
            return candles

        filled_candles = []
        prev_c = sorted_candles[0]
        filled_candles.append(prev_c)
        
        step_delta = datetime.timedelta(minutes=freq_minutes)
        
        for current_c in sorted_candles[1:]:
            try:
                prev_time_str = prev_c['time']
                curr_time_str = current_c['time']
                
                # 날짜 파싱 방어 코드
                fmt_prev = '%Y-%m-%d %H:%M:%S' if '-' in prev_time_str else '%Y%m%d%H%M%S'
                fmt_curr = '%Y-%m-%d %H:%M:%S' if '-' in curr_time_str else '%Y%m%d%H%M%S'
                
                prev_dt = datetime.datetime.strptime(prev_time_str[:19] if '-' in prev_time_str else prev_time_str, fmt_prev)
                curr_dt = datetime.datetime.strptime(curr_time_str[:19] if '-' in curr_time_str else curr_time_str, fmt_curr)
                    
                expected_time = prev_dt + step_delta
                
                # 공백(Void Gap) 채우기 연산
                while expected_time < curr_dt:
                    if 8 <= expected_time.hour < 20: # 정규장 + 시간외(NXT) 포함 범위
                        gap_candle = {
                            'time': expected_time.strftime(fmt_prev),
                            'date': prev_c.get('date', expected_time.strftime('%Y-%m-%d')),
                            'open': prev_c['close'],
                            'high': prev_c['close'],
                            'low': prev_c['close'],
                            'close': prev_c['close'],
                            'volume': 0
                        }
                        filled_candles.append(gap_candle)
                    expected_time += step_delta
            except Exception:
                pass
                
            filled_candles.append(current_c)
            prev_c = current_c
            
        return filled_candles

    @staticmethod
    def verify_and_adjust_historical_candles(candles: list, daily_candles: list) -> list:
        # Reverted: Do not adjust garbage data from Kiwoom. 
        # The 1.5% cross-validation will block garbage data instead.
        return candles

    def seed_initial_data(self, past_120ticks: list, past_1m_candles: list, past_3m: list = None, past_5m: list = None, past_15m: list = None, past_daily: list = None):
        """
        장 시작 전(또는 스크립트 가동 시) REST API로 가져온 과거 데이터를 큐에 채워넣습니다.
        """
        for t in past_120ticks:
            self.ticks_120_deque.append(t)
            
        for c in past_1m_candles:
            self.candles_1m_deque.append(c)
            
            # 마지막 분을 초기화하여 다음 체결 시 분이 바뀜을 감지
            if c.get("time") and len(c["time"]) >= 16:
                # "YYYY-MM-DD HH:MM:SS" -> "HHMM"
                time_str = c["time"]
                try:
                    hhmm = time_str[11:13] + time_str[14:16]
                    self.last_processed_minute = hhmm
                except:
                    pass

        if past_3m:
            for c in past_3m: self.candles_3m_deque.append(c)
        if past_5m:
            for c in past_5m: self.candles_5m_deque.append(c)
        if past_15m:
            for c in past_15m: self.candles_15m_deque.append(c)
        if past_daily:
            for c in past_daily: self.daily_candles_deque.append(c)

        logger.info(f"[{self.stock_code}] 초기 시드 데이터 적재 완료 (허수 캔들 없이 순수 체결 데이터만 적재) (1m/3m/5m/15m/daily)")

    def process_realtime_tick(self, current_price: float, volume: int, volume_power: float, time_str: str):
        """
        웹소켓(또는 하이브리드 폴링)을 통해 들어온 단일 틱 데이터를 처리하여 120틱/1분봉을 조립합니다.
        time_str 형식: "HHMMSS" (예: "090123")
        """
        if not time_str or len(time_str) < 4:
            return
            
        current_minute = time_str[:4]  # "0901" 형식으로 분만 추출
        
        # 원시 틱 데이터 객체 생성
        tick_data = {
            'price': float(current_price),
            'volume': int(volume),
            'volume_power': float(volume_power),
            'time': time_str
        }
        self.raw_tick_buffer.append(tick_data)
        import time
        self.tick_timestamps.append(time.time())

        # 체결 타임스탬프 기록 (최근 20개 유지)
        self.tick_timestamps.append(time.time())
        if len(self.tick_timestamps) > 20:
            self.tick_timestamps.pop(0)

        # [필터링 1] 매수 체결 여부 추론 (현재가가 직전 체결가 이상이면 매수세로 간주)
        is_buy = False
        if self.last_tick_price == 0.0:
            is_buy = True
        elif current_price >= self.last_tick_price:
            is_buy = True
        self.last_tick_price = current_price

        # [필터링 2] 3초 누적 1억 원 or 단일 5천만 원 돌파 감지
        sugeub_spike_triggered = False
        if is_buy:
            import time
            current_time_sec = time.time()
            amount = float(current_price) * abs(volume)
            
            self.sugeub_history.append((current_time_sec, amount))
            
            # 3초가 지난 과거 데이터 메모리에서 즉시 삭제
            while self.sugeub_history and (current_time_sec - self.sugeub_history[0][0] > 3.0):
                self.sugeub_history.popleft()
                
            total_3s_amount = sum(x[1] for x in self.sugeub_history)
            
            if amount >= 50000000 or total_3s_amount >= self.cumulative_limit:
                sugeub_spike_triggered = True
                logger.info(f"🚨 [수급포착] {self.stock_code} | 순간체결: {amount:,.0f}원 | 3초누적: {total_3s_amount:,.0f}원 (기준: {self.cumulative_limit:,.0f}원)")

        # ----------------------------------------------------
        # 1. 120틱 캔들 생성 로직 (120회 체결마다 1개 봉 생성)
        # ----------------------------------------------------
        if len(self.raw_tick_buffer) > 0 and len(self.raw_tick_buffer) % 120 == 0:
            target_ticks = self.raw_tick_buffer[-120:]
            prices = [t['price'] for t in target_ticks]
            volumes = [t['volume'] for t in target_ticks]
            
            import datetime
            now = datetime.datetime.now()
            # 시간 문자열 포맷팅 YYYY-MM-DD HH:MM:SS
            dt_str = f"{now.year}-{now.month:02d}-{now.day:02d} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
            
            tick_candle = {
                'open': prices[0],
                'high': max(prices),
                'low': min(prices),
                'close': prices[-1],
                'volume': sum(volumes),
                'time': dt_str
            }
            self.ticks_120_deque.append(tick_candle)
            
        # ----------------------------------------------------
        # 2. 1분봉 캔들 생성 로직 (시간이 분 단위로 교체될 때)
        # ----------------------------------------------------
        if self.last_processed_minute == "":
            self.last_processed_minute = current_minute
            
        elif current_minute != self.last_processed_minute:
            # 분이 바뀌었으므로 직전 분의 모든 틱 데이터를 모아서 1분봉 생성
            prev_minute_ticks = [t for t in self.raw_tick_buffer if t['time'].startswith(self.last_processed_minute)]
            
            if prev_minute_ticks:
                p_prices = [t['price'] for t in prev_minute_ticks]
                p_volumes = [t['volume'] for t in prev_minute_ticks]
                
                import datetime
                now = datetime.datetime.now()
                # 1분봉 타임스탬프 (이전 분 기준)
                dt_str = f"{now.year}-{now.month:02d}-{now.day:02d} {self.last_processed_minute[:2]}:{self.last_processed_minute[2:4]}:00"
                date_only = f"{now.year}-{now.month:02d}-{now.day:02d}"
                
                candle_1m = {
                    'time': dt_str,
                    'date': date_only,
                    'open': p_prices[0],
                    'high': max(p_prices),
                    'low': min(p_prices),
                    'close': p_prices[-1],
                    'volume': sum(p_volumes)
                }
                self.candles_1m_deque.append(candle_1m)
                
                # 메모리 관리를 위해 처리된 이전 분의 원시 데이터는 버퍼에서 삭제
                self.raw_tick_buffer = [t for t in self.raw_tick_buffer if not t['time'].startswith(self.last_processed_minute)]
                
            self.last_processed_minute = current_minute

        # ----------------------------------------------------
        # 3. 3분, 5분, 15분, 일봉 실시간 라이브 업데이트
        # ----------------------------------------------------
        try:
            hour = int(current_minute[:2])
            minute = int(current_minute[2:4])
            
            import datetime
            now = datetime.datetime.now()
            date_only = f"{now.year}-{now.month:02d}-{now.day:02d}"
            
            def update_live_candle(deque_obj, dt_str, price, vol):
                if len(deque_obj) > 0 and deque_obj[-1].get('time', '').startswith(dt_str[:16]):
                    deque_obj[-1]['high'] = max(deque_obj[-1].get('high', price), price)
                    deque_obj[-1]['low'] = min(deque_obj[-1].get('low', price), price)
                    deque_obj[-1]['close'] = price
                    deque_obj[-1]['volume'] = deque_obj[-1].get('volume', 0) + vol
                else:
                    new_candle = {
                        'time': dt_str,
                        'date': date_only,
                        'open': price,
                        'high': price,
                        'low': price,
                        'close': price,
                        'volume': vol
                    }
                    deque_obj.append(new_candle)
                    
                if sugeub_spike_triggered and len(deque_obj) > 0:
                    deque_obj[-1]['signal_sugeub_spike'] = True
                    
            m_3 = (minute // 3) * 3
            dt_3m = f"{date_only} {hour:02d}:{m_3:02d}:00"
            update_live_candle(self.candles_3m_deque, dt_3m, float(current_price), int(volume))
            
            m_5 = (minute // 5) * 5
            dt_5m = f"{date_only} {hour:02d}:{m_5:02d}:00"
            update_live_candle(self.candles_5m_deque, dt_5m, float(current_price), int(volume))
            
            m_15 = (minute // 15) * 15
            dt_15m = f"{date_only} {hour:02d}:{m_15:02d}:00"
            update_live_candle(self.candles_15m_deque, dt_15m, float(current_price), int(volume))
            
            # 일봉은 날짜만 비교 (startswith date_only)
            if len(self.daily_candles_deque) > 0 and self.daily_candles_deque[-1].get('date', '').startswith(date_only):
                self.daily_candles_deque[-1]['high'] = max(self.daily_candles_deque[-1].get('high', float(current_price)), float(current_price))
                self.daily_candles_deque[-1]['low'] = min(self.daily_candles_deque[-1].get('low', float(current_price)), float(current_price))
                self.daily_candles_deque[-1]['close'] = float(current_price)
                self.daily_candles_deque[-1]['volume'] = self.daily_candles_deque[-1].get('volume', 0) + int(volume)
            else:
                self.daily_candles_deque.append({
                    'time': f"{date_only} 00:00:00",
                    'date': date_only,
                    'open': float(current_price),
                    'high': float(current_price),
                    'low': float(current_price),
                    'close': float(current_price),
                    'volume': int(volume)
                })
                
            if sugeub_spike_triggered and len(self.daily_candles_deque) > 0:
                self.daily_candles_deque[-1]['signal_sugeub_spike'] = True
                
        except Exception as e:
            logger.error(f"라이브 캔들 조립 중 에러: {e}")

    def get_120tick_list(self):
        """메인 루프에서 Phase 2 연산용으로 즉시 가져가는 120틱 리스트 (df 변환 불필요, 딕셔너리 리스트 반환)"""
        return list(self.ticks_120_deque)

    def get_1min_list(self):
        return list(self.candles_1m_deque)

    def get_3min_list(self):
        return list(self.candles_3m_deque)

    def get_5min_list(self):
        return list(self.candles_5m_deque)

    def get_15min_list(self):
        return list(self.candles_15m_deque)
        
    def get_daily_list(self):
        return list(self.daily_candles_deque)

    def get_tick_velocity(self) -> float:
        """
        Return time difference between first and last tick in recent 20 ticks.
        """
        if len(self.tick_timestamps) < 20:
            return 999.0
        return self.tick_timestamps[-1] - self.tick_timestamps[0]
