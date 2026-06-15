import os
import sys
import json
import time
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Add current directory to path so we can import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from kiwoom_client import KiwoomClient

SEED_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data")

def fetch_and_save_seed_data():
    logger.info("==============================================")
    logger.info("시드 데이터 야간 프리패치(Pre-fetch) 작업을 시작합니다.")
    logger.info("==============================================")
    
    if not os.path.exists(SEED_DATA_DIR):
        os.makedirs(SEED_DATA_DIR)
        logger.info(f"생성됨: {SEED_DATA_DIR}")

    app_key = config.KIWOOM_APP_KEY
    app_secret = getattr(config, 'KIWOOM_REAL_APP_SECRET', getattr(config, 'KIWOOM_APP_SECRET', ''))

    if not app_key or not app_secret:
        logger.error("APP KEY 또는 SECRET KEY가 설정되지 않았습니다. 종료합니다.")
        return

    config.KIWOOM_APP_KEY = app_key
    if hasattr(config, 'KIWOOM_REAL_APP_SECRET'):
        config.KIWOOM_REAL_APP_SECRET = app_secret
    else:
        config.KIWOOM_APP_SECRET = app_secret

    client = KiwoomClient()
    logger.info("키움 API 클라이언트 초기화 완료.")

    target_codes = config.HARDCODED_TARGET_STOCKS
    total = len(target_codes)
    logger.info(f"총 {total}개 타겟 종목에 대해 데이터 수집을 시작합니다.")

    all_seed_data = {}

    for idx, code in enumerate(target_codes):
        logger.info(f"[{idx+1}/{total}] 종목코드 {code} 수집 중...")
        
        try:
            # API 호출 (수정주가구분=1 적용됨)
            seed_1m = client.get_1min_candles(code, last_n_days=1)
            time.sleep(0.2)
            seed_3m = client.get_3min_candles(code, 2)
            time.sleep(0.2)
            seed_5m = client.get_5min_candles(code, 2)
            time.sleep(0.2)
            seed_15m = client.get_15min_candles(code, 30)
            time.sleep(0.2)
            seed_daily = client.get_daily_candles(code, 200)
            time.sleep(0.2)
            seed_120t = client.get_tick_data(code, "120", limit=100)
            time.sleep(0.2)

            # 데이터 가공
            past_1m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_1m] if seed_1m else []
            past_3m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_3m] if seed_3m else []
            past_5m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_5m] if seed_5m else []
            past_15m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_15m] if seed_15m else []
            past_daily = [{'time': i.get('time', i['date']), 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_daily] if seed_daily else []
            past_120 = [{'time': i['time'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_120t] if seed_120t else []

            # JSON 저장용 딕셔너리에 추가
            all_seed_data[code] = {
                "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data": {
                    "120t": past_120,
                    "1m": past_1m,
                    "3m": past_3m,
                    "5m": past_5m,
                    "15m": past_15m,
                    "daily": past_daily
                }
            }
            logger.info(f"[{code}] 데이터 수집 완료")
            
        except Exception as e:
            logger.error(f"[{code}] 데이터 수집 실패: {e}")

    # 단일 JSON 파일로 통째로 구워내기 (HFT 최적화 구조)
    file_path = os.path.join(SEED_DATA_DIR, "seed_data.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(all_seed_data, f, ensure_ascii=False, indent=2)
        
    logger.info(f"모든 종목의 시드 데이터가 단일 파일로 저장되었습니다 -> {file_path}")

    logger.info("==============================================")
    logger.info("시드 데이터 야간 프리패치 작업이 모두 완료되었습니다.")
    logger.info("==============================================")

if __name__ == "__main__":
    fetch_and_save_seed_data()
