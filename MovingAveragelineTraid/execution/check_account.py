import sys
import os
import logging

# 콘솔 출력 인코딩 강제 설정 (Windows)
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# real trading 폴더 경로를 최우선으로 추가 (해당 폴더의 config.py를 로드하기 위함)
real_trading_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading")
sys.path.insert(0, real_trading_path)

try:
    from kiwoom_client import KiwoomRealClient
except ImportError as e:
    print(f"Error importing KiwoomRealClient: {e}")
    sys.exit(1)

def check_account():
    print("==================================================")
    print(" 📊 실시간 계좌 잔고 및 보유 종목 조회 스크립트")
    print("==================================================")
    print("키움증권 서버에 연결 중입니다 (Real Trading API)...")
    
    try:
        client = KiwoomRealClient()
    except Exception as e:
        print(f"클라이언트 초기화 실패: {e}")
        return
    
    if not client.test_connection():
        print("\n❌ API 연결에 실패했습니다.")
        print("-> 원인: .env 파일에 키움증권 앱 키(APP_KEY/SECRET)가 없거나 잘못되었습니다.")
        print("-> 확인 경로: C:\\Users\\zoela\\OneDrive\\바탕 화면\\PythonWorksplace\\.env")
        return

    # 예수금 조회
    cash = client.get_cash_balance()
    print(f"\n💰 [예수금 현황]")
    print(f" - 매수 가능 금액: {cash:,.0f}원")

    # 잔고 조회
    holdings = client.get_holdings()
    print(f"\n📦 [보유 종목 현황]")
    if not holdings:
        print(" - 현재 보유 중인 종목이 없습니다. (빈 계좌)")
    else:
        for h in holdings:
            profit_rate = ((h['current_price'] - h['buy_price']) / h['buy_price'] * 100) if h['buy_price'] > 0 else 0.0
            print(f" - {h['name']}({h['code']}): {h['quantity']}주")
            print(f"   └ 매수단가: {h['buy_price']:,.0f}원 | 현재가: {h['current_price']:,.0f}원 | 수익률: {profit_rate:+.2f}%")
            
    # 미체결 조회 (해당 메서드가 존재할 경우)
    print(f"\n⏳ [미체결 내역]")
    if hasattr(client, 'get_unexecuted_orders'):
        try:
            unexec = client.get_unexecuted_orders()
            if not unexec:
                print(" - 미체결 주문이 없습니다.")
            else:
                for u in unexec:
                    print(f" - {u}")
        except Exception as e:
            print(" - 미체결 내역 조회 실패 또는 권한 없음")
    else:
        print(" - (기존 클라이언트에 미체결 조회 기능 미구현)")
        
    print("\n✅ 조회가 완료되었습니다.")

if __name__ == "__main__":
    check_account()
