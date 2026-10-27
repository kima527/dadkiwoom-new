import sys
import os
import pandas as pd
import numpy as np
from typing import Dict, Any, List
import matplotlib.pyplot as plt

# 경로 안전성 확보
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from execution.indicators import (
        calculate_all_60m_indicators,
        calculate_daily_tema_deadcross
    )
    from execution.strategy import ThemeGate60mStrategy, TradeOrder, StrategyState
    from execution.config import DEFAULT_CONFIG
except ImportError:
    from indicators import (
        calculate_all_60m_indicators,
        calculate_daily_tema_deadcross
    )
    from strategy import ThemeGate60mStrategy, TradeOrder, StrategyState
    from config import DEFAULT_CONFIG


def run_backtest(df_60m: pd.DataFrame, df_daily: pd.DataFrame, initial_capital: float = 10_000_000) -> Dict[str, Any]:
    """
    60분봉과 일봉 데이터를 융합하여 테마급등관문선 전략 백테스트 실행
    """
    # 1. 지표 계산
    print(">> [1/4] 60분봉 지표 계산 중 (테마급등관문선, 급등관문고가선, 테마기준선)...")
    df_60m_calc = calculate_all_60m_indicators(
        df_60m, 
        p1=DEFAULT_CONFIG.TEMA_FAST, 
        p2=DEFAULT_CONFIG.TEMA_SLOW, 
        p_slow=DEFAULT_CONFIG.SMA_SLOW
    )
    
    print(">> [2/4] 일봉 지표 계산 중 (TEMA 5-20 데드크로스 및 추세)...")
    df_daily_calc = calculate_daily_tema_deadcross(
        df_daily, 
        p1=DEFAULT_CONFIG.TEMA_FAST, 
        p2=DEFAULT_CONFIG.TEMA_SLOW
    )
    
    # 일봉 데이터를 60분봉의 날짜별로 매핑 (as-of 매칭)
    df_60m_calc['date_key'] = pd.to_datetime(df_60m_calc['timestamp']).dt.date
    df_daily_calc['date_key'] = pd.to_datetime(df_daily_calc['timestamp']).dt.date
    
    daily_map = df_daily_calc.set_index('date_key')[['daily_dead_cross', 'daily_trend_bull']].to_dict('index')
    
    # 2. 시뮬레이션 실행
    print(">> [3/4] 60분봉 상태머신 매매 시뮬레이션 순회...")
    engine = ThemeGate60mStrategy(
        initial_capital=initial_capital,
        gate_sl_pct=DEFAULT_CONFIG.GATE_STOP_LOSS_PCT,
        max_reentry=DEFAULT_CONFIG.MAX_REENTRY_COUNT
    )
    
    equity_curve = []
    
    for idx, row in df_60m_calc.iterrows():
        d_key = row['date_key']
        d_info = daily_map.get(d_key, {'daily_dead_cross': False, 'daily_trend_bull': True})
        
        daily_dc = d_info.get('daily_dead_cross', False)
        daily_bull = d_info.get('daily_trend_bull', True)
        
        # 캔들 평가
        order = engine.evaluate_bar(row, daily_dead_cross=daily_dc, daily_bull=daily_bull)
        
        # 실시간 평가자산 계산
        holding_val = engine.position.total_qty * row['close']
        total_equity = engine.cash + holding_val
        equity_curve.append({
            'timestamp': row['timestamp'],
            'close': row['close'],
            'cash': engine.cash,
            'holding_qty': engine.position.total_qty,
            'holding_value': holding_val,
            'total_equity': total_equity,
            'state': engine.position.state.value
        })
        
    df_equity = pd.DataFrame(equity_curve)
    
    # 3. 성과 지표 산출
    print(">> [4/4] 성과 분석 및 리포트 작성...")
    trades = engine.trade_history
    trade_df = pd.DataFrame([vars(t) for t in trades]) if trades else pd.DataFrame()
    
    final_equity = df_equity['total_equity'].iloc[-1] if not df_equity.empty else initial_capital
    total_return_pct = ((final_equity - initial_capital) / initial_capital) * 100
    
    # MDD 계산
    df_equity['peak'] = df_equity['total_equity'].cummax()
    df_equity['drawdown'] = (df_equity['total_equity'] - df_equity['peak']) / df_equity['peak']
    max_drawdown_pct = df_equity['drawdown'].min() * 100
    
    # 승률 계산 (익절 vs 손절)
    win_trades = 0
    loss_trades = 0
    if not trade_df.empty:
        win_trades = len(trade_df[trade_df['action'].isin(['TAKE_PROFIT', 'RE_SELL'])])
        loss_trades = len(trade_df[trade_df['action'] == 'STOP_LOSS'])
        
    total_exits = win_trades + loss_trades
    win_rate = (win_trades / total_exits * 100) if total_exits > 0 else 0.0
    
    result = {
        'initial_capital': initial_capital,
        'final_equity': final_equity,
        'total_return_pct': total_return_pct,
        'max_drawdown_pct': max_drawdown_pct,
        'total_trade_count': len(trades),
        'win_trades': win_trades,
        'loss_trades': loss_trades,
        'win_rate': win_rate,
        'trade_history_df': trade_df,
        'equity_df': df_equity,
        'df_calc': df_60m_calc
    }
    
    print("\n" + "="*60)
    print("        [60분봉 테마급등관문선 전략 백테스트 결과]        ")
    print("="*60)
    print(f" 초기 자본금     : {initial_capital:,.0f} 원")
    print(f" 최종 평가액     : {final_equity:,.0f} 원")
    print(f" 총 수익률       : {total_return_pct:+.2f} %")
    print(f" 최대 낙폭 (MDD) : {max_drawdown_pct:.2f} %")
    print(f" 총 체결 횟수   : {len(trades)} 회")
    print(f" 청산(익절/손절) : {win_trades}승 / {loss_trades}패 (승률: {win_rate:.1f}%)")
    print("="*60)
    
    if not trade_df.empty:
        print("\n[주요 거래 내역 (최근 10건)]")
        print(trade_df[['timestamp', 'action', 'price', 'qty', 'amount', 'reason']].tail(10).to_string(index=False))
        
    return result

if __name__ == '__main__':
    try:
        from execution.generate_sample_data import generate_realistic_sample_data
    except ImportError:
        from generate_sample_data import generate_realistic_sample_data
    df_60m, df_daily = generate_realistic_sample_data()
    run_backtest(df_60m, df_daily)

