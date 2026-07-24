import os
import sys
import json
import logging
import pandas as pd
import asyncio

real_trading_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading")
if real_trading_path not in sys.path:
    sys.path.insert(0, real_trading_path)
    
strategy_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\MovingAveragelineTraid\execution")
if strategy_path not in sys.path:
    sys.path.insert(0, strategy_path)

from kiwoom_client import KiwoomRealClient
from strategy_sma_breakout import calculate_sma_breakout_signals, TradeState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Backtester")

def run_backtest():
    client = KiwoomRealClient()
    
    with open(r"C:\Users\zoela\OneDrive\바탕 화면\MovingAveragelineTraid\watchlist.json", "r", encoding="utf-8") as f:
        watchlist = json.load(f)
        
    results = []
    
    for code, info in watchlist.items():
        name = info['name']
        logger.info(f"[{name}] 백테스트 데이터 가져오는 중...")
        
        candles = client.get_1min_candles(code, last_n_days=1)
        if not candles or len(candles) < 60:
            logger.warning(f"{name} 1분봉 데이터 부족 ({len(candles) if candles else 0}봉). 백테스트 스킵.")
            continue
            
        df = pd.DataFrame(candles)
        
        if len(df) < 10:
            logger.warning(f"{name} 데이터 부족. 스킵.")
            continue
            
        # 첫 5개 캔들로 초기 고점 및 최고점봉의 최저점(손절선) 세팅
        first_5 = df.iloc[:5]
        max_idx = first_5['high'].idxmax()
        max_candle = first_5.loc[max_idx]
        
        initial_high = max_candle['high']
        stop_loss = max_candle['low']
        
        trade_state = TradeState(initial_high, stop_loss)
        
        position = None
        trades = []
        
        # 6번째 캔들(인덱스 5)부터 시뮬레이션 시작
        for i in range(5, len(df)):
            sub_df = df.iloc[:i+1].copy()
            signals = calculate_sma_breakout_signals(sub_df, trade_state)
            current_time = sub_df.iloc[-1].get('date', f"Index_{i}")
            
            if not trade_state.is_holding:
                if signals.get('buy'):
                    buy_price = signals.get('price')
                    
                    trade_state.is_holding = True
                    trade_state.has_traded_today = True
                    
                    position = {
                        'buy_time': current_time,
                        'buy_price': buy_price,
                        'reason': signals.get('buy_reason', '매수')
                    }
            else:
                if signals.get('sell'):
                    sell_price = signals.get('price')
                    yield_pct = ((sell_price - position['buy_price']) / position['buy_price']) * 100 - 0.26  # Fee/Tax
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
                    trade_state.is_holding = False
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
    logger.info(f"평균 수익률: {total_yield/len(results):.2f}%")

if __name__ == "__main__":
    run_backtest()
