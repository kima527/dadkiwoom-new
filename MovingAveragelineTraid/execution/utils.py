import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
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
        # ── 당일 매매 상태 자동 리셋용 ──
        self.last_action_date = None    # 마지막 매수/매도 처리 일자 ("YYYY-MM-DD")

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
            'last_action_date': getattr(self, 'last_action_date', None),
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
        state.last_action_date = data.get('last_action_date')
        return state

def _parse_tick_time(t: dict) -> Optional[float]:
    """틱 레코드에서 타임스탬프(초 단위 float)를 추출합니다."""
    raw = t.get("time") or t.get("cntr_tm") or t.get("dt") or t.get("timestamp")
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    raw_str = str(raw).strip()
    try:
        if len(raw_str) >= 19 and '-' in raw_str:
            return pd.to_datetime(raw_str).timestamp()
        elif len(raw_str) == 14 and raw_str.isdigit():
            return pd.to_datetime(raw_str, format="%Y%m%d%H%M%S").timestamp()
        elif len(raw_str) == 8 and ':' in raw_str:
            parts = raw_str.split(':')
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(raw_str) == 6 and raw_str.isdigit():
            return int(raw_str[:2]) * 3600 + int(raw_str[2:4]) * 60 + float(raw_str[4:6])
        else:
            return pd.to_datetime(raw_str).timestamp()
    except Exception:
        return None


@dataclass
class TickRecord:
    timestamp: float
    price: float
    volume: int
    is_buy: bool
    amount: float


class NextGenOrderFlowEngine:
    """
    [차세대 마이크로 오더플로우 체결강도 측정 엔진]
    
    1안. 가격 추진 속도(Price Velocity, %/sec) 및 1% 상승 소요 시간(seconds_to_rise_1pct)
    2안. 틱 도착 빈도 가속도(초당 매수 체결 건수 buy_tick_freq) 및 체결 횟수(buy_ticks)
    3안. 자전거래 1주 낚시 필터링(is_fake_wash) 및 큰손 티켓 크기 비대칭도(ticket_asymmetry)
    """
    def __init__(self, window_seconds: float = 5.0, min_valid_ticket_krw: float = 300_000):
        self.window_seconds = window_seconds
        self.min_valid_ticket_krw = min_valid_ticket_krw
        self.buffers: Dict[str, deque] = {}

    def add_tick(self, code: str, price: float, volume: int, is_buy: bool, timestamp: Optional[float] = None) -> Dict[str, Any]:
        now = timestamp if timestamp else time.time()
        amount = price * volume
        if code not in self.buffers:
            self.buffers[code] = deque()
        buf = self.buffers[code]
        buf.append(TickRecord(timestamp=now, price=price, volume=volume, is_buy=is_buy, amount=amount))
        while buf and now - buf[0].timestamp > self.window_seconds:
            buf.popleft()
        
        # 딕셔너리 리스트로 변환하여 분석
        tick_list = [
            {"price": t.price, "volume": t.volume, "change": 1 if t.is_buy else -1, "timestamp": t.timestamp}
            for t in buf
        ]
        return calculate_smart_micro_flow(tick_list, min_ticket_val=self.min_valid_ticket_krw)


