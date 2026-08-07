"""
trading_bot.py - 5분봉 분할매수 + TEMA 손절 + 3분봉 익절 통합 봇
===========================================================================

구조:
  1. BuyManager     - 5분봉 WMA 골든크로스 기반 분할매수 (50% + 50%)
  2. StopLossManager - 5분봉 TEMA 기반 손절 (손절가 하향 이탈 시 전량 매도)
  3. TakeProfitManager - 3분봉 SMA 데드크로스 기반 수익실현

각 매니저는 독립적으로 활성화/비활성화할 수 있으며,
하나의 프로세스 내에서 공유 상태(TradeState)와 API Lock을 통해 안전하게 동작합니다.

실행 방법:
  python trading_bot.py                          # 전체 임무 실행
  python trading_bot.py --task buy                # 매수 봇만 실행
  python trading_bot.py --task stoploss           # 손절 봇만 실행
  python trading_bot.py --task takeprofit         # 수익실현 봇만 실행
  python trading_bot.py --task buy stoploss       # 매수 + 손절만 실행
"""

import os
import sys
import json
import time
import asyncio
import logging
import argparse
from real_api_adapter import RealAPIAdapter
from utils import TradeState, get_tick_size
from strategy_buy import analyze_buy_signals
from strategy_stoploss import analyze_stoploss_signals, get_tema_stoploss_price
from strategy_takeprofit import analyze_takeprofit_signals
from datetime import datetime, time as dtime

# real trading 폴더의 websocket_client를 가져오기 위한 경로 추가
real_trading_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'real trading'))
if real_trading_path not in sys.path:
    sys.path.insert(0, real_trading_path)

