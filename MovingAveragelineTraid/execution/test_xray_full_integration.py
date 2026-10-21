import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta

sys.path.append(r"c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\MovingAveragelineTraid\execution")
from strategy_120t_wma60 import evaluate_120t_wma60_entry, WMA60TickParams, calculate_2m_macro_gates
from xray_analyzer import evaluate_xray_power, XRayParams

def test_xray_integration():
    # 1. 2분봉 데이터 준비 (관문선 돌파 상태)
    now = datetime.now()
    times_2m = [now - timedelta(minutes=2 * i) for i in range(60, 0, -1)]
    prices_2m = [10000 + i * 50 for i in range(50)] + [12500 + i * 100 for i in range(10)]
    df_2m = pd.DataFrame({
        'time': times_2m,
        'open': [p - 20 for p in prices_2m],
        'high': [p + 50 for p in prices_2m],
        'low': [p - 50 for p in prices_2m],
        'close': prices_2m,
        'volume': [10000 for _ in prices_2m]
    }).set_index('time')

    # 2. 120틱 데이터 준비 (역배열 후 순차 돌파)
    prices_120t = [14000 - i * 30 for i in range(70)] + [12000, 12200, 12400, 13600]
    df_120t = pd.DataFrame({'close': prices_120t})

    # 3. 실시간 X-Ray 틱 데이터 준비 (동일 1초에 대형 3건 싹쓸이 발생)
    now_str = "2026-10-21 12:05:30"
    mock_ticks = [
        {'time': now_str, 'close': 13600, 'volume': 2000},  # 2720만원 (대형 1)
        {'time': now_str, 'close': 13650, 'volume': 2500},  # 3412만원 (대형 2)
        {'time': now_str, 'close': 13700, 'volume': 2200},  # 3014만원 (대형 3) -> 1초 3건 싹쓸이!
        {'time': "2026-10-21 12:05:28", 'close': 13500, 'volume': 300},
        {'time': "2026-10-21 12:05:25", 'close': 13450, 'volume': 1800}, # 2421만원 (대형 4)
    ]

    params = WMA60TickParams(require_gate_break=True, use_2m_macro_filter=True, use_xray_filter=True)
    res = evaluate_120t_wma60_entry(df_120t, current_price=13700, params=params, df_2m=df_2m, ticks=mock_ticks)

    print("=== [120틱 + 2분봉 + X-Ray 순간체결량 융합 결과] ===")
    print(f"Should Buy: {res['should_buy']}")
    print(f"X-Ray 등급: {res['xray_grade']}")
    print(f"1초 싹쓸이 여부: {res['has_1sec_sweep']}")
    print(f"포착빈도 카운트: {res['xray_freq']}회")
    print(f"X-Ray 보너스 점수: +{res['xray_bonus']}점")
    print(f"최종 매수 사유:\n{res['reason']}")

    assert res['should_buy'] == True, "매수 조건 충족되어야 함"
    assert res['has_1sec_sweep'] == True, "1초 3건 싹쓸이가 감지되어야 함"
    assert res['xray_grade'] == 'S', "S급 X-Ray로 판정되어야 함"
    assert "X-Ray S급" in res['reason'], "사유에 X-Ray S급 태그가 포함되어야 함"
    print("\n>>> [검증 성공] X-Ray 순간체결량 & 포착빈도 로직이 전략에 완벽히 접목되었습니다!")

if __name__ == '__main__':
    test_xray_integration()
