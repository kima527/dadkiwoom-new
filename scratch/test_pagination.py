import sys
import os

# Add real trading folder to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))

import config
from kiwoom_client import KiwoomClient
from kiwoom_rest_api.koreanstock.sector import Sector

def fetch_all_components(mrkt_tp, inds_cd):
    client = KiwoomClient()
    sector_api = Sector(base_url=client.base_url, token_manager=client.token_manager)
    
    all_stocks = []
    cont_yn = "N"
    next_key = ""
    
    print(f"Fetching components for mrkt_tp={mrkt_tp}, inds_cd={inds_cd}...")
    while True:
        res = sector_api.industrywise_stock_price_request_ka20002(
            mrkt_tp=mrkt_tp,
            inds_cd=inds_cd,
            stex_tp="1",
            cont_yn=cont_yn,
            next_key=next_key
        )
        if not res or res.get("return_code") != 0:
            print("Failed:", res)
            break
            
        stocks = res.get("inds_stkpc", [])
        all_stocks.extend(stocks)
        print(f"  Fetched {len(stocks)} stocks (Total: {len(all_stocks)})")
        
        # Check if there is next_key or continuation
        # Let's print the keys to see what is returned
        print("Response keys:", list(res.keys()))
        next_key = res.get("next_key", "")
        # If there is no next_key, or it is empty, stop
        if not next_key:
            # Check other possible pagination indicators in Kiwoom REST API responses
            # e.g., 'tr_cont' or 'cont_yn'
            break
            
        cont_yn = "Y"
        # Delay to comply with API rate limit
        import time
        time.sleep(0.5)
        
    return all_stocks

if __name__ == "__main__":
    kospi200 = fetch_all_components("0", "201")
    print(f"Final KOSPI 200 count: {len(kospi200)}")
    
    kosdaq150 = fetch_all_components("1", "150")
    print(f"Final KOSDAQ 150 count: {len(kosdaq150)}")
