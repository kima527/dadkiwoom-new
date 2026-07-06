import sys
import time
from kiwoom_client import KiwoomClient

def main():
    client = KiwoomClient()
    
    if not client.test_connection():
        print("API 연결 실패.")
        return
    
    target_code = "005930" # 삼성전자
    qty = 1
    
    print("1주 시장가 매수 주문 전송...")
    client.place_buy_order(target_code, qty, price=0, order_type="03") # 03: 시장가
    
    print("3초 대기...")
    time.sleep(3)
    
    print("1주 시장가 매도 주문 전송...")
    client.place_sell_order(target_code, qty, price=0, order_type="03") # 03: 시장가
    
    print("주문 테스트 완료.")
    
    # app.exec_() is not strictly needed for just sending order and exiting, but wait a bit
    time.sleep(1)

if __name__ == "__main__":
    main()
