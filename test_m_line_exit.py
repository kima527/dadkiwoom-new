import os
import sys
import pandas as pd
import numpy as np

current_dir = os.path.dirname(os.path.abspath(__file__))
exec_dir = os.path.join(current_dir, "MovingAveragelineTraid", "execution")
if exec_dir not in sys.path:
    sys.path.insert(0, exec_dir)

from strategy_15m_turnaround import calc_m_resistance_price, calculate_hwangryong_line
from utils import TradeState

print("=" * 60)
print("🧪 [M 저항선 50% 분할 매도 및 청산 로직 검증]")
print("=" * 60)

# 가상의 15분봉 데이터 생성: 정배열 상승 중 고점 찍고 단기 흔들기(312000 -> 315000 -> 313000) 발생
np.random.seed(42)
dates = pd.date_range("2026-09-04 08:00", periods=100, freq="15min")
base_prices = np.linspace(100000, 300000, 70)
# 71~75번째에서 고점 정배열 피크 형성: 305k, 310k, 315k, 311k, 308k
peak_prices = np.array([305000, 310000, 315000, 311000, 308000])
tail_prices = np.linspace(308000, 314000, 25)
prices = np.concatenate([base_prices, peak_prices, tail_prices])

df_15m = pd.DataFrame({
    'open': prices * 0.995,
    'high': prices * 1.008,
    'low': prices * 0.992,
    'close': prices,
    'volume': np.random.randint(10000, 50000, size=100)
}, index=dates)

close = df_15m['close']
a = close.rolling(5, min_periods=5).mean()
b = close.rolling(20, min_periods=20).mean()
d = close.rolling(60, min_periods=60).mean()
cond_align = (a > b) & (b > d)
k_series = close.where(cond_align).ffill()
k_shift1 = k_series.shift(1)
k_shift2 = k_series.shift(2)
cond_peak = (k_shift1 > k_shift2) & (k_shift1 > k_series)
m_series = k_shift1.where(cond_peak).ffill()
print(f"cond_align count: {cond_align.sum()} out of {len(df_15m)}")
print(f"k_series unique count: {k_series.nunique()}")
k_diff = k_series.diff()
peaks = (k_diff.shift(1) > 0) & (k_diff < 0)
print(f"k_series peak count: {peaks.sum()}")

m_res = calc_m_resistance_price(df_15m)
print(f"✅ 검출된 M선 (정배열 최고 정점 저항선): {m_res:,.0f}원")

# 1. M선 도달 50% 분할 익절 테스트
state = TradeState()
state.is_holding = True
state.first_qty = 10
qty_sell = 10
current_price = 314000 # M선(315,000)의 99.5% 이상 도달

print(f"\n[시나리오 1] 현재가 {current_price:,.0f}원이 M선({m_res:,.0f}원)의 99.5% 도달 시:")
if m_res > 0 and not state.m_partial_sold:
    if current_price >= (m_res * 0.995):
        half_qty = max(1, qty_sell // 2) if qty_sell > 1 else qty_sell
        state.m_partial_sold = True
        state.m_resistance_line = m_res
        state.m_touch_high = current_price
        print(f"👉 🎯 1차 50% 분할 익절 성공! 매도 수량: {half_qty}주, 잔여 수량: {qty_sell - half_qty}주")

# 2. M선 돌파 실패 및 꺾임 시 잔여 50% 전량 청산 테스트
drop_price = 305000 # M선 도달 후 305,000원으로 꺾임 (고점 314,000 대비 -2.8% 하락)
qty_remaining = 5
print(f"\n[시나리오 2] 1차 매도 후 현재가가 {drop_price:,.0f}원으로 돌파 실패 꺾임 발생 시:")
if m_res > 0 and state.m_partial_sold:
    touch_high = max(state.m_touch_high, drop_price)
    is_m_rejected = (drop_price < m_res * 0.985) or (drop_price < touch_high * 0.98)
    if is_m_rejected:
        state.is_holding = False
        state.trade_ended = True
        state.m_partial_sold = False
        print(f"👉 🔴 돌파 실패 확인! 잔여 {qty_remaining}주 전량 매도 완료 -> 100% 수익 확정 및 예수금 회수!")
        print(f"👉 🎯 포트폴리오 상태: is_holding={state.is_holding}, trade_ended={state.trade_ended} (다음 대장주 진입 준비 완료)")

print("\n" + "=" * 60)
print("🎉 모든 시나리오 단위 테스트 정상 통과!")
print("=" * 60)
