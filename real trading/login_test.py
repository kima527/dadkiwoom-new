import sys
import os
import logging

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from kiwoom_client import KiwoomRealClient
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def test_real_login():
    print("=" * 60)
    print("        🚀 KIWOOM REAL TRADING CONNECTION TEST 🚀")
    print("=" * 60)
    
    # 1. 설정 출력
    config.print_real_config()
    
    # 2. 키 값 유효성 기본 검사
    if config.KIWOOM_APP_KEY == "실전용_APP_KEY_입력" or not config.KIWOOM_APP_KEY:
        logger.error("❌ 'KIWOOM_REAL_APP_KEY' 설정이 누락되었거나 기본 템플릿 값입니다.")
        logger.info("real trading 폴더의 '.env' 파일을 열어 발급받은 실전 API Key를 기입해주세요.")
        return
        
    if config.KIWOOM_REAL_APP_SECRET == "실전용_APP_SECRET_입력" or not config.KIWOOM_REAL_APP_SECRET:
        logger.error("❌ 'KIWOOM_REAL_APP_SECRET' 설정이 누락되었거나 기본 템플릿 값입니다.")
        return

    # 3. 클라이언트 객체 생성 및 로그인 테스트
    try:
        logger.info("Connecting to Kiwoom Real API server...")
        client = KiwoomRealClient()
        
        # OAuth 2.0 세션 연결 테스트
        success = client.test_connection()
        if success:
            print("\n" + "🟢" * 20)
            print("  인증 성공: 키움 실전투자 서버 세션이 성공적으로 활성화되었습니다!")
            print("🟢" * 20 + "\n")
            
            # 계좌 예수금 및 잔고를 한 번 테스트 삼아 조회해봅니다.
            logger.info("Testing account query APIs...")
            cash = client.get_cash_balance()
            logger.info(f"💰 실전 계좌 예수금: {cash:,.0f} 원")
            
            holdings = client.get_holdings()
            logger.info(f"📦 현재 보유 종목 수: {len(holdings)}개")
            for idx, h in enumerate(holdings, 1):
                logger.info(f"  [{idx}] {h['name']} ({h['code']}) | 수량: {h['quantity']}주 | 매입가: {h['buy_price']:,.0f}원")
                
            print("\n" + "=" * 60)
            print("  ✅ 실전매매 연결 테스트 완료 (모든 세션 정상 작동)")
            print("=" * 60)
        else:
            print("\n" + "🔴" * 20)
            print("  인증 실패: APP_KEY 및 APP_SECRET을 다시 확인해주세요.")
            print("🔴" * 20 + "\n")
            
    except Exception as e:
        logger.error(f"❌ 로그인 과정 중 예상치 못한 치명적 오류가 발생했습니다: {e}")
        logger.info("패키지 설치 상태 또는 키움증권 Open API 실거래 등록 상태를 점검해주세요.")

if __name__ == "__main__":
    test_real_login()
