import sys
from kiwoom_client import KiwoomClient
client = KiwoomClient()
res = client.get_top_trading_value_stocks(market_type="000", limit=100)
for code in res:
    name = client.get_stock_name(code)
    if name and ("LG" in name or "씨엔에스" in name):
        print(f"{name} : {code}")
