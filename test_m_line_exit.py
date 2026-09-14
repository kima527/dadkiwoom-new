import os
import sys
import pandas as pd
import numpy as np

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

current_dir = os.path.dirname(os.path.abspath(__file__))
exec_dir = os.path.join(current_dir, "MovingAveragelineTraid", "execution")
if exec_dir not in sys.path:
    sys.path.insert(0, exec_dir)

from strategy_sell import analyze_sell_signals, calc_m_resistance, evaluate_1m_m_breakout
from strategy_buy import check_smallcap_supply_signal
from utils import TradeState

print("=" * 70)
print("🧪 [통합 전략 검증: 중소형주 분봉 수급 매수 & M선 돌파 실패 / -2% 손절]")
print("=" * 70)

# 가상의 15분봉 데이터 생성: 정배열 상승 중 고점 찍고 단기 흔들기(312000 -> 315000 -> 308000) 발생
np.random.seed(42)
dates = pd.date_range("2026-09-04 08:00", periods=100, freq="15min")
base_prices = np.linspace(100000, 300000, 70)
# 71~75번째에서 고점 정배열 피크 형성: 305k, 310k, 315k, 311k, 308k
peak_prices = np.array([305000, 310000, 315000, 311000, 308000])
tail_prices = np.linspace(308000, 314000, 25)
prices = np.concatenate([base_prices, peak_prices, tail_prices])

volumes = np.random.randint(10000, 50000, size=100)
# 99번째 봉에 중소형주 수급 폭발 조건 인위 생성:
# 20봉 평균 대비 5배 수급 & 양봉 몸통 > 윗꼬리 * 1.2 & 직전 2봉 평균 대비 3배 수급
volumes[-1] = 500000 # 대량 거래량

df_15m = pd.DataFrame({
    'open': prices * 0.995,
    'high': prices * 1.008,
    'low': prices * 0.992,
    'close': prices,
    'volume': volumes
}, index=dates)

# 99번째 봉을 강한 양봉으로 설정 (윗꼬리 짧고 몸통 큼)
df_15m.iloc[-1, df_15m.columns.get_loc('open')] = 310000
df_15m.iloc[-1, df_15m.columns.get_loc('close')] = 318000
df_15m.iloc[-1, df_15m.columns.get_loc('high')] = 319000
df_15m.iloc[-1, df_15m.columns.get_loc('low')] = 309000

m_res = calc_m_resistance(df_15m)
print(f"✅ 검출된 M선 (정배열 최고 정점 저항선): {m_res:,.0f}원")

# ── [테스트 1] 중소형주 분봉 수급 매수 수식 검증 ──
print("\n[테스트 1] 중소형주 분봉 수급 매수 수식 검증 (A >= AvgA * 5 & 양봉 & 몸통>윗꼬리*1.2 & 직전2봉 3배):")
is_supply_sig, supply_info = check_smallcap_supply_signal(df_15m)
print(f"👉 중소형주 수급 신호 발생 여부: {is_supply_sig}")
print(f"👉 상세 수급 데이터: {supply_info}")
assert is_supply_sig == True, "중소형주 수급 조건 매수 신호가 정상 감지되어야 합니다."
print("👉 🎯 [테스트 1 통과] 중소형주 분봉 수급 매수 신호 정상 검출!")

# ── [테스트 2] 절대적 매도 조건 (매수가 대비 -2.0% 손절) 검증 ──
print("\n[테스트 2] 절대적 매도 조건 (매수가 대비 -2% 손절매) 검증:")
buy_price = 300000
drop_price_sl = 293000 # -2.33% 하락
sl_result = analyze_sell_signals(df_15m, buy_price=buy_price, current_price=drop_price_sl)
print(f"👉 매수가 {buy_price:,.0f}원 대비 현재가 {drop_price_sl:,.0f}원 손익률: {sl_result['profit_pct']:+.2f}%")
print(f"👉 매도 신호: {sl_result['sell']}, 사유: {sl_result['reason']}")
assert sl_result['sell'] == True, "매수가 대비 -2% 도달 시 즉시 매도 신호가 발생해야 합니다."
assert sl_result['exit_type'] == "STOP_LOSS_2PCT", "exit_type이 STOP_LOSS_2PCT 여야 합니다."
print("👉 🎯 [테스트 2 통과] -2% 절대 손절 신호 정상 발동!")

