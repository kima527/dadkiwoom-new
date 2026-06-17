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
        self.candles_3m = deque(maxlen=10)
        self.candles_15m = deque(maxlen=200)
        self.candles_daily = deque(maxlen=20)  # 일봉 (SMA3, SMA5 계산용)
        
        # 현재 진행 중인 캔들 상태
        self.current_3m_candle = None
        self.current_15m_candle = None
        self.current_daily_candle = None
        
        # 현재가
        self.latest_price = 0.0

    def seed_initial_data(self, past_3m: list, past_15m: list, past_daily: list = None):
        """프로그램 시작 시 과거 분봉/일봉 데이터를 적재합니다."""
        if past_3m:
            for c in past_3m:
                self.candles_3m.append(c)
        if past_15m:
            for c in past_15m:
                self.candles_15m.append(c)
        if past_daily:
            for c in past_daily:
                self.candles_daily.append(c)

    def _get_candle_time_str(self, time_str: str, minutes: int) -> str:
        """시간 문자열(HHMMSS)을 받아서 해당 분봉의 시작 시간(HHMM00)으로 변환합니다."""
        # time_str: "090123"
        if len(time_str) >= 6:
            hh = int(time_str[0:2])
            mm = int(time_str[2:4])
            
            # 15분봉 등은 시각을 넘어갈 수 있으므로 전체 분(minute)으로 계산 후 내림
            total_minutes = hh * 60 + mm
            candle_total_minutes = (total_minutes // minutes) * minutes
            candle_hh = candle_total_minutes // 60
            candle_mm = candle_total_minutes % 60
            
            return f"{candle_hh:02d}{candle_mm:02d}00"
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

    def process_realtime_tick(self, current_price: float, volume: int, time_str: str, date_str: str = None):
        """실시간 틱(또는 폴링된 데이터)을 수신하여 분봉과 일봉을 업데이트합니다."""
        self.latest_price = current_price
        
        # 3분봉 업데이트
        time_3m = self._get_candle_time_str(time_str, 3)
        if self.current_3m_candle and self.current_3m_candle['time'] != time_3m:
            self.candles_3m.append(self.current_3m_candle)
            self.current_3m_candle = None
            
        self.current_3m_candle = self._update_candle(self.current_3m_candle, current_price, volume, time_3m)

        # 15분봉 업데이트
        time_15m = self._get_candle_time_str(time_str, 15)
        if self.current_15m_candle and self.current_15m_candle['time'] != time_15m:
            self.candles_15m.append(self.current_15m_candle)
            self.current_15m_candle = None
            
        self.current_15m_candle = self._update_candle(self.current_15m_candle, current_price, volume, time_15m)
        
        # 일봉 업데이트 (date_str가 제공되면 활용, 아니면 오늘 날짜)
        if not date_str:
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            
        if self.current_daily_candle and self.current_daily_candle['time'] != date_str:
            self.candles_daily.append(self.current_daily_candle)
            self.current_daily_candle = None
            
        self.current_daily_candle = self._update_candle(self.current_daily_candle, current_price, volume, date_str)

    def get_completed_and_current_3m_candles(self) -> list:
        """완성된 3분봉 리스트와 현재 진행중인 3분봉을 합쳐서 반환합니다."""
        lst = list(self.candles_3m)
        if self.current_3m_candle:
            lst.append(self.current_3m_candle)
        return lst

    def get_completed_and_current_15m_candles(self) -> list:
        """완성된 15분봉 리스트와 현재 진행중인 15분봉을 합쳐서 반환합니다."""
        lst = list(self.candles_15m)
        if self.current_15m_candle:
            lst.append(self.current_15m_candle)
        return lst
        
    def get_completed_and_current_daily_candles(self) -> list:
        """완성된 일봉 리스트와 현재 진행중인 일봉을 합쳐서 반환합니다."""
        lst = list(self.candles_daily)
        if self.current_daily_candle:
            lst.append(self.current_daily_candle)
        return lst
