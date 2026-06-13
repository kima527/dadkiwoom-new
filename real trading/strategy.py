import time
from datetime import datetime
import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

def evaluate_trend_buy(curr_15m):
    """
    추세 매수 로직 (15분봉 골든크로스 + 관문선 지지 + 거래량 1.2배 급증)
    """
    curr_t3 = curr_15m.get("tema3")
    curr_t60 = curr_15m.get("tema60")
    curr_gate = curr_15m.get("tema_gate_line")
    curr_vol_avg3 = curr_15m.get("vol_avg_3", 0)
    curr_vol = curr_15m.get("volume", 0)
    close_price_15m = curr_15m.get("close")
    low_price = curr_15m.get("low")
    
    # 1. 15m TEMA3 > TEMA60 (Golden Cross state)
    is_golden_cross_state = (curr_t3 is not None and curr_t60 is not None and curr_t3 > curr_t60)
    
    # 2. Gate Line Support
    is_gate_supported = False
    if curr_gate and low_price is not None and close_price_15m is not None:
        is_gate_supported = (low_price <= curr_gate * 1.005) and (close_price_15m >= curr_gate)
        
    # 3. Volume Spike (1.2x)
    is_volume_spike = (curr_vol_avg3 > 0 and curr_vol >= curr_vol_avg3 * 1.2)
    
    if is_golden_cross_state and is_gate_supported and is_volume_spike:
        return True, "15m 골든크로스+관문선지지+거래량급증"
        
    return False, ""

def evaluate_rebuy(curr_15m, code, completed_trades, current_date):
    """
    재매수 로직 (당일 매도 이력 있는 종목의 15분봉 볼린저 밴드 하단 눌림목 반등)
    """
    curr_t3 = curr_15m.get("tema3")
    curr_t60 = curr_15m.get("tema60")
    bb5_lower = curr_15m.get("bb5_lower")
    low_price = curr_15m.get("low")
    close_price_15m = curr_15m.get("close")
    
    # 기본 전제: TEMA3 > TEMA60
    is_golden_cross_state = (curr_t3 is not None and curr_t60 is not None and curr_t3 > curr_t60)
    if not is_golden_cross_state:
        return False, ""
        
    has_sold_today = False
    for t in completed_trades:
        if t.get("code") == code and t.get("time", "").startswith(current_date):
            has_sold_today = True
            break
            
    is_bb_rebuy = (bb5_lower is not None and low_price is not None and 
                   low_price <= bb5_lower and close_price_15m > bb5_lower and has_sold_today)
                   
    if is_bb_rebuy:
        return True, "15m 볼린저하단 반등 재매수"
        
    return False, ""

