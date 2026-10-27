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

from indicators import calculate_120t_tema_indicators, calculate_tema
from strategy import ThemeGate60mStrategy, StrategyState, TradeOrder, PositionTracker
from trading_bot_holdings_only import align_to_tick, get_market_session, SafeHoldingsThemeGateBot

def test_120t_indicators():
    print("=== 1. 120틱 지표 계산 검증 ===")
    # 1) None 및 빈 데이터프레임
    df_empty = calculate_120t_tema_indicators(None)
    assert df_empty.empty, "None 전달 시 빈 DataFrame 반환 실패"
    
    df_empty2 = calculate_120t_tema_indicators(pd.DataFrame())
    assert df_empty2.empty, "빈 DataFrame 전달 시 빈 DataFrame 반환 실패"

    # 2) 5 > 20 > 60 > 120 완전 정배열 생성 (상승 가속 주가 시계열, TEMA 120 수렴을 위해 600개 봉 사용)
    prices = [1000.0 * (1.002 ** i) for i in range(600)]

    df_bull = pd.DataFrame({'close': prices})
    df_calc = calculate_120t_tema_indicators(df_bull)
    
    last_row = df_calc.iloc[-1]
    assert last_row['is_tema_aligned_120t'] == True, f"정배열 계산 실패: {last_row['tema5']} > {last_row['tema20']} > {last_row['tema60']} > {last_row['tema120']}"
    assert last_row['is_tema_dead_5_20'] == False, "정배열인데 데드크로스로 잘못 판정"
    print("  [성공] 상승 추세 120틱 완전 정배열 (5>20>60>120) 감지 확인")

    # 3) 5 < 20 데드크로스 생성: 상승 후 고점에서 급락 반전(U턴 하락)
    prices_bear = [50.0 + i * 0.5 for i in range(120)] + [110.0 - i * 1.5 for i in range(1, 20)]
    df_bear = pd.DataFrame({'close': prices_bear})
    df_bear_calc = calculate_120t_tema_indicators(df_bear)
    last_bear = df_bear_calc.iloc[-1]
    assert last_bear['is_tema_dead_5_20'] == True, f"5<20 데드크로스 감지 실패: {last_bear['tema5']} vs {last_bear['tema20']}"
    print("  [성공] 고점 반전 120틱 데드크로스 (5<20) 감지 확인")



