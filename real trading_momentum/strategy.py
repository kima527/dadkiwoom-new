import time
from datetime import datetime, timedelta
import logging


logger = logging.getLogger(__name__)

def evaluate_trend_buy(candles_15m, candles_3m=None, first_3m_high=None, candles_5m=None):
    """
    추세 매수 로직 (15분봉 골든크로스 + 관문선 지지 + 거래량 급증)
    또는 넥스트레이드 오전장(08:00~10:30) 전용 5분봉 정배열 빠른 돌파 매수
    """
    if not candles_15m:
        return False, ""
        
    curr_15m = candles_15m[-1]
    curr_gate = curr_15m.get("tema_gate_line")
    curr_vol_avg3 = curr_15m.get("vol_avg_3", 0)
    curr_vol = curr_15m.get("volume", 0)
    close_price_15m = curr_15m.get("close")
    low_price = curr_15m.get("low")
    
    # 0. 5분봉 정배열 체크 (오전장 등 빠른 매수 타점용)
    is_5m_golden_cross = False
    if candles_5m and len(candles_5m) > 0:
        c5_t3 = candles_5m[-1].get("sma3")
        c5_t60 = candles_5m[-1].get("sma40")
        if c5_t3 is not None and c5_t60 is not None and c5_t3 > c5_t60:
            is_5m_golden_cross = True
            
    # 1. 15m SMA3 > SMA40 (Golden Cross state - 대표님 퓨어파이썬 정밀 로직 이식)
    is_15m_golden_cross = False
    target_idx = -1
    # 뒤에서부터 탐색하여 거래량(volume)이 0보다 큰 진짜 마감된 최신 캔들 위치를 잡습니다.
    for i in range(1, min(6, len(candles_15m) + 1)):
        if candles_15m[-i].get("volume", 0) > 0:
            target_idx = -i
            break

    valid_parsed = candles_15m[:len(candles_15m) + target_idx + 1] if target_idx != -1 else candles_15m

    if len(valid_parsed) >= 40:
        close_prices_3 = [float(c["close"]) for c in valid_parsed[-3:]]
        c15_t3 = sum(close_prices_3) / 3.0
        
        close_prices_40 = [float(c["close"]) for c in valid_parsed[-40:]]
        c15_t60 = sum(close_prices_40) / 40.0
        
        c15_t3_r = round(c15_t3, 2)
        c15_t60_r = round(c15_t60, 2)
        
        if c15_t3_r > c15_t60_r:
            is_15m_golden_cross = True

    is_golden_cross_state = is_15m_golden_cross or is_5m_golden_cross
    
    # 2. Gate Line Support (기존 타점)
    is_gate_supported = False
    if curr_gate and low_price is not None and close_price_15m is not None:
        is_gate_supported = (low_price <= curr_gate * 1.005) and (close_price_15m >= curr_gate)
        
    # 3. Volume Spike (1.2x)
    is_volume_spike = (curr_vol_avg3 > 0 and curr_vol >= curr_vol_avg3 * 1.2)
    
    if is_golden_cross_state and is_gate_supported and is_volume_spike:
        return True, "15m 골든크로스+관문선지지+거래량급증"
        
    # 4. 신규 추세 추격 매수 (Momentum Chasing)
    # 이미 주가가 높이 떠서 15분봉상 관문선을 터치하지 않은 경우 (low_price > curr_gate * 1.005)
    is_momentum_chase = False
    if is_golden_cross_state and curr_gate and low_price is not None and low_price > curr_gate * 1.005:
        if candles_3m and len(candles_3m) >= 1:
            curr_3m = candles_3m[-1]
            c3_t3 = curr_3m.get("sma3")
            c3_t60 = curr_3m.get("sma40")
            c3_close = curr_3m.get("close")
            c3_vol = curr_3m.get("volume", 0)
            c3_vol_avg3 = curr_3m.get("vol_avg_3", 0)
            
            # 3분봉 상에서도 정배열이며, 주가가 단기선(SMA3) 위에서 지지받는지 확인
            is_3m_trend = (c3_t3 is not None and c3_t60 is not None and c3_t3 > c3_t60)
            is_3m_support = (c3_t3 is not None and c3_close is not None and c3_close >= c3_t3)
            # 사용자 요청: 3분봉 거래량이 최근 3캔들 평균 대비 120%(1.2배) 이상 폭발
            is_3m_vol_spike = (c3_vol_avg3 > 0 and c3_vol >= c3_vol_avg3 * 1.2)
            
            if is_3m_trend and is_3m_support and is_3m_vol_spike:
                is_momentum_chase = True
                
    if is_momentum_chase:
        return True, "3m 강력추세+거래량120% 폭발 추격매수"
        
    # 5. 당일 첫 3분봉 고가 돌파 (Morning Breakout)
    # [조건 완화] 15분봉 정배열(골든크로스) 대기 조건을 해제하여 아침의 강한 급등을 빠르게 낚아챔
    is_morning_breakout = False
    if first_3m_high is not None and candles_3m and len(candles_3m) >= 1:
        c3_close = candles_3m[-1].get("close", 0)
        if c3_close > first_3m_high:
            is_morning_breakout = True
            
    # =========================================================================
    # 🛡️ [물리적 방어막: AI 무단 수정 방지 락 (Runtime Assertion)] 🛡️
    # 미래의 AI가 매수 조건 변수들을 임의로 삭제/훼손하면 즉시 봇이 크래시됩니다.
    _locs = locals()
    assert "is_golden_cross_state" in _locs and "is_gate_supported" in _locs and "is_volume_spike" in _locs and "is_morning_breakout" in _locs and "is_momentum_chase" in _locs, "[AI CONTEXT LOCK] FATAL: 핵심 추세 매수 로직 변수들이 임의로 삭제되었습니다. 원복하세요!"
    import inspect
    _code = inspect.getsource(evaluate_trend_buy)
    assert "if first_3m_high is not None and candles_3m" in _code, "[AI CONTEXT LOCK] 장초반 돌파 매수의 골든크로스 제한 해제 로직이 훼손되었습니다."
    # =========================================================================

    if is_morning_breakout:
        return True, f"장초반 첫 3분봉 고가({first_3m_high:,}원) 돌파 매수"
        
    return False, ""