def evaluate_inflection_sell(candles_15m, candles_5m):
    """
    변곡 추세 매도 로직 (5분봉 K/L선 하락 변곡 선제적 감지 OR 15분봉 TEMA3 데드크로스)
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
        
        if is_k_peak or is_l_peak:
            should_sell = True
            peak_type = "K선" if is_k_peak else "L선"
            sell_reason_str = f"5m {peak_type} 하락 변곡 (고점 예측)"
            return should_sell, sell_reason_str

    # 방어망 2: 15분봉 TEMA3 데드크로스
    if candles_15m and len(candles_15m) >= 1:
        curr_15m = candles_15m[-1]
        curr_t3 = curr_15m.get("tema3")
        curr_t60 = curr_15m.get("tema60")
        if curr_t3 is not None and curr_t60 is not None and curr_t3 < curr_t60:
            should_sell = True
            sell_reason_str = "15m TEMA3 데드크로스"
            return should_sell, sell_reason_str
            
    return False, ""

def convert_to_chart_df(api_response_list):
    """
    stk_min_pole_chart_qry 리스트 데이터를 Pandas DataFrame으로 변환
    """
    if not api_response_list:
        return pd.DataFrame()
        
    df = pd.DataFrame(api_response_list)
    
    # 1. 필드명 매핑 및 정수형 변환 (부호 제거 및 절대값 처리)
    df['open'] = df['open_pric'].astype(float).abs().astype(int)
    df['high'] = df['high_pric'].astype(float).abs().astype(int)
    df['low'] = df['low_pric'].astype(float).abs().astype(int)
    df['close'] = df['cur_prc'].astype(float).abs().astype(int)
    df['volume'] = df['trde_qty'].astype(float).abs().astype(int)
    
    # 2. 시간 축 설정 (cntr_tm: YYYYMMDDHHMMSS)
    df['datetime'] = pd.to_datetime(df['cntr_tm'], format='%Y%m%d%H%M%S')
    df.set_index('datetime', inplace=True)
    
    # 3. HTS 정렬 방식 맞추기 (과거 -> 최신순 오름차순 정렬)
    df.sort_index(ascending=True, inplace=True)
    
    # 필요한 컬럼만 추출
    return df[['open', 'high', 'low', 'close', 'volume']]

def update_realtime_15min_candle(df_15min, current_tick):
    """
    current_tick: 웹소켓 등으로 수신한 실시간 데이터 딕셔너리
    예: {'cntr_tm': '20260612100325', 'cur_prc': 80500, 'trde_qty': 120}
    """
    tick_time = pd.to_datetime(current_tick['cntr_tm'], format='%Y%m%d%H%M%S')
    tick_price = abs(int(float(current_tick['cur_prc'])))
    tick_qty = abs(int(float(current_tick['trde_qty'])))
    
    # 15분봉의 기준 시작 시간 계산 (예: 10:03:25 -> 10:00:00 / 10:16:00 -> 10:15:00)
    candle_time = tick_time.floor('15min')
    
    if candle_time in df_15min.index:
        # 기존에 존재하는 15분봉 업데이트 (장중 실시간 변동)
        df_15min.loc[candle_time, 'high'] = max(df_15min.loc[candle_time, 'high'], tick_price)
        df_15min.loc[candle_time, 'low'] = min(df_15min.loc[candle_time, 'low'], tick_price)
        df_15min.loc[candle_time, 'close'] = tick_price
        df_15min.loc[candle_time, 'volume'] += tick_qty
    else:
        # 새로운 15분봉 시작 (새로운 캔들 생성)
        new_row = pd.DataFrame([{
            'open': tick_price, 'high': tick_price, 'low': tick_price, 'close': tick_price, 'volume': tick_qty
        }], index=[candle_time])
        df_15min = pd.concat([df_15min, new_row])
        
        # 메모리 관리를 위해 너무 오래된 데이터는 삭제 (최근 500개만 유지)
        if len(df_15min) > 500:
            df_15min = df_15min.iloc[-500:]
            
    return df_15min

class TradingBot15Min:
    def __init__(self, stk_cd):
        self.stk_cd = stk_cd
        self.df = pd.DataFrame()       # 15분봉 차트 데이터 구조
        self.balance = {}              # 예수금 및 잔고 구조
        self.open_orders = {}          # 미체결 주문 구조
        
    def refresh_market_data(self, api_client):
        """15분봉 과거 데이터 조회 및 구조화"""
        raw_chart = api_client.get_chart_data(self.stk_cd, type='min') # 수신 키: stk_min_pole_chart_qry
        self.df = convert_to_chart_df(raw_chart['stk_min_pole_chart_qry'])
        
    def refresh_account_data(self, api_client):
        """계좌 잔고, 예수금, 미체결 현황 갱신"""
        acnt_data = api_client.get_account_info()
        
        # 예수금 갱신 (prsm_dpst_aset_amt)
        self.balance['cash'] = int(acnt_data.get('prsm_dpst_aset_amt', 0))
        
        # 보유 종목 구조화 (acnt_evlt_remn_indv_tot)
        holdings = acnt_data.get('acnt_evlt_remn_indv_tot', [])
        self.balance['items'] = {
            item['stk_cd']: {
                'qty': int(item['rmnd_qty']),
                'pur_price': int(item['pur_pric']),
                'cur_price': int(item['cur_prc'])
            } for item in holdings
        }
        
        # 미체결 주문 구조화 (ccld_nccld_qry)
        unfilled = api_client.get_unfilled_orders() # ccld_nccld_qry 수신
        self.open_orders = {
            ord['ord_no']: {
                'stk_cd': ord['stk_cd'],
                'qty': int(ord['nccld_qty']),
                'price': int(ord['ord_uv']),
                'type': ord['sell_buy_tp_nm'] # 매수/매도
            } for ord in unfilled.get('ccld_nccld_qry', [])
        }

    def check_strategy_and_order(self, api_client):
        """15분봉 기술 지표 계산 및 매매 판단"""
        if len(self.df) < 20: return # 최소 데이터 확보
        
        # 예시: 15분봉 종가 기준 5일 이동평균선 계산
        self.df['ma5'] = self.df['close'].rolling(window=5).mean()
        
        # 가장 최근에 '완성된' 캔들의 지표 확인 (현재 진행중인 [-1] 대신 바로 전 [-2] 사용 권장)
        last_completed_candle = self.df.iloc[-2]
        
        # 보유 수량 확인
        my_qty = self.balance['items'].get(self.stk_cd, {}).get('qty', 0)
        
        # 매매 로직 예시 (5MA 골든크로스 등)
        if last_completed_candle['close'] > last_completed_candle['ma5'] and my_qty == 0:
            if not self.open_orders: # 미체결 주문이 없을 때만
                print("15분봉 조건 만족: 매수 주문 전송")
                # api_client.send_order(...) 호출

def update_nxt_15min_candle(df_15min, current_tick):
    """
    NXT 시장 거래시간(08:00~20:00)을 반영한 15분봉 실시간 생성 로직
    """
    tick_time = pd.to_datetime(current_tick['cntr_tm'], format='%Y%m%d%H%M%S')
    
    # 1. NXT 정규 거래 시간 체크 (08시 이전 또는 20시 이후 데이터 필터링)
    if tick_time.hour < 8 or tick_time.hour >= 20:
        return df_15min  # 처리하지 않고 반환
        
    tick_price = abs(int(float(current_tick['cur_prc'])))
    tick_qty = abs(int(float(current_tick['trde_qty'])))
    
    # 2. 15분 기준 버킷 내림 처리 (08:03 -> 08:00 / 15:25 -> 15:15)
    candle_time = tick_time.floor('15min')
    
    # 3. 데이터프레임 업데이트 구조
    if candle_time in df_15min.index:
        df_15min.loc[candle_time, 'high'] = max(df_15min.loc[candle_time, 'high'], tick_price)
        df_15min.loc[candle_time, 'low'] = min(df_15min.loc[candle_time, 'low'], tick_price)
        df_15min.loc[candle_time, 'close'] = tick_price
        df_15min.loc[candle_time, 'volume'] += tick_qty
    else:
        # 새로운 NXT 타임슬롯 진입 시 캔들 생성
        new_row = pd.DataFrame([{
            'open': tick_price, 'high': tick_price, 'low': tick_price, 'close': tick_price, 'volume': tick_qty
        }], index=[candle_time])
        df_15min = pd.concat([df_15min, new_row])
        
    return df_15min

# [NXT 필수] 장 시작(08시)부터 끝(20시)까지의 완전한 15분 연속 시간축 만들기
def fill_nxt_void_slots(df):
    if df.empty: return df
    
    # 현재 데이터의 날짜 추출
    current_date = df.index.min().strftime('%Y-%m-%d')
    
    # NXT 거래시간인 08:00부터 19:45까지 15분 간격의 완전한 타임라인 생성
    nxt_full_timeline = pd.date_range(
        start=f"{current_date} 08:00:00", 
        end=f"{current_date} 19:45:00", 
        freq='15min'
    )
    
    # 비어있는 분봉 칸을 뼈대 위에 매핑 후 이전 종가로 전방 채움(Forward Fill)
    df = df.reindex(nxt_full_timeline)
    df['close'] = df['close'].ffill()
    df['open'] = df['open'].fillna(df['close'])
    df['high'] = df['high'].fillna(df['close'])
    df['low'] = df['low'].fillna(df['close'])
    df['volume'] = df['volume'].fillna(0)  # 거래가 없었으므로 거래량은 0
    
    return df

def convert_nxt_only_df(api_response_list):
    if not api_response_list:
        return pd.DataFrame()
        
    df = pd.DataFrame(api_response_list)
    
    # 1. 원천 데이터 형변환 및 부호 제거
    df['open'] = df['open_pric'].astype(float).abs().astype(int)
    df['high'] = df['high_pric'].astype(float).abs().astype(int)
    df['low'] = df['low_pric'].astype(float).abs().astype(int)
    df['close'] = df['cur_prc'].astype(float).abs().astype(int)
    df['volume'] = df['trde_qty'].astype(float).abs().astype(int)
    
    # 2. NXT 타임 인덱스 설정
    df['datetime'] = pd.to_datetime(df['cntr_tm'], format='%Y%m%d%H%M%S')
    df.set_index('datetime', inplace=True)
    df.sort_index(ascending=True, inplace=True)
    
    # 3. [NXT 단독 필수] 거래 시간 가드 필터 (08:00 ~ 20:00 사이 데이터만 생존)
    # nxt_only_df = df.between_time('08:00', '19:59:59')
    
    return df[['open', 'high', 'low', 'close', 'volume']]

def aggregate_nxt_realtime_tick(df_nxt, current_tick):
    """
    NXT 단독 세션 실시간 틱 수신 시 15분봉 업데이트 로직
    """
    tick_time = pd.to_datetime(current_tick['cntr_tm'], format='%Y%m%d%H%M%S')
    
    # NXT 정규 세션 타임 외의 틱 데이터 진입 원천 차단
    if tick_time.hour < 8 or tick_time.hour >= 20:
        return df_nxt
        
    tick_price = abs(int(float(current_tick['cur_prc'])))
    tick_qty = abs(int(float(current_tick['trde_qty'])))
    
    # 15분 단위 내림 연산 (08:01 -> 08:00 / 19:54 -> 19:45)
    candle_time = tick_time.floor('15min')
    
    if candle_time in df_nxt.index:
        # 실시간 진행 중인 15분봉 업데이트
        df_nxt.loc[candle_time, 'high'] = max(df_nxt.loc[candle_time, 'high'], tick_price)
        df_nxt.loc[candle_time, 'low'] = min(df_nxt.loc[candle_time, 'low'], tick_price)
        df_nxt.loc[candle_time, 'close'] = tick_price
        df_nxt.loc[candle_time, 'volume'] += tick_qty
    else:
        # 새로운 15분 타임슬롯 생성
        new_row = pd.DataFrame([{
            'open': tick_price, 'high': tick_price, 'low': tick_price, 'close': tick_price, 'volume': tick_qty
        }], index=[candle_time])
        df_nxt = pd.concat([df_nxt, new_row])
        
    return df_nxt

def finalize_nxt_time_series(df):
    if df.empty: return df
    
    # 현재 데이터프레임의 날짜 기준 추출
    current_date = df.index.min().strftime('%Y-%m-%d')
    
    # 08:00부터 19:45까지 총 48개의 완벽한 NXT 15분봉 타임프레임 표준 생성
    nxt_standard_timeline = pd.date_range(
        start=f"{current_date} 08:00:00", 
        end=f"{current_date} 19:45:00", 
        freq='15min'
    )
    
    # 표준 타임라인에 기존 데이터를 매핑하여 빈 구멍(Gap) 찾아내기
    df = df.reindex(nxt_standard_timeline)
    
    # 거래가 없던 15분 구간은 이전 15분봉의 '종가'를 그대로 유지
    df['close'] = df['close'].ffill()
    df['open'] = df['open'].fillna(df['close'])
    df['high'] = df['high'].fillna(df['close'])
    df['low'] = df['low'].fillna(df['close'])
    df['volume'] = df['volume'].fillna(0) # 거래량만 0 처리
    
    return df
