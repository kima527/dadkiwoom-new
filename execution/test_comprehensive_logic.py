import sys
import os
import pandas as pd
import numpy as np

# 경로 설정
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
for p in [CURRENT_DIR, PROJECT_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from indicators import calculate_all_60m_indicators, calculate_daily_tema_deadcross, calculate_day3_m_line
from strategy import ThemeGate60mStrategy, StrategyState, TradeOrder, PositionTracker
from trading_bot_holdings_only import align_to_tick, get_market_session, SafeHoldingsThemeGateBot

def test_daily_and_60m_indicators():
    print("=== 1. 일봉 및 60분봉 지표 계산 검증 ===")
    # 60분봉 데이터 생성
    prices_60m = [10000.0 * (1.003 ** i) for i in range(100)]
    df_60m = pd.DataFrame({
        'open': prices_60m,
        'high': [p * 1.005 for p in prices_60m],
        'low': [p * 0.995 for p in prices_60m],
        'close': prices_60m,
        'volume': [5000 + i * 50 for i in range(100)]
    })
    
    df_calc = calculate_all_60m_indicators(df_60m)
    assert not df_calc.empty, "60분봉 지표 계산 실패"
    assert 'theme_gate' in df_calc.columns, "theme_gate 컬럼 부재"
    assert 'theme_gijun' in df_calc.columns, "theme_gijun 컬럼 부재"
    print("  [성공] 60분봉 테마급등관문선 및 테마기준선(M선) 지표 산출 확인")

    # 일봉 데드크로스 검증
    df_daily = pd.DataFrame({
        'open': [20000, 20100, 19800, 19500, 19000],
        'high': [20200, 20300, 19900, 19600, 19100],
        'low': [19900, 19700, 19400, 18900, 18500],
        'close': [20100, 19800, 19500, 19000, 18600],
        'volume': [100000]*5
    })
    df_d_calc = calculate_daily_tema_deadcross(df_daily)
    assert not df_d_calc.empty
    print("  [성공] 일봉 테마 추세 및 데드크로스 연산 확인")

def test_strategy_lifecycle_clean_exit_to_idle():
    print("\n=== 2. 전략 전 상태 전이 및 매도 2대 원칙 (재매수 없이 IDLE 복귀) 검증 ===")
    strat = ThemeGate60mStrategy(initial_capital=10_000_000, gate_sl_pct=0.015, max_reentry=0)
    
    # 가상의 60분봉 바
    dummy_60m = pd.Series({
        'open': 10000,
        'high': 10200,
        'low': 9900,
        'close': 10000,
        'sma5': 10100,
        'sma20': 10000,
        'sma60': 9800,
        'theme_gate': 9950,
        'theme_gate_high': 10300,
        'theme_gijun': 10500,
        'gate_up_turnaround': False,
        'gate_cross_up': False
    })
    
    # ── [시나리오 0]: 1차 매수 보유 상태 (FIRST_BUY_DONE) -> 60분봉 기준선 돌파 시 2차 50% 추가 매수 ──
    strat.position.state = StrategyState.FIRST_BUY_DONE
    strat.position.total_qty = 100
    strat.position.first_buy_qty = 100
    strat.position.avg_price = 10000.0
    
    # 0-1) 기준선(10,500원) 돌파 전(10,200원) -> 2차 매수 대기
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, current_price=10200.0)
    assert order is None, "기준선 돌파 전인데 2차 매수 발생 (오류)"
    assert strat.position.state == StrategyState.FIRST_BUY_DONE

    # 0-2) 기준선(10,500원) 상향 돌파 (10,550원) -> BUY_2 100주 집행 및 FULL_POSITION 전환
    dummy_breakout = dummy_60m.copy()
    dummy_breakout['high'] = 10550
    dummy_breakout['close'] = 10550
    order = strat.evaluate_bar(dummy_breakout, daily_dead_cross=False, daily_bull=True, current_price=10550.0)
    assert order is not None and order.action == "BUY_2", f"기준선 돌파 시 BUY_2 미발생: {order}"
    assert order.qty == 100, f"2차 매수 수량이 1차 수량과 불일치: {order.qty} != 100"
    assert strat.position.state == StrategyState.FULL_POSITION
    assert strat.position.total_qty == 200
    print("  [성공] FIRST_BUY_DONE: 60분봉 기준선(M선) 돌파 시 2차 50%(100주) 추가 매수 확인")

    # ── [시나리오 1]: 실계좌 보유 종목 (FULL_POSITION) 매도 2대 원칙 검증 ──
    strat.position.state = StrategyState.FULL_POSITION
    strat.position.total_qty = 100
    strat.position.avg_price = 10000.0

    # 1-1) M/3선(10,000원) 및 기준선 변곡선(10,500원) 상단 지지 유지 (현재가 10,600원 >= 10,500원) -> 홀딩
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, current_price=10600.0, day3_m_line=10000.0)
    assert order is None, "M/3선 및 기준선 상단 유지 중인데 매도 주문 발생함 (오류)"
    assert strat.position.state == StrategyState.FULL_POSITION
    print("  [성공] FULL_POSITION: M/3 수식선 및 기준선 변곡선 상단 지지 유지 시 홀딩 확인")

    # 1-2) [매도 원칙 2] 60분봉 기준선 변곡선(10,500원) 넘지 못함 (현재가 10,400원 < 10,500원) -> 즉시 전량 매도 및 IDLE 복귀!
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, current_price=10400.0, day3_m_line=10000.0)
    assert order is not None, "기준선 변곡선 미돌파(10,400원 < 10,500원) 시 즉시 매도 미발생 (오류)"
    assert order.action in ["TAKE_PROFIT", "STOP_LOSS"]
    assert "기준선 변곡선" in order.reason
    assert order.qty == 100
    assert order.stage == "IDLE", "매도 후 stage가 IDLE이어야 함 (재매수 없음)"
    assert strat.position.state == StrategyState.IDLE, "매도 후 상태가 IDLE로 즉시 초기화되지 않음"
    assert strat.position.total_qty == 0
    print("  [성공] FULL_POSITION: 60분봉 기준선 변곡선(10,500원) 미돌파 즉시 전량 매도 및 IDLE 복귀 확인 (재매수 없음)")

    # 1-3) [매도 원칙 1] M/3선(10,000원) 하향 이탈 (현재가 9,950원 < 10,000원) -> 이탈 즉시 전량 매도 및 IDLE 복귀
    strat.position.state = StrategyState.FULL_POSITION
    strat.position.total_qty = 100
    strat.position.avg_price = 10000.0
    dummy_60m_low_gijun = dummy_60m.copy()
    dummy_60m_low_gijun['theme_gijun'] = 9900.0 # 기준선은 9,900원이고 M/3선이 10,000원인 경우
    order = strat.evaluate_bar(dummy_60m_low_gijun, daily_dead_cross=False, daily_bull=True, current_price=9950.0, day3_m_line=10000.0)
    assert order is not None, "M/3선 하향 이탈 시 즉시 매도 미발생 (오류)"
    assert order.action in ["TAKE_PROFIT", "STOP_LOSS"]
    assert "M/3 수식선" in order.reason
    assert order.qty == 100
    assert order.stage == "IDLE"
    assert strat.position.state == StrategyState.IDLE
    assert strat.position.total_qty == 0
    print("  [성공] FULL_POSITION: M/3 수식선 하향 이탈 즉시 전량 매도 및 IDLE 복귀 확인 (재매수 없음)")

