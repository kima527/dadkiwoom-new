import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta

sys.path.append(r"c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\MovingAveragelineTraid\execution")
from strategy_120t_wma60 import (
    evaluate_120t_wma60_entry,
    evaluate_120t_wma60_exit,
    calculate_2m_macro_gates,
    WMA60TickParams
)

def test_2m_macro_gates():
    # 2분봉 60개 데이터 생성
    now = datetime.now()
    times = [now - timedelta(minutes=2 * i) for i in range(60, 0, -1)]
    
    # 5, 20, 60 골든크로스와 정배열이 발생하는 가격 시나리오
    prices = [10000 + i * 50 for i in range(50)] + [12500 + i * 100 for i in range(10)]
    highs = [p + 50 for p in prices]
    lows = [p - 50 for p in prices]
    opens = [p - 20 for p in prices]
    volumes = [10000 for _ in prices]
    
    df_2m = pd.DataFrame({
        'time': times,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': prices,
        'volume': volumes
    })
    df_2m.set_index('time', inplace=True)
    
    # 1. 2분봉 매크로 게이트 산출 테스트
    gates = calculate_2m_macro_gates(df_2m)
    print("=== [2분봉 매크로 관문선 산출 결과] ===")
    print(f"테마급등관문선: {gates['tema_gate']:,.1f}원")
    print(f"급등관문고가선(HH): {gates['gate_high']:,.1f}원")
    print(f"목표 기준선(M선): {gates['m_line']:,.1f}원")
    print(f"볼린저 밴드폭: {gates['bandwidth']:.4f}")
    
    assert gates['tema_gate'] > 0, "테마선이 유효해야 합니다."
    assert gates['gate_high'] > 0, "급등관문고가선이 유효해야 합니다."
    assert gates['m_line'] > 0, "기준선 M선이 유효해야 합니다."
    
    # 2. 120틱 데이터 준비 (WMA 20<40<60 역배열 후 1이평 순차 돌파)
    prices_120t = [14000 - i * 30 for i in range(70)] # 70봉 역배열
    prices_120t += [12000, 12200, 12400, 13600] # 순차 돌파 (2분봉 고가선 13450 초과)
    df_120t = pd.DataFrame({'close': prices_120t})
    
    params = WMA60TickParams(require_gate_break=True, use_2m_macro_filter=True)
    res = evaluate_120t_wma60_entry(df_120t, current_price=prices_120t[-1], params=params, df_2m=df_2m)
    
    print("\n=== [120틱 + 2분봉 융합 판정 결과] ===")
    print(f"Should Buy: {res['should_buy']}")
    print(f"Target Price: {res['target_price']}")
    print(f"M Target Price (익절 목표): {res['m_target_price']}")
    print(f"Reason: {res['reason']}")
    
    assert res['m_target_price'] == gates['m_line'], "2분봉 기준선 M선이 목표가로 연동되어야 함"
    assert "2분봉" in res['reason'], "이유에 2분봉이 명시되어야 함"
    assert res['should_buy'] == True, "조건 충족 시 매수가 발생해야 함"

    # 3. 2분봉 M선 도달 익절 테스트
    exit_res = evaluate_120t_wma60_exit(
        df_120t, current_price=14200, buy_price=12490, params=params,
        target_m_line=res['m_target_price'], tema_sl=res['tema_gate']
    )
    print("\n=== [청산/익절 판정 결과] ===")
    print(f"Should Sell: {exit_res['should_sell']}")
    print(f"Reason: {exit_res['reason']}")
    assert exit_res['should_sell'] == True, "2분봉 M선 돌파 시 목표 익절되어야 함"
    assert "M선" in exit_res['reason'], "익절 사유에 M선 명시되어야 함"

    print("\n>>> [전체 검증 완료] 120틱 진입 스나이핑 + 2분봉 관문 돌파 + 2분봉 M선 목표익절 완벽 작동!")

if __name__ == '__main__':
    test_2m_macro_gates()
