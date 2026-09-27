import pandas as pd

def get_tick_size(price: int) -> int:
    """한국 거래소 기준 호가 단위(Tick Size) 계산"""
    if price < 2000:
        return 1
    elif price < 5000:
        return 5
    elif price < 20000:
        return 10
    elif price < 50000:
        return 50
    elif price < 200000:
        return 100
    elif price < 500000:
        return 500
    else:
        return 1000

class TradeState:
    def __init__(self):
        self.is_holding = False
        self.trade_ended = False
        self.first_buy_candle_time = None
        self.added_on = False
        self.first_qty = 0
        self.trailing_high = 0.0
        self.initial_breakout_high = 0.0
        self.sold_once = False
        self.reentry_qty = 0
        self.sell_target = 0.0
        self.stop_loss = 0.0
        # ── 분할매수 봇용 ──
        self.buy_step = 0           # 0: 미매수, 1: 1차(50%) 매수 완료, 2: 2차(50%) 매수 완료
        self.tema_sl_price = 0.0    # TEMA 기반 손절가
        self.signal_1 = 0.0         # WMA 골든크로스 시점 WMA5 값
        self.signal_2 = 0.0         # WMA 골든크로스 시점 고가(HH)
        self.is_w_rebound = False   # 30분봉 260이평 W자 반등 여부
        self.buy_time = 0.0         # 매수 체결 시간 (초 단위 timestamp)
        # ── M선(정배열 정점 저항선) 50% 분할 익절용 ──
        self.m_resistance_line = 0.0 # 정배열 최고 정점선 (M선 가격)
        self.m_partial_sold = False  # M선 도달 50% 1차 익절 완료 여부
        self.m_touch_high = 0.0      # M선 도달 후 기록한 최고가
        self.quick_partial_sold = False # +1.2% 단기 빠른 1차 분할 익절 여부

    def to_dict(self) -> dict:
        return {
            'is_holding': self.is_holding,
            'trade_ended': self.trade_ended,
            'first_buy_candle_time': str(self.first_buy_candle_time) if self.first_buy_candle_time else None,
            'added_on': self.added_on,
            'first_qty': self.first_qty,
            'trailing_high': self.trailing_high,
            'initial_breakout_high': self.initial_breakout_high,
            'sold_once': self.sold_once,
            'reentry_qty': self.reentry_qty,
            'sell_target': getattr(self, 'sell_target', 0.0),
            'stop_loss': getattr(self, 'stop_loss', 0.0),
            'buy_step': getattr(self, 'buy_step', 0),
            'tema_sl_price': getattr(self, 'tema_sl_price', 0.0),
            'signal_1': getattr(self, 'signal_1', 0.0),
            'signal_2': getattr(self, 'signal_2', 0.0),
            'is_w_rebound': getattr(self, 'is_w_rebound', False),
            'buy_time': getattr(self, 'buy_time', 0.0),
            'm_resistance_line': getattr(self, 'm_resistance_line', 0.0),
            'm_partial_sold': getattr(self, 'm_partial_sold', False),
            'm_touch_high': getattr(self, 'm_touch_high', 0.0),
            'quick_partial_sold': getattr(self, 'quick_partial_sold', False),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TradeState':
        state = cls()
        state.is_holding = data.get('is_holding', False)
        state.trade_ended = data.get('trade_ended', False)
        time_str = data.get('first_buy_candle_time')
        state.first_buy_candle_time = pd.to_datetime(time_str) if time_str else None
        state.added_on = data.get('added_on', False)
        state.first_qty = data.get('first_qty', 0)
        state.trailing_high = data.get('trailing_high', 0.0)
        state.initial_breakout_high = data.get('initial_breakout_high', 0.0)
        state.sold_once = data.get('sold_once', False)
        state.reentry_qty = data.get('reentry_qty', 0)
        state.sell_target = data.get('sell_target', 0.0)
        state.stop_loss = data.get('stop_loss', 0.0)
        state.buy_step = data.get('buy_step', 0)
        state.tema_sl_price = data.get('tema_sl_price', 0.0)
        state.signal_1 = data.get('signal_1', 0.0)
        state.signal_2 = data.get('signal_2', 0.0)
        state.is_w_rebound = data.get('is_w_rebound', False)
        state.buy_time = data.get('buy_time', 0.0)
        state.m_resistance_line = data.get('m_resistance_line', 0.0)
        state.m_partial_sold = data.get('m_partial_sold', False)
        state.m_touch_high = data.get('m_touch_high', 0.0)
        state.quick_partial_sold = data.get('quick_partial_sold', False)
        return state

def calculate_trade_intensity(tick_data: list) -> dict:
    """최근 틱(체결) 데이터를 분석하여 매수/매도 체결 비율을 계산합니다."""
    if not tick_data or len(tick_data) < 2:
        return {"buy_vol": 0, "sell_vol": 0, "ratio": 0.0, "is_strong": False}

    buy_vol = 0
    sell_vol = 0

    for i, tick in enumerate(tick_data):
        vol = abs(int(tick.get("volume", tick.get("cnt", 0))))
        change = tick.get("change", None)

        if change is not None:
            if float(change) > 0:
                buy_vol += vol
            elif float(change) < 0:
                sell_vol += vol
            else:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5
        else:
            if i == 0:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5
                continue
            prev_price = float(tick_data[i - 1].get("price", tick_data[i - 1].get("close", 0)))
            cur_price = float(tick.get("price", tick.get("close", 0)))
            if cur_price > prev_price:
                buy_vol += vol
            elif cur_price < prev_price:
                sell_vol += vol
            else:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5

    ratio = (buy_vol / sell_vol) if sell_vol > 0 else 999.0
    is_strong = ratio >= 1.02

    return {
        "buy_vol": int(buy_vol),
        "sell_vol": int(sell_vol),
        "ratio": round(ratio, 2),
        "is_strong": is_strong,
    }


def calculate_smart_micro_flow(tick_data: list, min_ticket_val: float = 200_000) -> dict:
    """
    [순간 마이크로 오더플로우 (Smart Flow Trigger) 분석]
    최근 틱(체결) 데이터를 분석하여:
    1. 순간 +호가(매수) 체결 횟수 (buy_ticks)
    2. 순간 매수 거래량 (buy_vol)
    3. 순간 매수 거래대금 (buy_amount)
    4. 건당 평균 매수대금 (avg_ticket_size = buy_amount / buy_ticks)
    5. 세력 큰손 체결 여부 (is_whale: 단일 1,000만원 이상 또는 평균 300만원 이상)
    6. 순간 체결강도 (intensity_ratio = buy_vol / sell_vol)
    7. 자전거래 1주 낚시 여부 (is_fake_wash: 건당 평균 min_ticket_val 미만)
    8. 스마트 돌파 발화 여부 (is_smart_breakout)
    """
    default_res = {
        "buy_ticks": 0,
        "sell_ticks": 0,
        "buy_vol": 0,
        "sell_vol": 0,
        "buy_amount": 0.0,
        "sell_amount": 0.0,
        "avg_ticket_size": 0.0,
        "intensity_ratio": 1.0,
        "is_whale": False,
        "is_fake_wash": False,
        "is_smart_breakout": False,
        "reason": "틱 데이터 부족"
    }
    if not tick_data or len(tick_data) < 2:
        return default_res

    buy_ticks = 0
    sell_ticks = 0
    buy_vol = 0
    sell_vol = 0
    buy_amount = 0.0
    sell_amount = 0.0
    max_single_buy_amt = 0.0

    for i, tick in enumerate(tick_data):
        try:
            vol = abs(int(tick.get("volume", tick.get("cnt", 0))))
            price = float(tick.get("price", tick.get("close", 0)))
            amt = price * vol
            change = tick.get("change", None)

            is_buy = False
            is_sell = False

            if change is not None:
                if float(change) > 0:
                    is_buy = True
                elif float(change) < 0:
                    is_sell = True
            else:
                open_p = float(tick.get("open", price))
                if price > open_p:
                    is_buy = True
                elif price < open_p:
                    is_sell = True
                elif i > 0:
                    prev_price = float(tick_data[i - 1].get("price", tick_data[i - 1].get("close", 0)))
                    if price > prev_price:
                        is_buy = True
                    elif price < prev_price:
                        is_sell = True
                    else:
                        high_p = float(tick.get("high", price))
                        low_p = float(tick.get("low", price))
                        if high_p > low_p and price == high_p:
                            is_buy = True
                        elif high_p > low_p and price == low_p:
                            is_sell = True

            if is_buy:
                buy_ticks += 1
                buy_vol += vol
                buy_amount += amt
                if amt > max_single_buy_amt:
                    max_single_buy_amt = amt
            elif is_sell:
                sell_ticks += 1
                sell_vol += vol
                sell_amount += amt
            else:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5
                buy_amount += amt * 0.5
                sell_amount += amt * 0.5
        except (ValueError, TypeError) as e:
            continue

    avg_ticket_size = (buy_amount / buy_ticks) if buy_ticks > 0 else 0.0
    intensity_ratio = (buy_vol / sell_vol) if sell_vol > 0 else 999.0

    # 세력 큰손 판별
    is_whale = (max_single_buy_amt >= 10_000_000) or (avg_ticket_size >= 3_000_000)

    # 자전거래 1주 낚시 판별 (체결 횟수는 많은데 건당 평균이 min_ticket_val 미만)
    is_fake_wash = (buy_ticks >= 8) and (avg_ticket_size < min_ticket_val)

    # 스마트 수급 폭발 (Smart Breakout Flow):
    # 매수 체결 6회 이상 & 체결강도 115% 이상 & 건당 평균 50만원 이상 & 순간 매수대금 1,500만원 이상
    is_smart_breakout = (
        (buy_ticks >= 6) and
        (intensity_ratio >= 1.15) and
        (avg_ticket_size >= 500_000) and
        (buy_amount >= 15_000_000) and
        (not is_fake_wash)
    )

    reason = (
        f"순간매수 {buy_ticks}회 | 매수대금 {buy_amount/1e8:.2f}억 | "
        f"건당평균 {avg_ticket_size/1e4:.0f}만원 | 체결강도 {intensity_ratio*100:.0f}%"
    )

    return {
        "buy_ticks": buy_ticks,
        "sell_ticks": sell_ticks,
        "buy_vol": int(buy_vol),
        "sell_vol": int(sell_vol),
        "buy_amount": buy_amount,
        "sell_amount": sell_amount,
        "avg_ticket_size": avg_ticket_size,
        "intensity_ratio": round(intensity_ratio, 2),
        "is_whale": is_whale,
        "is_fake_wash": is_fake_wash,
        "is_smart_breakout": is_smart_breakout,
        "reason": reason
    }