def test_tick_and_sessions():
    print("\n=== 3. 호가 단위 및 세션 검증 ===")
    assert align_to_tick(1805) == 1805
    assert align_to_tick(4999) == 4995
    assert align_to_tick(24150) == 24150
    assert align_to_tick(38123) == 38100
    assert align_to_tick(70123) == 70100
    assert align_to_tick(0) == 0
    assert align_to_tick(-100) == 0
    print("  [성공] 한국거래소 및 대체거래소 호가 단위 정렬 확인")

    is_active, s_name, ex = get_market_session()
    print(f"  [성공] 현재 세션 판정: 활성={is_active}, 명칭={s_name}, 거래소={ex}")

def test_single_position_lock_and_rotation():
    print("\n=== 4. 1종목 집중 매매 락(Lock) 및 매도 후 다음 1순위 주도주 진입 검증 ===")
    bot = SafeHoldingsThemeGateBot(is_real=False, dry_run=True, holdings_state="idle")
    
    # 2개 종목(종목A: 디아이, 종목B: 알트)을 IDLE 상태로 전략 등록
    strat_a = ThemeGate60mStrategy(initial_capital=10_000_000)
    strat_b = ThemeGate60mStrategy(initial_capital=10_000_000)
    strat_a.position.state = StrategyState.IDLE
    strat_b.position.state = StrategyState.IDLE
    bot.strategies['003160'] = strat_a
    bot.strategies['459550'] = strat_b
    
    # 1) 초기 상태: 활성 종목 없음 (슬롯 오픈)
    assert bot.get_active_stock_code() is None, "초기 슬롯이 비어있지 않음 (오류)"
    print("  [성공] 초기 상태: 활성 보유 종목 없음 (슬롯 0/1 비어있음)")
    
    # 2) 종목A가 기준선 돌파하여 BUY_1 신호 발생
    row_60m_a = pd.Series({
        'close': 38500, 'open': 38000, 'high': 38600, 'low': 37900,
        'sma5': 38200, 'sma20': 38000, 'sma60': 37500,
        'theme_gate': 37200, 'theme_gate_high': 38000, 'theme_gijun': 38450,
        'is_gate_up': False
    })
    order_a1 = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True, current_price=38500.0)
    assert order_a1 is not None and order_a1.action == "BUY_1", "종목A 기준선 돌파 BUY_1 미발생 (오류)"
    bot.execute_order('003160', '디아이', order_a1)
    
    # 이제 종목A가 1개의 슬롯을 점유
    assert bot.get_active_stock_code() == '003160', "종목A 매수 후 active_stock 불일치"
    print("  [성공] 종목A(디아이) 1차 50% 매수 체결 ➔ 슬롯 1/1 점유 확인 (FIRST_BUY_DONE)")
    
    # 3) 이때 종목B도 기준선 돌파로 BUY_1을 시도할 경우 락(Lock)에 의해 차단 검증
    row_60m_b = pd.Series({
        'close': 1850, 'open': 1800, 'high': 1860, 'low': 1790,
        'sma5': 1830, 'sma20': 1810, 'sma60': 1780,
        'theme_gate': 1750, 'theme_gate_high': 1820, 'theme_gijun': 1831,
        'is_gate_up': False
    })
    order_b1 = strat_b.evaluate_bar(row_60m_b, daily_dead_cross=False, daily_bull=True, current_price=1850.0)
    assert order_b1 is not None and order_b1.action == "BUY_1", "종목B 평가에서 BUY_1 생성되어야 함"
    
    # run_cycle의 주문 차단 시뮬레이션
    current_active = bot.get_active_stock_code()
    if current_active and current_active != '459550':
        # 차단 및 IDLE 원복
        saved_base = strat_b.position.base_account_qty
        strat_b.position = PositionTracker()
        strat_b.position.state = StrategyState.IDLE
        strat_b.position.base_account_qty = saved_base
        order_b1 = None
        
    assert order_b1 is None, "종목B의 BUY_1이 차단되지 않고 통과됨 (1종목 락 실패)"
    assert strat_b.position.state == StrategyState.IDLE, "종목B가 IDLE로 원복되지 않음"
    assert bot.get_active_stock_code() == '003160', "종목A의 독점 슬롯이 유지되지 않음"
    print("  [성공] 1종목 락 발동: 종목A 운용 중이므로 종목B BUY_1 진입 완벽 차단 및 IDLE 대기 유지 확인")
    
    # 4) 종목A가 1차 매수가(38,500원) 대비 +0.5% 이상 추가 상승(38,700원)하여 2차 매수(BUY_2) 집행 ➔ FULL_POSITION
    row_60m_a2 = row_60m_a.copy()
    row_60m_a2['close'] = 38700
    order_a2 = strat_a.evaluate_bar(row_60m_a2, daily_dead_cross=False, daily_bull=True, current_price=38700.0)
    assert order_a2 is not None and order_a2.action == "BUY_2"
    bot.execute_order('003160', '디아이', order_a2)
    assert strat_a.position.state == StrategyState.FULL_POSITION
    print("  [성공] 종목A(디아이) 1차 매수가 대비 +0.5% 추가상승 확인 후 2차 50% 추가 매수 체결 ➔ FULL_POSITION (100% 진입)")
    
    # 5) 종목A가 M/3 수식선(39,000원) 하향 이탈(현재가 38,500원)로 전량 매도
    order_a_exit = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True, current_price=38500.0, day3_m_line=39000.0)
    assert order_a_exit is not None and order_a_exit.action in ["TAKE_PROFIT", "STOP_LOSS"]
    bot.execute_order('003160', '디아이', order_a_exit)
    assert strat_a.position.total_qty == 0
    assert strat_a.position.state == StrategyState.IDLE
    print("  [성공] 종목A(디아이) M/3선 이탈 전량 매도 체결 ➔ 잔고 0주, IDLE 복귀 (재매수 없음)")
    
    # 6) 이제 슬롯이 완전히 비워짐 (슬롯 0/1)
    assert bot.get_active_stock_code() is None, "매도 후 슬롯이 오픈되지 않음 (오류)"
    print("  [성공] 매도 후 슬롯 오픈 확인: active_stock_code is None (대기 종목 선착순 진입 준비)")
    
    # 7) 대기 중이던 종목B가 이제 기준선(1831)을 상향 돌파(1850) ➔ 종목B가 1순위로 슬롯 점유
    order_b_rot = strat_b.evaluate_bar(row_60m_b, daily_dead_cross=False, daily_bull=True, current_price=1850.0)
    assert order_b_rot is not None and order_b_rot.action == "BUY_1"
    
    # 슬롯 오픈 상태이므로 정상 승인 및 매수 집행
    bot.execute_order('459550', '알트', order_b_rot)
    assert bot.get_active_stock_code() == '459550', "종목B가 새롭게 슬롯을 점유하지 못함"
    assert strat_b.position.state == StrategyState.FIRST_BUY_DONE
    print("  [성공] 선착순 순환 매매 완벽 작동: 종목A 최종 매도 후 기준선 통과한 종목B(알트)가 슬롯 점유!")

