import time
import logging
from collections import deque
import asyncio
import heapq
from typing import Callable

logger = logging.getLogger(__name__)

# ==========================================
# [설정값] 초단타 매매 임계값
# ==========================================
MIN_TICK_COUNT_3S = 30        # 3초간 발생해야 할 최소 체결 건수 (빈도수 폭발)
WINDOW_SECONDS = 3.0          # 가속도 측정 윈도우(초)

class ScalpingPositionManager:
    """
    틱 단위로 수익률과 가속도 소멸을 감시하는 동적 청산 알고리즘
    """
    def __init__(self, expected_buy_price, qty):
        self.buy_price = expected_buy_price
        self.qty = qty
        
        self.highest_price = expected_buy_price     
        # [방어선 설정]
        self.stop_loss_ratio = 0.015       
        self.trailing_activation = 0.020   
        self.trailing_drop = 0.007         

    def update_real_buy_price(self, real_chegel_price: float):
        if real_chegel_price > 0:
            self.buy_price = real_chegel_price
            if self.highest_price < real_chegel_price:
                self.highest_price = real_chegel_price
            logger.info(f"🔄 [단가 보정] 예상가 -> 실제 체결가({real_chegel_price}원) 트레일링 기준점 변경")

    def update_tick(self, current_price, current_acceleration):
        if current_price > self.highest_price:
            self.highest_price = current_price

        current_return = (current_price - self.buy_price) / self.buy_price

        if current_return <= -self.stop_loss_ratio:
            return "SELL", "CRITICAL_STOP_LOSS (기본 손절선 이탈)"

        return_from_high = (current_price - self.highest_price) / self.highest_price
        if (self.highest_price - self.buy_price) / self.buy_price >= self.trailing_activation:
            if return_from_high <= -self.trailing_drop:
                return "SELL", "TRAILING_STOP_PROFIT (고점대비 방어선 이탈, 수익 확보)"

        if current_return > 0.005 and current_acceleration <= 0.0001:
            return "SELL", "ACCELERATION_FADE_OUT (가속도 급락, 고점 징후)"

        return "HOLD", "MONITORING"


class TickAccelerationEngine:
    """
    무결점 체결 가속도 분석 엔진 (상위 3종목 캐싱 + 메모리 누수 방지 적용)
    """
    def __init__(self, kiwoom_client, stock_cache: dict):
        self.client = kiwoom_client
        self.stock_cache = stock_cache
        
        self.on_buy_signal: Callable = None
        self.on_sell_signal: Callable = None
        
        self.last_volumes = {}     
        self.tick_buffers = {}     
        self.latest_prices = {}    
        self.rankings = {}         
        self.position_managers = {} 
        
        self.pending_orders = set()
        
        # [O(1) 한계 극복] 상위 3개 종목(Top-3) 캐싱
        # 대장주의 가속도가 감소했을 때 전체 탐색 대신 2등주가 즉각 1등으로 올라올 수 있게 대비
        self.top3_cache = [] # [(accel, code), ...] 
        self.top_code = ""
        self.top_accel = 0.0
        
    def get_latest_price(self, code: str) -> float:
        return self.latest_prices.get(code, 0.0)
        
    def add_position(self, code: str, expected_buy_price: float, qty: int):
        self.position_managers[code] = ScalpingPositionManager(expected_buy_price, qty)
        if code in self.pending_orders:
            self.pending_orders.remove(code) 
            
    def update_position_real_price(self, code: str, real_price: float):
        if code in self.position_managers:
            self.position_managers[code].update_real_buy_price(real_price)
        
    def remove_position(self, code: str):
        if code in self.position_managers:
            del self.position_managers[code]
            
    def release_lock(self, code: str):
        if code in self.pending_orders:
            self.pending_orders.remove(code)
            
    def _update_top3_cache(self):
        """Python C 모듈인 heapq를 활용해 상위 3개를 초고속으로 추출"""
        if not self.rankings:
            self.top3_cache = []
            self.top_code = ""
            self.top_accel = 0.0
            return
            
        top3_items = heapq.nlargest(3, list(self.rankings.items()), key=lambda x: x[1])
        self.top3_cache = [(val, k) for k, val in top3_items]
        self.top_code = self.top3_cache[0][1] if self.top3_cache else ""
        self.top_accel = self.top3_cache[0][0] if self.top3_cache else 0.0

    async def process_tick(self, tick_data: dict):
        code = tick_data['code']
        price = tick_data['price']
        accum_volume = tick_data['accum_volume']
        now = time.time()
        
        self.latest_prices[code] = price
        
        if code not in self.stock_cache:
            self.stock_cache[code] = {'name': code}
            
        if code not in self.last_volumes:
            self.last_volumes[code] = accum_volume
            self.tick_buffers[code] = deque()
            return
            
        delta_vol = accum_volume - self.last_volumes[code]
        self.last_volumes[code] = accum_volume
        
        if delta_vol > 0:
            self.tick_buffers[code].append(now)
            
        buffer = self.tick_buffers[code]
        while buffer and now - buffer[0] > WINDOW_SECONDS:
            buffer.popleft()
            
        # 중소형주의 경우 돈의 크기보다 호가창을 연달아 갉아먹는 빈도수가 상승의 핵심입니다.
        accel_ratio = float(len(buffer))
        self.rankings[code] = accel_ratio
        
        # --- 3. [상위 3종목 캐싱 업데이트] ---
        if accel_ratio > self.top_accel:
            # 새로운 대장주 등극 (초고속 업데이트)
            self.top_accel = accel_ratio
            self.top_code = code
            
        elif code == self.top_code and accel_ratio < self.top_accel:
            # 기존 대장주의 힘이 빠진 경우 (Top-3 캐시 재구축)
            self._update_top3_cache()
            
        elif self.top3_cache and code in [c for _, c in self.top3_cache]:
            # 2등, 3등주의 가속도가 변동된 경우 순위 재정렬 필요 시
            if accel_ratio > self.top3_cache[1][0] if len(self.top3_cache) > 1 else True:
                self._update_top3_cache()
                
        # --- 4. [랭킹 정보 제공용 속성 업데이트] ---
        # 외부 루프(main_condition_scalper)에서 top3_cache나 rankings 딕셔너리를 직접 조회합니다.
        pass
