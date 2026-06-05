import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from kiwoom_client import KiwoomClient

def explore():
    client = KiwoomClient()
    code = "000660" # SK Hynix
    
    print("Calling daily_stock_price_request_ka10003 for SK Hynix...")
    try:
        res = client.stock_info_api.daily_stock_price_request_ka10003(stock_code=code)
        # print first item keys
        items = res.get("stk_dt_prc_qry", [])
        if items:
            print("First item keys:", items[0].keys())
            print(json.dumps(items[0], indent=4, ensure_ascii=False))
        else:
            print("No items returned in daily price trend:", res)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    explore()
