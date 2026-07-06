import sys
from kiwoom_client import KiwoomClient

def main():
    client = KiwoomClient()
    if not client.test_connection():
        return
        
    print("\n--- Testing get_holdings ---")
    holdings = client.get_holdings()
    print("Holdings:", holdings)

if __name__ == "__main__":
    main()