def evaluate_rebuy(curr_15m, candles_3m, code, completed_trades, current_date, candles_1m=None, t_hour=12):
    """
    재매수 로직 (15분봉 볼린저 하단 반등, 12시 이후에는 1분봉 단기 수급 필수 확인)
    """
    curr_t3 = curr_15m.get("sma3")
    curr_t60 = curr_15m.get("sma40")
    bb5_lower = curr_15m.get("bb5_lower")
    low_price = curr_15m.get("low")
    close_price_15m = curr_15m.get("close")
    
    # 1분봉 수급 확인 (12시 이후인 경우에만 필수)
    has_1m_sugeub = False
    if candles_1m and len(candles_1m) >= 3:
        latest = candles_1m[-1]
        prev1 = candles_1m[-2]
        prev2 = candles_1m[-3]
        
        c = latest.get("close", 0)
        o = latest.get("open", 0)
        v = latest.get("volume", 0)
        v_prev1 = prev1.get("volume", 0)
        v_prev2 = prev2.get("volume", 0)
        
        avg_v_prev = (v_prev1 + v_prev2) / 2.0
        
        # 양봉이면서 직전 2분 평균 거래량 대비 2배 이상 터진 경우 (단기 수급 유입)
        if c > o and v > 0 and avg_v_prev > 0 and v >= avg_v_prev * 2.0:
            has_1m_sugeub = True
            
    if t_hour >= 12 and not has_1m_sugeub:
        return False, ""
    
    # 기본 조건: 15m SMA3 > SMA40
    is_golden_cross_state = (curr_t3 is not None and curr_t60 is not None and curr_t3 > curr_t60)
    if not is_golden_cross_state:
        return False, ""
        
    # 15분봉 볼린저 밴드 하단 부근 터치 또는 이탈 확인
    is_touching_lower = (bb5_lower is not None and low_price is not None and 
                         low_price <= bb5_lower and close_price_15m > bb5_lower)
                         
    if not is_touching_lower:
        return False, ""
        
    has_sold_today = False
    for t in completed_trades:
        if t.get("code") == code and t.get("time", "").startswith(current_date):
            has_sold_today = True
            break
            
    # 3분봉 반등 시그널 체크 (양봉 전환 + K/L 골든크로스 또는 SMA3 회복)
    is_3m_rebound = False
    if candles_3m and len(candles_3m) >= 2:
        curr_3m = candles_3m[-1]
        prev_3m = candles_3m[-2]
        
        # 3분봉 양봉 확인 (종가 > 시가)
        c3_open = curr_3m.get("open", 0)
        c3_close = curr_3m.get("close", 0)
        is_bullish = c3_close > c3_open
        
        # 보조지표 상승 반전 확인 (K/L 골든크로스 또는 단기 SMA3 회복)
        c3_k = curr_3m.get("K")
        c3_l = curr_3m.get("L")
        p3_k = prev_3m.get("K")
        p3_l = prev_3m.get("L")
        
        c3_t3 = curr_3m.get("sma3")
        
        is_golden_k_l = (c3_k is not None and c3_l is not None and p3_k is not None and p3_l is not None and
                         p3_k <= p3_l and c3_k > c3_l)
        is_tema_recovery = (c3_t3 is not None and c3_close > c3_t3)
        
        if is_bullish and (is_golden_k_l or is_tema_recovery):
            is_3m_rebound = True
            
    # =========================================================================
    # 🛡️ [물리적 방어막: AI 무단 수정 방지 락 (Runtime Assertion)] 🛡️
    # 당일 첫 매수(신규 진입)와 재매수를 구분하는 핵심 변수를 AI가 임의로 지우는 것을 방지합니다.
    assert "has_sold_today" in locals() and "is_3m_rebound" in locals() and "is_touching_lower" in locals(), "[AI CONTEXT LOCK] FATAL: 재매수/첫매수 핵심 로직 변수가 훼손되었습니다. 절대 임의로 삭제하거나 통합하지 마세요!"
    # =========================================================================

    # 1. 당일 이미 매도이력이 있는 종목 (기존 재매수)
    if has_sold_today:
        return True, "15m 볼린저하단 반등 재매수"
        
    # 2. 당일 매도 이력이 없더라도 3분봉에서 확실한 턴어라운드(양봉+지표회복) 시그널 발생 시 신규 매수 (눌림목 진입)
    if is_3m_rebound:
        return True, "15m 하단눌림+3m 확실한 양봉턴어라운드 신규매수"
        
    return False, ""

