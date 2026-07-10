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
            df = pd.read_csv(file_path, encoding='cp949')
            if not df.empty:
                last_col = df.columns[-1]
                codes = []
                for val in df[last_col].dropna():
                    val_str = str(val).strip()
                    if val_str.startswith("'"):
                        val_str = val_str[1:]
                    if val_str.isdigit():
                        codes.append(val_str.zfill(6))
                if codes:
                    target_stocks = codes
                    logger.info(f"my_pick.xlsx에서 {len(codes)}개의 종목을 로드했습니다.")
        except Exception as e:
            logger.error(f"my_pick.xlsx 로드 실패: {e}")
            
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
        is_buy_window = dt_time(9, 0) <= current_time <= dt_time(10, 30)
        
        # 보유 현황 조회 (실제 계좌와 동기화)
        holdings_list = await asyncio.to_thread(client.get_holdings)
        holdings_dict = {h["code"]: h for h in holdings_list} if holdings_list else {}
        
        # 캐시 및 가용 금액 확인
        cash = await asyncio.to_thread(client.get_cash_balance)
        budget_per_stock = 5000000 # 500만 원 집중 투자
        
        for code in target_stocks:
            try:
                # 1. 5분봉 데이터 수집 (오전장 전용)
                candles = await asyncio.to_thread(client.get_5min_candles, code, 50)
                await asyncio.sleep(0.4) # API Rate Limit 회피 (초당 약 2.5회 호출)
                
                if not candles or len(candles) < 50:
                    continue
                    
                closes = [c['close'] for c in candles]
                highs = [c['high'] for c in candles]
                lows = [c['low'] for c in candles]
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
                
                # 2. Pandas를 이용한 AI 다중 지표 계산 (BB10, RSI14, MACD, ATR14)
                df = pd.DataFrame({'Close': closes, 'High': highs, 'Low': lows})
                
                exp1 = df['Close'].ewm(span=12, adjust=False).mean()
                exp2 = df['Close'].ewm(span=26, adjust=False).mean()
                macd = exp1 - exp2
                macd_signal = macd.ewm(span=9, adjust=False).mean()
                
                bb_mid = df['Close'].rolling(window=10).mean()
                bb_std_val = df['Close'].rolling(window=10).std()
                bb_up = bb_mid + (bb_std_val * 1.5)
                bb_low = bb_mid - (bb_std_val * 1.5)
                
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                
                high_low = df['High'] - df['Low']
                high_close = np.abs(df['High'] - df['Close'].shift())
                low_close = np.abs(df['Low'] - df['Close'].shift())
                tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
                atr = tr.rolling(window=14).mean()
                
                p_macd = macd.iloc[-2]
                p_signal = macd_signal.iloc[-2]
                p_bb_low = bb_low.iloc[-2]
                p_bb_up = bb_up.iloc[-2]
                p_rsi = rsi.iloc[-2]
                p_atr = atr.iloc[-2]
                
                if pd.isna(p_macd) or pd.isna(p_bb_low) or pd.isna(p_rsi):
                    continue
                    
                stock_name = client.get_stock_name(code) or code
                    
                # 3. 매수/매도 로직 판별
                if qty == 0:
                    # [매수 조건] MACD 상승장 & 주가 볼린저 하단 이하 & RSI 40 미만
                    if (p_macd > p_signal) and (current_price <= p_bb_low * 1.02) and (p_rsi < 40):
                        if not is_buy_window:
                            logger.info(f"🕒 [{stock_name}] 매수 신호 발생했으나, 매수 허용 시간(09:00~10:30)이 아닙니다.")
                        elif len(holdings_dict) >= 2:
                            logger.warning(f"🔒 [{stock_name}] 매수 신호 발생했으나, 이미 2종목을 보유 중이므로 신규 진입을 차단합니다.")
                        elif cash >= budget_per_stock:
                            buy_qty = int(budget_per_stock // current_price)
                            if buy_qty > 0:
                                logger.info(f"🚀 [매수 신호] {stock_name} ({code}) - AI 복합조건 만족 (오전장 5분봉)")
                                await asyncio.to_thread(client.place_buy_order, code, buy_qty, price=0, order_type="03") # 시장가 매수
                                await telegram_bot.send_message(f"🟢 [매수] {stock_name}\n전략: AI 5분봉 단타\n단가: 약 {current_price:,}원")
                                cash -= budget_per_stock # 예상 현금 차감
                        else:
                            logger.warning(f"⚠️ [{stock_name}] 매수 신호 발생했으나 예수금 부족 (현금: {cash:,}원)")
                else:
                    # [매도 조건]
                    sell_signal = False
                    signal_msg = ""
                    
                    # 1순위: 볼린저 밴드 상단 도달 (익절)
                    if current_price >= p_bb_up:
                        sell_signal = True
                        signal_msg = "볼린저 밴드 상단 도달 (익절)"
                        
                    # 1.5순위: RSI 과매수 (70 이상) 익절
                    elif p_rsi >= 70:
                        sell_signal = True
                        signal_msg = f"RSI 과매수 ({p_rsi:.1f} >= 70) 익절"
                        
                    # 2순위: ATR 트레일링 스탑 (최고가 대비 하락)
                    else:
                        current_stop_loss = highest_prices.get(code, buy_price) - (2.5 * p_atr)
                        if current_price <= current_stop_loss:
                            sell_signal = True
                            signal_msg = f"ATR 트레일링 스탑 발동 (고점 대비 하락)"
                            
                    # 3순위: 하드 스탑 (-2%)
                    if not sell_signal and buy_price > 0 and current_price <= buy_price * 0.98:
                        sell_signal = True
                        signal_msg = f"하드 스탑 (-2% 하락)"
                        
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
    logger.info("Morning-Exclusive Multi-Stock Bot Started")
    logger.info("Strategy: AI 5m 단타 (BB상단 익절, 500만 원 집중)")
    logger.info("=========================================")

    client = KiwoomClient()
    if not client.test_connection():
        logger.error("API 연결 실패. 프로그램을 종료합니다.")
        return

    # 시작 알림 전송
    await telegram_bot.send_message("🤖 다중 감시 집중투자 봇이 실행되었습니다.\n(Max 2종목 / 500만 원 매수 / 볼린저 상단 익절 가동 중)")

    # 태스크 병렬 실행
    trading_task = asyncio.create_task(multi_trading_loop(client))
    telegram_task = asyncio.create_task(telegram_bot.poll_telegram_updates())

    await asyncio.gather(trading_task, telegram_task)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
