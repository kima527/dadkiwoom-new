import config
from kiwoom_client import KiwoomClient

client = KiwoomClient()
holdings = client.get_holdings()
print("HOLDINGS:", holdings)