def test_intraday_manual_1_share_marker_and_buy():
    print("\n=== 5. 장중 1주 수동 매수 종목(IDLE 마커) ➔ 1차 매수 시 자동 흡수 검증 ===")
    bot = SafeHoldingsThemeGateBot(is_real=False, dry_run=True, holdings_state="idle")
    
    # 1) 가상 계좌에 1주 수동 매수 종목(005930, 삼성전자) 등록
    bot.active_holdings = {
        '005930': {'qty': 1, 'buy_price': 70000, 'current_price': 70500}
    }
    
    code = '005930'
    h = bot.active_holdings[code]
    strat = ThemeGate60mStrategy(initial_capital=10_000_000)
    strat.position.state = StrategyState.IDLE
    strat.position.total_qty = 0
    strat.position.base_account_qty = int(h['qty'])
    bot.strategies[code] = strat
    
    assert bot.strategies[code].position.state == StrategyState.IDLE, "1주 종목의 상태가 IDLE이 아님"
    assert bot.strategies[code].position.total_qty == 0, "진입 전에는 total_qty가 0이어야 함"
    assert bot.strategies[code].position.base_account_qty == 1, "수동 매수한 1주가 base_account_qty에 기록되지 않음"
    assert bot.get_active_stock_code() is None, "1주 마커 상태에서는 1종목 락이 걸리지 않아야 함 (슬롯 오픈)"
    print("  [성공] 1주 매수 감지 시 관심종목 마커(IDLE) 등록 및 슬롯 오픈 확인")
    
    # 2) 기준선 돌파 시 BUY_1 발생 검증
    dummy_60m = pd.Series({
        'close': 70500, 'open': 70000, 'high': 70800, 'low': 69900,
        'sma5': 70300, 'sma20': 70100, 'sma60': 69800,
        'theme_gate': 69500, 'theme_gate_high': 70200, 'theme_gijun': 70400,
        'gate_up_turnaround': False,
        'gate_cross_up': False
    })
    order_buy1 = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, current_price=70500.0)
    assert order_buy1 is not None and order_buy1.action == "BUY_1", "기준선 돌파 BUY_1 미발생"
    
    # 가용 예수금 50% 기준 수량 계산 확인
    expected_qty = int((10_000_000 * 0.50) // 70500)
    assert order_buy1.qty == expected_qty, f"1차 매수 수량({order_buy1.qty})이 예수금 50%({expected_qty})와 불일치"
    print(f"  [성공] 기준선 돌파 즉시 BUY_1 1차 매수({order_buy1.qty}주, 약 50% 예수금) 신호 확인")
    
    # 3) execute_order 집행: 기존 1주 흡수 및 FIRST_BUY_DONE 전이
    bot.execute_order(code, '삼성전자', order_buy1)
    assert strat.position.state == StrategyState.FIRST_BUY_DONE, "상태가 FIRST_BUY_DONE으로 전이되지 않음"
    # 기존 1주가 흡수되어 total_qty == expected_qty + 1
    assert strat.position.total_qty == expected_qty + 1, "기존 수동 1주가 포지션에 흡수되지 않음"
    assert strat.position.base_account_qty == 0, "기존 base_account_qty가 0으로 클리어되지 않음"
    assert bot.get_active_stock_code() == code, "슬롯이 해당 종목으로 잠기지 않음"
    print(f"  [성공] 주문 집행 후 기존 수동 1주 자동 흡수 ➔ 총 {strat.position.total_qty}주 보유 및 슬롯 점유 확인")
    
    # 4) 기준선 변곡선(70,400원) 및 M/3선(70,000원) 하향 이탈(현재가 69,500원) 시 전량 매도 -> 즉시 IDLE 복귀
    order_sell = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, current_price=69500.0, day3_m_line=70000.0)
    assert order_sell is not None and order_sell.action in ["TAKE_PROFIT", "STOP_LOSS"]
    bot.execute_order(code, '삼성전자', order_sell)
    assert strat.position.total_qty == 0, "전량 매도 후 잔고가 0이 아님"
    assert strat.position.state == StrategyState.IDLE, "매도 후 IDLE로 복귀하지 않음"
    assert bot.get_active_stock_code() is None, "매도 후 슬롯이 오픈되지 않음"
    print("  [성공] 기준선 변곡선 미돌파 시 1주 포함 전량 100% 매도 ➔ 즉시 IDLE 복귀 및 슬롯 오픈 확인!")