from websocket_client import KiwoomWebSocketClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# BuyManager - 5분봉 WMA 골든크로스 분할매수
# ═══════════════════════════════════════════════════════════════
class BuyManager:
    """
    5분봉 WMA5/WMA20 골든크로스 기반 분할매수 매니저

    매수 1차 (50%): 골든크로스 발생 시점의 WMA5 값(Signal_1) 이상에서 매수
    매수 2차 (50%): 골든크로스 발생 시점의 고가(Signal_2)를 강하게 돌파 시 매수
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict,
                 buy_amount: int = 2500000):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist
        self.buy_amount = buy_amount  # 총 매수 금액 (1차+2차 합산)

    async def run(self, holdings: dict, unexecuted: list):
        """매수 감시 사이클 실행"""
        now = datetime.now().time()

        # 10시 이후에는 재돌파(sold_once) 종목만 허용
        is_after_10am = now >= dtime(10, 0)

        # 보유 종목 수 제한 (4개)
        pending_buy_codes = {
            o['code'] for o in self.tracked_orders.values()
            if str(o.get('order_type', '')).startswith('buy')
        }
        total_positions = len(holdings) + len(pending_buy_codes)
        if total_positions >= 4:
            logger.info(
                f"⚠️ 최대 보유 종목 수(4개)에 도달. "
                f"(보유: {len(holdings)}개, 매수대기: {len(pending_buy_codes)}개) "
                f"신규 매수 탐색 스킵."
            )
            return

        for code, state in list(self.trade_states.items()):
            # 이미 2차까지 매수 완료한 종목은 스킵
            if state.buy_step >= 2 or state.trade_ended:
                continue

            # 이미 보유 중인데 buy_step이 0이면 → 이전 버전 복구 상태
            if state.is_holding and state.buy_step == 0:
                state.buy_step = 2  # 이전 버전에서 이미 매수 완료로 간주
                continue

            # 10시 이후: sold_once가 아닌 순수 신규 종목은 스킵
            if is_after_10am and not state.sold_once and state.buy_step == 0:
                continue

            # watchlist에서 이탈한 종목은, 재돌파 대기 중이 아니면 스킵
            if code not in self.watchlist and not state.sold_once:
                continue

            # 이미 보유 중이고 1차까지만 완료 → 2차 매수만 시도
            # 미보유 상태 → 1차 매수 시도
            if state.buy_step == 1 and code not in holdings:
                # 1차 매수 주문 완료했는데 아직 체결 안 된 상태 → 스킵
                continue

            # 중복 주문 방지
            is_unexecuted = any(o['code'] == code for o in self.tracked_orders.values())
            if is_unexecuted or any(u.get('stock_code') == code for u in unexecuted):
                continue

            name = self.watchlist.get(code, {}).get('name', code)

            # 5분봉 데이터 조회
            async with self.api_lock:
                df_5m = await asyncio.to_thread(self.client.get_5m_candles, code)
                await asyncio.sleep(0.25)

            if df_5m is None or df_5m.empty or len(df_5m) < 25:
                continue

            signals = analyze_buy_signals(df_5m)

            # ── 1차 매수 (50%): 아직 매수하지 않은 상태 ──
            if state.buy_step == 0 and signals.get('buy_1'):
                buy_price = signals['close']
                half_amount = self.buy_amount // 2  # 50%
                tick = get_tick_size(int(buy_price))
                price_limit = int((int(buy_price) // tick) * tick)
                qty = int(half_amount // price_limit) if price_limit > 0 else 0

                if qty > 0:
                    # ★ 매수 진입 시점에 TEMA 손절가를 한 번 계산하여 고정
                    tema_sl = get_tema_stoploss_price(df_5m)
                    if tema_sl <= 0:
                        # TEMA 크로스가 아직 없으면 현재가 -5% 를 기본 손절로 설정
                        tema_sl = buy_price * 0.95
                        logger.warning(
                            f"⚠️ [{name}] TEMA 크로스 미발생, "
                            f"기본 손절가({tema_sl:,.0f}) 적용"
                        )

                    logger.info(
                        f"🟢 [{name}] 1차 매수 신호 (50%)! {signals['reason']} "
                        f"| 손절선(고정): {tema_sl:,.0f}"
                    )
                    async with self.api_lock:
                        order_no = await asyncio.to_thread(
                            self.client.place_buy_order, code, qty,
                            price=price_limit, order_type="00"
                        )
                    if order_no:
                        self.tracked_orders[order_no] = {
                            'code': code, 'qty': qty,
                            'time': time.time(), 'order_type': 'buy_1'
                        }
                        state.first_qty = qty
                        state.first_buy_candle_time = df_5m.index[-1]
                        state.buy_step = 1
                        state.signal_1 = signals['signal_1']
                        state.signal_2 = signals['signal_2']
                        state.tema_sl_price = tema_sl  # ★ 진입 시점 손절가 고정
                        logger.info(
                            f"✅ [{name}] 1차 매수 대기: "
                            f"{price_limit:,}원 x {qty}주 (주문번호: {order_no})"
                        )

            # ── 2차 매수 (50%): 1차 매수 진입 시점에 고정된 Signal_2(HH) 강하게 돌파 시 ──
            elif state.buy_step == 1:
                # 1차 매수가 체결되었는지 확인 (보유 중이어야 함)
                if code not in holdings:
                    continue

                if state.signal_2 <= 0:
                    continue

                latest = df_5m.iloc[-1]
                prev = df_5m.iloc[-2] if len(df_5m) >= 2 else latest
                
                close_price = float(latest['close'])
                prev_close = float(prev['close']) if pd.notna(prev['close']) else 0.0

                # 고정된 signal_2를 0.3% 초과 강하게 돌파 (이전 봉은 이하, 현재 봉은 초과)
                if close_price > state.signal_2 * 1.003 and prev_close <= state.signal_2:
                    buy_price = close_price
                half_amount = self.buy_amount // 2  # 나머지 50%
                tick = get_tick_size(int(buy_price))
                price_limit = int((int(buy_price) // tick) * tick)
                qty = int(half_amount // price_limit) if price_limit > 0 else 0

                if qty > 0:
                    logger.info(
                        f"🔵 [{name}] 2차 매수 신호 (50%)! {signals['reason']}"
                    )
                    async with self.api_lock:
                        order_no = await asyncio.to_thread(
                            self.client.place_buy_order, code, qty,
                            price=price_limit, order_type="00"
                        )
                    if order_no:
                        self.tracked_orders[order_no] = {
                            'code': code, 'qty': qty,
                            'time': time.time(), 'order_type': 'buy_2'
                        }
                        state.buy_step = 2
                        state.added_on = True
                        logger.info(
                            f"✅ [{name}] 2차 매수 대기: "
                            f"{price_limit:,}원 x {qty}주 (주문번호: {order_no})"
                        )


# ═══════════════════════════════════════════════════════════════
# StopLossManager - 매수 진입 시 고정된 TEMA 손절가 기반 손절
# ═══════════════════════════════════════════════════════════════
class StopLossManager:
    """
    매수 진입 시점에 BuyManager가 계산한 TEMA 손절가(state.tema_sl_price)를
    기준으로 현재가가 하향 이탈하면 전량 시장가 매도.

    ★ TEMA는 매 사이클마다 재계산하지 않음 → 진입 시 고정된 값만 사용.
    ★ 봇 재시작 등으로 tema_sl_price가 0인 경우에만 복구용으로 재계산.
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist

    async def run(self, holdings: dict):
        """손절 감시 사이클 실행 (보유 종목만 대상)"""
        for code in list(holdings.keys()):
            state = self.trade_states.get(code)
            if not state or not state.is_holding:
                continue

            # 이미 매도 주문이 진행 중이면 스킵
            is_sell_pending = any(
                o['code'] == code and o.get('order_type') == 'sell'
                for o in self.tracked_orders.values()
            )
            if is_sell_pending:
                continue

            name = self.watchlist.get(code, {}).get('name', code)

            # ★ 진입 시 고정된 손절가가 없으면 복구용으로 한 번만 계산
            if state.tema_sl_price <= 0:
                async with self.api_lock:
                    df_5m = await asyncio.to_thread(self.client.get_5m_candles, code)
                    await asyncio.sleep(0.25)
                if df_5m is not None and not df_5m.empty and len(df_5m) >= 25:
                    recovered_sl = get_tema_stoploss_price(df_5m)
                    if recovered_sl > 0:
                        state.tema_sl_price = recovered_sl
                        logger.info(
                            f"🔄 [{name}] 손절가 복구 완료: {recovered_sl:,.0f}"
                        )
                    else:
                        # TEMA 크로스 자체가 없는 경우 매입가 -5% 기본 손절
                        hold_info = holdings[code]
                        buy_price = hold_info.get('buy_price', 0) if isinstance(hold_info, dict) else 0.0
                        if buy_price > 0:
                            state.tema_sl_price = buy_price * 0.95
                            logger.warning(
                                f"⚠️ [{name}] TEMA 크로스 미발생, "
                                f"매입가 기준 -5% 손절가({state.tema_sl_price:,.0f}) 적용"
                            )
                continue  # 복구한 사이클에서는 바로 적용하지 않고 다음 사이클에서 판단

            # ★ 현재가 조회 (5분봉 최신 종가)
            async with self.api_lock:
                df_5m = await asyncio.to_thread(self.client.get_5m_candles, code)
                await asyncio.sleep(0.25)

            if df_5m is None or df_5m.empty:
                continue

            # 컬럼명 소문자 통일
            col_map = {c: c.lower() for c in df_5m.columns if c.lower() in ('close',)}
            df_5m.rename(columns=col_map, inplace=True)
            close_price = float(df_5m.iloc[-1]['close'])

            # ── 손절 판단: 현재가 < 진입 시 고정된 TEMA 손절가 ──
            if close_price < state.tema_sl_price:
                hold_info = holdings[code]
                qty_sell = hold_info.get('qty', 1) if isinstance(hold_info, dict) else hold_info

                logger.info(
                    f"🔴 [{name}] TEMA 손절 신호! "
                    f"현재가({close_price:,.0f}) < 손절선({state.tema_sl_price:,.0f})"
                )
                async with self.api_lock:
                    order_no = await asyncio.to_thread(
                        self.client.place_sell_order, code, qty_sell,
                        price=0, order_type="03"  # 시장가 매도
                    )
                if order_no:
                    self.tracked_orders[order_no] = {
                        'code': code, 'qty': qty_sell,
                        'time': time.time(), 'order_type': 'sell'
                    }
                    state.sold_once = True
                    logger.info(
                        f"🚨 [{name}] 손절 매도 전송! "
                        f"{qty_sell}주 시장가 매도 (주문번호: {order_no})"
                    )