# ── [테스트 3] 계좌 수익 중 M선 돌파 실패 시 전량 매도 검증 ──
print("\n[테스트 3] 계좌 수익 중 M선 돌파 여부 확인 및 실패 시 전량 매도 검증:")
buy_price_profit = 280000 # 수익 중
# M선(315,000) 부근 314,500원까지 올라갔다가 309,000원으로 꺾인 상황 (고점 314,500원 대비 -1.75% 하락)
touch_high_val = 314500
curr_dropped = 309000 # M선(315k)의 98.1% 수준으로 꺾임
m_result = analyze_sell_signals(df_15m, buy_price=buy_price_profit, current_price=curr_dropped, touch_high=touch_high_val)
print(f"👉 매수가 {buy_price_profit:,.0f}원 (수익 중 +{m_result['profit_pct']:.1f}%), M선({m_res:,.0f}원) 부근 고점 {touch_high_val:,.0f}원 도달 후 {curr_dropped:,.0f}원으로 꺾임")
print(f"👉 매도 신호: {m_result['sell']}, 사유: {m_result['reason']}")
assert m_result['sell'] == True, "수익 중 M선 돌파 실패 시 전량 매도 신호가 발생해야 합니다."
assert m_result['exit_type'] == "M_BREAKOUT_FAIL", "exit_type이 M_BREAKOUT_FAIL 여야 합니다."
print("👉 🎯 [테스트 3 통과] 수익 중 M선 돌파 실패 전량 매도 정상 발동!")

# ── [테스트 4] 계좌 수익 중 정상 상승 유지 시 (M선 돌파 실패 아님) 매도 보류 검증 ──
print("\n[테스트 4] 계좌 수익 중 정상 상승 추세 유지 시 매도 보류 검증:")
curr_rising = 316000 # M선(315k)을 뚫고 316,000원으로 안착 상승 중
hold_result = analyze_sell_signals(df_15m, buy_price=buy_price_profit, current_price=curr_rising, touch_high=curr_rising)
print(f"👉 현재가 {curr_rising:,.0f}원 (M선 돌파 성공 안착 상승 중) -> 매도 신호: {hold_result['sell']}")
assert hold_result['sell'] == False, "M선 상향 돌파 안착 중에는 홀딩을 유지해야 합니다."
print("👉 🎯 [테스트 4 통과] M선 돌파 안착 시 안정적 홀딩 유지!")

# ── [테스트 5] 15분봉 M선 근접 시 1분봉 M선 돌파/실패 정밀 판별 검증 ──
print("\n" + "=" * 70)
print("🧪 [테스트 5] 15분봉 M선 근접 시 1분봉 정밀 돌파/실패 판별 검증 (evaluate_1m_m_breakout)")
print("=" * 70)

# 가상 1분봉 데이터 생성 함수
def create_1m_data(candle_patterns):
    dates_1m = pd.date_range("2026-09-04 10:00", periods=len(candle_patterns), freq="1min")
    records = []
    for o, h, l, c in candle_patterns:
        records.append({'open': o, 'high': h, 'low': l, 'close': c, 'volume': 1000})
    return pd.DataFrame(records, index=dates_1m)

m_level = 315000.0
buy_p = 290000.0

# Case 5-A: 터치 후 2연속 음봉 + 1분봉 5선 이탈 (1M_M_REJECTION)
print("\n[5-A] 1분봉 M선 터치 후 2연속 음봉 + 5이평선 하향 이탈 판별:")
c_patterns_rejection = [
    (312000, 313000, 311000, 312500),
    (312500, 314000, 312000, 313800),
    (313800, 314800, 313500, 314600), # M선 99.5% 터치 (314,800 >= 313,425)
    (314600, 314600, 313000, 313200), # 음봉 1
    (313200, 313200, 312000, 312200), # 음봉 2 & 5선(약 313,260) 하회
]
df_1m_rej = create_1m_data(c_patterns_rejection)
res_rej = evaluate_1m_m_breakout(df_1m_rej, m_resistance=m_level, buy_price=buy_p, touch_high=314800)
print(f"👉 결과: sell={res_rej['sell']}, exit_type={res_rej['exit_type']}, 사유: {res_rej['reason']}")
assert res_rej['sell'] == True, "1분봉 2연속 음봉 및 5이평선 이탈 시 매도 신호가 발생해야 합니다."
assert res_rej['exit_type'] == "1M_M_REJECTION", "exit_type이 1M_M_REJECTION 이어야 합니다."
print("👉 🎯 [5-A 통과] 1분봉 M선 터치 저항 꺾임 매도 정상 발동!")

