"""
trading_bot.py - 일봉/30분봉 SMA돌파 + 가중5-20고가선 돌파 매수 + 15분봉 SMA 데드크로스 매도 봇
===========================================================================

구조:
  1. BuyManager  - 일봉 SMA20 돌파 + HH 돌파 / 30분봉 SMA260 돌파 + HH 돌파 매수
  2. SellManager - 15분봉 SMA5/SMA40 데드크로스 매도

전략 요약:
  - 매수: 조건검색식 편입 종목 → 일봉/30분봉 SMA 돌파 및 가중5-20 고가선(HH) 돌파 시 매수
  - 매도: 15분봉 SMA5가 SMA40 데드크로스 시 전량 시장가 매도
  - 오버나잇 허용, 매매 시간 제한 없음
  - 최대 30종목 보유 가능

실행 방법:
  python trading_bot.py                      # 전체 임무 실행
  python trading_bot.py --task buy           # 매수 봇만 실행
  python trading_bot.py --task sell          # 매도 봇만 실행
  python trading_bot.py --task buy sell      # 매수 + 매도 실행
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
from strategy_sell import analyze_sell_signals
from datetime import datetime, time as dtime

# real trading 폴더의 websocket_client를 가져오기 위한 경로 추가
real_trading_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'real trading'))
if real_trading_path not in sys.path:
    sys.path.insert(0, real_trading_path)

from websocket_client import KiwoomWebSocketClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# MarketIndexGuard - 코스피/코스닥 지수 급락 감지 및 매수 방어 모듈
# ═══════════════════════════════════════════════════════════════
class MarketIndexGuard:
    """
    KODEX 200(069500) 및 KODEX 코스닥150(229200)의 15분봉 및 당일 등락률을 모니터링하여,
    지수 급락(-1.5% 이하) 또는 폭락 시 신규 매수를 일시 중단(Pause)하는 안전장치.
    """
    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock):
        self.client = client
        self.api_lock = api_lock
        self.last_check_time = 0
        self.cached_status = {"safe": True, "kospi_chg": 0.0, "kosdaq_chg": 0.0, "reason": "정상"}

    async def check_market_health(self) -> dict:
        now = time.time()
        # 30초마다 지수 갱신 (API 부하 절감)
        if now - self.last_check_time < 30 and self.cached_status.get("checked", False):
            return self.cached_status

        kospi_chg = 0.0
        kosdaq_chg = 0.0
        kospi_safe = True
        kosdaq_safe = True
        warning_reasons = []

        try:
            # 1. 코스피 대표 (069500 KODEX 200) 및 코스닥 대표 (229200 KODEX 코스닥150) 15분봉 조회
            async with self.api_lock:
                df_kospi = await asyncio.to_thread(self.client.get_15m_candles, "069500")
                await asyncio.sleep(0.1)
                df_kosdaq = await asyncio.to_thread(self.client.get_15m_candles, "229200")
                await asyncio.sleep(0.1)

            if df_kospi is not None and not df_kospi.empty and len(df_kospi) >= 20:
                today_mask = df_kospi.index.date == df_kospi.index[-1].date()
                df_today = df_kospi[today_mask]
                if not df_today.empty:
                    open_p = float(df_today.iloc[0]['open'])
                    curr_p = float(df_today.iloc[-1]['close'])
                    kospi_chg = ((curr_p - open_p) / open_p) * 100
                    
                if kospi_chg <= -1.5:
                    kospi_safe = False
                    warning_reasons.append(f"코스피 급락({kospi_chg:+.2f}%)")

            if df_kosdaq is not None and not df_kosdaq.empty and len(df_kosdaq) >= 20:
                today_mask = df_kosdaq.index.date == df_kosdaq.index[-1].date()
                df_today = df_kosdaq[today_mask]
                if not df_today.empty:
                    open_p = float(df_today.iloc[0]['open'])
                    curr_p = float(df_today.iloc[-1]['close'])
                    kosdaq_chg = ((curr_p - open_p) / open_p) * 100
                    
                if kosdaq_chg <= -1.8:
                    kosdaq_safe = False
                    warning_reasons.append(f"코스닥 급락({kosdaq_chg:+.2f}%)")

            is_safe = kospi_safe and kosdaq_safe
            reason = "정상 (매수 허용)" if is_safe else ", ".join(warning_reasons) + " 발생 (매수 보류)"

            self.cached_status = {
                "safe": is_safe,
                "kospi_chg": kospi_chg,
                "kosdaq_chg": kosdaq_chg,
                "reason": reason,
                "checked": True
            }
            self.last_check_time = now

        except Exception as e:
            logger.warning(f"지수 확인 중 예외 발생: {e}")
            self.cached_status["safe"] = True

        return self.cached_status


# ═══════════════════════════════════════════════════════════════
# BuyManager - 일봉/30분봉 돌파 매수 + 지수 안전장치
# ═══════════════════════════════════════════════════════════════
class BuyManager:
    """
    일봉 SMA20 돌파 & HH 돌파 또는 30분봉 SMA260 돌파 & HH 돌파 시 종목당 30만원 매수.
    지수 급락 시에는 신규 매수를 일시 보류하여 자산을 보호함.
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict,
                 market_guard: MarketIndexGuard = None,
                 buy_amount: int = 300000, max_positions: int = 30):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist
        self.market_guard = market_guard
        self.buy_amount = buy_amount        # 종목당 매수 금액
        self.max_positions = max_positions  # 최대 보유 종목 수

    async def run(self, holdings: dict, unexecuted: list):
        """매수 감시 사이클 실행"""

        # ── 1. 시장 지수 급락 안전장치 검사 ──
        if self.market_guard:
            market_status = await self.market_guard.check_market_health()
            kospi_str = f"KOSPI: {market_status['kospi_chg']:+.2f}%"
            kosdaq_str = f"KOSDAQ: {market_status['kosdaq_chg']:+.2f}%"
            
            if not market_status['safe']:
                logger.warning(
                    f"🛑 [지수 급락 방어 발동] {kospi_str} | {kosdaq_str} -> "
                    f"{market_status['reason']}. 이번 사이클 신규 매수를 일시 중단합니다."
                )
                return
            else:
                logger.info(f"🌐 [시장 지수 상태] {kospi_str} | {kosdaq_str} -> 정상 (매수 탐색 진행)")

        # 보유 종목 수 제한 (30개)
        pending_buy_codes = {
            o['code'] for o in self.tracked_orders.values()
            if str(o.get('order_type', '')).startswith('buy')
        }
        total_positions = len(holdings) + len(pending_buy_codes)
        if total_positions >= self.max_positions:
            logger.info(
                f"⚠️ 최대 보유 종목 수({self.max_positions}개)에 도달. "
                f"(보유: {len(holdings)}개, 매수대기: {len(pending_buy_codes)}개) "
                f"신규 매수 탐색 스킵."
            )
            return

        for code, state in list(self.trade_states.items()):
            # 이미 매수 완료한 종목은 스킵
            if state.buy_step >= 1 or state.trade_ended:
                continue

            # watchlist에서 이탈한 종목은 스킵
            if code not in self.watchlist:
                continue

            # 중복 주문 방지
            is_unexecuted = any(o['code'] == code for o in self.tracked_orders.values())
            if is_unexecuted or any(u.get('stock_code') == code for u in unexecuted):
                continue

            name = self.watchlist.get(code, {}).get('name', code)

            # 30분봉(거시) + 일봉(필터) 데이터 동시 조회
            async with self.api_lock:
                df_30m = await asyncio.to_thread(self.client.get_30m_candles, code)
                await asyncio.sleep(0.1)
                daily_df = await asyncio.to_thread(self.client.get_daily_candles, code)
                await asyncio.sleep(0.1)

            if df_30m is None or df_30m.empty:
                continue

            signals = analyze_buy_signals(df_30m, None, daily_df)
            
            if signals.get('remove_watchlist'):
                logger.info(f"🗑️ [{name}] 이미 SMA20을 훌쩍 넘긴 종목. 감시대상에서 제외합니다.")
                if code in self.watchlist:
                    del self.watchlist[code]
                continue

            buy_price = signals['close']
            if buy_price > self.buy_amount:
                logger.info(f"⏭️ [{name}] 1주 가격({buy_price:,.0f}원)이 종목당 투자예산({self.buy_amount:,.0f}원)을 초과하여 감시대상에서 제외합니다.")
                if code in self.watchlist:
                    del self.watchlist[code]
                continue

            # ── 매수: 조건 충족 시 매수 ──
            if signals.get('buy'):
                buy_price = signals['close']
                tick = get_tick_size(int(buy_price))
                price_limit = int((int(buy_price) // tick) * tick)
                qty = self.buy_amount // int(buy_price)

                if qty > 0:
                    logger.info(
                        f"🟢 [{name}] 매수 신호! {signals['reason']} "
                        f"| LL: {signals['ll']:,.0f}"
                    )
                    async with self.api_lock:
                        order_no = await asyncio.to_thread(
                            self.client.place_buy_order, code, qty,
                            price=price_limit, order_type="00"
                        )
                    if order_no:
                        self.tracked_orders[order_no] = {
                            'code': code, 'qty': qty,
                            'time': time.time(), 'order_type': 'buy'
                        }
                        state.buy_step = 1
                        state.first_qty = qty
                        state.first_buy_candle_time = df_30m.index[-1]
                        state.signal_1 = signals['ll']  # LL 값 저장
                        logger.info(
                            f"✅ [{name}] 매수 주문 전송: "
                            f"{price_limit:,}원 x {qty}주 = "
                            f"{price_limit * qty:,}원 (주문번호: {order_no})"
                        )


# ═══════════════════════════════════════════════════════════════
# SellManager - 15분봉 SMA5/SMA40 데드크로스 매도
# ═══════════════════════════════════════════════════════════════
class SellManager:
    """
    15분봉 SMA5가 SMA40을 데드크로스할 때 전량 시장가 매도.
    수익/손실 여부 무관. 오버나잇 허용.
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist

    async def run(self, holdings: dict):
        """매도 감시 사이클 실행 (보유 종목만 대상)"""
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

            name = self.watchlist.get(code, {}).get('name')
            if not name:
                name = await asyncio.to_thread(self.client.get_stock_name, code)

            # 15분봉 데이터 조회
            async with self.api_lock:
                df_15m = await asyncio.to_thread(self.client.get_15m_candles, code)
                await asyncio.sleep(0.25)

            if df_15m is None or df_15m.empty or len(df_15m) < 45:
                continue

            signals = analyze_sell_signals(df_15m)
            
            latest_high = float(df_15m.iloc[-1]['high'])
            close_price = float(df_15m.iloc[-1]['close'])
            
            hold_info = holdings[code]
            buy_price = hold_info.get('buy_price', 0) if isinstance(hold_info, dict) else 0.0

            # ── 1. 트레일링 스탑을 위한 최고점(trailing_high) 갱신 ──
            if state.trailing_high < buy_price:
                state.trailing_high = buy_price
            state.trailing_high = max(state.trailing_high, latest_high)

            # ── 3. 매도 신호 (데드크로스 또는 트레일링 스탑) ──
            if signals.get('sell'):
                qty_sell = hold_info.get('qty', 1) if isinstance(hold_info, dict) else hold_info

                logger.info(f"🔴 [{name}] 매도 신호! {signals['reason']}")
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
                        f"✅ [{name}] 매도 주문 전송! "
                        f"{qty_sell}주 시장가 매도 (주문번호: {order_no})"
                    )


# ═══════════════════════════════════════════════════════════════
# TradingBot - 통합 메인 클래스
# ═══════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self, condition_name="Traiding",
                 enable_buy=True, enable_sell=True,
                 buy_amount=300000, max_positions=30):
        self.client = RealAPIAdapter()
        self.condition_name = condition_name
        self.watchlist = {}

        self.tracked_orders = {}  # { order_no: {'code', 'qty', 'time', 'order_type'} }
        self.trade_states = {}    # { code: TradeState }
        self.api_lock = asyncio.Lock()

        # ── 임무 활성화 설정 ──
        self.enable_buy = enable_buy
        self.enable_sell = enable_sell

        # ── 시장 지수 안전가드 생성 ──
        self.market_guard = MarketIndexGuard(self.client, self.api_lock)

        # ── 매니저 생성 ──
        self.buy_manager = BuyManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist,
            market_guard=self.market_guard,
            buy_amount=buy_amount, max_positions=max_positions
        ) if enable_buy else None

        self.sell_manager = SellManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist
        ) if enable_sell else None

    # ─────────────────────────────────────────────────
    # 조건검색 콜백
    # ─────────────────────────────────────────────────
    async def on_insert(self, code: str):
        logger.info(f"🟢 [조건검색 편입] 종목코드: {code}")
        if code not in self.watchlist:
            name = await asyncio.to_thread(self.client.get_stock_name, code)
            self.watchlist[code] = {'name': name, 'weight': 1.0}
            logger.info(f"✅ 관심종목 추가 완료: {name} ({code})")
            self.save_watchlist()

            if code not in self.trade_states:
                self.trade_states[code] = TradeState()

    async def on_delete(self, code: str):
        logger.info(f"🔴 [조건검색 이탈] 종목코드: {code}")
        if code in self.watchlist:
            name = self.watchlist[code]['name']
            # del self.watchlist[code] # 검색식 이탈 시 삭제하지 않고 영구 추적
            logger.info(f"📌 관심종목 이탈 감지됨, 삭제 없이 계속 추적합니다: {name} ({code})")

    # ─────────────────────────────────────────────────
    # 상태 저장/로드
    # ─────────────────────────────────────────────────
    def save_watchlist(self):
        watch_file = os.path.join(os.path.dirname(__file__), "today_picks.json")
        try:
            with open(watch_file, 'w', encoding='utf-8') as f:
                json.dump(self.watchlist, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"관심종목 저장 실패: {e}")

    def load_watchlist(self):
        watch_file = os.path.join(os.path.dirname(__file__), "today_picks.json")
        if os.path.exists(watch_file):
            try:
                with open(watch_file, 'r', encoding='utf-8') as f:
                    self.watchlist = json.load(f)
                logger.info(f"📂 저장된 관심종목 리스트를 불러왔습니다. ({len(self.watchlist)}개 종목)")
            except Exception as e:
                logger.error(f"관심종목 로드 실패: {e}")

    def load_states(self):
        self.load_watchlist()
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
        self.save_watchlist()
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
                    if order_type == 'buy':
                        # 매수 취소 → 다시 매수 가능 상태로 복귀
                        state.first_buy_candle_time = None
                        state.first_qty = 0
                        state.buy_step = 0

    # ─────────────────────────────────────────────────
    # 메인 사이클
    # ─────────────────────────────────────────────────
    async def run_cycle(self):
        tasks_str = []
        if self.enable_buy:
            tasks_str.append("매수")
        if self.enable_sell:
            tasks_str.append("매도")

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
                    state.trade_ended = True  # 당일 재매수 금지 (무한 반복 매매 방지)

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
                    state.buy_step = 1  # 재시작 후에는 매수 완료로 간주
                    state.added_on = True

        # 6. 매수 완료된 종목 관심종목에서 제외 (더 이상 매수 감시 안 함)
        for code in list(self.watchlist.keys()):
            state = self.trade_states.get(code)
            if state and (state.is_holding or state.trade_ended):
                name = self.watchlist[code]['name']
                logger.info(f"🗑️ [관심종목 정리] 매수(또는 매매 완료)된 종목을 감시 리스트에서 삭제합니다: {name} ({code})")
                del self.watchlist[code]

        # ═══════════════════════════════════════════════════════════
        # 각 매니저별 감시 실행
        # ═══════════════════════════════════════════════════════════

        # [매도 봇] - 최우선 실행 (매도가 가장 급함)
        if self.sell_manager:
            try:
                await self.sell_manager.run(holdings)
            except Exception as e:
                logger.error(f"❌ SellManager 에러: {e}")

        # [매수 봇] - 매도 처리 후 실행
        if self.buy_manager:
            try:
                await self.buy_manager.run(holdings, unexecuted)
            except Exception as e:
                logger.error(f"❌ BuyManager 에러: {e}")

        # 사이클 종료 후 상태 저장 (이때 save_watchlist도 함께 호출됨)
        self.save_states()

    async def start(self):
        """비동기 스케줄러: 10초 주기로 사이클 실행"""
        tasks_str = []
        if self.enable_buy:
            tasks_str.append("매수")
        if self.enable_sell:
            tasks_str.append("매도")

        logger.info("=" * 60)
        logger.info(" 🚀 [30분봉 WMA 고가돌파 매수 + 15분봉 WMA 데드크로스 매도 봇] 시작")
        logger.info(f" 활성 임무: {', '.join(tasks_str)}")
        logger.info(f" 전략: 30분봉 WMA(5,20) 골든크로스 고가(HH) 돌파 매수")
        logger.info(f"       15분봉 WMA(5,40) 데드크로스 매도")
        logger.info(f" 종목당 투자금: 300,000원 | 최대 30종목")
        logger.info(f" 오버나잇: 허용 | 시간 제한: 없음")
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
        description="30분봉 WMA 고가돌파 매수 + WMA 데드크로스 매도 트레이딩 봇"
    )
    parser.add_argument(
        '--task', nargs='+',
        choices=['buy', 'sell', 'all'],
        default=['all'],
        help="활성화할 임무 선택 (기본: all)"
    )
    parser.add_argument(
        '--condition', type=str, default='Traiding',
        help="키움증권 조건검색식 이름 (기본: Traiding)"
    )
    parser.add_argument(
        '--amount', type=int, default=300000,
        help="종목당 매수 금액 (기본: 300,000원)"
    )
    parser.add_argument(
        '--max-positions', type=int, default=30,
        help="최대 보유 종목 수 (기본: 30)"
    )

    args = parser.parse_args()

    # 임무 파싱
    tasks = set(args.task)
    if 'all' in tasks:
        enable_buy = True
        enable_sell = True
    else:
        enable_buy = 'buy' in tasks
        enable_sell = 'sell' in tasks

    bot = TradingBot(
        condition_name=args.condition,
        enable_buy=enable_buy,
        enable_sell=enable_sell,
        buy_amount=args.amount,
        max_positions=args.max_positions,
    )
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