# ═══════════════════════════════════════════════════════════════
# TakeProfitManager - 3분봉 SMA 데드크로스 수익실현
# ═══════════════════════════════════════════════════════════════
class TakeProfitManager:
    """
    3분봉 SMA5가 SMA20을 데드크로스할 때,
    현재가가 매입단가보다 높으면(수익 중) 전량 수익실현.
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist

    async def run(self, holdings: dict):
        """수익실현 감시 사이클 실행 (보유 종목만 대상)"""
        for code in list(holdings.keys()):
            state = self.trade_states.get(code)
            if not state or not state.is_holding:
                continue

            # 이미 매도 주문이 진행 중이면 스킵
            is_sell_pending = any(
                o['code'] == code and o.get('order_type') == 'sell'
                for o in self.tracked_orders.values()
            )
            if is_sell_pending:
                continue

            name = self.watchlist.get(code, {}).get('name', code)
            hold_info = holdings[code]
            buy_price = hold_info.get('buy_price', 0) if isinstance(hold_info, dict) else 0.0

            # 3분봉 데이터 조회
            async with self.api_lock:
                df_3m = await asyncio.to_thread(self.client.get_3m_candles, code)
                await asyncio.sleep(0.25)

            if df_3m is None or df_3m.empty or len(df_3m) < 25:
                continue

            signals = analyze_takeprofit_signals(df_3m, buy_price=buy_price)

            # ── 수익실현 신호: 3분봉 SMA 데드크로스 + 수익 중 ──
            if signals.get('sell'):
                qty_sell = hold_info.get('qty', 1) if isinstance(hold_info, dict) else hold_info

                logger.info(f"💰 [{name}] 수익실현 신호! {signals['reason']}")
                async with self.api_lock:
                    order_no = await asyncio.to_thread(
                        self.client.place_sell_order, code, qty_sell,
                        price=0, order_type="03"  # 시장가 매도
                    )
                if order_no:
                    self.tracked_orders[order_no] = {
                        'code': code, 'qty': qty_sell,
                        'time': time.time(), 'order_type': 'sell'
                    }
                    state.sold_once = True
                    logger.info(
                        f"✅ [{name}] 수익실현 매도 전송! "
                        f"{qty_sell}주, 수익률 {signals.get('profit_pct', 0):.1f}% "
                        f"(주문번호: {order_no})"
                    )


# ═══════════════════════════════════════════════════════════════
# TradingBot - 통합 메인 클래스
# ═══════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self, condition_name="Traiding",
                 enable_buy=True, enable_stoploss=True, enable_takeprofit=True,
                 buy_amount=2500000):
        self.client = RealAPIAdapter()
        self.condition_name = condition_name
        self.watchlist = {}

        self.tracked_orders = {}  # { order_no: {'code', 'qty', 'time', 'order_type'} }
        self.trade_states = {}    # { code: TradeState }
        self.api_lock = asyncio.Lock()

        # ── 임무 활성화 설정 ──
        self.enable_buy = enable_buy
        self.enable_stoploss = enable_stoploss
        self.enable_takeprofit = enable_takeprofit

        # ── 매니저 생성 ──
        self.buy_manager = BuyManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist,
            buy_amount=buy_amount
        ) if enable_buy else None

        self.stoploss_manager = StopLossManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist
        ) if enable_stoploss else None

        self.takeprofit_manager = TakeProfitManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist
        ) if enable_takeprofit else None

    # ─────────────────────────────────────────────────
    # 조건검색 콜백
    # ─────────────────────────────────────────────────
    async def on_insert(self, code: str):
        logger.info(f"🟢 [조건검색 편입] 종목코드: {code}")
        if code not in self.watchlist:
            name = await asyncio.to_thread(self.client.get_stock_name, code)
            self.watchlist[code] = {'name': name, 'weight': 1.0}
            logger.info(f"✅ 관심종목 추가 완료: {name} ({code})")

            if code not in self.trade_states:
                self.trade_states[code] = TradeState()

    async def on_delete(self, code: str):
        logger.info(f"🔴 [조건검색 이탈] 종목코드: {code}")
        if code in self.watchlist:
            name = self.watchlist[code]['name']
            del self.watchlist[code]
            logger.info(f"❌ 관심종목 제거 완료: {name} ({code})")

    # ─────────────────────────────────────────────────
    # 상태 저장/로드
    # ─────────────────────────────────────────────────
    def load_states(self):
        state_file = os.path.join(os.path.dirname(__file__), "trade_states.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for code, state_dict in data.items():
                        self.trade_states[code] = TradeState.from_dict(state_dict)
                logger.info(f"💾 이전 상태 정보를 로드했습니다. ({len(self.trade_states)}개 종목)")
            except Exception as e:
                logger.error(f"상태 정보 로드 실패: {e}")

    def save_states(self):
        state_file = os.path.join(os.path.dirname(__file__), "trade_states.json")
        try:
            data = {code: state.to_dict() for code, state in self.trade_states.items()}
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"상태 정보 저장 실패: {e}")

    # ─────────────────────────────────────────────────
    # 미체결 주문 관리
    # ─────────────────────────────────────────────────
    async def manage_unexecuted_orders(self):
        """접수 후 3분(180초) 경과한 미체결 주문 취소"""
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if current_time - info['time'] > 180:
                logger.info(f"⏳ 3분 경과! 미체결 주문 자동 취소 진행 (종목: {info['code']})")
                async with self.api_lock:
                    await asyncio.to_thread(
                        self.client.cancel_order, order_no, info['code'], info['qty']
                    )
                del self.tracked_orders[order_no]

                state = self.trade_states.get(info['code'])
                if state:
                    order_type = info.get('order_type', 'buy')
                    if order_type == 'buy_1':
                        # 1차 매수 취소 → 다시 매수 가능 상태로 복귀
                        state.first_buy_candle_time = None
                        state.first_qty = 0
                        state.buy_step = 0
                    elif order_type == 'buy_2':
                        # 2차 매수 취소 → 2차 매수 재시도 가능
                        state.buy_step = 1

    # ─────────────────────────────────────────────────
    # 메인 사이클
    # ─────────────────────────────────────────────────
    async def run_cycle(self):
        now = datetime.now().time()

        if now < dtime(9, 0):
            logger.info("⏰ 장 시작 전입니다. 대기 중...")
            return

        tasks_str = []
        if self.enable_buy:
            tasks_str.append("매수")
        if self.enable_stoploss:
            tasks_str.append("손절")
        if self.enable_takeprofit:
            tasks_str.append("익절")

        logger.info(
            f"🔄 [전략 감시 사이클] 감시 종목: {len(self.trade_states)}개 | "
            f"활성 임무: {', '.join(tasks_str)}"
        )

        # 1. 미체결 주문 관리
        await self.manage_unexecuted_orders()

        # 2. 계좌 상태 조회
        holdings = await asyncio.to_thread(self.client.get_account_holdings)
        unexecuted = await asyncio.to_thread(self.client.get_unexecuted_orders)

        # 3. 체결된 주문을 tracked_orders에서 제거 (5초 유예)
        unexecuted_codes = [u.get('stock_code') for u in unexecuted]
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if info['code'] not in unexecuted_codes and (current_time - info['time'] > 5):
                logger.info(
                    f"✅ 주문 체결(또는 취소) 확인됨: 종목 {info['code']}, "
                    f"주문번호 {order_no}"
                )
                del self.tracked_orders[order_no]

        # 4. 잔고에서 사라진 종목 처리 (매도 체결 완료)
        for code, state in list(self.trade_states.items()):
            if state.is_holding and code not in holdings:
                is_sell_unexecuted = any(
                    o['code'] == code and o.get('order_type') == 'sell'
                    for o in self.tracked_orders.values()
                )
                if not is_sell_unexecuted:
                    logger.info(f"✅ 잔고 소진 확인 (매도 체결 완료): {code}")
                    state.is_holding = False
                    state.buy_step = 0  # 매도 완료 → 매수 단계 리셋

        if now >= dtime(15, 20):
            logger.info("⏰ 15:20 이후 - 신규 매수/매도 감시를 중단합니다.")
            return

        # 5. 보유 종목 상태 동기화
        for code in list(holdings.keys()):
            state = self.trade_states.get(code)
            if not state:
                logger.info(f"🔄 미등록 보유 종목 발견: {code}, 상태를 복구합니다.")
                state = TradeState()
                self.trade_states[code] = state

            if not state.is_holding:
                if state.first_buy_candle_time is not None:
                    logger.info(f"✅ 매수 체결 확인: {code} 보유 상태로 전환합니다.")
                    state.is_holding = True
                else:
                    hold_info = holdings[code]
                    sync_qty = hold_info.get('qty', 1) if isinstance(hold_info, dict) else hold_info
                    logger.info(
                        f"🔄 잔고 동기화: 봇 재시작으로 인해 {code}의 보유 상태를 "
                        f"True로 복구합니다. (수량: {sync_qty})"
                    )
                    state.is_holding = True
                    state.first_qty = sync_qty
                    state.buy_step = 2  # 재시작 후에는 매수 완료로 간주
                    state.added_on = True

        # ═══════════════════════════════════════════════════════════
        # 각 매니저별 감시 실행
        # ═══════════════════════════════════════════════════════════

        # [손절 봇] - 최우선 실행 (손절이 가장 급함)
        if self.stoploss_manager:
            try:
                await self.stoploss_manager.run(holdings)
            except Exception as e:
                logger.error(f"❌ StopLossManager 에러: {e}")

        # [수익실현 봇] - 손절 다음으로 실행
        if self.takeprofit_manager:
            try:
                await self.takeprofit_manager.run(holdings)
            except Exception as e:
                logger.error(f"❌ TakeProfitManager 에러: {e}")

        # [매수 봇] - 매도 처리 후 마지막으로 실행
        if self.buy_manager:
            try:
                await self.buy_manager.run(holdings, unexecuted)
            except Exception as e:
                logger.error(f"❌ BuyManager 에러: {e}")

        # 사이클 종료 후 상태 저장
        self.save_states()

    async def start(self):
        """비동기 스케줄러: 10초 주기로 사이클 실행"""
        tasks_str = []
        if self.enable_buy:
            tasks_str.append("매수")
        if self.enable_stoploss:
            tasks_str.append("손절")
        if self.enable_takeprofit:
            tasks_str.append("익절")

        logger.info("=" * 60)
        logger.info(" 🚀 [5분봉 분할매수 + TEMA 손절 + 3분봉 익절 통합 봇] 시작")
        logger.info(f" 활성 임무: {', '.join(tasks_str)}")
        logger.info(f" 전략: 5분봉 WMA 골든크로스 50/50 분할매수")
        logger.info(f"       5분봉 TEMA(5,20) 0.95배 손절선")
        logger.info(f"       3분봉 SMA(5,20) 데드크로스 수익실현")
        logger.info("=" * 60)

        self.load_states()

        self.ws_client = KiwoomWebSocketClient(
            target_condition_name=self.condition_name,
            on_insert=self.on_insert,
            on_delete=self.on_delete
        )
        asyncio.create_task(self.ws_client.run())

        await self.run_cycle()

        while True:
            await asyncio.sleep(10)  # 10초 주기
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"run_cycle 에러: {e}")


# ═══════════════════════════════════════════════════════════════
# 메인 진입점
# ═══════════════════════════════════════════════════════════════
async def main():
    parser = argparse.ArgumentParser(
        description="5분봉 분할매수 + TEMA 손절 + 3분봉 익절 통합 트레이딩 봇"
    )
    parser.add_argument(
        '--task', nargs='+',
        choices=['buy', 'stoploss', 'takeprofit', 'all'],
        default=['all'],
        help="활성화할 임무 선택 (기본: all)"
    )
    parser.add_argument(
        '--condition', type=str, default='Traiding',
        help="키움증권 조건검색식 이름 (기본: Traiding)"
    )
    parser.add_argument(
        '--amount', type=int, default=2500000,
        help="종목당 총 매수 금액 (기본: 2,500,000원, 1차+2차 합산)"
    )

    args = parser.parse_args()

    # 임무 파싱
    tasks = set(args.task)
    if 'all' in tasks:
        enable_buy = True
        enable_stoploss = True
        enable_takeprofit = True
    else:
        enable_buy = 'buy' in tasks
        enable_stoploss = 'stoploss' in tasks
        enable_takeprofit = 'takeprofit' in tasks

    bot = TradingBot(
        condition_name=args.condition,
        enable_buy=enable_buy,
        enable_stoploss=enable_stoploss,
        enable_takeprofit=enable_takeprofit,
        buy_amount=args.amount,
    )
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