# Case 5-B: 1분봉 가짜 돌파 (Bull Trap) 후 M선 재이탈 (1M_BULL_TRAP)
print("\n[5-B] 1분봉 가짜 돌파(Bull Trap) 후 M선 아래 재붕괴 판별:")
c_patterns_trap = [
    (312000, 313000, 311000, 312500),
    (312500, 314000, 312000, 313800),
    (313800, 315500, 313500, 315200), # M선(315,000) 돌파 (High 315,500)
    (315200, 315300, 313000, 313100), # 돌파 후 M선 아래(< 313,425)로 재붕괴
]
df_1m_trap = create_1m_data(c_patterns_trap)
res_trap = evaluate_1m_m_breakout(df_1m_trap, m_resistance=m_level, buy_price=buy_p, touch_high=315500)
print(f"👉 결과: sell={res_trap['sell']}, exit_type={res_trap['exit_type']}, 사유: {res_trap['reason']}")
assert res_trap['sell'] == True, "1분봉 M선 불트랩 붕괴 시 즉시 매도 신호가 발생해야 합니다."
assert res_trap['exit_type'] == "1M_BULL_TRAP", "exit_type이 1M_BULL_TRAP 이어야 합니다."
print("👉 🎯 [5-B 통과] 1분봉 불트랩 붕괴 매도 정상 발동!")

# Case 5-C: 1분봉 고점 대비 트레일링 꺾임 (1M_TRAILING_FALL)
print("\n[5-C] 1분봉 M선 부근 고점 대비 -1.2% 이상 하락 꺾임 판별:")
c_patterns_trail = [
    (312000, 313000, 311000, 312500),
    (312500, 314000, 312000, 313800),
    (313800, 314500, 313500, 314200), # M선 부근 고점 314,500
    (314200, 314200, 311500, 310500), # 314,500 대비 -1.27% 하락 (310,500)
]
df_1m_trail = create_1m_data(c_patterns_trail)
res_trail = evaluate_1m_m_breakout(df_1m_trail, m_resistance=m_level, buy_price=buy_p, current_price=310500, touch_high=314500)
print(f"👉 결과: sell={res_trail['sell']}, exit_type={res_trail['exit_type']}, 사유: {res_trail['reason']}")
assert res_trail['sell'] == True, "M선 부근 최고점 대비 -1.2% 이상 하락 시 즉시 매도 신호가 발생해야 합니다."
assert res_trail['exit_type'] == "1M_TRAILING_FALL", "exit_type이 1M_TRAILING_FALL 이어야 합니다."
print("👉 🎯 [5-C 통과] 1분봉 트레일링 꺾임 매도 정상 발동!")

# Case 5-D: 1분봉 M선 돌파 안착 성공 및 홀딩 (HOLD_BREAKOUT)
print("\n[5-D] 1분봉 M선 돌파 안착 성공 시 안정적 홀딩 유지 판별:")
c_patterns_hold = [
    (312000, 313000, 311000, 312500),
    (312500, 314000, 312000, 313800),
    (313800, 315500, 313500, 315200),
    (315200, 316500, 315000, 316200), # M선(315k) 상향 안착 중 (Close 316,200)
]
df_1m_hold = create_1m_data(c_patterns_hold)
res_hold = evaluate_1m_m_breakout(df_1m_hold, m_resistance=m_level, buy_price=buy_p, current_price=316200, touch_high=316500)
print(f"👉 결과: sell={res_hold['sell']}, exit_type={res_hold['exit_type']}, 사유: {res_hold['reason']}")
assert res_hold['sell'] == False, "1분봉 M선 돌파 안착 중에는 매도하지 않고 홀딩해야 합니다."
assert res_hold['exit_type'] == "HOLD_BREAKOUT", "exit_type이 HOLD_BREAKOUT 이어야 합니다."
print("👉 🎯 [5-D 통과] 1분봉 M선 돌파 안착 홀딩 정상 유지!")

print("\n" + "=" * 70)
print("🎉 [축하] 15분봉 및 1분봉 M선 돌파/실패 정밀 로직 전체 단위 테스트 100% 정상 통과!")
print("=" * 70)