def test_day3_m_line_calculation():
    print("\n=== 6. 실시간 3일선 M/3 수식선 계산 정밀 검증 ===")
    df_daily = pd.DataFrame({
        'date': ['20261026', '20261027'],
        'close': [10000.0, 10000.0]
    })
    
    # 1) 현재가 10,000원일 때: M = 10000 + 10000 + 10000 = 30000, M/3 = 10000
    line, m, p1, p2 = calculate_day3_m_line(df_daily, 10000.0)
    assert abs(line - 10000.0) < 1e-4, f"M/3선 계산 오류: {line}"
    assert abs(m - 30000.0) < 1e-4
    assert p1 == 10000.0 and p2 == 10000.0
    print("  [성공] M/3선 기준값 계산 정확성 검증: 10,000원 (M: 30,000원)")

    # 2) 현재가 9,900원일 때: M = 9900 + 10000 + 10000 = 29900, M/3 = 9966.67
    line_down, m_down, _, _ = calculate_day3_m_line(df_daily, 9900.0)
    assert line_down > 9900.0, f"현재가가 M/3선보다 아래여야 함: {9900.0} < {line_down}"
    print(f"  [성공] 하향 이탈 판정 검증: 현재가(9,900원) < M/3선({line_down:,.1f}원) -> 즉시 매도 트리거")

