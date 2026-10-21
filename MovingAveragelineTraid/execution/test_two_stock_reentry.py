"""
test_two_stock_reentry.py
=========================
사용자 최종 요구사항 집중 검증:
1. 하루에 최고센 종목 2개를 선정해서 집중매매 (2종목 락인, 3번째 종목 차단)
2. 매도 후 하락하던 것이:
   - 경로 A: 2분봉 기준선(M선)을 상향 통과하거나,
   - 경로 B: 2분봉 급등관문고가선(HH)을 재차 통과할 때 재매수!
3. 하루에 두 종목으로만 끝내는 순환 매매 검증
"""

import os
import sys
import time
import asyncio
import numpy as np
import pandas as pd

_exec_dir = os.path.abspath(os.path.dirname(__file__))
if sys.path[0] != _exec_dir:
    sys.path.insert(0, _exec_dir)

from utils import TradeState
from strategy_120t_wma60 import evaluate_reentry_signal, WMA60TickParams, calculate_2m_macro_gates
from trading_bot import BuyManager, SellManager

def generate_mock_2m_df(base_price=10000, n_bars=40, scenario="dip_and_recover_m"):
    np.random.seed(42)
    closes = [base_price]
    highs = [base_price + 50]
    lows = [base_price - 50]
    opens = [base_price]
    volumes = [10000]

    for i in range(1, n_bars):
        if scenario == "dip_and_recover_m":
            # 초반 상승 -> 매도 후 하락(눌림) -> 기준선(M선) 상향 재돌파
            if i < 25:
                # 완만한 상승세로 5, 20, 60 정배열 및 M선 형성
                c = closes[-1] + 20
            elif i < 33:
                # 매도 후 하락 (눌림 구간)
                c = closes[-1] - 40
            else:
                # 기준선 상향 재돌파 반등
                c = closes[-1] + 50
        elif scenario == "dip_and_recover_hh":
            # 초반 급등 -> 눌림 -> 급등관문고가선 재돌파
            if i < 25:
                c = closes[-1] + 25
            elif i < 33:
                c = closes[-1] - 35
            else:
                c = closes[-1] + 60
        else:
            c = closes[-1] + 10

        h = c + 30
        l = c - 30
        o = closes[-1]
        v = 15000 + (5000 if i >= 33 else 0)

        closes.append(c)
        highs.append(h)
        lows.append(l)
        opens.append(o)
        volumes.append(v)

    dates = pd.date_range("2026-10-21 09:00", periods=n_bars, freq="2min")
    return pd.DataFrame({
        'open': opens, 'high': highs, 'low': lows, 'close': closes, 'volume': volumes
    }, index=dates)


def test_reentry_signal_m_cross():
    print("\n--- [TEST 1] 매도 후 하락 ➔ 기준선(M선) 상향 통과 시 재매수 검증 ---")
    df_2m = generate_mock_2m_df(10000, n_bars=40, scenario="dip_and_recover_m")
    macro = calculate_2m_macro_gates(df_2m)
    m_line = macro['m_line']
    hh_line = macro['gate_high']
    tema_line = macro['tema_gate']
    curr_c = df_2m['close'].iloc[-1]

    print(f"2분봉 지표 -> 기준선(M선): {m_line:,.0f}원 | 급등관문선(HH): {hh_line:,.0f}원 | 테마선: {tema_line:,.0f}원 | 현재가: {curr_c:,.0f}원")

    # 매도 상태 모의 설정
    state = TradeState()
    state.sold_once = True
    state.is_holding = False
    state.trade_ended = False
    state.sold_price = 10400  # 10,400원에 1차 매도
    state.sold_time = time.time() - 100.0  # 100초 전 매도
    state.dip_min_price = 10050  # 10,050원까지 하락(눌림) 발생했음
    state.dip_detected = True

    eval_res = evaluate_reentry_signal(
        df_120t=None, df_2m=df_2m, current_price=curr_c, state=state
    )

    print(f"재매수 시그널 판정: should_buy={eval_res['should_buy']}, 이유: {eval_res['reason']}")
    assert eval_res['should_buy'] == True, "기준선 상향 통과 시 재매수 시그널이 발생해야 합니다!"
    assert eval_res['is_m_cross'] == True or eval_res['is_hh_cross'] == True
    print("✅ TEST 1 성공: 매도 후 하락 ➔ 기준선/관문선 통과 시 재매수 완벽 작동!")


def test_two_stock_lock():
    print("\n--- [TEST 2] 당일 최고센 2종목 락인 (제3의 종목 원천 차단) 검증 ---")
    class MockClient:
        def get_account_holdings(self): return {}
        def get_cash_balance(self): return 50_000_000
        def get_stock_name(self, code): return f"종목_{code}"
        def place_buy_order(self, code, qty, price, order_type): return "999001"

    daily_traded = ["005930", "000660"] # 삼성전자, SK하이닉스 2종목 이미 락인됨
    trade_states = {
        "005930": TradeState(),
        "000660": TradeState(),
        "035420": TradeState()  # 제3의 종목 (NAVER)
    }

    bm = BuyManager(
        client=MockClient(),
        api_lock=asyncio.Lock(),
        trade_states=trade_states,
        tracked_orders={},
        watchlist={"005930": {"name": "삼성전자"}, "000660": {"name": "SK하이닉스"}, "035420": {"name": "NAVER"}},
        daily_traded_stocks=daily_traded,
        max_daily_stocks=2,
        max_reentry_per_stock=3
    )

    # 1. 3번째 종목 (035420) evaluate_single_stock 호출 시 차단되는지 확인
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bm.evaluate_single_stock("035420"))

    assert "035420" not in bm.daily_traded_stocks, "3번째 종목은 daily_traded_stocks에 들어가서는 안 됩니다!"
    assert len(bm.tracked_orders) == 0, "3번째 종목은 주문이 전송되어서는 안 됩니다!"
    print("✅ TEST 2 성공: 당일 2종목 락인으로 제3의 종목 매수 100% 원천 차단 확인!")


