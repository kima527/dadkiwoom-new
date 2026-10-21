"""
test_falling_guard.py
=====================
1. 실시간 지수 하락 감지 (고점 대비 밀림, 15분봉 5-20선 역배열) -> 매수 100% 전면 차단
2. 개별 종목 하락 추세 차단 (check_falling_stock):
   - 당일 시가(Open) 아래 파란색 음봉 종목 차단
   - 당일 최고가(High) 대비 -4% 이상 폭락한 설거지/투매 종목 차단
   - 2분봉 20선 아래 역배열 하락 종목 차단
   - 최근 3개 분봉 연속 음봉 하락(떨어지는 칼날) 차단
"""

import os
import sys
import pandas as pd
import numpy as np

_exec_dir = os.path.abspath(os.path.dirname(__file__))
if sys.path[0] != _exec_dir:
    sys.path.insert(0, _exec_dir)

from trading_bot import check_falling_stock

def test_falling_stock_filters():
    print("\n--- [TEST] 계속 하락하는 종목 선제 차단 엔진(check_falling_stock) 검증 ---")

    # 1. 당일 시가 아래 파란색 음봉 종목
    daily_df_negative = pd.DataFrame([{
        'open': 10000, 'high': 10200, 'low': 9800, 'close': 9900, 'volume': 100000
    }])
    is_fall, reason = check_falling_stock("001", "음봉종목", 9900, daily_df_negative, None, None)
    assert is_fall == True, "당일 시가 아래 음봉 종목은 반드시 차단되어야 합니다!"
    print(f"✅ 1. 당일 시가 아래 음봉 차단 성공: {reason}")

    # 2. 당일 최고가 대비 -4% 이상 폭락한 설거지 종목 (시가는 10,000, 고가 12,000, 현재 11,200: -6.6% 폭락)
    daily_df_dump = pd.DataFrame([{
        'open': 10000, 'high': 12000, 'low': 9900, 'close': 11200, 'volume': 100000
    }])
    is_fall, reason = check_falling_stock("002", "설거지종목", 11200, daily_df_dump, None, None)
    assert is_fall == True, "고점 대비 -4% 이상 폭락한 종목은 차단되어야 합니다!"
    print(f"✅ 2. 고점 대비 -4% 폭락 설거지 차단 성공: {reason}")

    # 3. 2분봉 20선 아래 역배열 종목
    closes = [10500 - i * 10 for i in range(25)] # 줄줄 흘러내림
    opens = [c + 5 for c in closes]
    highs = [c + 15 for c in closes]
    lows = [c - 15 for c in closes]
    df_2m_down = pd.DataFrame({'open': opens, 'high': highs, 'low': lows, 'close': closes})
    curr_c = closes[-1]
    daily_df_ok = pd.DataFrame([{'open': 10000, 'high': 10500, 'low': 9900, 'close': curr_c, 'volume': 100000}])

    is_fall, reason = check_falling_stock("003", "20선하회종목", curr_c, daily_df_ok, df_2m_down, None)
    assert is_fall == True, "2분봉 20선 아래 역배열 종목은 차단되어야 합니다!"
    print(f"✅ 3. 2분봉 20선 아래 역배열 차단 성공: {reason}")

    # 4. 최근 3개 분봉 연속 음봉 하락 (떨어지는 칼날)
    df_2m_3down = pd.DataFrame({
        'open': [10000, 10050, 10040, 10030, 10010],
        'close': [10000, 10040, 10030, 10010, 9990],
        'high': [10020, 10060, 10050, 10035, 10015],
        'low': [9990, 10030, 10020, 10000, 9980]
    })
    is_fall, reason = check_falling_stock("004", "연속음봉종목", 9990, None, df_2m_3down, None)
    assert is_fall == True, "최근 3개 연속 음봉 하락은 차단되어야 합니다!"
    print(f"✅ 4. 최근 3개 연속 음봉 떨어지는 칼날 차단 성공: {reason}")

    # 5. 정상 주도 대장주 (당일 시가 위 양봉 + 고점 부근 + 20선 위 우상향)
    daily_leader = pd.DataFrame([{'open': 10000, 'high': 10500, 'low': 9950, 'close': 10450, 'volume': 100000}])
    df_2m_leader = pd.DataFrame({
        'open': [10000 + i * 20 for i in range(25)],
        'close': [10010 + i * 20 for i in range(25)],
        'high': [10020 + i * 20 for i in range(25)],
        'low': [9990 + i * 20 for i in range(25)]
    })
    is_fall, reason = check_falling_stock("005", "진짜대장주", 10450, daily_leader, df_2m_leader, None)
    assert is_fall == False, "정상 주도주는 통과되어야 합니다!"
    print(f"✅ 5. 진짜 주도 대장주(양봉, 20선 위 지지) 정상 통과 확인: {reason}")

    print("\n🎉 모든 하락 종목 차단 테스트 100% 완벽 통과!")

if __name__ == '__main__':
    test_falling_stock_filters()
