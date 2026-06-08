"""
매수/매도 주문 테스트 스크립트
기업은행(024110) 1주를 매수한 뒤 즉시 매도하여 주문 시스템이 정상 작동하는지 확인합니다.
"""
import time
from kiwoom_client import KiwoomRealClient

client = KiwoomRealClient()

TEST_CODE = "024110"  # 기업은행 (저가 종목이라 1주 테스트에 적합)
TEST_QTY = 1

print("=" * 60)
print("🧪 매수/매도 주문 테스트 시작")
print("=" * 60)

# 1) 현재가 조회
print(f"\n[1] {TEST_CODE} 현재가 조회 중...")
try:
    info = client.stock_info_api.basic_stock_information_request_ka10001(stock_code=TEST_CODE)
    if info and info.get("return_code") == 0:
        cur_price = abs(int(info.get("cur_prc", "0")))
        stock_name = info.get("stk_nm", "").strip()
        print(f"  ✅ 종목명: {stock_name}, 현재가: {cur_price:,}원")
    else:
        print(f"  ❌ 현재가 조회 실패: {info}")
        cur_price = 0
        stock_name = TEST_CODE
except Exception as e:
    print(f"  ❌ 현재가 조회 에러: {e}")
    cur_price = 0
    stock_name = TEST_CODE

if cur_price == 0:
    print("현재가를 알 수 없어 테스트를 중단합니다.")
    exit(1)

# 2) 매수 주문 (시장가)
print(f"\n[2] 매수 주문: {stock_name}({TEST_CODE}) {TEST_QTY}주 @ 시장가")
buy_res = client.place_buy_order(TEST_CODE, TEST_QTY, price=cur_price, order_type="3")
print(f"  📦 매수 응답: {buy_res}")

if buy_res and buy_res.get("return_code") == 0:
    print(f"  ✅ 매수 주문 성공! 주문번호: {buy_res.get('ord_no')}")
else:
    err_msg = buy_res.get("return_msg") if buy_res else "응답 없음"
    print(f"  ❌ 매수 주문 실패: {err_msg}")
    
    # 시장가 실패 시 지정가로 재시도
    print(f"\n[2-1] 지정가 매수 재시도: {cur_price:,}원")
    buy_res = client.place_buy_order(TEST_CODE, TEST_QTY, price=cur_price, order_type="0")
    print(f"  📦 지정가 매수 응답: {buy_res}")
    if buy_res and buy_res.get("return_code") == 0:
        print(f"  ✅ 지정가 매수 주문 성공! 주문번호: {buy_res.get('ord_no')}")
    else:
        err_msg2 = buy_res.get("return_msg") if buy_res else "응답 없음"
        print(f"  ❌ 지정가 매수도 실패: {err_msg2}")

# 3) 5초 대기 (체결 기다리기)
print("\n[3] 5초 대기 (체결 대기)...")
time.sleep(5)

# 4) 보유 종목 확인
print("\n[4] 보유 종목 확인...")
holdings = client.get_holdings()
print(f"  보유 종목: {holdings}")

# 5) 매도 주문
print(f"\n[5] 매도 주문: {stock_name}({TEST_CODE}) {TEST_QTY}주 @ 시장가")
sell_res = client.place_sell_order(TEST_CODE, TEST_QTY, price=cur_price, order_type="3")
print(f"  📦 매도 응답: {sell_res}")

if sell_res and sell_res.get("return_code") == 0:
    print(f"  ✅ 매도 주문 성공! 주문번호: {sell_res.get('ord_no')}")
else:
    err_msg = sell_res.get("return_msg") if sell_res else "응답 없음"
    print(f"  ❌ 매도 주문 실패: {err_msg}")
    
    # 시장가 실패 시 지정가로 재시도
    print(f"\n[5-1] 지정가 매도 재시도: {cur_price:,}원")
    sell_res = client.place_sell_order(TEST_CODE, TEST_QTY, price=cur_price, order_type="0")
    print(f"  📦 지정가 매도 응답: {sell_res}")
    if sell_res and sell_res.get("return_code") == 0:
        print(f"  ✅ 지정가 매도 주문 성공! 주문번호: {sell_res.get('ord_no')}")
    else:
        err_msg2 = sell_res.get("return_msg") if sell_res else "응답 없음"
        print(f"  ❌ 지정가 매도도 실패: {err_msg2}")

print("\n" + "=" * 60)
print("🧪 테스트 완료")
print("=" * 60)
