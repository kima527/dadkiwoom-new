import sys
import os
import time

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

def extract_order_no(result):
    if not result: return None
    # 응답 dict 안에 주문번호(ord_no)가 있는지 탐색
    for k, v in result.items():
        if 'ord_no' in k.lower() and str(v).strip():
            return str(v).strip()
    return None

def execute_limit_test_trade():
    print("==================================================")
    print(" ⚠️ [실전 매매] 지정가 매수/매도 후 3초 대기 취소 ⚠️")
    print("==================================================")
    
    client = KiwoomRealClient()
    if not client.test_connection():
        print("❌ API 연결 실패")
        return

    stock_code = "005930" # 삼성전자
    qty = 1
    sell_price = 261000
    buy_price = 259000
    
    sell_order_no = None
    buy_order_no = None

    print(f"\n[1/4] {stock_code} {qty}주를 {sell_price}원에 '지정가' 매도 주문 전송 중...")
    sell_result = client.place_sell_order(stock_code, qty, price=sell_price, order_type="00")
    print(f"-> 매도 주문 결과: {sell_result}")
    
    if sell_result and sell_result.get('return_code') == 0:
        sell_order_no = extract_order_no(sell_result)
        if sell_order_no: print(f"✅ 매도 주문번호 확보: {sell_order_no}")
        else: print("⚠️ 결과에 주문번호(ord_no)가 명시되지 않았습니다.")

    print(f"\n[2/4] {stock_code} {qty}주를 {buy_price}원에 '지정가' 매수 주문 전송 중...")
    buy_result = client.place_buy_order(stock_code, qty, price=buy_price, order_type="00")
    print(f"-> 매수 주문 결과: {buy_result}")
    
    if buy_result and buy_result.get('return_code') == 0:
        buy_order_no = extract_order_no(buy_result)
        if buy_order_no: print(f"✅ 매수 주문번호 확보: {buy_order_no}")
        else: print("⚠️ 결과에 주문번호(ord_no)가 명시되지 않았습니다.")

    print("\n[3/4] 3초 대기합니다...")
    time.sleep(3)

    print(f"\n[4/4] 미체결 주문 취소 진행 중...")
    
    if sell_order_no:
        print(f" - 매도 주문 취소 요청 (주문번호: {sell_order_no})")
        c_res = client.cancel_order(sell_order_no, stock_code, qty)
        print(f" -> 취소 결과: {c_res}")
    else:
        print(" - (매도 주문번호가 없거나 주문이 거절되어 취소를 생략합니다)")
        
    if buy_order_no:
        print(f" - 매수 주문 취소 요청 (주문번호: {buy_order_no})")
        c_res = client.cancel_order(buy_order_no, stock_code, qty)
        print(f" -> 취소 결과: {c_res}")
    else:
        print(" - (매수 주문번호가 없거나 주문이 거절되어 취소를 생략합니다)")
        
    print("\n✅ 모든 프로세스가 완료되었습니다.")

if __name__ == "__main__":
    execute_limit_test_trade()
