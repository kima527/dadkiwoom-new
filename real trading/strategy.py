import time
from datetime import datetime, timedelta
import logging


logger = logging.getLogger(__name__)

def evaluate_trend_buy(candles_15m, candles_5m, volume_power):
    """
    15분봉 SMA20 > SMA40 일때, SMA3/5 골든크로스 + 체결강도 51 이상 + 5분봉 수급(거래량 120%) 매수
    """
    if not candles_15m or len(candles_15m) < 2:
        return False, ""
        
    curr_15m = candles_15m[-1]
    prev_15m = candles_15m[-2]
    
    # 1. 15분봉 SMA5 > SMA20 체크
    sma5 = curr_15m.get("sma5")
    sma20 = curr_15m.get("sma20")
    if sma5 is None or sma20 is None or sma5 <= sma20:
        return False, ""
        
    # 2. 15분봉 SMA3 & SMA5 골든크로스
    curr_sma3 = curr_15m.get("sma3")
    curr_sma5 = curr_15m.get("sma5")
    prev_sma3 = prev_15m.get("sma3")
    prev_sma5 = prev_15m.get("sma5")
    
    if curr_sma3 is None or curr_sma5 is None or prev_sma3 is None or prev_sma5 is None:
        return False, ""
        
    is_golden_cross = (prev_sma3 <= prev_sma5) and (curr_sma3 > curr_sma5)
    if not is_golden_cross:
        return False, ""
        
    # 3. 체결강도(매수비율) 51 이상
    if volume_power < 51.0:
        return False, ""
        
    # 4. 5분봉 수급 체크 (거래량 120% 이상)
    from indicator import check_short_term_sugeub
    has_sugeub = check_short_term_sugeub(candles_5m, 5, threshold=1.2)
    if not has_sugeub:
        return False, ""
        
    return True, "15m 3/5이평 골든크로스+체결강도51+5m수급(120%) 매수"

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

def evaluate_inflection_sell(candles_15m):
    """
    15분봉 SMA20 > SMA40 일때, 15분봉 SMA3과 SMA5의 데드크로스 매도
    """
    if not candles_15m or len(candles_15m) < 2:
        return False, ""
        
    curr_15m = candles_15m[-1]
    prev_15m = candles_15m[-2]
    
    sma5 = curr_15m.get("sma5")
    sma20 = curr_15m.get("sma20")
    if sma5 is None or sma20 is None or sma5 <= sma20:
        return False, ""
        
    curr_sma3 = curr_15m.get("sma3")
    curr_sma5 = curr_15m.get("sma5")
    prev_sma3 = prev_15m.get("sma3")
    prev_sma5 = prev_15m.get("sma5")
    
    if curr_sma3 is None or curr_sma5 is None or prev_sma3 is None or prev_sma5 is None:
        return False, ""
        
    is_dead_cross = (prev_sma3 >= prev_sma5) and (curr_sma3 < curr_sma5)
    
    if is_dead_cross:
        return True, "15m 3/5이평 데드크로스 매도"
        
    return False, ""

def check_highspeed_liquidation(candles_15m, current_tick_price):
    """
    [초고속 청산 가드] 15분봉 3대 저항선(K선, L선, 관문선) 중 하나라도 돌파 실패 시 즉시 전량 매도
    """
    if not candles_15m or len(candles_15m) == 0:
        return False, ""
        
    latest_15m = candles_15m[-1]
    
    k_line = latest_15m.get("K")
    l_line = latest_15m.get("L")
    gate_line = latest_15m.get("tema_gate_line")
    
    active_resistance_lines = [
        ("15m K선", k_line),
        ("15m L선", l_line),
        ("15m 관문선", gate_line)
    ]
    
    valid_lines = [(name, val) for name, val in active_resistance_lines if val is not None]
    if not valid_lines:
        return False, ""
        
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

