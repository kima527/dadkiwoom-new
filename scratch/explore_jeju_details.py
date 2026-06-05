import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from kiwoom_client import KiwoomClient

def explore():
    client = KiwoomClient()
    code = "000660" # SK Hynix
    
    print("Calling basic_stock_information_request_ka10001 for SK Hynix...")
    try:
        res = client.stock_info_api.basic_stock_information_request_ka10001(stock_code=code)
        print("API Response keys:", res.keys())
        print(json.dumps(res, indent=4, ensure_ascii=False))
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    explore()