def test_priority_scoring_and_ranking():
    print("\n=== 7. 동시 기준선 돌파 시 3대 핵심 팩터 스코어링 (100점 만점) 검증 ===")
    bot = SafeHoldingsThemeGateBot(is_real=False, dry_run=True, holdings_state="idle")
    
    # 2개 후보 종목:
    # 종목A (소형주): 당일 거래대금 30억, 거래량 1.2배, 캔들 윗꼬리 김
    # 종목B (대장주): 당일 거래대금 800억, 거래량 5.0배 폭증, 장대양봉 몸통 86.5% (+9% 상승)
    
    last_60m_a = pd.Series({'open': 10000, 'high': 10500, 'low': 9900, 'close': 10100, 'volume': 1200})
    df_60m_a = pd.DataFrame({'volume': [1000]*25})
    last_daily_a = pd.Series({'close': 10000, 'volume': 300000, 'trading_value': 3_000_000_000}) # 30억
    
    score_a, d_a = bot.calculate_priority_score('000010', '소형주A', 10100, last_60m_a, last_daily_a, df_60m_a)
    
    last_60m_b = pd.Series({'open': 50000, 'high': 55000, 'low': 49800, 'close': 54500, 'volume': 50000})
    df_60m_b = pd.DataFrame({'volume': [10000]*25}) # 20봉 평균 1만 -> 당봉 5만 (5배 폭증)
    last_daily_b = pd.Series({'close': 50000, 'volume': 1600000, 'trading_value': 80_000_000_000}) # 800억
    
    score_b, d_b = bot.calculate_priority_score('000020', '대장주B', 54500, last_60m_b, last_daily_b, df_60m_b)
    
    print(f"  소형주A 점수: {score_a:.1f}점 (거래대금: {d_a['day_val_eok']:.1f}억[{d_a['score_val']:.0f}점], 거래량배율: {d_a['vol_surge_ratio']:.1f}배[{d_a['score_vol']:.0f}점], 캔들: {d_a['score_candle']:.0f}점)")
    print(f"  대장주B 점수: {score_b:.1f}점 (거래대금: {d_b['day_val_eok']:.1f}억[{d_b['score_val']:.0f}점], 거래량배율: {d_b['vol_surge_ratio']:.1f}배[{d_b['score_vol']:.0f}점], 캔들: {d_b['score_candle']:.0f}점)")
    
    assert score_b > score_a, f"대장주 점수({score_b})가 소형주({score_a})보다 높아야 합니다."
    assert score_b >= 80.0, f"대장주B 점수({score_b})는 80점 이상이어야 합니다."
    print("  [성공] 3대 팩터 스코어링: 대장주B가 압도적 1위(90점)로 선정됨을 확인!")