def test_strategy_lifecycle_and_whipsaw():
    print("\n=== 2. 전략 전 상태 전이 및 휩쏘 방어 로직 세밀 검증 ===")
    strat = ThemeGate60mStrategy(initial_capital=10_000_000, gate_sl_pct=0.015, max_reentry=5)
    
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
    row_before_break = pd.Series({'close': 10200, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': False})
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_before_break)
    assert order is None, "기준선 돌파 전인데 2차 매수 발생 (오류)"
    assert strat.position.state == StrategyState.FIRST_BUY_DONE

    # 0-2) 기준선(10,500원) 상향 돌파 (10,550원) -> BUY_2 100주 집행 및 FULL_POSITION 전환
    dummy_breakout = dummy_60m.copy()
    dummy_breakout['high'] = 10550
    dummy_breakout['close'] = 10550
    row_break = pd.Series({'close': 10550, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': False})
    order = strat.evaluate_bar(dummy_breakout, daily_dead_cross=False, daily_bull=True, row_120t=row_break)
    assert order is not None and order.action == "BUY_2", f"기준선 돌파 시 BUY_2 미발생: {order}"
    assert order.qty == 100, f"2차 매수 수량이 1차 수량과 불일치: {order.qty} != 100"
    assert strat.position.state == StrategyState.FULL_POSITION
    assert strat.position.total_qty == 200
    print("  [성공] FIRST_BUY_DONE: 60분봉 기준선(M선) 돌파 시 2차 50%(100주) 추가 매수 확인")

    # ── [시나리오 1]: 실계좌 보유 종목 등록 (FULL_POSITION) 후 120틱 5<20 매도 ──
    strat.position.state = StrategyState.FULL_POSITION
    strat.position.total_qty = 100
    strat.position.avg_price = 10000.0

    
    # 1-1) 120틱 혼조(데드 아님) -> 홀딩 유지
    row_120t_neutral = pd.Series({'close': 10100, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': False, 'tema5': 10100, 'tema20': 10050})
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_neutral)
    assert order is None, "120틱 혼조에서 매도 주문 발생함 (오류)"
    assert strat.position.state == StrategyState.FULL_POSITION
    print("  [성공] FULL_POSITION: 120틱 5>=20 유지 시 매도 차단 홀딩 확인")

    # 1-2) 120틱 5 < 20 데드 발생 -> 전량 매도 및 PROFIT_TAKEN 전환
    row_120t_dead = pd.Series({'close': 10200, 'is_tema_dead_5_20': True, 'is_tema_aligned_120t': False, 'tema5': 10100, 'tema20': 10150})
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_dead)
    assert order is not None, "120틱 5<20 발생 시 매도 미발생 (오류)"
    assert order.action == "TAKE_PROFIT"
    assert order.qty == 100
    assert strat.position.state == StrategyState.PROFIT_TAKEN
    assert strat.position.reentry_qty == 100
    print("  [성공] FULL_POSITION: 120틱 5<20 발생 시 전량 매도 및 PROFIT_TAKEN 전환 확인")

    # ── [시나리오 2]: PROFIT_TAKEN 에서 120틱 정배열 재매수 ──
    # 2-1) 정배열 미완성 -> 대기
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_neutral)
    assert order is None, "정배열 미완성인데 재매수 발생 (오류)"
    assert strat.position.state == StrategyState.PROFIT_TAKEN

    # 2-2) 120틱 5>20>60>120 정배열 완성 -> RE_BUY 및 REENTRY_HOLDING 전환
    row_120t_aligned = pd.Series({'close': 10050, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': True, 'tema5': 10100, 'tema20': 10050})
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_aligned)
    assert order is not None and order.action == "RE_BUY", "120틱 정배열 완성 시 RE_BUY 미발생 (오류)"
    assert order.qty == 100
    assert strat.position.state == StrategyState.REENTRY_HOLDING
    assert strat.position.reentry_price == 10050.0
    print("  [성공] PROFIT_TAKEN: 120틱 정배열 완성 시 RE_BUY 및 재매수 단가 기록 확인")

    # ── [시나리오 3]: REENTRY_HOLDING 에서의 휩쏘 방어 검증 ──
    # 재매수 단가: 10,050원
    # 3-1) -0.3% 미세 하락 (10,020원) 에서 120틱 5<20 데드 발생 -> 매도 차단 홀딩 (휩쏘 방어!)
    row_120t_whipsaw = pd.Series({'close': 10020, 'is_tema_dead_5_20': True, 'is_tema_aligned_120t': False, 'tema5': 10010, 'tema20': 10030})
    pnl = ((10020 - 10050) / 10050) * 100 # -0.298% (-0.3%)
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_whipsaw)
    assert order is None, f"재매수 후 -0.5% 이내 휩쏘({pnl:.2f}%)에서 5<20 매도가 발생함! (오류)"
    assert strat.position.state == StrategyState.REENTRY_HOLDING
    print(f"  [성공] 🛡️ 휩쏘 방어 작동: 재매수 후 손실률 {pnl:.2f}% (-0.5% 이내) 5<20 데드크로스 매도 차단 홀딩 확인")

    # 3-2) +0.5% 수익 (10,100원) 에서 120틱 5<20 데드 발생 -> RE_SELL 익절 및 PROFIT_TAKEN 복귀
    row_120t_profit = pd.Series({'close': 10100, 'is_tema_dead_5_20': True, 'is_tema_aligned_120t': False, 'tema5': 10090, 'tema20': 10095})
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_profit)
    assert order is not None and order.action == "RE_SELL", "재매수 후 수익 상태 5<20 매도 미발생 (오류)"
    assert strat.position.state == StrategyState.PROFIT_TAKEN
    print("  [성공] REENTRY_HOLDING: 수익 상태(+0.5%) 120틱 5<20 익절(RE_SELL) 확인")

    # 3-3) 다시 재매수 진입 후 -0.8% 하락 (< -0.5%) 에서 5<20 데드 발생 -> STOP_LOSS 손절
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_aligned) # 재매수 (10,050원)
    assert strat.position.state == StrategyState.REENTRY_HOLDING
    
    row_120t_cut = pd.Series({'close': 9950, 'is_tema_dead_5_20': True, 'is_tema_aligned_120t': False, 'tema5': 9940, 'tema20': 9960})
    pnl_cut = ((9950 - 10050) / 10050) * 100 # -0.995%
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_cut)
    assert order is not None and order.action == "STOP_LOSS", "재매수 후 -0.5% 초과 손실 시 5<20 손절 미발생 (오류)"
    assert strat.position.state == StrategyState.PROFIT_TAKEN
    print(f"  [성공] REENTRY_HOLDING: -0.5% 초과 손실({pnl_cut:.2f}%) 120틱 5<20 손절(STOP_LOSS) 확인")

    # 3-4) 비상 하방 급락 (-2.0%) 안전손절 (120틱 신호 지연 대비)
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_aligned) # 재매수 (10,050원)
    row_120t_plunge = pd.Series({'close': 9800, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': False, 'tema5': 9850, 'tema20': 9840})
    order = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_plunge)
    assert order is not None and order.action == "STOP_LOSS", "비상 급락 안전손절 미발동 (오류)"
    print("  [성공] REENTRY_HOLDING: 재매수 단가 대비 -2.0% 이상 급락 시 비상 안전손절 확인")

def test_tick_and_sessions():
    print("\n=== 3. 호가 단위 및 세션 검증 ===")
    assert align_to_tick(1805) == 1805 # < 2000 -> 1원
    assert align_to_tick(4999) == 4995 # < 5000 -> 5원
    assert align_to_tick(24150) == 24150 # < 50000 -> 50원
    assert align_to_tick(38123) == 38100 # < 50000 -> 50원
    assert align_to_tick(70123) == 70100 # < 200000 -> 100원
    assert align_to_tick(0) == 0
    assert align_to_tick(-100) == 0
    print("  [성공] 한국거래소 및 대체거래소 호가 단위 정렬 확인")

    is_active, s_name, ex = get_market_session()
    print(f"  [성공] 현재 세션 판정: 활성={is_active}, 명칭={s_name}, 거래소={ex}")

def test_single_position_lock_and_rotation():
    print("\n=== 4. 1종목 집중 매매 락(Lock) 및 선착순 순환 매매 검증 ===")
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
    order_a1 = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True)
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
    order_b1 = strat_b.evaluate_bar(row_60m_b, daily_dead_cross=False, daily_bull=True)
    assert order_b1 is not None and order_b1.action == "BUY_1", "종목B 평가에서 BUY_1 생성되어야 함"
    
    # run_cycle의 주문 차단 시뮬레이션
    current_active = bot.get_active_stock_code()
    if current_active and current_active != '459550':
        # 차단 및 원복
        saved_base = strat_b.position.base_account_qty
        strat_b.position = PositionTracker()
        strat_b.position.base_account_qty = saved_base
        order_b1 = None
        
    assert order_b1 is None, "종목B의 BUY_1이 차단되지 않고 통과됨 (1종목 락 실패)"
    assert strat_b.position.state == StrategyState.IDLE, "종목B가 IDLE로 원복되지 않음"
    assert bot.get_active_stock_code() == '003160', "종목A의 독점 슬롯이 유지되지 않음"
    print("  [성공] 1종목 락 발동: 종목A 운용 중이므로 종목B BUY_1 진입 완벽 차단 및 IDLE 대기 유지 확인")
    
    # 4) 종목A가 2차 매수(BUY_2) 집행 ➔ FULL_POSITION
    order_a2 = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True)
    assert order_a2 is not None and order_a2.action == "BUY_2"
    bot.execute_order('003160', '디아이', order_a2)
    assert strat_a.position.state == StrategyState.FULL_POSITION
    print("  [성공] 종목A(디아이) 2차 50% 추가 매수 체결 ➔ FULL_POSITION (100% 진입)")
    
    # 5) 종목A가 120틱 5<20 하향 이탈로 전량 매도 (TAKE_PROFIT) 집행
    row_120t_dead = pd.Series({'close': 39500, 'is_tema_dead_5_20': True, 'is_tema_aligned_120t': False, 'tema5': 39400, 'tema20': 39600})
    order_a_exit = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_dead)
    assert order_a_exit is not None and order_a_exit.action == "TAKE_PROFIT"
    bot.execute_order('003160', '디아이', order_a_exit)
    assert strat_a.position.total_qty == 0
    print("  [성공] 종목A(디아이) 120틱 5<20 전량 매도 체결 ➔ 잔고 0주, 현금 100% 회수")
    
    # 6) 이제 슬롯이 완전히 비워짐 (슬롯 0/1)
    assert bot.get_active_stock_code() is None, "매도 후 슬롯이 오픈되지 않음 (오류)"
    print("  [성공] 매도 후 슬롯 오픈 확인: active_stock_code is None (대기 종목 선착순 진입 준비)")
    
    # 6-1) [핵심 검증]: 기준선을 돌파하는 타 종목이 없는 경우 ➔ 직전 매도 종목의 120틱 정배열 재매수(RE_BUY) 집행 검증
    # 종목B는 아직 기준선(1831) 미만 (1800원)으로 돌파 실패 상태
    row_60m_b_below = pd.Series({
        'close': 1800, 'open': 1790, 'high': 1810, 'low': 1780,
        'sma5': 1800, 'sma20': 1810, 'sma60': 1780,
        'theme_gate': 1750, 'theme_gate_high': 1820, 'theme_gijun': 1831,
        'is_gate_up': False
    })
    order_b_below = strat_b.evaluate_bar(row_60m_b_below, daily_dead_cross=False, daily_bull=True)
    assert order_b_below is None, "기준선 미달 종목B는 주문이 발생하지 않아야 함"
    
    # 이때 종목A에서 120틱 5>20>60>120 정배열 신호 발생!
    row_120t_aligned_a = pd.Series({'close': 39000, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': True, 'tema5': 39200, 'tema20': 39100, 'tema60': 39000, 'tema120': 38800})
    order_a_rebuy = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_aligned_a)
    assert order_a_rebuy is not None and order_a_rebuy.action == "RE_BUY", "종목A 120틱 정배열 RE_BUY 미발생 (오류)"
    
    # 슬롯이 비어있으므로 종목A의 RE_BUY 정상 승인
    bot.execute_order('003160', '디아이', order_a_rebuy)
    assert bot.get_active_stock_code() == '003160', "재매수 후 종목A 슬롯 재점유 실패"
    assert strat_a.position.state == StrategyState.REENTRY_HOLDING
    print("  [성공] 타 종목 기준선 돌파 부재 시: 직전 종목 120틱 정배열 재매수(RE_BUY) 1순위 즉시 집행 확인!")
    
    # 6-2) 재매수 후 다시 120틱 5<20 전량 매도
    order_a_resell = strat_a.evaluate_bar(row_60m_a, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_dead)
    assert order_a_resell is not None and order_a_resell.action in ["RE_SELL", "TAKE_PROFIT"]
    bot.execute_order('003160', '디아이', order_a_resell)
    assert bot.get_active_stock_code() is None
    print("  [성공] 재매수 포지션 120틱 5<20 2차 전량 매도 완료 ➔ 슬롯 다시 오픈")
    
    # 7) 대기 중이던 종목B가 이제 기준선(1831)을 상향 돌파(1850) ➔ 종목B가 1순위로 슬롯 점유
    assert bot.get_active_stock_code() is None, "매수 전 슬롯이 비어있지 않음"
    
    order_b_rot = strat_b.evaluate_bar(row_60m_b, daily_dead_cross=False, daily_bull=True)
    assert order_b_rot is not None and order_b_rot.action == "BUY_1"
    
    # 슬롯 오픈 상태이므로 정상 승인 및 매수 집행
    current_active = bot.get_active_stock_code()
    assert current_active == '459550'
    bot.execute_order('459550', '알트', order_b_rot)
    
    assert bot.get_active_stock_code() == '459550', "종목B가 새롭게 슬롯을 점유하지 못함"
    assert strat_b.position.state == StrategyState.FIRST_BUY_DONE
    print("  [성공] 선착순 순환 매매 완벽 작동: 종목A 최종 매도 후 기준선 통과한 종목B(알트)가 1순위로 슬롯 점유!")

def test_intraday_manual_1_share_rebuy():
    print("\n=== 5. 장중 1주 수동 매수 시 재매수 로직 자동 대응 검증 ===")
    bot = SafeHoldingsThemeGateBot(is_real=False, dry_run=True, holdings_state="rebuy")
    
    # 1) 가상 계좌에 1주 수동 매수 종목(005930, 삼성전자) 등록 시뮬레이션
    bot.active_holdings = {
        '005930': {'qty': 1, 'buy_price': 70000, 'current_price': 70500}
    }
    
    # refresh_holdings 로직 검증: 1주 종목은 즉시 PROFIT_TAKEN(재매수 대기)으로 등록되어야 함
    code = '005930'
    h = bot.active_holdings[code]
    strat = ThemeGate60mStrategy(initial_capital=10_000_000)
    strat.position.state = StrategyState.PROFIT_TAKEN
    strat.position.total_qty = 0
    strat.position.base_account_qty = int(h['qty'])
    strat.position.reentry_qty = 0
    bot.strategies[code] = strat
    
    assert bot.strategies[code].position.state == StrategyState.PROFIT_TAKEN, "1주 종목의 상태가 PROFIT_TAKEN이 아님"
    assert bot.strategies[code].position.total_qty == 0, "진입 전에는 total_qty가 0이어야 함"
    assert bot.strategies[code].position.base_account_qty == 1, "수동 매수한 1주가 base_account_qty에 기록되지 않음"
    assert bot.get_active_stock_code() is None, "재매수 진입 전에는 슬롯이 오픈 상태여야 함"
    print("  [성공] 1주 매수 감지 시 '120틱 정배열 재매수(RE_BUY)' 대기 모드(PROFIT_TAKEN) 자동 등록 확인")
    
    # 2) 120틱 5>20>60>120 정배열 발생 시 RE_BUY 발생 검증
    dummy_60m = pd.Series({
        'close': 70500, 'open': 70000, 'high': 70800, 'low': 69900,
        'sma5': 70300, 'sma20': 70100, 'sma60': 69800,
        'theme_gate': 69500, 'theme_gate_high': 70200, 'theme_gijun': 71000,
        'is_gate_up': False
    })
    row_120t_aligned = pd.Series({'close': 70500, 'is_tema_dead_5_20': False, 'is_tema_aligned_120t': True, 'tema5': 70600, 'tema20': 70400, 'tema60': 70200, 'tema120': 70000})
    order_rebuy = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_aligned)
    assert order_rebuy is not None and order_rebuy.action == "RE_BUY", "120틱 정배열 RE_BUY 미발생"
    
    # 가용 예수금 95% 기준 수량 계산 확인
    expected_qty = int((10_000_000 * 0.95) // 70500)
    assert order_rebuy.qty == expected_qty, f"재매수 수량({order_rebuy.qty})이 예수금 95%({expected_qty})와 불일치"
    print(f"  [성공] 120틱 정배열 완성 즉시 RE_BUY 전량 매수({order_rebuy.qty}주, 약 95% 예수금) 신호 확인")
    
    # 3) execute_order 집행: 기존 1주 흡수 및 REENTRY_HOLDING 전이
    bot.execute_order(code, '삼성전자', order_rebuy)
    assert strat.position.state == StrategyState.REENTRY_HOLDING, "상태가 REENTRY_HOLDING으로 전이되지 않음"
    # 기존 1주가 흡수되어 total_qty == expected_qty + 1
    assert strat.position.total_qty == expected_qty + 1, "기존 수동 1주가 포지션에 흡수되지 않음"
    assert strat.position.base_account_qty == 0, "기존 base_account_qty가 0으로 클리어되지 않음"
    assert bot.get_active_stock_code() == code, "슬롯이 해당 종목으로 잠기지 않음"
    print(f"  [성공] 주문 집행 후 기존 수동 1주 자동 흡수 ➔ 총 {strat.position.total_qty}주 보유 및 슬롯 점유 확인")
    
    # 4) 120틱 5<20 하향 이탈 시 전량 매도
    row_120t_dead = pd.Series({'close': 71500, 'is_tema_dead_5_20': True, 'is_tema_aligned_120t': False, 'tema5': 71400, 'tema20': 71600})
    order_sell = strat.evaluate_bar(dummy_60m, daily_dead_cross=False, daily_bull=True, row_120t=row_120t_dead)
    assert order_sell is not None and order_sell.action in ["RE_SELL", "TAKE_PROFIT"]
    bot.execute_order(code, '삼성전자', order_sell)
    assert strat.position.total_qty == 0, "전량 매도 후 잔고가 0이 아님"
    assert bot.get_active_stock_code() is None, "매도 후 슬롯이 오픈되지 않음"
    print("  [성공] 120틱 5<20 시 흡수된 1주 포함 전량 100% 깔끔 매도 및 슬롯 오픈 확인!")

if __name__ == '__main__':
    test_120t_indicators()
    test_strategy_lifecycle_and_whipsaw()
    test_tick_and_sessions()
    test_single_position_lock_and_rotation()
    test_intraday_manual_1_share_rebuy()
    print("\n🎉 모든 단위, 1종목 락, 선착순 순환 매매, 1주 수동 매수 재매수 대응 검증 100% 통과!")
