import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)

class RealtimeDataManager:
    def __init__(self, stock_code: str, name: str, reference_price: float):
        self.stock_code = stock_code
        self.name = name
        self.reference_price = reference_price
        
        # 보조 지표 계산용 버퍼
        self.candles_120t = deque(maxlen=400) # 120틱 캔들 버퍼 (충분한 길이 유지)
        self.candles_1m = deque(maxlen=200)
        self.candles_3m = deque(maxlen=10)
        self.candles_5m = deque(maxlen=200)
        self.candles_15m = deque(maxlen=200)
        self.candles_30m = deque(maxlen=200)
        self.candles_daily = deque(maxlen=20)  # 일봉 (SMA3, SMA5 계산용)
        
        # 현재 진행 중인 캔들 상태
        self.current_1m_candle = None
        self.current_3m_candle = None
        self.current_5m_candle = None
        self.current_15m_candle = None
        self.current_30m_candle = None
        self.current_daily_candle = None
        
        self.current_120t_buffer = [] # 120틱을 세기 위한 임시 버퍼
        
        # 현재가
        self.latest_price = 0.0

    def seed_initial_data(self, past_1m: list, past_3m: list, past_5m: list, past_15m: list, past_daily: list = None, past_30m: list = None, past_120t: list = None):
        """프로그램 시작 시 과거 분봉/일봉/틱 데이터를 적재합니다."""
        if past_120t:
            for c in past_120t:
                self.candles_120t.append(c)
        if past_1m:
            for c in past_1m:
                self.candles_1m.append(c)
        if past_3m:
            for c in past_3m:
                self.candles_3m.append(c)
        if past_5m:
            for c in past_5m:
                self.candles_5m.append(c)
        if past_15m:
            for c in past_15m:
                self.candles_15m.append(c)
        if past_30m:
            for c in past_30m:
                self.candles_30m.append(c)
        if past_daily:
            for c in past_daily:
                self.candles_daily.append(c)

    def _get_candle_time_str(self, time_str: str, minutes: int, formatted_date: str = "") -> str:
        """시간 문자열(HHMMSS)을 받아서 해당 분봉의 시작 시간(YYYY-MM-DD HH:MM:00)으로 변환합니다."""
        # time_str: "090123"
        if len(time_str) >= 6:
            hh = int(time_str[0:2])
            mm = int(time_str[2:4])
            
            # 15분봉 등은 시각을 넘어갈 수 있으므로 전체 분(minute)으로 계산 후 내림
            total_minutes = hh * 60 + mm
            candle_total_minutes = (total_minutes // minutes) * minutes
            candle_hh = candle_total_minutes // 60
            candle_mm = candle_total_minutes % 60
            
            time_part = f"{candle_hh:02d}:{candle_mm:02d}:00"
            if formatted_date:
                return f"{formatted_date} {time_part}"
            return time_part
        return time_str

    def _update_candle(self, current_candle: dict, price: float, volume: int, time_key: str):
        if current_candle is None or current_candle['time'] != time_key:
            # 새 캔들 생성
            return {
                'time': time_key,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': volume
            }
        else:
            # 기존 캔들 갱신
            current_candle['high'] = max(current_candle['high'], price)
            current_candle['low'] = min(current_candle['low'], price)
            current_candle['close'] = price
            current_candle['volume'] += volume
            return current_candle

    def process_realtime_tick(self, current_price: float, volume: int, volume_power: float, time_str: str, date_str: str = None):
        """실시간 틱(또는 폴링된 데이터)을 수신하여 분봉과 일봉을 업데이트합니다."""
        self.latest_price = current_price
        
        # 일봉 업데이트 (date_str가 제공되면 활용, 아니면 오늘 날짜)
        if not date_str:
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        
        # --- 120틱 캔들 업데이트 로직 ---
        if len(time_str) >= 6:
            full_time_str = f"{formatted_date} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
        else:
            full_time_str = f"{formatted_date} 00:00:00"
            
        self.current_120t_buffer.append({
            'price': current_price,
            'volume': volume,
            'time': full_time_str
        })
        
        if len(self.current_120t_buffer) >= 120:
            prices = [t['price'] for t in self.current_120t_buffer]
            volumes = [t['volume'] for t in self.current_120t_buffer]
            # 마지막 틱의 시간으로 캔들 시간 설정
            candle_time = self.current_120t_buffer[-1]['time']
            
            new_120t_candle = {
                'time': candle_time,
                'open': prices[0],
                'high': max(prices),
                'low': min(prices),
                'close': prices[-1],
                'volume': sum(volumes)
            }
            self.candles_120t.append(new_120t_candle)
            self.current_120t_buffer.clear()
            
        # --- 분봉 및 일봉 업데이트 로직 ---
        
        # 1분봉 업데이트
        time_1m = self._get_candle_time_str(time_str, 1, formatted_date)
        if self.current_1m_candle is None and len(self.candles_1m) > 0 and self.candles_1m[-1]['time'] == time_1m:
            self.current_1m_candle = self.candles_1m.pop()
            
        if self.current_1m_candle and self.current_1m_candle['time'] != time_1m:
            self.candles_1m.append(self.current_1m_candle)
            self.current_1m_candle = None
            
        self.current_1m_candle = self._update_candle(self.current_1m_candle, current_price, volume, time_1m)
        
        # 3분봉 업데이트
        time_3m = self._get_candle_time_str(time_str, 3, formatted_date)
        if self.current_3m_candle is None and len(self.candles_3m) > 0 and self.candles_3m[-1]['time'] == time_3m:
            self.current_3m_candle = self.candles_3m.pop()
            
        if self.current_3m_candle and self.current_3m_candle['time'] != time_3m:
            self.candles_3m.append(self.current_3m_candle)
            self.current_3m_candle = None
            
        self.current_3m_candle = self._update_candle(self.current_3m_candle, current_price, volume, time_3m)

        # 5분봉 업데이트
        time_5m = self._get_candle_time_str(time_str, 5, formatted_date)
        if self.current_5m_candle is None and len(self.candles_5m) > 0 and self.candles_5m[-1]['time'] == time_5m:
            self.current_5m_candle = self.candles_5m.pop()
            
        if self.current_5m_candle and self.current_5m_candle['time'] != time_5m:
            self.candles_5m.append(self.current_5m_candle)
            self.current_5m_candle = None
            
        self.current_5m_candle = self._update_candle(self.current_5m_candle, current_price, volume, time_5m)

        # 15분봉 업데이트
        time_15m = self._get_candle_time_str(time_str, 15, formatted_date)
        if self.current_15m_candle is None and len(self.candles_15m) > 0 and self.candles_15m[-1]['time'] == time_15m:
            self.current_15m_candle = self.candles_15m.pop()
            
        if self.current_15m_candle and self.current_15m_candle['time'] != time_15m:
            self.candles_15m.append(self.current_15m_candle)
            self.current_15m_candle = None
            
        self.current_15m_candle = self._update_candle(self.current_15m_candle, current_price, volume, time_15m)

        # 30분봉 업데이트
        time_30m = self._get_candle_time_str(time_str, 30, formatted_date)
        if self.current_30m_candle is None and len(self.candles_30m) > 0 and self.candles_30m[-1]['time'] == time_30m:
            self.current_30m_candle = self.candles_30m.pop()
            
        if self.current_30m_candle and self.current_30m_candle['time'] != time_30m:
            self.candles_30m.append(self.current_30m_candle)
            self.current_30m_candle = None
            
        self.current_30m_candle = self._update_candle(self.current_30m_candle, current_price, volume, time_30m)
        
        # 일봉은 이미 위에서 date_str 처리함
        daily_time_str = f"{formatted_date} 09:00:00"
        
        if self.current_daily_candle is None and len(self.candles_daily) > 0 and self.candles_daily[-1]['time'] == daily_time_str:
            self.current_daily_candle = self.candles_daily.pop()
            
        if self.current_daily_candle and self.current_daily_candle['time'] != daily_time_str:
            self.candles_daily.append(self.current_daily_candle)
            self.current_daily_candle = None
            
        self.current_daily_candle = self._update_candle(self.current_daily_candle, current_price, volume, daily_time_str)

    def get_completed_and_current_120t_candles(self) -> list:
        """완성된 120틱 리스트와 현재 진행중인 120틱 버퍼를 캔들 형태로 합쳐서 반환합니다."""
        lst = list(self.candles_120t)
        if self.current_120t_buffer:
            prices = [t['price'] for t in self.current_120t_buffer]
            volumes = [t['volume'] for t in self.current_120t_buffer]
            candle_time = self.current_120t_buffer[-1]['time']
            current_candle = {
                'time': candle_time,
                'open': prices[0],
                'high': max(prices),
                'low': min(prices),
                'close': prices[-1],
                'volume': sum(volumes)
            }
            lst.append(current_candle)
        return lst

    def get_completed_and_current_1m_candles(self) -> list:
        """완성된 1분봉 리스트와 현재 진행중인 1분봉을 합쳐서 반환합니다."""
        lst = list(self.candles_1m)
        if self.current_1m_candle:
            lst.append(self.current_1m_candle)
        return lst

    def get_completed_and_current_3m_candles(self) -> list:
        """완성된 3분봉 리스트와 현재 진행중인 3분봉을 합쳐서 반환합니다."""
        lst = list(self.candles_3m)
        if self.current_3m_candle:
            lst.append(self.current_3m_candle)
        return lst

    def get_completed_and_current_15m_candles(self):
        """
        지표 계산용 15분봉 캔들 세트를 반환합니다. (완성된 캔들 + 실시간 변동 중인 현재 캔들)
        """
        c_list = list(self.candles_15m)
        if self.current_15m_candle:
            c_list.append(self.current_15m_candle)
        return c_list

    def get_completed_and_current_5m_candles(self):
        """
        지표 계산용 5분봉 캔들 세트를 반환합니다. (완성된 캔들 + 실시간 변동 중인 현재 캔들)
        """
        c_list = list(self.candles_5m)
        if self.current_5m_candle:
            c_list.append(self.current_5m_candle)
        return c_list

    def get_completed_and_current_30m_candles(self):
        """
        지표 계산용 30분봉 캔들 세트를 반환합니다. (완성된 캔들 + 실시간 변동 중인 현재 캔들)
        """
        c_list = list(self.candles_30m)
        if self.current_30m_candle:
            c_list.append(self.current_30m_candle)
        return c_list
        
    def get_completed_and_current_daily_candles(self) -> list:
        """완성된 일봉 리스트와 현재 진행중인 일봉을 합쳐서 반환합니다."""
        lst = list(self.candles_daily)
        if self.current_daily_candle:
            lst.append(self.current_daily_candle)
        return lst