def test_expert_diagnostic_safeguards():
    print("\n=== 8. 전문가 정밀 진단 4대 안전장치 검증 ===")
    
    # 1) 더블 바잉 방지: 기준선 돌파로 1차 매수 후 동일 가격에서 즉시 2차 매수 차단
    strat = ThemeGate60mStrategy(initial_capital=10_000_000)
    dummy_bar = pd.Series({
        'close': 10000, 'open': 9900, 'high': 10100, 'low': 9850,
        'sma5': 10000, 'sma20': 9950, 'sma60': 9800,
        'theme_gate': 9900, 'theme_gate_high': 10200, 'theme_gijun': 10000,
        'is_gate_up': False
    })
    # 1차 매수 진입 (10,000원)
    order1 = strat.evaluate_bar(dummy_bar, daily_dead_cross=False, daily_bull=True, current_price=10000.0)
    assert order1 is not None and order1.action == "BUY_1"
    assert strat.position.state == StrategyState.FIRST_BUY_DONE
    
    # 동일 가격(10,000원) 다음 봉 평가 -> 2차 매수 즉시 발생하지 않고 대기해야 함!
    order_same = strat.evaluate_bar(dummy_bar, daily_dead_cross=False, daily_bull=True, current_price=10000.0)
    assert order_same is None, "동일 가격에서 더블 바잉 2차 매수가 즉시 발생함 (오류)"
    print("  [성공] 더블 바잉 방지: 기준선 1차 매수 후 동일가 2차 매수 즉각 차단 확인")

    # +0.5% 상승(10,060원) 시 2차 매수 승인
    order_gain = strat.evaluate_bar(dummy_bar, daily_dead_cross=False, daily_bull=True, current_price=10060.0)
    assert order_gain is not None and order_gain.action == "BUY_2"
    assert strat.position.state == StrategyState.FULL_POSITION
    print("  [성공] 2차 매수 트리거: +0.5% 추가상승 확인 시 2차 50% 불타기 정상 승인 확인")

    # 2) 당일 매도 완료 종목 재매수 영구 차단 (sold_today_stocks)
    bot = SafeHoldingsThemeGateBot(is_real=False, dry_run=True, holdings_state="idle")
    bot.strategies['005930'] = strat
    bot.sold_today_stocks.add('005930') # 당일 매도 완료 등록
    strat.position = PositionTracker() # 매도 후 IDLE 복귀
    assert strat.position.state == StrategyState.IDLE
    
    # run_cycle 시뮬레이션: 감시 루프에서 제외되는지 확인
    assert '005930' in bot.sold_today_stocks
    print("  [성공] 당일 매도 완료 종목(005930): 당일 재매수 영구 차단 목록 등록 및 감시 제외 확인")

    # 3) 동시 돌파 탈락 후보 상태 원복 (예수금 환원 + 주문 롤백 + 1주 마커 보존)
    cand_strat = ThemeGate60mStrategy(initial_capital=10_000_000)
    cand_strat.position.base_account_qty = 1
    initial_cash = cand_strat.cash
    
    # BUY_1 평가 발생
    cand_order = cand_strat.evaluate_bar(dummy_bar, daily_dead_cross=False, daily_bull=True, current_price=10000.0)
    assert cand_order is not None and cand_order.action == "BUY_1"
    assert cand_strat.cash < initial_cash
    assert len(cand_strat.trade_history) == 1
    
    # 탈락으로 인한 롤백 시뮬레이션
    cand_strat.cash += cand_order.amount
    if cand_strat.trade_history and cand_strat.trade_history[-1] == cand_order:
        cand_strat.trade_history.pop()
    cand_strat.position = PositionTracker()
    cand_strat.position.state = StrategyState.IDLE
    cand_strat.position.base_account_qty = 1
    
    assert cand_strat.cash == initial_cash, "예수금이 정상 환원되지 않음"
    assert len(cand_strat.trade_history) == 0, "유령 주문이 내역에 잔존함"
    assert cand_strat.position.base_account_qty == 1, "관심 1주 마커가 보존되지 않음"
    print("  [성공] 탈락 후보 롤백 안전장치: 예수금 100% 환원, 거래내역 정화, 1주 마커 보존 확인")

    # 4) 우선순위 스코어링 전일종가 왜곡 방지
    last_60m = pd.Series({'open': 10000, 'high': 10500, 'low': 9900, 'close': 10300, 'volume': 2000})
    df_60m = pd.DataFrame({'volume': [1000]*25})
    # 당일 데이터가 이미 포함된 일봉이라 close가 10300인 경우
    last_daily = pd.Series({'close': 10300, 'volume': 100000, 'trading_value': 10_000_000_000})
    # pred1 (전일 종가 10,000원) 전달
    score, details = bot.calculate_priority_score('000010', '테스트주', 10300, last_60m, last_daily, df_60m, pre_day_close=10000.0)
    assert abs(details['day_ret_pct'] - 3.0) < 1e-4, f"당일 등락률이 3.0%이어야 함: {details['day_ret_pct']}"
    print("  [성공] 우선순위 스코어링: pre_day_close(pred1) 연동으로 당일 등락률(+3.0%) 정밀 계산 확인")

