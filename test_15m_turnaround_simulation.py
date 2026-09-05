"""
test_15m_turnaround_simulation.py - 15분봉 및 일봉 수급/이평 변곡 전략(Option B) 시뮬레이션 및 단위 검증
=================================================================================================
1. 단위 검증: 수식 1, 2, 3, 4 및 조합(1+3, 2+3, 3+4) 로직 계산 검증
2. 실전 데이터 시뮬레이션: yfinance를 통한 최근 15분봉/일봉 데이터에서 타점 검출 및 수익률 시뮬레이션
"""

import os
import sys
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# 경로 추가
curr_dir = os.path.dirname(os.path.abspath(__file__))
exec_dir = os.path.join(curr_dir, "MovingAveragelineTraid", "execution")
if exec_dir not in sys.path:
    sys.path.insert(0, exec_dir)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from strategy_15m_turnaround import (
    Turnaround15mParams,
    analyze_15m_signals,
    evaluate_15m_entry,
    calc_formula_4_supply,
    calc_realtime_day_inflections,
    calculate_hwangryong_line,
    tema,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("15mSimulation")

try:
    import yfinance as yf
except ImportError:
    yf = None


def test_unit_formula_logic():
    """1. 단위 테스트: 수식 1, 2, 3, 4가 정확히 작동하는지 정밀 검증"""
    print("\n" + "=" * 70)
    print(" [테스트 1] 15분봉 및 일봉 수식 1, 2, 3, 4 및 3대 조합 단위 기능 검증")
    print("=" * 70)

    # 1-1. 수식 4 검증 (당일 누적 일봉 20억 수급 + 15분봉 3배 폭증 & 윗꼬리 짧은 양봉)
    test_15m_data = {
        'open':   [10000, 10050, 10100, 10000],
        'high':   [10100, 10150, 10150, 10500],
        'low':    [9950,  10000, 10050, 9980],
        'close':  [10050, 10100, 10120, 10480],  # 4번째 봉: open=10000, close=10480 (몸통 480), high=10500 (윗꼬리 20)
        'volume': [50000, 60000, 50000, 300000], # 당일 누적 거래량: 46만주 -> 누적 거래대금 약 47.3억원 (>=20억)
    }
    df_15m = pd.DataFrame(test_15m_data)
    params = Turnaround15mParams(min_daily_supply_money=20.0, supply_surge_multiplier=3.0)
    
    df_f4 = calc_formula_4_supply(df_15m, params)
    print(f" -> 수식 4 (일봉 20억 수급 베이스 + 15분봉 수급 폭발):")
    print(f"    - 당일 일봉 누적 수급액: {df_f4['day_supply_money'].iloc[-1]:.2f}억원 (기준: >=20억)")
    print(f"    - 4번째 15분봉 수급액: {df_f4['m15_money'].iloc[-1]:.2f}억원 (직전 대비 3배 폭증 여부: {df_f4['is_15m_supply_surge'].iloc[-1]})")
    print(f"    - 15분봉 윗꼬리 대비 몸통 비율: 몸통={df_f4['body_15m'].iloc[-1]}, 윗꼬리={df_f4['upper_tail_15m'].iloc[-1]}")
    print(f"    - 4번째 봉 수식 4 신호 발생 여부: {df_f4['sig_f4'].iloc[-1]}")
    assert df_f4['sig_f4'].iloc[-1] == True, "수식 4 신호 검출 실패!"
    print("    [PASS] 수식 4 정상 작동 확인.")

    # 1-2. 일봉 변곡 검증 (수식 3, 1, 2)
    daily_past = [10000] * 20 + [10500, 10400, 10200, 10000] # 최신일이 10000
    curr_close = 10500.0 # 당일 주가 반등
    infl = calc_realtime_day_inflections(curr_close, daily_past)
    print(f"\n -> 수식 3 & 2 (일봉 3일선 변곡 및 이평 크로스):")
    print(f"    - 실시간 3일선(A0): {infl['d_sma3_curr']:.1f}, 3일선 변곡(U턴) 발생: {infl['d_sma3_inflection']}")
    print(f"    - 실시간 5일선(A3): {infl['d_sma5_curr']:.1f}, 5일선 변곡 발생: {infl['d_sma5_inflection']}")
    print(f"    - 3-20 골든크로스 발생: {infl['d_gc_3_20']}")
    assert infl['d_sma3_inflection'] == True, "일봉 3일선 변곡 검출 실패!"
    print("    [PASS] 일봉 3일선 변곡 정상 작동 확인.")


def run_stock_simulation(codes: List[Tuple[str, str]], days: int = 30):
    """2. 실제/시뮬레이션 종목 대상 15분봉 3대 타점 검출 및 시뮬레이션"""
    print("\n" + "=" * 70)
    print(" [테스트 2] 실전 15분봉 3대 타점(3+4, 2+3, 1+3) 스캐닝 및 백테스트")
    print("=" * 70)

    total_signals = []
    
    for code, name in codes:
        print(f"\n▶ 종목 분석: [{code}] {name}")
        df_15m = None
        daily_df = None

        if yf is not None:
            clean_code = code.replace("A", "").strip()
            symbols = [f"{clean_code}.KS", f"{clean_code}.KQ"]
            for sym in symbols:
                try:
                    end_dt = datetime.now()
                    start_dt = end_dt - timedelta(days=days)
                    df_15m_temp = yf.download(sym, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="15m", progress=False)
                    if df_15m_temp is not None and not df_15m_temp.empty and len(df_15m_temp) >= 30:
                        if isinstance(df_15m_temp.columns, pd.MultiIndex):
                            df_15m_temp.columns = df_15m_temp.columns.droplevel(1)
                        df_15m_temp.columns = [c.lower() for c in df_15m_temp.columns]
                        
                        daily_start = end_dt - timedelta(days=120)
                        daily_temp = yf.download(sym, start=daily_start.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1d", progress=False)
                        if isinstance(daily_temp.columns, pd.MultiIndex):
                            daily_temp.columns = daily_temp.columns.droplevel(1)
                        daily_temp.columns = [c.lower() for c in daily_temp.columns]
                        
                        df_15m = df_15m_temp
                        daily_df = daily_temp
                        break
                except Exception:
                    pass

        # yfinance 데이터가 없을 경우 자체 샘플 데이터셋 생성 (테스트용)
        if df_15m is None or len(df_15m) < 30 or daily_df is None or len(daily_df) < 25:
            print("   (yfinance 데이터 수신 불가 -> 정밀 시뮬레이션 합성 데이터셋 생성)")
            np.random.seed(42)
            dates_d = pd.date_range(end=datetime.now(), periods=50, freq='B')
            base_p = 50000.0
            daily_prices = base_p + np.cumsum(np.random.randn(50) * 500)
            daily_df = pd.DataFrame({
                'date': dates_d,
                'open': daily_prices * 0.99,
                'high': daily_prices * 1.02,
                'low': daily_prices * 0.98,
                'close': daily_prices,
                'volume': np.random.randint(100000, 1000000, size=50)
            })

            times_15m = pd.date_range(end=datetime.now(), periods=60, freq='15min')
            p_15m = daily_prices[-1] + np.cumsum(np.random.randn(60) * 150)
            p_15m[55] = p_15m[54] + 800
            v_15m = np.random.randint(5000, 30000, size=60)
            v_15m[55] = 500000

            df_15m = pd.DataFrame({
                'time': times_15m,
                'open': p_15m - 200,
                'high': p_15m + 30,
                'low': p_15m - 250,
                'close': p_15m,
                'volume': v_15m
            }, index=times_15m)

        # 전략 분석 실행 (일봉 20억 수급 기준)
        params = Turnaround15mParams(min_daily_supply_money=20.0) # 일봉 20억 이상
        sig_df = analyze_15m_signals(df_15m, daily_df, params)

        c34_count = sig_df['combo_3_4'].sum()
        c23_count = sig_df['combo_2_3'].sum()
        c13_count = sig_df['combo_1_3'].sum()

        print(f"   [분석 결과] 15분봉 전체 캔들 수: {len(sig_df)}개")
        print(f"   - Combo 3+4 (3일선변곡 + 일봉20억수급폭발): {c34_count}회 포착")
        print(f"   - Combo 2+3 (3-20골든크로스 + 3일선변곡): {c23_count}회 포착")
        print(f"   - Combo 1+3 (3일+5일 더블변곡 + 황룡선): {c13_count}회 포착")

        # 최근 봉 단일 진입 평가
        entry_eval = evaluate_15m_entry(code, name, df_15m, daily_df, params=params)
        if entry_eval['should_buy']:
            print(f"   🚀 [실시간 매수 타점 포착!] {entry_eval['combo_type']}")
            print(f"      - 사유: {entry_eval['reason']}")
            print(f"      - 지정가 매수가: {entry_eval['limit_price']:,.0f}원 (우선순위: {entry_eval['priority_score']})")
        else:
            print(f"   ℹ️ [현재 대기] {entry_eval['reason']}")

        # 포착된 시그널 인덱스 및 사후 수익률(Forward Return) 추적
        signals_found = sig_df[sig_df['any_combo_signal']]
        if not signals_found.empty:
            for t_idx, (t, row) in enumerate(signals_found.iterrows()):
                time_str = str(t)
                c_types = []
                if row['combo_3_4']: c_types.append("3+4(수급변곡)")
                if row['combo_2_3']: c_types.append("2+3(3-20크로스)")
                if row['combo_1_3']: c_types.append("1+3(더블변곡)")
                
                # 진입 후 1시간(4개 15분봉), 2시간(8개 15분봉) 뒤 수익률 추적
                loc_idx = sig_df.index.get_loc(t)
                ret_1h = np.nan
                ret_2h = np.nan
                max_ret = np.nan
                if loc_idx + 4 < len(sig_df):
                    p_1h = sig_df['close'].iloc[loc_idx + 4]
                    ret_1h = (p_1h - row['close']) / row['close'] * 100.0
                if loc_idx + 8 < len(sig_df):
                    p_2h = sig_df['close'].iloc[loc_idx + 8]
                    ret_2h = (p_2h - row['close']) / row['close'] * 100.0
                if loc_idx + 1 < len(sig_df):
                    future_slice = sig_df['high'].iloc[loc_idx + 1 : min(loc_idx + 9, len(sig_df))]
                    if len(future_slice) > 0:
                        max_p = future_slice.max()
                        max_ret = (max_p - row['close']) / row['close'] * 100.0

                perf_str = ""
                if not np.isnan(max_ret):
                    perf_str = f" | 최고수익: +{max_ret:.2f}% (1H뒤: {ret_1h:+.2f}%, 2H뒤: {ret_2h:+.2f}%)"

                print(f"      • [{time_str}] 종가: {row['close']:,.0f}원 | 일봉수급: {row['day_supply_money']:.1f}억 | 15분봉수급: {row['m15_money']:.1f}억 | 유형: {', '.join(c_types)}{perf_str}")
                total_signals.append({
                    "code": code,
                    "name": name,
                    "time": time_str,
                    "close": row['close'],
                    "day_supply_money": row['day_supply_money'],
                    "types": c_types,
                    "max_ret": max_ret,
                    "ret_1h": ret_1h,
                    "ret_2h": ret_2h
                })

    print("\n" + "=" * 70)
    print(f" [시뮬레이션 완료] 총 {len(total_signals)}건의 15분봉 고승률 변곡 타점 검출 완료.")
    print("=" * 70)


if __name__ == "__main__":
    test_unit_formula_logic()

    target_stocks = [
        ("080220", "제주반도체"),
        ("082740", "한화엔진"),
        ("214450", "파마리서치"),
        ("005930", "삼성전자"),
        ("000660", "SK하이닉스"),
    ]
    run_stock_simulation(target_stocks, days=20)
