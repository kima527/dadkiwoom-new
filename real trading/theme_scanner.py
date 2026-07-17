import os
import sys
import logging
import asyncio
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from kiwoom_client import KiwoomClient

logger = logging.getLogger(__name__)

class ThemeScanner:
    def __init__(self, client: KiwoomClient):
        self.client = client

    def get_market_leaders(self, top_n=3, min_fluctuation=10.0) -> list:
        """
        거래대금 상위 + 등락률 상위의 교집합을 찾아 당일 완벽한 대장주(주도주)를 반환합니다.
        min_fluctuation: 당일 최고가(또는 현재가)가 최소 이 퍼센트 이상 오른 종목만 취급.
        """
        logger.info("🔍 [스캐너] 당일 주도테마 대장주 색출 작업을 시작합니다...")
        
        try:
            # 1. 거래대금 상위 100위 추출 (시장 전체)
            vol_top = self.client.get_top_trading_value_stocks(market_type="000", limit=100)
            if not vol_top:
                logger.error("거래대금 상위 목록을 불러오지 못했습니다.")
                return []
                
            vol_codes = [item['code'] for item in vol_top]
            
            # 2. 등락률 상위 100위 추출 (시장 전체)
            fluc_top = self.client.get_top_fluctuation_stocks_with_rates(market_type="000", limit=100)
            if not fluc_top:
                # Fallback to get_top_fluctuation_stocks if dict version is empty/fails
                fluc_top_list = self.client.get_top_fluctuation_stocks(market_type="000", limit=100)
                fluc_codes = [item['code'] for item in fluc_top_list]
                fluc_rates = {code: 10.0 for code in fluc_codes} # 임시 비율
            else:
                fluc_codes = list(fluc_top.keys())
                fluc_rates = fluc_top
                
            # 3. 교집합 추출 (돈이 가장 많이 몰리면서 가장 많이 오른 종목 = 주도주)
            leaders = []
            for code in vol_codes:
                if code in fluc_codes:
                    rate = float(fluc_rates.get(code, 0.0))
                    if rate >= min_fluctuation:
                        leaders.append(code)
                        
            # ETF, ETN, 스팩 등 제외 로직 (간단히 코드 첫자리 필터)
            leaders = [code for code in leaders if code[0] not in ['5', '7']]
            
            # 상위 top_n 개만 추출
            final_leaders = leaders[:top_n]
            
            if final_leaders:
                names_dict = self.client.get_stock_names(final_leaders)
                for code in final_leaders:
                    logger.info(f"👑 [대장주 포착] {names_dict.get(code, code)} ({code}) - 현재 등락률: {fluc_rates.get(code, 0.0)}%")
            else:
                logger.warning("조건에 맞는 대장주가 없습니다.")
                
            return final_leaders
            
        except Exception as e:
            logger.error(f"대장주 스캔 중 오류 발생: {e}")
            return []

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    client = KiwoomClient()
    if client.test_connection():
        scanner = ThemeScanner(client)
        leaders = scanner.get_market_leaders()
        print(f"최종 추출된 대장주 코드: {leaders}")