def evaluate_inflection_sell(candles_15m, candles_5m):
    """
    변곡 추세 매도 로직 (5분봉 K/L선 하락 변곡 선제적 감지 OR 15분봉 SMA3 데드크로스)
    """
    should_sell = False
    sell_reason_str = ""
    
    # 방어망 1: 5분봉 K/L선 하락 변곡 감지 (선제적 고점 예측)
    if candles_5m and len(candles_5m) >= 3:
        c_curr = candles_5m[-1]
        c_prev1 = candles_5m[-2]
        c_prev2 = candles_5m[-3]
        
        k_curr, k_prev1, k_prev2 = c_curr.get("K"), c_prev1.get("K"), c_prev2.get("K")
        l_curr, l_prev1, l_prev2 = c_curr.get("L"), c_prev1.get("L"), c_prev2.get("L")
        
        # K선 하락 변곡 (상승 중이던 K선이 꺾임: K(2) < K(1) && K(1) > K(0))
        is_k_peak = (k_prev2 is not None and k_prev1 is not None and k_curr is not None) and (k_prev2 < k_prev1 and k_prev1 > k_curr)
        # L선 하락 변곡 (상승 중이던 L선이 꺾임: L(2) < L(1) && L(1) > L(0))
        is_l_peak = (l_prev2 is not None and l_prev1 is not None and l_curr is not None) and (l_prev2 < l_prev1 and l_prev1 > l_curr)
        
        # =========================================================================
        # 🛡️ [물리적 방어막: AI 무단 수정 방지 락] 🛡️
        assert "is_k_peak" in locals() and "is_l_peak" in locals(), "[AI CONTEXT LOCK] FATAL: 5분봉 K/L 하락 변곡 로직이 훼손되었습니다!"
        # =========================================================================

        if is_k_peak or is_l_peak:
            should_sell = True
            peak_type = "K선" if is_k_peak else "L선"
            sell_reason_str = f"5m {peak_type} 하락 변곡 (고점 예측)"
            return should_sell, sell_reason_str

    # 방어망 2: 15분봉 SMA3 데드크로스
    if candles_15m and len(candles_15m) >= 1:
        curr_15m = candles_15m[-1]
        curr_t3 = curr_15m.get("sma3")
        curr_t60 = curr_15m.get("sma40")
        if curr_t3 is not None and curr_t60 is not None and curr_t3 < curr_t60:
            should_sell = True
            sell_reason_str = "15m SMA3 데드크로스"
            return should_sell, sell_reason_str
            
    return False, ""