def test_reentry_execution_flow():
    print("\n--- [TEST 3] 매수 ➔ 매도 ➔ 하락 ➔ 기준선 재통과 ➔ 재매수 발주 전체 사이클 검증 ---")
    class MockClient:
        def __init__(self):
            self.orders = []
        def get_account_holdings(self): return {}
        def get_cash_balance(self): return 50_000_000
        def get_stock_name(self, code): return "대장주"
        def get_2m_candles(self, code): return generate_mock_2m_df(10000, 40, "dip_and_recover_m")
        def get_120t_candles(self, code): return None
        def get_daily_candles(self, code): return pd.DataFrame([{'open': 10000, 'high': 10600, 'low': 9950, 'close': 10510, 'volume': 100000}])
        def get_tick_data(self, code): return [{'price': 10510}]
        def place_buy_order(self, code, qty, price, order_type):
            self.orders.append(('BUY', code, qty, price))
            return "ORDER_BUY_001"
        def place_sell_order(self, code, qty, price, order_type):
            self.orders.append(('SELL', code, qty, price))
            return "ORDER_SELL_001"

    client = MockClient()
    daily_traded = ["005930"]
    state = TradeState()
    trade_states = {"005930": state}
    tracked_orders = {}

    bm = BuyManager(
        client=client,
        api_lock=asyncio.Lock(),
        trade_states=trade_states,
        tracked_orders=tracked_orders,
        watchlist={"005930": {"name": "대장주"}},
        daily_traded_stocks=daily_traded,
        max_daily_stocks=2,
        max_reentry_per_stock=3
    )

    # 매도 완료 상태 세팅
    state.sold_once = True
    state.is_holding = False
    state.trade_ended = False
    state.sold_price = 10400
    state.sold_time = time.time() - 100.0
    state.dip_min_price = 10050
    state.dip_detected = True
    state.reentry_count = 0

    loop = asyncio.get_event_loop()
    loop.run_until_complete(bm.process_reentry_for_stock("005930", holdings={}))

    assert len(client.orders) == 1, "재매수 주문이 전송되어야 합니다!"
    assert client.orders[0][0] == 'BUY'
    assert client.orders[0][1] == '005930'
    assert state.is_holding == True
    assert state.reentry_count == 1
    print(f"✅ TEST 3 성공: 매도 후 하락 ➔ 기준선 재통과 ➔ 재매수 발주 성공! (회차: {state.reentry_count}회, 주문: {client.orders[0]})")


def test_early_sell_prevention():
    print("\n--- [TEST 4] 매수 직후 10초 만의 조기 매도 차단 (Grace Period) 검증 ---")
    from strategy_120t_wma60 import evaluate_120t_wma60_exit

    # 모의 120틱 데이터 (과거 하락으로 WMA60 기울기 음수 상태)
    closes = [10000 - i * 5 for i in range(70)]
    df_120t = pd.DataFrame({'close': closes})

    # 매수 후 10초밖에 안 된 상태 (holding_seconds=10)
    # 현재가가 WMA60보다 아래에 있고 기울기가 음수여도 조기 매도되지 않아야 함!
    res_early = evaluate_120t_wma60_exit(
        df_120t=df_120t,
        current_price=9600,
        buy_price=9650,
        holding_seconds=10.0,
        max_profit_pct=0.0
    )
    assert res_early['should_sell'] == False, "매수 후 3분 이내 틱 노이즈로는 조기 매도되지 않아야 합니다!"
    print("✅ TEST 4-1 성공: 매수 10초 후 WMA60 음수 기울기 노이즈에 의한 조기 매도 100% 방어 확인!")

    # 단, 테마급등관문선 하향 이탈(-1.5%) 시에는 10초여도 즉시 손절되어야 함!
    res_sl = evaluate_120t_wma60_exit(
        df_120t=df_120t,
        current_price=9400,
        buy_price=9650,
        tema_sl=9600,  # 테마선 9,600원인데 9,400원까지 이탈
        holding_seconds=10.0
    )
    assert res_sl['should_sell'] == True, "테마급등관문선 이탈 시에는 즉시 손절되어야 합니다!"
    print("✅ TEST 4-2 성공: 테마급등관문선 하향 이탈 시에는 즉시 안전 손절 작동 확인!")


if __name__ == '__main__':
    test_reentry_signal_m_cross()
    test_two_stock_lock()
    test_reentry_execution_flow()
    test_early_sell_prevention()
    print("\n🎉 모든 단위/통합 테스트 (2종목 락인 + 매도 후 하락 ➔ 재통과 재매수 + 조기 매도 방지) 100% 통과!")
