import pandas as pd

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
    def __init__(self, stock_code: str, max_len: int = 100):
        self.stock_code = stock_code
        self.max_len = max_len
        
        # 원시 틱 체결 데이터 임시 저장소 (120틱 및 1분봉 생성용)
        self.raw_tick_buffer = []
        
        # 로컬에 적립할 최종 캔들 큐 (속도 향상을 위해 deque 사용)
        self.ticks_120_deque = deque(maxlen=max_len)
        self.candles_1m_deque = deque(maxlen=max_len)
        
        # 1분봉 경계면 체크를 위한 변수 (HHMM)
        self.last_processed_minute = ""
        
        logger.info(f"[{stock_code}] RealtimeDataManager 초기화 완료 (max_len={max_len})")

    def seed_initial_data(self, past_120ticks: list, past_1m_candles: list):
        """
        장 시작 전(또는 스크립트 가동 시) REST API로 가져온 과거 데이터를 큐에 채워넣습니다.
        """
        for t in past_120ticks:
            self.ticks_120_deque.append(t)
            
        for c in past_1m_candles:
            self.candles_1m_deque.append(c)
            
            # 마지막 분을 초기화하여 다음 체결 시 분 바뀜을 감지
            if c.get("time") and len(c["time"]) >= 16:
                # "YYYY-MM-DD HH:MM:SS" -> "HHMM"
                time_str = c["time"]
                try:
                    hhmm = time_str[11:13] + time_str[14:16]
                    self.last_processed_minute = hhmm
                except:
                    pass

        logger.info(f"[{self.stock_code}] 초기 시드 데이터 적재 완료: 120틱({len(self.ticks_120_deque)}개), 1분봉({len(self.candles_1m_deque)}개)")

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

    def get_120tick_list(self):
        """메인 루프에서 Phase 2 연산용으로 즉시 가져가는 120틱 리스트 (df 변환 불필요, 딕셔너리 리스트 반환)"""
        # 기존 main.py 구조가 리스트(딕셔너리)를 기반으로 작동하므로 그대로 반환
        return list(self.ticks_120_deque)

    def get_1min_list(self):
        """메인 루프에서 Phase 2 연산용으로 즉시 가져가는 1분봉 리스트"""
        return list(self.candles_1m_deque)
