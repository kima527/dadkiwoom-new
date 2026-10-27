import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_realistic_sample_data(num_days: int = 40, bars_per_day: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    테마급등관문선, 급등관문고가선, 테마기준선 매매 시나리오를 완벽히 테스트할 수 있는
    실제와 유사한 60분봉 및 일봉 데이터셋 생성기
    
    사이클:
    - Phase 1 (1~10일): 완만한 하락 조정 및 바닥 다지기 (테마급등관문선 하락)
    - Phase 2 (11~20일): 1차 골든크로스 및 2차 골든크로스 상승변곡 (저점 상승 U턴)
    - Phase 3 (21~25일): 급등관문고가선 돌파 및 테마기준선(피크선) 돌파 익절
    - Phase 4 (26~32일): 테마급등관문선으로 눌림(재매수) 후 재상승 익절 순환
    - Phase 5 (33~40일): 일봉 테마 5-20 데드크로스 발생 및 전체 전략 종료
    """
    np.random.seed(42)
    start_date = datetime(2026, 1, 5, 9, 0)
    
    total_bars = num_days * bars_per_day
    timestamps = []
    
    curr_time = start_date
    for _ in range(num_days):
        # 하루 7개 60분봉 (09:00, 10:00, 11:00, 12:00, 13:00, 14:00, 15:00)
        day_time = curr_time
        for h in range(bars_per_day):
            timestamps.append(day_time + timedelta(hours=h))
        curr_time += timedelta(days=1)
        # 주말 건너뛰기
        if curr_time.weekday() >= 5:
            curr_time += timedelta(days=2)
            
    # 가격 시뮬레이션
    base_price = 10000.0
    prices = [base_price]
    
    for i in range(1, total_bars):
        day_idx = i // bars_per_day
        
        if day_idx < 10:
            # Phase 1: 하락 및 횡보
            trend = -0.002
            vol = 0.008
        elif day_idx < 20:
            # Phase 2: 바닥 반등 및 상승변곡 형성
            trend = 0.003
            vol = 0.007
        elif day_idx < 26:
            # Phase 3: 강력한 돌파 상승 (고가선 및 기준선 돌파)
            trend = 0.006
            vol = 0.010
        elif day_idx < 33:
            # Phase 4: 관문선 눌림 지지 및 재반등 (재매수 사이클)
            cycle = np.sin((i % (bars_per_day * 3)) / (bars_per_day * 3) * 2 * np.pi)
            trend = 0.001 + cycle * 0.004
            vol = 0.008
        else:
            # Phase 5: 하락 전환 (일봉 데드크로스 유도)
            trend = -0.008
            vol = 0.012
            
        ret = np.random.normal(trend, vol)
        next_price = prices[-1] * (1.0 + ret)
        prices.append(max(next_price, 1000.0))
        
    df_60m = pd.DataFrame({'timestamp': timestamps, 'close': prices})
    
    # Open, High, Low, Volume 합성
    noise_h = np.random.uniform(0.002, 0.012, size=total_bars)
    noise_l = np.random.uniform(0.002, 0.012, size=total_bars)
    df_60m['open'] = df_60m['close'].shift(1).fillna(df_60m['close'].iloc[0])
    df_60m['high'] = np.maximum(df_60m['open'], df_60m['close']) * (1.0 + noise_h)
    df_60m['low'] = np.minimum(df_60m['open'], df_60m['close']) * (1.0 - noise_l)
    df_60m['volume'] = np.random.randint(10000, 150000, size=total_bars)
    
    # 60분봉을 기반으로 일봉(Daily) 집계 생성
    df_60m['date'] = pd.to_datetime(df_60m['timestamp']).dt.date
    daily_groups = df_60m.groupby('date')
    
    daily_records = []
    for d, g in daily_groups:
        daily_records.append({
            'timestamp': pd.to_datetime(d),
            'open': g['open'].iloc[0],
            'high': g['high'].max(),
            'low': g['low'].min(),
            'close': g['close'].iloc[-1],
            'volume': g['volume'].sum()
        })
        
    df_daily = pd.DataFrame(daily_records)
    
    return df_60m, df_daily

if __name__ == '__main__':
    df_60m, df_daily = generate_realistic_sample_data()
    print(f"생성 완료: 60분봉 {len(df_60m)}개, 일봉 {len(df_daily)}개")
    print(df_60m.head())