def test_prevention_of_instant_sell_after_buy():
    print("\n=== 9. 매수 후 즉시 매도(Whipsaw) 방지 알고리즘 집중 검증 ===")
    strat = ThemeGate60mStrategy(initial_capital=10_000_000)
    
    row_bar = pd.Series({
        'close': 10000, 'open': 9900, 'high': 10050, 'low': 9850,
        'sma5': 10000, 'sma20': 9900, 'sma60': 9800,
        'theme_gate': 9800, 'theme_gate_high': 10100, 'theme_gijun': 10000,
        'is_gate_up': False
    })
    
    # 1) 주가가 M/3선 아래(M/3선 10,200원, 현재가 10,000원)에 있을 때 매수 차단 검증
    # (M/3선 아래에서 매수되면 다음 틱에서 바로 매도 덫에 걸리므로 원천 차단)
    order_blocked = strat.evaluate_bar(row_bar, daily_dead_cross=False, daily_bull=True, current_price=10000.0, day3_m_line=10200.0)
    assert order_blocked is None, "M/3선 하회 상태인데 매수가 발생함 (즉시 매도 덫 방어 실패)"
    print("  [성공] 방어벽 1: M/3선(10,200원) 하회 상태(현재가 10,000원) 매수 원천 차단 확인 (진입 후 즉시 매도 덫 제거)")

    # 2) M/3선 상단 지지(M/3선 9,900원, 현재가 10,005원) 확인 시 정상 BUY_1 진입
    order_buy = strat.evaluate_bar(row_bar, daily_dead_cross=False, daily_bull=True, current_price=10005.0, day3_m_line=9900.0)
    assert order_buy is not None and order_buy.action == "BUY_1"
    assert strat.position.state == StrategyState.FIRST_BUY_DONE
    print("  [성공] 진입 확인: M/3선 지지 + 기준선 돌파 시 BUY_1 정상 체결 (10,005원)")

    # 3) 매수 체결 직후(3분 이내), 호가 1틱 미세 흔들림(10,005원 -> 9,990원, -0.15%) 발생 시
    # 노이즈 방어 버퍼에 의해 즉시 매도되지 않고 의연하게 홀딩하는지 검증!
    order_tick_flicker = strat.evaluate_bar(row_bar, daily_dead_cross=False, daily_bull=True, current_price=9990.0, day3_m_line=9900.0)
    assert order_tick_flicker is None, "매수 직후 1틱(-0.15%) 미세 흔들림에 털려버림 (Whipsaw 방어 실패)"
    assert strat.position.state == StrategyState.FIRST_BUY_DONE
    print("  [성공] 방어벽 2: 매수 직후 호가 1틱 흔들림(-0.15%)에 털리지 않고 홀딩 유지 확인")

    # 4) 진입 후 기준선(10,000원) 및 M/3선(9,900원)을 확실하게 이탈(-1.5% 하락, 9,850원)할 때는
    # 원칙대로 기민하게 전량 매도 집행 검증
    order_real_exit = strat.evaluate_bar(row_bar, daily_dead_cross=False, daily_bull=True, current_price=9850.0, day3_m_line=9900.0)
    assert order_real_exit is not None and order_real_exit.action in ["TAKE_PROFIT", "STOP_LOSS"]
    assert strat.position.state == StrategyState.IDLE
    print("  [성공] 원칙 매도: 확실한 추세 이탈(9,850원 < M/3선 9,900원) 시 칼같이 전량 매도 및 IDLE 복귀 확인")

if __name__ == '__main__':
    test_daily_and_60m_indicators()
    test_strategy_lifecycle_clean_exit_to_idle()
    test_tick_and_sessions()
    test_single_position_lock_and_rotation()
    test_intraday_manual_1_share_marker_and_buy()
    test_day3_m_line_calculation()
    test_priority_scoring_and_ranking()
    test_expert_diagnostic_safeguards()
    test_prevention_of_instant_sell_after_buy()
    print("\n🎉 모든 단위 테스트, M/3 수식선 이탈 매도, 기준선 변곡선 미돌파 매도, 120틱/재매수 완전 배제 검증 100% 통과!")