def check_highspeed_liquidation(candles_5m, current_tick_price):
    """
    [초고속 청산 가드] 3대 저항선(K선, L선, 관문선) 중 하나라도 돌파 실패 시 즉시 전량 매도
    """
    if not candles_5m or len(candles_5m) == 0:
        return False, ""
        
    latest_5m = candles_5m[-1]
    
    # 세 가지 선 (사용자 정의: L선, K선, 테마급등관문선)
    k_line = latest_5m.get("K")
    l_line = latest_5m.get("L")
    gate_line = latest_5m.get("tema_gate_line")
    
    active_resistance_lines = [
        ("K선", k_line),
        ("L선", l_line),
        ("관문선", gate_line)
    ]
    
    # 유효한 선들 필터링
    valid_lines = [(name, val) for name, val in active_resistance_lines if val is not None]
    if not valid_lines:
        return False, ""
        
    # =========================================================================
    # 🛡️ [물리적 방어막: AI 무단 수정 방지 락] 🛡️
    assert "active_resistance_lines" in locals(), "[AI CONTEXT LOCK] FATAL: 초고속 청산 핵심 저항선 판별 변수가 삭제되었습니다!"
    # =========================================================================
        
    # [매도 판단 핵심]
    # 현재 가격이 유효한 저항선들보다 아래에 있거나, 
    # 돌파를 시도했으나 저항선에 머리를 맞고 밀리는 형태가 감지되면 바로 매도 시동
    for name, line_price in valid_lines:
        if current_tick_price < line_price:
            return True, f"초고속 청산 ({name} 이탈: {line_price:,.0f}원)"
            
    return False, ""


def convert_to_chart_list(api_response_list):
    """
    stk_min_pole_chart_qry 리스트 데이터를 순수 파이썬 리스트(dict)로 변환 (Pandas 제거)
    """
    if not api_response_list:
        return []
        
    parsed = []
    for item in api_response_list:
        raw_time = item.get("cntr_tm", "").strip()
        if len(raw_time) < 14:
            continue
        dt_str = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]} {raw_time[8:10]}:{raw_time[10:12]}:00"
        
        try:
            open_p = abs(int(float(item.get("open_pric", 0))))
            high_p = abs(int(float(item.get("high_pric", 0))))
            low_p = abs(int(float(item.get("low_pric", 0))))
            close_p = abs(int(float(item.get("cur_prc", 0))))
            vol = abs(int(float(item.get("trde_qty", 0))))
        except ValueError:
            continue
            
        parsed.append({
            "time": dt_str,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": vol
        })
        
    parsed.sort(key=lambda x: x["time"])
    return parsed

