import pandas as pd
import numpy as np

def calculate_tema(series, period):
    """ TEMA(Triple Exponential Moving Average) 계산 """
    ema1 = series.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    return 3 * ema1 - 3 * ema2 + ema3

def calc_theme_gate(df, p1=5, p2=20, prefix=""):
    """ 테마급등관문선 계산 (ValueWhen 메커니즘 완벽 교정) """
    tema1 = calculate_tema(df['close'], p1)
    tema2 = calculate_tema(df['close'], p2)
    
    # 골든크로스 판별 (CrossUp)
    gold_cross = (tema1.shift(1) <= tema2.shift(1)) & (tema1 > tema2)
    
    # [교정]: 골든크로스 시점의 tema1 값만 남기고 나머지는 nan 처리 후 ffill로 유지
    gate_values = np.where(gold_cross, tema1, np.nan)
    
    df[f'theme_gate{prefix}'] = pd.Series(gate_values, index=df.index).ffill()
    return df

def prepare_1m_data(df_1m):
    """ 1분봉 데이터 전처리 및 지표 계산 """
    df = df_1m.copy()
    df.sort_values('timestamp', inplace=True)
    
    df = calc_theme_gate(df, 5, 20, prefix="_1m")
    
    # [교정]: 미래 참조 방지를 위해 1분봉의 종가와 지표를 1개 행 아래로 밀어줌 (Look-ahead bias 방지)
    df['close_1m'] = df['close']
    df['theme_gate_1m_shifted'] = df['theme_gate_1m'].shift(1)
    df['close_1m_shifted'] = df['close_1m'].shift(1)
    
    return df[['timestamp', 'close_1m_shifted', 'theme_gate_1m_shifted']].rename(
        columns={'close_1m_shifted': 'close_1m', 'theme_gate_1m_shifted': 'theme_gate_1m'}
    )

def prepare_3m_data(df_3m):
    """ 3분봉 데이터 전처리 및 지표 계산 """
    df = df_3m.copy()
    df.sort_values('timestamp', inplace=True)
    
    # 1. 볼린저 밴드 (20, 2)
    df['sma20'] = df['close'].rolling(20).mean()
    std = df['close'].rolling(20).std()
    df['bb_upper'] = df['sma20'] + 2 * std
    df['bb_lower'] = df['sma20'] - 2 * std
    
    # 2. 이동평균선 (5, 20, 60)
    df['sma5'] = df['close'].rolling(5).mean()
    df['sma60'] = df['close'].rolling(60).mean()
    
    # 3. 3분봉 테마급등관문선
    df = calc_theme_gate(df, 5, 20, prefix="_3m")
    
    # 4. 기준선 (gijun_3m) 교정
    # 정배열 조건에 따른 K 값 선언 (K = valuewhen(1, a>b && b>d && a>d, C))
    jeongbae = (df['sma5'] > df['sma20']) & (df['sma20'] > df['sma60']) & (df['sma5'] > df['sma60'])
    df['K'] = np.where(jeongbae, df['close'], np.nan)
    df['K'] = df['K'].ffill()
    
    # [교정]: 오리지널 변곡점 수식 반영 (K(2) < K(1) && K(1) > K)
    k_prev1 = df['K'].shift(1)
    k_prev2 = df['K'].shift(2)
    is_peak = (k_prev2 < k_prev1) & (k_prev1 > df['K'])
    
    # M = valuewhen(1, 변곡점, K(1))
    df['gijun_3m'] = np.where(is_peak, k_prev1, np.nan)
    df['gijun_3m'] = df['gijun_3m'].ffill()
    
    # 5. 세력선 (seryek_3m) 교정
    # valuewhen(1, crossup(a, M), a) -> 5일선(a)이 기준선(M)을 돌파할 때의 5일선 값
    sma5_prev = df['sma5'].shift(1)
    gijun_prev = df['gijun_3m'].shift(1)
    seryek_cross = (sma5_prev <= gijun_prev) & (df['sma5'] > df['gijun_3m'])
    
    df['seryek_3m'] = np.where(seryek_cross, df['sma5'], np.nan)
    df['seryek_3m'] = df['seryek_3m'].ffill()
    
    # 매매 로직 연동을 위한 크로스오버 플래그
    df['gijun_breakout'] = (df['close'].shift(1) <= df['gijun_3m']) & (df['close'] > df['gijun_3m'])
    df['seryek_breakout'] = (df['close'].shift(1) <= df['seryek_3m']) & (df['close'] > df['seryek_3m'])
    
    return df

