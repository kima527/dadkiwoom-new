import sys
from kiwoom_client import KiwoomClient

def main():
    client = KiwoomClient()
    if not client.test_connection():
        return
        
    print("\n--- Requesting holdings raw data ---")
    result = client.account_api.account_evaluation_balance_detail_request_kt00018(
        query_type="1",
        domestic_exchange_type="KRX"
    )
    import pprint
    pprint.pprint(result)

if __name__ == "__main__":
    main()
