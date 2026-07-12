import os
import sys
import time
import logging
import asyncio
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Add local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from kiwoom_client import KiwoomClient
import telegram_bot

def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def is_market_open():
    """장 운영 시간 확인 (08:00 ~ 20:00)"""
    now = get_kst_now()
    if now.weekday() >= 5: # 주말
        return False
    current_time = now.time()
    from datetime import time as dt_time
    return dt_time(8, 0) <= current_time <= dt_time(20, 0)

def round_to_tick(price):
    """한국거래소 호가 단위 산출 후 내림 처리 (주식)"""
    if price < 2000: tick = 1
    elif price < 5000: tick = 5
    elif price < 20000: tick = 10
    elif price < 50000: tick = 50
    elif price < 200000: tick = 100
    elif price < 500000: tick = 500
    else: tick = 1000
    return (int(price) // tick) * tick

async def multi_trading_loop(client: KiwoomClient):
    """
    다중 종목 감시 루프
    - API Rate Limit을 고려하여 순차적으로 폴링합니다.
    - 30분봉 데이터를 직접 조회하여 지표를 계산하므로 별도의 DataFeeder가 필요 없습니다.
    """
    # 우선 my_pick.xlsx가 있으면 읽고, 없으면 하드코딩된 리스트 사용
    target_stocks = config.HARDCODED_TARGET_STOCKS
    
    file_path = config.WATCHLIST_FILE
    if os.path.exists(file_path):
        try:
            if file_path.endswith('.xlsx'):
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path, encoding='cp949')
                
            if not df.empty:
                # '종목코드' 컬럼이 명시적으로 있으면 사용, 없으면 첫 번째 컬럼 사용
                code_col = '종목코드' if '종목코드' in df.columns else df.columns[0]
                codes = []
                for val in df[code_col].dropna():
                    val_str = str(val).strip()
                    if val_str.startswith("'"):
                        val_str = val_str[1:]
                    val_str = val_str.replace("A", "") # 'A005930' 형식 처리
                    if val_str.isdigit():
                        codes.append(val_str.zfill(6))
                if codes:
                    target_stocks = codes
                    logger.info(f"{os.path.basename(file_path)}에서 {len(codes)}개의 종목을 로드했습니다.")
        except Exception as e:
            logger.error(f"{os.path.basename(file_path)} 로드 실패: {e}")
            
    if not target_stocks:
        logger.error("대상 종목이 없습니다. config.py를 확인하세요.")
        return
        
    logger.info(f"총 {len(target_stocks)}개 우량주 다중 감시를 시작합니다.")
    
    # 종목별 상태 저장용 딕셔너리
    highest_prices = {code: 0.0 for code in target_stocks}
    
    while True:
        if not is_market_open():
            logger.info("장이 닫혀있습니다. 60초 후 다시 확인합니다.")
            await asyncio.sleep(60)
            continue
            
        current_time = get_kst_now().time()
        from datetime import time as dt_time
        is_buy_window = dt_time(8, 0) <= current_time <= dt_time(20, 0)
        
        # 보유 현황 조회 (실제 계좌와 동기화)
        holdings_list = await asyncio.to_thread(client.get_holdings)
        holdings_dict = {h["code"]: h for h in holdings_list} if holdings_list else {}
        
        # 캐시 및 가용 금액 확인
        cash = await asyncio.to_thread(client.get_cash_balance)
        budget_per_stock = config.BUDGET_PER_STOCK # config 연동
        
        for code in target_stocks:
            try:
                # 1. 15분봉 데이터 수집
                candles = await asyncio.to_thread(client.get_15min_candles, code, 50)
                await asyncio.sleep(0.4) # API Rate Limit 회피 (초당 약 2.5회 호출)
                
                if not candles or len(candles) < 50:
                    continue
                    
                closes = [c['close'] for c in candles]
                current_price = closes[-1]
                
                # 보유 정보 확인
                is_held = code in holdings_dict
                qty = holdings_dict[code]['quantity'] if is_held else 0
                buy_price = holdings_dict[code]['buy_price'] if is_held else 0
                
                # 최고가 갱신 (트레일링 스탑용)
                if qty > 0:
                    if current_price > highest_prices.get(code, 0.0):
                        highest_prices[code] = current_price
                else:
                    highest_prices[code] = 0.0
                
                # 2. Pandas를 이용한 SMA 계산 (SMA 20, 40)
                df = pd.DataFrame({'Close': closes})
                df['SMA20'] = df['Close'].rolling(window=20).mean()
                df['SMA40'] = df['Close'].rolling(window=40).mean()
                
                p_sma20 = df['SMA20'].iloc[-2]
                p_sma40 = df['SMA40'].iloc[-2]
                c_sma20 = df['SMA20'].iloc[-1]
                c_sma40 = df['SMA40'].iloc[-1]
                
                if pd.isna(p_sma40) or pd.isna(c_sma40):
                    continue
                    
                stock_name = client.get_stock_name(code) or code
                    
                # 3. 매수/매도 로직 판별
                if qty == 0:
                    # [매수 조건] 15분봉 SMA 20 > SMA 40 골든크로스
                    if (p_sma20 <= p_sma40) and (c_sma20 > c_sma40):
                        if not is_buy_window:
                            logger.info(f"🕒 [{stock_name}] 매수 신호 발생했으나, 매수 허용 시간이 아닙니다.")
                        elif not telegram_bot.IS_BOT_ACTIVE:
                            logger.info(f"⏸️ [{stock_name}] 매수 신호 발생했으나, 텔레그램(스마트폰) 명령으로 신규 매수가 중지된 상태입니다.")
                        elif len(holdings_dict) >= 3:
                            logger.warning(f"🔒 [{stock_name}] 매수 신호 발생했으나, 이미 3종목을 보유 중이므로 신규 진입을 차단합니다.")
                        elif cash >= budget_per_stock:
                            buy_qty = int(budget_per_stock // current_price)
                            if buy_qty > 0:
                                logger.info(f"🚀 [매수 신호] {stock_name} ({code}) - 15분봉 SMA20>40 골든크로스")
                                await asyncio.to_thread(client.place_buy_order, code, buy_qty, price=0, order_type="03") # 시장가 매수
                                await telegram_bot.send_message(f"🟢 [매수] {stock_name}\n전략: 15분봉 정배열\n단가: 약 {current_price:,}원")
                                cash -= budget_per_stock # 예상 현금 차감
                        else:
                            logger.warning(f"⚠️ [{stock_name}] 매수 신호 발생했으나 예수금 부족 (현금: {cash:,}원)")
                else:
                    # [매도 조건]
                    sell_signal = False
                    signal_msg = ""
                    
                    # 1순위: K-Peak 트레일링 스탑 (최고가 대비 1% 하락)
                    highest_price = highest_prices.get(code, buy_price)
                    current_stop_loss = highest_price * 0.99
                    
                    if current_price <= current_stop_loss:
                        sell_signal = True
                        signal_msg = f"K-Peak 트레일링 스탑 발동 (최고가 대비 1% 하락)"
                        
                    if sell_signal:
                        logger.info(f"🚨 [매도 신호] {stock_name} ({code}) - {signal_msg}")
                        await asyncio.to_thread(client.place_sell_order, code, qty, price=0, order_type="03") # 시장가 매도
                        await telegram_bot.send_message(f"🔴 [매도] {stock_name}\n사유: {signal_msg}\n단가: 약 {current_price:,}원")
                        highest_prices[code] = 0.0
                        
            except Exception as e:
                logger.error(f"[{code}] 감시 루프 실행 중 에러 발생: {e}", exc_info=True)
                
        # 모든 종목을 1회 스캔한 후 대기 (API Rate Limit 감안하여 10초 휴식)
        logger.info(f"✅ 1주기 스캔 완료. 다음 스캔 대기 중...")
        await asyncio.sleep(10)


async def async_main():
    logger.info("=========================================")
    logger.info("Basket Trading Bot Started (Top 10 Stocks)")
    logger.info("Strategy: 15m SMA20>40 Golden Cross & K-Peak 1% Trailing Stop")
    logger.info("=========================================")

    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 시작 알림 전송
    await telegram_bot.send_message("🤖 정예 10대장 바스켓 감시 봇이 실행되었습니다.\n(15분봉 정배열 매수 / 최고가 대비 1% 하락 시 기계적 익절 가동 중)")

    # 태스크 병렬 실행
    trading_task = asyncio.create_task(multi_trading_loop(client))
    telegram_task = asyncio.create_task(telegram_bot.poll_telegram_updates())

    await asyncio.gather(trading_task, telegram_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