def run_mtf_backtest(df_3m, df_1m):
    """ MTF 백테스트 실행기 """
    df_3m_prep = prepare_3m_data(df_3m)
    df_1m_prep = prepare_1m_data(df_1m)
    
    # 3분봉과 데이터가 밀린(Safe) 1분봉 데이터를 매칭
    df_merged = pd.merge_asof(
        df_3m_prep, 
        df_1m_prep, 
        on='timestamp', 
        direction='backward'
    )
    
    position = 0        
    buy_price = 0
    circulation_state = "IDLE"  # 'IDLE', 'WAIT_SERYEK', 'WAIT_GIJUN'
    trades = []         
    
    for i in range(1, len(df_merged)):
        row = df_merged.iloc[i]
        
        # ─── [교정] 순환 상태 메커니즘의 정교화 ───
        if row['gijun_breakout']:
            circulation_state = "WAIT_SERYEK"
        elif circulation_state == "WAIT_SERYEK" and row['seryek_breakout']:
            circulation_state = "WAIT_GIJUN"
        elif circulation_state == "WAIT_GIJUN" and row['gijun_breakout']:
            circulation_state = "WAIT_SERYEK"
            
        # ──────────────── 매수(BUY) 로직 ────────────────
        if position == 0:
            cond_bb_lower = row['close'] <= row['bb_lower']
            cond_3m_support = row['close'] > row['theme_gate_3m']
            
            # 1분봉 지지 확인 (Look-ahead bias가 제거된 과거 완성봉 기준)
            cond_1m_support = pd.notna(row['close_1m']) and pd.notna(row['theme_gate_1m']) and (row['close_1m'] >= row['theme_gate_1m'])
            
            # 순환 상태 활성화 시 진입
            cond_circulation = circulation_state in ["WAIT_SERYEK", "WAIT_GIJUN"]
            
            if cond_bb_lower and cond_3m_support and cond_1m_support and cond_circulation:
                position = 1
                buy_price = row['close']
                trades.append({
                    'time': row['timestamp'], 
                    'type': 'BUY', 
                    'price': buy_price,
                    'reason': f"BB_Lower_Touch | State:{circulation_state}"
                })
                continue
                
        # ──────────────── 청산(SELL) 및 손절 로직 ────────────────
        if position > 0:
            # 1. 즉각 손절 로직 (1분봉 테마선 이탈 시)
            if pd.notna(row['close_1m']) and pd.notna(row['theme_gate_1m']) and (row['close_1m'] < row['theme_gate_1m']):
                position = 0
                sell_price = row['close'] 
                profit_pct = (sell_price / buy_price - 1) * 100
                trades.append({
                    'time': row['timestamp'], 
                    'type': 'STOP_LOSS', 
                    'price': sell_price, 
                    'profit_pct': profit_pct,
                    'reason': "1m_Theme_Gate_Breakdown"
                })
                continue
                
            # 2. 익절 로직 (3분봉 볼린저밴드 상단 돌파)
            if row['close'] > row['bb_upper']:
                position = 0
                sell_price = row['close']
                profit_pct = (sell_price / buy_price - 1) * 100
                trades.append({
                    'time': row['timestamp'], 
                    'type': 'TAKE_PROFIT', 
                    'price': sell_price, 
                    'profit_pct': profit_pct,
                    'reason': "3m_BB_Upper_Breakout"
                })
                
    return pd.DataFrame(trades), df_merged

# ==========================================
# 실행 예시 (가상 데이터 생성)
# ==========================================
if __name__ == "__main__":
    print("MTF 전략 백테스트 스크립트가 실행되었습니다. 임의의 데이터로 동작을 확인합니다.")
    
    # 1. 가상의 1분봉 데이터 생성
    dates_1m = pd.date_range('2023-01-01 09:00:00', periods=600, freq='1min')
    df_1m = pd.DataFrame({'timestamp': dates_1m, 'close': np.random.normal(1000, 10, 600).cumsum() + 50000})
    
    # 2. 가상의 3분봉 데이터 생성 (1분봉 기반 리샘플링)
    df_3m = df_1m.set_index('timestamp').resample('3min').agg({'close': 'last'}).reset_index()
    
    # 3. 백테스트 실행
    trades_df, merged_df = run_mtf_backtest(df_3m, df_1m)
    
    print("\n[매매 내역 결과]")
    if not trades_df.empty:
        print(trades_df.to_string())
    else:
        print("매매 내역이 없습니다.")
