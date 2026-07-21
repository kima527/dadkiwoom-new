import os
import json
import logging
from kiwoom_api import KiwoomRESTClient
from theme_manager import ThemeManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class ConditionScanner:
    def __init__(self):
        self.client = KiwoomRESTClient()
        self.condition_name = "Traiding" # The condition name specified by the user

    def run_scan(self):
        logger.info(f"🚀 Starting condition search scanner for [{self.condition_name}]")
        
        # 1. Fetch matching stocks from Kiwoom server
        matched_codes = self.client.get_condition_search_stocks(self.condition_name)
        
        if not matched_codes:
            logger.warning("No stocks matched the condition search.")
            return
            
        logger.info(f"Found {len(matched_codes)} stocks matching the condition.")
        
        # 2. Build the watchlist dictionary with real Naver Theme classification
        tm = ThemeManager()
        tm.load_top_themes(limit=30) # 당일 핫 테마 상위 30개 스크래핑
        
        sub_watchlist = {}
        for code in matched_codes:
            name = self.client.get_stock_name(code)
            themes = tm.get_stock_themes(code) # 네이버 테마 리스트 확인
            
            # Assign weights based on the classified theme (핫테마면 1.2배)
            weight = 1.2 if themes else 1.0
            theme_str = ", ".join(themes) if themes else "개별이슈"
                
            sub_watchlist[code] = {
                "name": name,
                "theme": theme_str,
                "weight": weight
            }
            logger.info(f"Classified [{name}]: Theme={theme_str}, Weight={weight}")
            
        # 3. Save to sub_watchlist.json
        output_path = os.path.join(os.path.dirname(__file__), '..', 'sub_watchlist.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(sub_watchlist, f, indent=4, ensure_ascii=False)
            
        logger.info(f"✅ Successfully saved {len(matched_codes)} stocks to {output_path}")

if __name__ == "__main__":
    scanner = ConditionScanner()
    scanner.run_scan()
