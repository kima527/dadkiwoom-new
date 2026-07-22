import logging
import time

logger = logging.getLogger(__name__)

class DynamicPoolManager:
    def __init__(self, api_client, max_pool_size=40):
        self.api_client = api_client
        self.max_pool_size = max_pool_size
        self.last_rebalance_time = 0
        self.rebalance_interval = 600  # 10분 (초)
        
    def get_market_ranking_codes(self):
        """거래대금/등락률 상위 종목 수집 로직 삭제됨 (고정 관심종목 전용)"""
        return [], []
        
    def rebalance_pool(self, current_active_codes, my_pick_codes, holdings_raw, unfilled_raw):
        """
        10분마다 호출되어 교체할 종목(add, remove) 리스트를 반환합니다.
        
        :param current_active_codes: 현재 메모리에 구동 중인 종목 리스트
        :param my_pick_codes: 엑셀 파일 등에서 불러온 고정 관심 종목 리스트
        :param holdings_raw: get_holdings() 에서 반환된 잔고 리스트
        :param unfilled_raw: get_unfilled_orders() 에서 반환된 미체결 리스트
        :return: (추가할_종목_리스트, 삭제할_종목_리스트)
        """
        current_time = time.time()
        if current_time - self.last_rebalance_time < self.rebalance_interval:
            return [], [] # 아직 쿨타임
            
        logger.info("🔄 [다이내믹 리밸런싱] 시장 주도주 랭킹 분석 시작...")
        
        # 1. 절대 삭제하면 안 되는 종목 가드 (잔고 보유 + 미체결)
        protected_codes = set()
        
        # 잔고 파싱 (보유 수량이 있는 종목 보호)
        for item in holdings_raw:
            code = item.get("code") or item.get("stk_cd")
            if code:
                # 코드에서 'A' 등의 접두사가 있을 수 있으니 제거
                protected_codes.add(code.replace('A', ''))
                
        # 미체결 파싱 (미체결 수량이 있는 종목 보호)
        for ord_item in unfilled_raw:
            code = ord_item.get("code") or ord_item.get("stk_cd")
            if code:
                protected_codes.add(code.replace('A', ''))
                
        # 2. 최신 실시간 랭킹 종목 로드
        intersection_codes, trade_codes = self.get_market_ranking_codes()
        
        # 3. 새로운 풀 구성 (보유/미체결 보호 종목 최우선)
        new_candidate_pool = list(protected_codes)
        
        # 4. [1순위] 거래대금 & 등락률 교집합 종목 편입
        for code in intersection_codes:
            if len(new_candidate_pool) >= self.max_pool_size:
                break
            if code not in new_candidate_pool:
                new_candidate_pool.append(code)
                
        # 5. [2순위] 슬롯이 남으면 거래대금 최상위 종목들로 순차적 채움
        for code in trade_codes:
            if len(new_candidate_pool) >= self.max_pool_size:
                break
            if code not in new_candidate_pool:
                new_candidate_pool.append(code)
                
        # 4. 기존 풀(current_active_codes)과 비교하여 삭제/추가 리스트 분리
        to_remove = []
        to_add = []
        
        for old_code in current_active_codes:
            if old_code not in new_candidate_pool and old_code not in protected_codes:
                to_remove.append(old_code)
                
        for new_code in new_candidate_pool:
            if new_code not in current_active_codes:
                to_add.append(new_code)
                
        self.last_rebalance_time = current_time
        
        if to_remove or to_add:
            logger.info(f"✅ [리밸런싱 완료] 퇴출: {len(to_remove)}개, 신규: {len(to_add)}개 / 현재 타겟 수: {len(new_candidate_pool)}")
            
        return to_add, to_remove
