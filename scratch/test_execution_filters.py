import sys
import os

# Add local path to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))

from kiwoom_client import KiwoomRealClient
from indicator import parse_tick_execution_data

def main():
    print("Initializing Kiwoom Live Client...")
    client = KiwoomRealClient()
    
    # Test connection
    if not client.test_connection():
        print("Failed to authenticate with Kiwoom API.")
        return

    # Check Samsung Electronics (005930)
    stock_code = "005930" # Samsung Electronics
    print(f"\nFetching live tick execution data (ka10003) for code: {stock_code}")
    
    try:
        res = client.stock_info_api.daily_stock_price_request_ka10003(stock_code=stock_code)
        print("Raw Response structure (keys):", res.keys() if res else "None")
        print("Return Code:", res.get("return_code"))
        print("Return Message:", res.get("return_msg"))
        
        # Try checking list and dict keys
        for key in res.keys():
            val = res[key]
            if isinstance(val, list):
                print(f"\nFound list key: {key} (length: {len(val)})")
                if len(val) > 0:
                    print("Sample item:", val[0])
            elif isinstance(val, dict):
                print(f"\nFound dict key: {key}")
                print("Content keys:", val.keys())
                # If there are sub lists in dict
                for sub_key in val.keys():
                    sub_val = val[sub_key]
                    if isinstance(sub_val, list):
                        print(f"  Found sub list: {sub_key} (length: {len(sub_val)})")
                        if len(sub_val) > 0:
                            print("  Sample sub item:", sub_val[0])
        
        # Parse data using indicators function
        volume_power, block_buy_count = parse_tick_execution_data(res)
        print(f"\n--- Analysis Results for {stock_code} ---")
        print(f"Volume Power (체결강도): {volume_power:.2f}%")
        print(f"Block Buy Count (최근 30틱 내 1억 이상 매수 건수): {block_buy_count}건")
        
        # Compare with 15m candle close
        candles_15m = client.get_15min_candles(stock_code, last_n_days=1)
        if candles_15m:
            latest_candle = candles_15m[-1]
            print(f"\nLatest 15m candle close: {latest_candle['close']}")
            print(f"ka10003 latest price: {res.get('cntr_infr')[0].get('cur_prc') if res.get('cntr_infr') else 'N/A'}")
            
        # Test get_tick_size and adjust_price_by_ticks border cases
        print("\n--- Testing KRX Tick Size Logic Border Cases ---")
        from indicator import get_tick_size, adjust_price_by_ticks
        
        test_cases = [
            # (current_price, ticks, expected_price)
            (1999, 1, 2000),      # Border: 1999 + 1 tick (size 1) = 2000
            (1999, 2, 2005),      # Border: 1999 + 2 ticks (1999->2000->2005)
            (2000, -1, 1999),     # Border: 2000 - 1 tick (4999-like logic) = 1999
            (4995, 1, 5000),      # Border: 4995 + 1 tick (size 5) = 5000
            (4995, 2, 5010),      # Border: 4995 + 2 ticks (4995->5000->5010)
            (5000, -1, 4995),     # Border: 5000 - 1 tick = 4995
            (49950, 1, 50000),    # Border: 49950 + 1 tick (size 50) = 50000
            (49950, 2, 50100),    # Border: 49950 + 2 ticks (49950->50000->50100)
            (50000, -1, 49950),   # Border: 50000 - 1 tick = 49950
            (199900, 1, 200000),  # Border: 199900 + 1 tick (size 100) = 200000
            (199900, 2, 200500),  # Border: 199900 + 2 ticks (199900->200000->200500)
            (200000, -1, 199900), # Border: 200000 - 1 tick = 199900
        ]
        
        success = True
        for p, t, expected in test_cases:
            result = adjust_price_by_ticks(p, t)
            matched = (result == expected)
            print(f"Price: {p:7,d} | Ticks: {t:+2d} | Result: {result:7,d} | Expected: {expected:7,d} | {'PASS' if matched else 'FAIL'}")
            if not matched:
                success = False
                
        if success:
            print("\n✅ All KRX Tick Size border tests passed successfully!")
        else:
            print("\n❌ Some KRX Tick Size border tests failed.")
                  
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    main()
