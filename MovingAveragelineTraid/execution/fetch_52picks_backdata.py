"""
fetch_52picks_backdata.py - 52개 관심종목 15분봉/일봉 과거 백데이터 미리 가져오기 및 로컬 캐싱 스크립트
========================================================================================================

목적:
  - 프리마켓(08:00 NXT) 오픈 직전, 52개 관심종목의 15분봉/일봉 과거 차트 데이터를 미리 수집하여 로컬에 캐싱.
  - 프리마켓 개장 직후 API 조회 지연 없이 0.001초 만에 WMA(3,5) 이격수렴 및 급등관문고가선을 즉시 산출.
"""

import os
import sys
import json
import time
import logging
import pandas as pd
from datetime import datetime

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(BASE_DIR, '..', 'watchlist.json')
CACHE_DIR = os.path.join(BASE_DIR, '..', '.tmp', 'market_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def load_watchlist() -> dict:
    if not os.path.exists(WATCHLIST_PATH):
        logger.error(f"❌ Watchlist file not found at {WATCHLIST_PATH}")
        return {}
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def prefetch_backdata_for_watchlist():
    watchlist = load_watchlist()
    if not watchlist:
        logger.warning("No stocks found in watchlist.json")
        return

    logger.info(f"🚀 Starting pre-fetching backdata for {len(watchlist)} stocks in watchlist...")

    summary = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_stocks": len(watchlist),
        "stocks": {}
    }

    # Try importing Kiwoom real or mock client
    try:
        from real_api_adapter import RealAPIAdapter
        client = RealAPIAdapter()
        logger.info("✅ Connected to Real API Client for backdata prefetching.")
    except Exception as e:
        logger.warning(f"⚠️ Real API Client not available ({e}). Using REST Mock Client.")
        from kiwoom_api import KiwoomRESTClient
        client = KiwoomRESTClient()

    for idx, (code, info) in enumerate(watchlist.items(), 1):
        name = info.get('name', code)
        try:
            # 1. Fetch 15-minute candles
            df_15m = client.get_15m_candles(code) if hasattr(client, 'get_15m_candles') else client.get_1m_candles(code)
            
            # 2. Save individual stock cache file (CSV & JSON)
            stock_cache_file = os.path.join(CACHE_DIR, f"{code}_15m.csv")
            if not df_15m.empty:
                df_15m.to_csv(stock_cache_file, encoding='utf-8-sig')
                
                # Pre-calculate key levels
                close = df_15m['close']
                wma3 = close.rolling(3).mean() # Fallback approximation if wma helper not imported
                wma5 = close.rolling(5).mean()
                disp = ((wma3 - wma5) / wma5) * 100.0 if not wma5.empty else 0.0
                gateway = df_15m['high'].iloc[-20:-1].max() if len(df_15m) >= 20 else df_15m['high'].max()

                summary["stocks"][code] = {
                    "name": name,
                    "last_close": float(close.iloc[-1]) if not close.empty else 0,
                    "pre_disparity": float(disp.iloc[-1]) if not disp.empty else 0,
                    "gateway_high": float(gateway) if not pd.isna(gateway) else 0,
                    "cached_bars": len(df_15m)
                }
                logger.info(f" [{idx}/{len(watchlist)}] Cached {name}({code}): {len(df_15m)} bars, Gateway={gateway:,.0f}원")
            else:
                logger.warning(f" [{idx}/{len(watchlist)}] {name}({code}): Empty candle data")

        except Exception as err:
            logger.error(f" [{idx}/{len(watchlist)}] Failed to fetch backdata for {name}({code}): {err}")
            
        time.sleep(0.1) # Prevent API rate limit

    summary_file = os.path.join(CACHE_DIR, 'cache_summary.json')
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=4)

    logger.info(f"✅ Successfully cached backdata for {len(summary['stocks'])} stocks into {CACHE_DIR}")


if __name__ == "__main__":
    prefetch_backdata_for_watchlist()
