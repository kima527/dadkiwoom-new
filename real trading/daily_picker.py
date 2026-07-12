import asyncio
import pandas as pd
import csv
import os
import sys
from PyQt5.QtWidgets import QApplication
from kiwoom_client import KiwoomClient
from logger_config import setup_logger

logger = setup_logger("daily_picker")

async def get_trend_status(client, code):
    try:
        daily = await asyncio.to_thread(client.get_daily_candles, code, 50)
        await asyncio.sleep(0.3)
        if not daily or len(daily) < 40:
            return False

        df_d = pd.DataFrame({'close': [c['close'] for c in daily]})
        df_d['SMA20'] = df_d['close'].rolling(20).mean()
        df_d['SMA40'] = df_d['close'].rolling(40).mean()
        
        d_sma20 = df_d['SMA20'].iloc[-1]
        d_sma40 = df_d['SMA40'].iloc[-1]

        if pd.isna(d_sma20) or pd.isna(d_sma40):
            return False

        # 일봉 상 정배열(우상향)인지 확인
        return d_sma20 > d_sma40

    except Exception as e:
        logger.error(f"Error analyzing {code}: {e}")
        return False

async def main():
    logger.info("=========================================")
    logger.info("🚀 AI Daily Stock Picker Started")
    logger.info("=========================================")

    # QApplication for Kiwoom API
    app = QApplication(sys.argv)
    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    logger.info("1. 거래대금 상위 종목 수집 중...")
    top_stocks = await asyncio.to_thread(client.get_top_trading_value_stocks, "000", 100)
    
    if not top_stocks:
        logger.error("상위 종목을 가져오지 못했습니다.")
        return

    selected_stocks = []
    
    # 삼성전자는 무조건 첫 번째로 추가 (사용자 요청)
    samsung_code = "005930"
    samsung_name = "삼성전자"
    selected_stocks.append((samsung_code, samsung_name))
    logger.info(f"✅ 필수 포함 종목 추가: {samsung_name} ({samsung_code})")

    logger.info("2. 일봉 추세(SMA 20 > SMA 40) 분석 시작...")
    
    for item in top_stocks:
        if len(selected_stocks) >= 11:  # 총 11개 종목(삼성전자 + 우량주 10개) 채우면 종료
            break
            
        code = item.get("stk_cd", "").replace("A", "")
        name = item.get("stk_nm", "")
        
        if not code or code == samsung_code:
            continue
            
        is_bullish = await get_trend_status(client, code)
        
        if is_bullish:
            selected_stocks.append((code, name))
            logger.info(f"✅ 우상향 종목 포착: {name} ({code}) - 일봉 정배열")
        else:
            logger.debug(f"❌ 추세 약함 패스: {name} ({code})")

    # target_pick.csv 에 저장
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "target_pick.csv")
    try:
        with open(file_path, 'w', encoding='cp949', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['종목코드', '종목명'])
            for code, name in selected_stocks:
                writer.writerow([code, name])
        logger.info(f"🎉 성공적으로 {len(selected_stocks)}개 종목을 {file_path}에 저장했습니다.")
    except Exception as e:
        logger.error(f"파일 저장 중 오류 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())