def calculate_smart_micro_flow(tick_data: list, min_ticket_val: float = 300_000) -> dict:
    """
    [차세대 오더플로우 (Smart Flow Trigger) 종합 분석기]
    
    [적용된 1, 2, 3안]:
    - 1안: 가격 추진 속도 (velocity_pct_per_sec) & 1% 주파 소요 시간 (seconds_to_rise_1pct)
    - 2안: 체결 횟수 (buy_ticks) & 초당 매수 체결 빈도 (buy_tick_freq)
    - 3안: 자전거래 1주 낚시 차단 (is_fake_wash) & 큰손 티켓 비대칭도 (ticket_asymmetry) & 가격 탄력성 (price_elasticity)
    """
    default_res = {
        "buy_ticks": 0,
        "sell_ticks": 0,
        "buy_vol": 0,
        "sell_vol": 0,
        "buy_amount": 0.0,
        "sell_amount": 0.0,
        "avg_ticket_size": 0.0,
        "avg_sell_ticket": 0.0,
        "intensity_ratio": 1.0,
        "is_whale": False,
        "is_fake_wash": False,
        "is_smart_breakout": False,
        "velocity_pct_per_sec": 0.0,
        "seconds_to_rise_1pct": 999.0,
        "is_fast_velocity": False,
        "buy_tick_freq": 0.0,
        "tick_freq_surge": False,
        "ticket_asymmetry": 1.0,
        "block_buy_count": 0,
        "price_elasticity": 0.0,
        "score": 0.0,
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
    block_buy_count = 0  # 1,000만원 이상 큰손 체결 건수

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
                if amt >= 10_000_000:
                    block_buy_count += 1
            elif is_sell:
                sell_ticks += 1
                sell_vol += vol
                sell_amount += amt
            else:
                buy_vol += vol * 0.5
                sell_vol += vol * 0.5
                buy_amount += amt * 0.5
                sell_amount += amt * 0.5
        except (ValueError, TypeError):
            continue

    # ── 시간 경과(elapsed_sec) 산출 ──
    t_start = _parse_tick_time(tick_data[0])
    t_end = _parse_tick_time(tick_data[-1])
    if t_start is not None and t_end is not None and t_end >= t_start:
        elapsed_sec = max(t_end - t_start, 0.5)
    else:
        # 타임스탬프 누락 시 틱당 평균 0.3초 가산
        elapsed_sec = max(len(tick_data) * 0.3, 1.0)

    # ═══════════════════════════════════════════════════════════════
    # [1안] 가격 추진 속도 (Price Velocity) & 1% 주파 소요 시간
    # ═══════════════════════════════════════════════════════════════
    first_p = float(tick_data[0].get("price", tick_data[0].get("close", tick_data[0].get("open", 0))))
    last_p = float(tick_data[-1].get("price", tick_data[-1].get("close", 0)))
    if first_p > 0 and last_p > 0:
        price_change_pct = ((last_p - first_p) / first_p) * 100.0
    else:
        price_change_pct = 0.0

    velocity_pct_per_sec = price_change_pct / elapsed_sec
    seconds_to_rise_1pct = (1.0 / velocity_pct_per_sec) if velocity_pct_per_sec > 0 else 999.0
    # 1% 주파 소요 시간이 25초 이내(초당 +0.04% 이상)면 강력 추진 돌파
    is_fast_velocity = (velocity_pct_per_sec >= 0.04) or (0 < seconds_to_rise_1pct <= 25.0)

    # ═══════════════════════════════════════════════════════════════
    # [2안] 체결 횟수 (Tick Frequency) & 초당 틱 도착 빈도 가속도
    # ═══════════════════════════════════════════════════════════════
    buy_tick_freq = buy_ticks / elapsed_sec
    tick_freq_surge = (buy_ticks >= 5) and (buy_tick_freq >= 0.8)

    # ═══════════════════════════════════════════════════════════════
    # [3안] 자전거래 1주 낚시 차단 & 큰손 티켓 비대칭도 & 가격 탄력도
    # ═══════════════════════════════════════════════════════════════
    avg_ticket_size = (buy_amount / buy_ticks) if buy_ticks > 0 else 0.0
    avg_sell_ticket = (sell_amount / sell_ticks) if sell_ticks > 0 else 0.0
    ticket_asymmetry = (avg_ticket_size / avg_sell_ticket) if avg_sell_ticket > 0 else 1.0
    intensity_ratio = (buy_vol / sell_vol) if sell_vol > 0 else 999.0

    # 🚫 자전거래 1주 낚시 감지: 체결 횟수는 많은데(6회 이상) 건당 평균이 min_ticket_val(30만원) 미만
    is_fake_wash = (buy_ticks >= 6) and (avg_ticket_size < min_ticket_val)

    # 🐳 세력 큰손 판별
    is_whale = (
        (max_single_buy_amt >= 10_000_000) or
        (avg_ticket_size >= 3_000_000) or
        (block_buy_count >= 1) or
        (ticket_asymmetry >= 2.0 and buy_amount >= 20_000_000)
    )

    # 📈 단위 대금당 가격 탄력도 (1억원 순매수당 주가 상승률)
    net_buy_100m = (buy_amount - sell_amount) / 100_000_000.0
    if abs(net_buy_100m) >= 0.05:
        price_elasticity = price_change_pct / net_buy_100m
    else:
        price_elasticity = 0.0

    # ═══════════════════════════════════════════════════════════════
    # [1, 2, 3안 융합] 스마트 돌파 발화 판정 (Smart Breakout)
    # ═══════════════════════════════════════════════════════════════
    is_smart_breakout = (
        (not is_fake_wash) and                                  # [3안] 1주 낚시 자전거래 완전 배제
        (is_fast_velocity or velocity_pct_per_sec >= 0.03) and # [1안] 1% 주파속도 25초 이내 또는 초당 +0.03% 이상 추진
        (buy_ticks >= 5 and buy_tick_freq >= 0.8) and          # [2안] 매수 체결 5회 이상 & 초당 0.8회 이상 긁기
        (intensity_ratio >= 1.15) and                          # 순간 체결강도 115% 이상
        (avg_ticket_size >= 500_000 or is_whale) and           # [3안] 평균 매수대금 50만원 이상 또는 큰손 개입
        (buy_amount >= 15_000_000)                             # 순간 매수대금 1,500만원 이상
    )

    # ── 종합 점수 산출 (0 ~ 100점) ──
    score = min(
        max(velocity_pct_per_sec * 250, 0.0) +
        min(intensity_ratio * 15, 30.0) +
        min(buy_tick_freq * 10, 20.0) +
        (block_buy_count * 10) +
        min(ticket_asymmetry * 5, 15.0),
        100.0
    )
    if is_fake_wash:
        score *= 0.2  # 낚시 자전거래 적발 시 80% 감점

    reason = (
        f"1%주파 {seconds_to_rise_1pct:.1f}초({velocity_pct_per_sec:+.2f}%/s) | "
        f"체결 {buy_ticks}건(초당 {buy_tick_freq:.1f}회) | "
        f"건당 {avg_ticket_size/1e4:.0f}만원(큰손 {block_buy_count}건, 비대칭 {ticket_asymmetry:.1f}배) | "
        f"체결강도 {intensity_ratio*100:.0f}%"
    )

    return {
        "buy_ticks": buy_ticks,
        "sell_ticks": sell_ticks,
        "buy_vol": int(buy_vol),
        "sell_vol": int(sell_vol),
        "buy_amount": buy_amount,
        "sell_amount": sell_amount,
        "avg_ticket_size": avg_ticket_size,
        "avg_sell_ticket": avg_sell_ticket,
        "intensity_ratio": round(intensity_ratio, 2),
        "is_whale": is_whale,
        "is_fake_wash": is_fake_wash,
        "is_smart_breakout": is_smart_breakout,
        # ── 1안 지표 ──
        "velocity_pct_per_sec": round(velocity_pct_per_sec, 4),
        "seconds_to_rise_1pct": round(seconds_to_rise_1pct, 1),
        "is_fast_velocity": is_fast_velocity,
        # ── 2안 지표 ──
        "buy_tick_freq": round(buy_tick_freq, 2),
        "tick_freq_surge": tick_freq_surge,
        # ── 3안 지표 ──
        "ticket_asymmetry": round(ticket_asymmetry, 2),
        "block_buy_count": block_buy_count,
        "price_elasticity": round(price_elasticity, 2),
        # ── 종합 평가 ──
        "score": round(score, 1),
        "reason": reason
    }


def calculate_trade_intensity(tick_data: list) -> dict:
    """
    최근 틱(체결) 데이터를 분석하여 매수/매도 체결 비율 및 차세대 오더플로우를 계산합니다.
    기존 코드와의 100% 하위 호환성을 보장하면서, 1안(속도), 2안(빈도), 3안(낚시방어/티켓)을 통합 제공합니다.
    """
    if not tick_data or len(tick_data) < 2:
        return {
            "buy_vol": 0, "sell_vol": 0, "ratio": 0.0, "is_strong": False,
            "velocity_pct_per_sec": 0.0, "seconds_to_rise_1pct": 999.0,
            "buy_tick_freq": 0.0, "ticket_asymmetry": 1.0,
            "is_fake_wash": False, "is_smart_breakout": False
        }

    flow = calculate_smart_micro_flow(tick_data)
    ratio = flow.get("intensity_ratio", 1.0)
    is_fake_wash = flow.get("is_fake_wash", False)
    # [3안 방어] 체결강도 102% 이상이더라도 1주 자전거래 낚시인 경우 강력 배제!
    is_strong = (ratio >= 1.02) and (not is_fake_wash)

    res = {
        "buy_vol": flow.get("buy_vol", 0),
        "sell_vol": flow.get("sell_vol", 0),
        "ratio": ratio,
        "is_strong": is_strong,
        "is_smart_breakout": flow.get("is_smart_breakout", False),
        "is_fake_wash": is_fake_wash,
        "velocity_pct_per_sec": flow.get("velocity_pct_per_sec", 0.0),
        "seconds_to_rise_1pct": flow.get("seconds_to_rise_1pct", 999.0),
        "buy_tick_freq": flow.get("buy_tick_freq", 0.0),
        "ticket_asymmetry": flow.get("ticket_asymmetry", 1.0),
        "block_buy_count": flow.get("block_buy_count", 0),
        "price_elasticity": flow.get("price_elasticity", 0.0),
        "score": flow.get("score", 0.0),
        "reason": flow.get("reason", "")
    }
    return res