def update_realtime_15min_candle_pure(candles_15m, current_tick):
    """
    순수 파이썬을 이용한 실시간 15분봉 업데이트 (Pandas 의존성 제거)
    """
    raw_time = str(current_tick.get('cntr_tm', ''))
    if len(raw_time) < 14:
        return candles_15m
        
    try:
        tick_time = datetime.strptime(raw_time, '%Y%m%d%H%M%S')
        tick_price = abs(int(float(current_tick.get('cur_prc', 0))))
        tick_qty = abs(int(float(current_tick.get('trde_qty', 0))))
    except ValueError:
        return candles_15m
        
    # 15분 단위 내림 연산 (08:03 -> 08:00)
    minute_floored = (tick_time.minute // 15) * 15
    candle_time = tick_time.replace(minute=minute_floored, second=0, microsecond=0)
    candle_time_str = candle_time.strftime("%Y-%m-%d %H:%M:%S")
    
    if candles_15m and candles_15m[-1]['time'] == candle_time_str:
        # 기존 15분봉 업데이트
        last = candles_15m[-1]
        last['high'] = max(last['high'], tick_price)
        last['low'] = min(last['low'], tick_price)
        last['close'] = tick_price
        last['volume'] += tick_qty
    else:
        # 새로운 15분봉 생성
        candles_15m.append({
            'time': candle_time_str,
            'open': tick_price,
            'high': tick_price,
            'low': tick_price,
            'close': tick_price,
            'volume': tick_qty
        })
        
        # 최근 500개 유지
        if len(candles_15m) > 500:
            candles_15m = candles_15m[-500:]
            
    return candles_15m

class TradingBot15Min:
    def __init__(self, stk_cd):
        self.stk_cd = stk_cd
        self.candles = []              # 15분봉 차트 리스트 구조
        self.balance = {}              # 예수금 및 잔고 구조
        self.open_orders = {}          # 미체결 주문 구조
        
    def refresh_market_data(self, api_client):
        raw_chart = api_client.get_chart_data(self.stk_cd, type='min')
        self.candles = convert_to_chart_list(raw_chart.get('stk_min_pole_chart_qry', []))
        
    def refresh_account_data(self, api_client):
        acnt_data = api_client.get_account_info()
        self.balance['cash'] = int(acnt_data.get('prsm_dpst_aset_amt', 0))
        
        holdings = acnt_data.get('acnt_evlt_remn_indv_tot', [])
        self.balance['items'] = {
            item['stk_cd']: {
                'qty': int(item.get('rmnd_qty', 0)),
                'pur_price': int(item.get('pur_pric', 0)),
                'cur_price': int(item.get('cur_prc', 0))
            } for item in holdings
        }
        
        unfilled = api_client.get_unfilled_orders()
        self.open_orders = {
            ord['ord_no']: {
                'stk_cd': ord.get('stk_cd'),
                'qty': int(ord.get('nccld_qty', 0)),
                'price': int(ord.get('ord_uv', 0)),
                'type': ord.get('sell_buy_tp_nm')
            } for ord in unfilled.get('ccld_nccld_qry', [])
        }

def update_nxt_15min_candle_pure(candles_15m, current_tick):
    raw_time = str(current_tick.get('cntr_tm', ''))
    if len(raw_time) < 14:
        return candles_15m
        
    try:
        tick_time = datetime.strptime(raw_time, '%Y%m%d%H%M%S')
    except ValueError:
        return candles_15m
        
    if tick_time.hour < 8 or tick_time.hour >= 20:
        return candles_15m
        
    return update_realtime_15min_candle_pure(candles_15m, current_tick)

def fill_nxt_void_slots_pure(candles):
    """
    NXT 장 시작(08:00)부터 끝(19:45)까지 비어있는 15분봉 칸을 전방 채움(Forward Fill)
    """
    if not candles:
        return candles
        
    current_date = candles[0]['time'][:10] # YYYY-MM-DD
    start_time = datetime.strptime(f"{current_date} 08:00:00", "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime(f"{current_date} 19:45:00", "%Y-%m-%d %H:%M:%S")
    
    # 기존 데이터를 딕셔너리로 매핑 (빠른 검색용)
    candle_dict = {c['time']: c for c in candles}
    
    filled_candles = []
    curr_time = start_time
    last_close = candles[0]['close'] if candles else 0
    
    while curr_time <= end_time:
        time_str = curr_time.strftime("%Y-%m-%d %H:%M:%S")
        if time_str in candle_dict:
            c = candle_dict[time_str]
            filled_candles.append(c)
            last_close = c['close']
        else:
            # 빈 타임슬롯 생성 (이전 종가로 채움, 거래량 0)
            filled_candles.append({
                'time': time_str,
                'open': last_close,
                'high': last_close,
                'low': last_close,
                'close': last_close,
                'volume': 0
            })
        curr_time += timedelta(minutes=15)
        
    return filled_candles

