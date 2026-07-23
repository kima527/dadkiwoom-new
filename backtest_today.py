import os
import sys
import json
import time
import logging
import pandas as pd

real_trading_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading")
if real_trading_path not in sys.path:
    sys.path.insert(0, real_trading_path) # 우선순위 높임
    
strategy_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\MovingAveragelineTraid\execution")
if strategy_path not in sys.path:
    sys.path.append(strategy_path) # 우선순위 낮춤 (config.py 충돌 방지)

from kiwoom_client import KiwoomRealClient
from strategy_sma import calculate_sma_signals
import ta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Backtester")

def run_backtest():
    client = KiwoomRealClient()
    
    with open(r"C:\Users\zoela\OneDrive\바탕 화면\MovingAveragelineTraid\watchlist.json", "r", encoding="utf-8") as f:
        watchlist = json.load(f)
        
    results = []
    
    for code, info in watchlist.items():
        code = code.strip()
        name = info['name']
        logger.info(f"[{name}] 백테스트 데이터 가져오는 중 (코드: {code})...")
        
        # 키움증권 초당 요청 제한(초당 5건) 방지를 위해 딜레이 추가
        time.sleep(1)
        
        candles = client.get_1min_candles(code, last_n_days=1)
        if not candles or len(candles) < 60:
            logger.warning(f"{name} 1분봉 데이터 부족 ({len(candles) if candles else 0}봉). 백테스트 스킵.")
            continue
            
        df = pd.DataFrame(candles)
        
        position = None
        trades = []
        
        # 60이평선 계산을 위해 60번째 분봉부터 탐색
        for i in range(60, len(df)):
            sub_df = df.iloc[:i+1].copy()
            signals = calculate_sma_signals(sub_df)
            current_time = sub_df.iloc[-1].get('date', f"Index_{i}")
            if 'time' in sub_df.columns:
                current_time = sub_df.iloc[-1]['time']
            current_price = sub_df.iloc[-1]['close']
            
            if position is None:
                if signals.get('buy') or signals.get('breakout_buy') or signals.get('dip_buy'):
                    reason = "시가 재돌파" if signals.get('breakout_buy') else ("3-20-60 눌림목" if signals.get('dip_buy') else "일반 정배열")
                    position = {
                        'buy_time': current_time,
                        'buy_price': current_price,
                        'reason': reason
                    }
            else:
                if signals.get('sell'):
                    sell_price = current_price
                    yield_pct = ((sell_price - position['buy_price']) / position['buy_price']) * 100 - 0.26  # 세금/수수료 0.26% 차감
                    trades.append({
                        'code': code,
                        'name': name,
                        'buy_time': position['buy_time'],
                        'sell_time': current_time,
                        'buy_price': position['buy_price'],
                        'sell_price': sell_price,
                        'reason': position['reason'],
                        'yield': yield_pct
                    })
                    position = None
                    
        # 장 마감 시 강제 청산
        if position is not None:
            sell_price = df.iloc[-1]['close']
            yield_pct = ((sell_price - position['buy_price']) / position['buy_price']) * 100 - 0.26
            trades.append({
                        'code': code,
                        'name': name,
                        'buy_time': position['buy_time'],
                        'sell_time': "장마감(종가)",
                        'buy_price': position['buy_price'],
                        'sell_price': sell_price,
                        'reason': position['reason'],
                        'yield': yield_pct
                    })
            
        results.extend(trades)
        
    if not results:
        logger.info("오늘 발생한 매매 내역이 없습니다.")
        return
        
    logger.info("========== [백테스트 결과] ==========")
    total_yield = 0
    for t in results:
        icon = "🔴" if t['yield'] > 0 else "🔵"
        logger.info(f"{icon} {t['name']}({t['reason']}): {t['buy_time']} 매수({t['buy_price']}원) -> {t['sell_time']} 매도({t['sell_price']}원) | 수익률: {t['yield']:.2f}%")
        total_yield += t['yield']
        
    logger.info(f"=====================================")
    logger.info(f"총 매매 횟수: {len(results)}회")
    logger.info(f"합산 수익률: {total_yield:.2f}%")
    if len(results) > 0:
        logger.info(f"평균 수익률: {total_yield/len(results):.2f}%")

if __name__ == "__main__":
    run_backtest()
