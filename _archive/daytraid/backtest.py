import sys
import time
import asyncio
import logging
from datetime import datetime

from config import HARDCODED_TARGET_STOCKS
from kiwoom_client import KiwoomRealClient
from strategy import get_daily_kl_lines, compute_sma

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

async def run_backtest():
    logger.info("="*50)
    logger.info("      📈 백테스트 시뮬레이터 (일봉 K/L선 동시 돌파) 📈")
    logger.info("="*50)
    
    client = KiwoomRealClient()
    stocks = HARDCODED_TARGET_STOCKS
    logger.info(f"대상 종목 수: {len(stocks)}개 (config.py 세팅 기준)")
    
    total_trades = 0
    winning_trades = 0
    total_profit_percent = 0.0
    
    trade_logs = []
    
    for idx, code in enumerate(stocks):
        name = client.get_stock_name(code) or code
        logger.info(f"[{idx+1}/{len(stocks)}] {name} ({code}) 데이터 수집 및 백테스트 중...")
        
        # 1. 일봉 데이터 수집 (과거 200일)
        try:
            daily_candles = await asyncio.to_thread(client.get_daily_candles, code, 200)
            time.sleep(0.5) # TR 제한 방지
            
            # 2. 15분봉 데이터 수집 (과거 10일치 정도)
            m15_candles = await asyncio.to_thread(client.get_15min_candles, code, 10)
            time.sleep(0.5) # TR 제한 방지
        except Exception as e:
            logger.error(f"  -> 데이터 수집 실패: {e}")
            continue
            
        if not daily_candles or not m15_candles:
            continue
            
        # 백테스트 상태 변수
        position = False
        buy_price = 0.0
        buy_time = ""
        sold_today = False
        sold_loss_today = False
        last_date = ""
        
        # 15분봉 데이터 오름차순 처리 (시간순)
        for i, candle in enumerate(m15_candles):
            c_time = candle['time'] # "YYYY-MM-DD HH:MM:SS"
            c_date = c_time[:10]
            if c_date != last_date:
                sold_today = False
                sold_loss_today = False
                first_buy_price = 0.0
                last_date = c_date
            c_high = candle['high']
            c_low = candle['low']
            c_close = candle['close']
            
            if not position:
                # 매수 타점 탐색
                # c_date보다 이전 날짜의 일봉 데이터만 추출하여 계산
                past_daily = [dc for dc in daily_candles if dc['date'] < c_date]
                if len(past_daily) < 40:
                    continue
                    
                k_line, l_line = get_daily_kl_lines(past_daily)
                if k_line is None or l_line is None:
                    continue
                    
                target_price = max(k_line, l_line)
                
                yesterday_close = past_daily[-1]['close']
                
                # 어제 종가가 타겟 아래였고, 오늘 15분봉 고가가 타겟을 뚫었는가?
                if target_price > 0 and yesterday_close <= target_price and c_high >= target_price:
                    # 당일 매도 이력 검사 (손절 후 재매수 금지, 익절 후 재진입 시 가격 제한)
                    if sold_today:
                        if sold_loss_today:
                            continue 
                        else:
                            if c_close <= first_buy_price:
                                continue
                        
                    buy_price = target_price
                    if buy_price == 0:
                        buy_price = c_close
                    position = {
                        'buy_price': buy_price,
                        'buy_time': c_time,
                        'max_price': buy_price
                    }
                    if first_buy_price == 0.0:
                        first_buy_price = buy_price
            else:
                # 고점 갱신 (트레일링 스탑용)
                if c_high > position['max_price']:
                    position['max_price'] = c_high
                    
                max_price = position['max_price']
                
                # 매도 타점 탐색 (손절 or 데드크로스)
                sell_price = 0.0
                sell_reason = ""
                
                c_open = candle['open']
                
                # 1. 트레일링 스탑 (최고점 대비 -1.5% 하락 시)
                if c_low <= max_price * 0.985:
                    sell_price = max_price * 0.985
                    if c_open < sell_price:
                        sell_price = c_open
                    sell_reason = "트레일링 스탑 (최고점 대비 -1.5%)"
                else:
                    # 2. 15분봉 데드크로스
                    past_15m = m15_candles[:i+1]
                    if len(past_15m) >= 40:
                        s3 = compute_sma(past_15m, 3)
                        s40 = compute_sma(past_15m, 40)
                        
                        curr_s3 = s3[-1]
                        curr_s40 = s40[-1]
                        prev_s3 = s3[-2]
                        prev_s40 = s40[-2]
                        
                        if prev_s3 is not None and prev_s40 is not None:
                            if prev_s3 >= prev_s40 and curr_s3 < curr_s40:
                                sell_price = c_close
                                sell_reason = "15분봉 데드크로스"
                                
                if sell_price > 0:
                    profit_pct = (sell_price - position['buy_price']) / position['buy_price'] * 100
                    profit_pct -= 0.23 # 수수료/세금
                    
                    total_trades += 1
                    if profit_pct > 0:
                        winning_trades += 1
                    total_profit_percent += profit_pct
                    
                    log = f"[{name}] 매수: {position['buy_time']} ({position['buy_price']:,.0f}원) -> 매도: {c_time} ({sell_price:,.0f}원) | 수익률: {profit_pct:+.2f}% ({sell_reason})"
                    trade_logs.append(log)
                    
                    position = False
                    sold_today = True
                    if profit_pct < 0:
                        sold_loss_today = True
                    
    logger.info("="*50)
    logger.info("              📊 백테스트 결과 📊")
    logger.info("="*50)
    for log in trade_logs:
        logger.info(log)
        
    logger.info("-" * 50)
    if total_trades > 0:
        win_rate = (winning_trades / total_trades) * 100
        logger.info(f"총 매매 횟수: {total_trades}회")
        logger.info(f"승률: {win_rate:.2f}% ({winning_trades}/{total_trades})")
        logger.info(f"총 누적 수익률(합산): {total_profit_percent:+.2f}%")
    else:
        logger.info("조건을 만족하는 매매 내역이 없습니다. (최근 10일 내 돌파 타점 없음)")
    logger.info("="*50)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_backtest())
