import sys
import os
import time
import logging

if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

real_trading_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading")
sys.path.insert(0, real_trading_path)

try:
    from kiwoom_client import KiwoomRealClient
except ImportError as e:
    print(f"Error importing KiwoomRealClient: {e}")
    sys.exit(1)

def execute_test_trade():
    print("==================================================")
    print(" ⚠️ [실전 매매] 1주 매도 후 1주 매수 테스트 ⚠️")
    print("==================================================")
    
    client = KiwoomRealClient()
    if not client.test_connection():
        print("❌ API 연결에 실패했습니다.")
        return

    stock_code = "005930" # 삼성전자
    qty = 1

    print(f"\n[1/2] {stock_code} (삼성전자) {qty}주 '시장가' 매도 주문 전송 중...")
    # 시장가 매도 (order_type="03")
    sell_result = client.place_sell_order(stock_code, qty, order_type="03")
    print(f"-> 매도 주문 결과: {sell_result}")

    print("\n[대기] 체결을 위해 3초 대기합니다...")
    time.sleep(3)

    print(f"\n[2/2] {stock_code} (삼성전자) {qty}주 '시장가' 매수 주문 전송 중...")
    # 시장가 매수 (order_type="03")
    buy_result = client.place_buy_order(stock_code, qty, order_type="03")
    print(f"-> 매수 주문 결과: {buy_result}")
    
    print("\n✅ 테스트 거래가 완료되었습니다.")

if __name__ == "__main__":
    execute_test_trade()
