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
    is_strong = ratio >= 1.5

    return {
        "buy_vol": int(buy_vol),
        "sell_vol": int(sell_vol),
        "ratio": round(ratio, 2),
        "is_strong": is_strong,
    }
