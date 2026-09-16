"""
trading_bot.py - 30분봉 260이평 W자 반등 우선 매수 + 15분봉 WMA 3-5 데드크로스 단일 매도 봇
===========================================================================

구조:
  1. BuyManager  - 15분봉 4대수식/수급변곡 + 30분봉 260이평 W자 반등 최우선 매수
  2. SellManager - 15분봉 WMA 3-5 데드크로스 단일 매도

전략 요약:
  - 매수: 15분봉 4대 수식 올인원 돌파 최우선 + 30분봉 260이평 W자 반등 매수
  - 매도: 15분봉 WMA 3-5 데드크로스 발생 시 전량 시장가(03) 매도
  - 오버나잇 허용, 세션 자동 연동 (NXT 프리 08:00 ~ KRX 정규 ~ NXT 애프터 20:00)
  - 종목당 500만원 / 최대 2종목 분산 보유 (총 1,000만원 한도)

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
import socket
import asyncio
import logging
import argparse
from real_api_adapter import RealAPIAdapter
from utils import TradeState, get_tick_size, calculate_trade_intensity
from strategy_buy import analyze_buy_signals
from strategy_sell import analyze_sell_signals
from strategy_15m_turnaround import evaluate_15m_entry, Turnaround15mParams
from strategy_15m_4formula_buy import evaluate_4formula_buy, Formula4Params
from db_logger import TradeDBLogger
from scan_tomorrow_picks import run_scanner
from theme_manager import ThemeManager
from datetime import datetime, time as dtime

# ═══════════════════════════════════════════════════════════════
# SingleInstanceLock - 봇 프로세스 중복 실행 방지 락 (Localhost Socket Lock)
# ═══════════════════════════════════════════════════════════════
class SingleInstanceLock:
    """
    로컬 TCP 포트 바인딩을 이용한 단일 인스턴스 보장 락.
    프로세스가 종료되거나 강제 종료되어도 OS가 포트를 즉시 회수하므로
    좀비 락 파일 문제 없이 100% 안전하게 중복 실행을 차단합니다.
    """
    def __init__(self, port: int = 59128):
        self.port = port
        self.sock = None

    def acquire(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.bind(('127.0.0.1', self.port))
            self.sock.listen(1)
            return True
        except OSError:
            return False

    def release(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

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
    지수 마지노선 이탈(코스피 시가 대비 -0.5% 이하, 코스닥 시가 대비 -0.8% 이하) 발생 시
    신규 매수를 선제적으로 일시 중단(Pause)하는 안전장치.
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
                last_dt = df_kospi.index[-1]
                target_date = last_dt.date() if hasattr(last_dt, 'date') else last_dt
                today_mask = [idx.date() == target_date if hasattr(idx, 'date') else idx == target_date for idx in df_kospi.index]
                df_today = df_kospi[today_mask]
                if not df_today.empty:
                    open_p = float(df_today.iloc[0]['open'])
                    curr_p = float(df_today.iloc[-1]['close'])
                    kospi_chg = ((curr_p - open_p) / open_p) * 100
                    if kospi_chg <= -0.5:
                        kospi_safe = False
                        warning_reasons.append(f"코스피 마지노선 이탈({kospi_chg:+.2f}% <= -0.5%)")

            if df_kosdaq is not None and not df_kosdaq.empty and len(df_kosdaq) >= 20:
                last_dt = df_kosdaq.index[-1]
                target_date = last_dt.date() if hasattr(last_dt, 'date') else last_dt
                today_mask = [idx.date() == target_date if hasattr(idx, 'date') else idx == target_date for idx in df_kosdaq.index]
                df_today = df_kosdaq[today_mask]
                if not df_today.empty:
                    open_p = float(df_today.iloc[0]['open'])
                    curr_p = float(df_today.iloc[-1]['close'])
                    kosdaq_chg = ((curr_p - open_p) / open_p) * 100
                    if kosdaq_chg <= -0.8:
                        kosdaq_safe = False
                        warning_reasons.append(f"코스닥 마지노선 이탈({kosdaq_chg:+.2f}% <= -0.8%)")

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
    일봉 SMA20 돌파 & HH 돌파 또는 30분봉 SMA260 돌파 & HH 돌파 시 종목당 500만원 매수.
    지수 급락 시에는 신규 매수를 일시 보류하여 자산을 보호함.
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict,
                 market_guard: MarketIndexGuard = None,
                 db_logger: TradeDBLogger = None,
                 buy_amount: int = 5000000, max_positions: int = 2):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist
        self.market_guard = market_guard
        self.db_logger = db_logger
        self.buy_amount = buy_amount        # 종목당 매수 금액 (500만원)
        self.max_positions = max_positions  # 최대 보유 종목 수 (기본: 2종목 분산 매매)
        self.params_15m = Turnaround15mParams(min_daily_supply_money=20.0)
        self.params_f4 = Formula4Params(min_supply_money=20.0)
        self._static_filter_cache = {}     # 당일 시가총액 & 5일 거래대금 정적 필터 캐시 {code: (passed: bool, date: str)}

    async def run(self, holdings: dict, unexecuted: list):
        """매수 감시 사이클 실행"""

        # ── 1. 시장 지수 급락 안전장치 검사 ──
        is_market_in_danger = False
        if self.market_guard:
            market_status = await self.market_guard.check_market_health()
            kospi_str = f"KOSPI: {market_status['kospi_chg']:+.2f}%"
            kosdaq_str = f"KOSDAQ: {market_status['kosdaq_chg']:+.2f}%"
            
            if not market_status['safe']:
                is_market_in_danger = True
                logger.warning(
                    f"🛑 [지수 급락 방어 모드] {kospi_str} | {kosdaq_str} -> "
                    f"{market_status['reason']}. 체결강도 150% 이상 강력 주도주 및 W자 반등 대장주만 선별 매수합니다."
                )
            else:
                logger.info(f"🌐 [시장 지수 상태] {kospi_str} | {kosdaq_str} -> 정상 (전체 매수 탐색 진행)")

        # 보유 종목 수 제한 (기본 2종목)
        pending_buy_codes = {
            o['code'] for o in self.tracked_orders.values()
            if str(o.get('order_type', '')).startswith('buy')
        }
        total_positions = len(holdings) + len(pending_buy_codes)
        if total_positions >= self.max_positions:
            logger.info(
                f"🎯 [2종목 분산 매매] 최대 보유 종목 수({self.max_positions}개) 도달. "
                f"(보유: {len(holdings)}개, 매수대기: {len(pending_buy_codes)}개) "
                f"신규 매수 탐색 스킵."
            )
            return

        buy_candidates = []

        for code, info in list(self.watchlist.items()):
            state = self.trade_states.setdefault(code, TradeState())
            
            # 이미 매수 완료한 종목은 스킵
            if state.buy_step >= 1 or state.trade_ended:
                continue

            # 중복 주문 방지
            is_unexecuted = any(o['code'] == code for o in self.tracked_orders.values())
            if is_unexecuted or any(u.get('stock_code') == code for u in unexecuted):
                continue

            name = info.get('name', code) if isinstance(info, dict) else str(info)
            weight = info.get('weight', 1.0) if isinstance(info, dict) else 1.0
            today_str = datetime.now().strftime("%Y-%m-%d")

            # ── [정적 필터 캐시 검사 (API 호출 병목 획기적 단축)] ──
            cached_filter = self._static_filter_cache.get(code)
            if cached_filter and cached_filter[1] == today_str:
                if not cached_filter[0]:
                    if code in self.watchlist:
                        del self.watchlist[code]
                    continue
                # 필터 통과한 종목은 데이터만 조회
                async with self.api_lock:
                    df_15m = await asyncio.to_thread(self.client.get_15m_candles, code)
                    await asyncio.sleep(0.04)
                    df_30m = await asyncio.to_thread(self.client.get_30m_candles, code)
                    await asyncio.sleep(0.04)
                    daily_df = await asyncio.to_thread(self.client.get_daily_candles, code)
                    await asyncio.sleep(0.04)
            else:
                # 최초 1회 정적 필터(시가총액 & 5일 거래대금) 검사 및 캐싱
                async with self.api_lock:
                    df_15m = await asyncio.to_thread(self.client.get_15m_candles, code)
                    await asyncio.sleep(0.04)
                    df_30m = await asyncio.to_thread(self.client.get_30m_candles, code)
                    await asyncio.sleep(0.04)
                    daily_df = await asyncio.to_thread(self.client.get_daily_candles, code)
                    await asyncio.sleep(0.04)

                if daily_df is None or len(daily_df) < 5:
                    continue

                # 5일 평균 거래대금 10억 미만 소외주 제외
                trade_val_5d = (daily_df['close'] * daily_df['volume']).tail(5).mean()
                if trade_val_5d < 1_000_000_000:
                    logger.info(f"⏭️ [{name}] 5일 평균 거래대금({trade_val_5d/1e8:.1f}억) 10억 미만으로 감시대상에서 제외합니다.")
                    self._static_filter_cache[code] = (False, today_str)
                    if code in self.watchlist:
                        del self.watchlist[code]
                    continue

                # 시가총액 10조 이상 초대형주 제외
                market_cap = await asyncio.to_thread(self.client.get_market_cap, code)
                if market_cap >= 10_000_000_000_000:
                    logger.info(f"⏭️ [{name}] 시가총액({market_cap/1e12:.1f}조원) 10조 이상 대형주로 감시대상에서 제외합니다.")
                    self._static_filter_cache[code] = (False, today_str)
                    if code in self.watchlist:
                        del self.watchlist[code]
                    continue

                self._static_filter_cache[code] = (True, today_str)

            if daily_df is None or len(daily_df) < 5:
                continue

            # ── 1. [최우선 0순위] 15분봉 4대 수식 완성 전략 평가 ──
            eval_f4 = evaluate_4formula_buy(code, name, df_15m, current_price=None, params=self.params_f4) if (df_15m is not None and not df_15m.empty) else {'should_buy': False}

            # ── 2. [1순위] 15분봉 수급 및 이평 변곡 전략 평가 ──
            eval_15m = evaluate_15m_entry(code, name, df_15m, daily_df, current_price=None, params=self.params_15m) if (df_15m is not None and not df_15m.empty) else {'should_buy': False}

            # ── 3. [2순위] 30분봉/일봉 이평 돌파 전략 평가 ──
            signals_30m = analyze_buy_signals(df_30m, None, daily_df, df_15m=df_15m) if (df_30m is not None and not df_30m.empty) else {'buy': False}
            
            if signals_30m.get('remove_watchlist'):
                logger.info(f"🗑️ [{name}] 이미 SMA20을 훌쩍 넘긴 종목. 감시대상에서 제외합니다.")
                if code in self.watchlist:
                    del self.watchlist[code]
                continue

            # 당일 최근 일봉 기준 수급(거래대금) 보너스 산출 (100억원당 +10점, 최대 +50점)
            latest_trade_val = (daily_df.iloc[-1]['close'] * daily_df.iloc[-1]['volume']) if (daily_df is not None and not daily_df.empty) else 0.0
            supply_money_100m = latest_trade_val / 100_000_000.0  # 억원 단위
            supply_bonus = min(supply_money_100m / 10.0, 50.0)    # 500억 이상이면 +50점 상한

            # 15분봉 4대 수식 올인원 신호 최우선 채택
            if eval_f4.get('should_buy'):
                buy_price = eval_f4['price']
                if buy_price > self.buy_amount:
                    continue
                base_score = 300.0
                final_score = (base_score + supply_bonus) * weight
                buy_candidates.append({
                    'code': code,
                    'name': name,
                    'state': state,
                    'signals': {
                        'buy': True,
                        'close': eval_f4['price'],
                        'target_price': eval_f4['price'],
                        'reason': eval_f4['reason'],
                        'll': eval_f4['price']
                    },
                    'df_30m': df_30m if df_30m is not None else df_15m,
                    'weight': weight,
                    'is_15m_4formula': True,
                    'is_15m_turnaround': False,
                    'is_w_rebound': False,
                    'base_score': base_score,
                    'supply_bonus': supply_bonus,
                    'final_score': final_score,
                    'priority_score': final_score
                })
            # 15분봉 수급 변곡 신호 채택
            elif eval_15m.get('should_buy'):
                buy_price = eval_15m['limit_price']
                if buy_price > self.buy_amount:
                    continue
                base_score = eval_15m['priority_score'] + 100.0
                final_score = (base_score + supply_bonus) * weight
                buy_candidates.append({
                    'code': code,
                    'name': name,
                    'state': state,
                    'signals': {
                        'buy': True,
                        'close': eval_15m['details']['close'],
                        'target_price': eval_15m['limit_price'],
                        'reason': f"🚀 [{eval_15m['combo_type']}] {eval_15m['reason']}",
                        'll': eval_15m['limit_price']
                    },
                    'df_30m': df_30m if df_30m is not None else df_15m,
                    'weight': weight,
                    'is_15m_4formula': False,
                    'is_15m_turnaround': True,
                    'is_w_rebound': False,
                    'base_score': base_score,
                    'supply_bonus': supply_bonus,
                    'final_score': final_score,
                    'priority_score': final_score
                })
            elif signals_30m.get('buy'):
                buy_price = signals_30m['close']
                if buy_price > self.buy_amount:
                    continue
                base_score = signals_30m.get('priority_score', 0.0)
                final_score = (base_score + supply_bonus) * weight
                buy_candidates.append({
                    'code': code,
                    'name': name,
                    'state': state,
                    'signals': signals_30m,
                    'df_30m': df_30m,
                    'weight': weight,
                    'is_15m_4formula': signals_30m.get('is_4formula_buy', False),
                    'is_15m_turnaround': False,
                    'is_w_rebound': signals_30m.get('is_w_rebound', False),
                    'base_score': base_score,
                    'supply_bonus': supply_bonus,
                    'final_score': final_score,
                    'priority_score': final_score
                })

        if not buy_candidates:
            return

        # ── 최우선 정렬 (통합 가중 점수: 전략 Base + 거래대금 수급 가산점 * 테마 가중치) ──
        buy_candidates.sort(
            key=lambda x: (
                1 if x.get('is_15m_4formula') else 0,
                1 if x.get('is_15m_turnaround') else 0,
                1 if x.get('is_w_rebound') else 0,
                x['final_score']
            ),
            reverse=True
        )

        # ── 정렬된 우선순위 순서대로 매수 집행 ──
        for candidate in buy_candidates:
            if total_positions >= self.max_positions:
                logger.info(f"⚠️ 매수 진행 중 최대 보유 종목 수({self.max_positions}개) 도달. 잔여 후보 매수 중단.")
                break

            logger.info(
                f"🏆 [최종 매수 선정 {candidate['name']}] 최종점수: {candidate['final_score']:.1f}점 "
                f"(기본: {candidate['base_score']:.1f}점 + 수급보너스: +{candidate['supply_bonus']:.1f}점, 테마배율: {candidate['weight']}x)"
            )

            code = candidate['code']
            name = candidate['name']
            state = candidate['state']
            signals = candidate['signals']
            df_30m = candidate['df_30m']
            is_w = candidate['is_w_rebound']

            # 매수 주문 가격: 3대 원칙 기준선(일봉 20선 / 30분봉 260선 / 실시간 3일선) 가격 그 자체로 지정가 매수!
            target_price = signals.get('target_price', signals['close'])
            buy_price = float(target_price) if target_price > 0 else signals['close']
            tick = get_tick_size(int(buy_price))
            price_limit = int((int(buy_price) // tick) * tick)

            # ── 틱 데이터 기반 체결강도 조회 및 스마트 1호가 공격 매수 판별 ──
            intensity_ratio = 1.0
            is_strong = False
            try:
                ticks = await asyncio.to_thread(self.client.get_tick_data, code)
                if ticks:
                    intensity_info = calculate_trade_intensity(ticks)
                    intensity_ratio = intensity_info.get('ratio', 1.0)
                    is_strong = intensity_info.get('is_strong', False)
            except Exception:
                pass

            # 지수 급락 방어 모드일 때는 W자 반등 대장주이거나 체결강도 150% 이상인 종목만 예외 매수 허용
            if is_market_in_danger:
                can_buy_in_danger = is_w or (is_strong and intensity_ratio >= 1.5)
                if not can_buy_in_danger:
                    logger.info(
                        f"⏸️ [{name}] 지수 급락 방어 중 - 체결강도({intensity_ratio * 100:.0f}%) 또는 W자 반등 기준 미달로 매수 보류"
                    )
                    continue
                else:
                    logger.info(
                        f"🔥 [{name}] 지수 급락 속 강력 주도주 예외 매수 승인! (W자반등={is_w}, 체결강도={intensity_ratio * 100:.0f}%)"
                    )

            is_aggressive = False
            if is_strong and intensity_ratio >= 1.5:
                price_limit = price_limit + tick
                is_aggressive = True
                logger.info(
                    f"⚡ [{name}] 체결강도 폭발({intensity_ratio * 100:.0f}%)! "
                    f"스마트 1호가 공격 매수 적용: {price_limit:,}원 (+1틱)"
                )

            qty = self.buy_amount // int(buy_price)

            # ── [중복 매수 원천 차단 이중 안전장치] ──
            # 1. 상태 객체 기준 이미 매수 완료/보유/당일매매종료 상태인지 재확인
            if state.buy_step >= 1 or state.is_holding or state.trade_ended:
                logger.info(
                    f"⏭️ [{name}] 이미 매수 처리되었거나 보유/종료된 종목입니다. "
                    f"(buy_step={state.buy_step}, is_holding={state.is_holding}) 중복 매수 스킵."
                )
                continue

            # 2. 현재 미체결/대기 중인 매수 주문이 있는지 재확인
            if any(o['code'] == code for o in self.tracked_orders.values()):
                logger.info(f"⏭️ [{name}] 이미 주문이 전송되어 대기 중이므로 중복 매수 스킵.")
                continue

            # 3. 실시간 계좌 잔고(holdings)에 이미 존재하는지 재확인
            if code in holdings:
                logger.info(f"⏭️ [{name}] 계좌 잔고에 이미 보유 중인 종목입니다. 상태를 동기화하고 중복 매수 스킵.")
                state.is_holding = True
                state.buy_step = 1
                continue

            if qty > 0:
                priority_tag = "🔥 [W자 반등 최우선]" if is_w else "🟢"
                logger.info(
                    f"{priority_tag} [{name}] 매수 신호 집행! (우선순위 점수: {candidate['priority_score']:.1f}) "
                    f"{signals['reason']} | LL: {signals['ll']:,.0f}"
                )
                async with self.api_lock:
                    order_no = await asyncio.to_thread(
                        self.client.place_buy_order, code, qty,
                        price=price_limit, order_type="00"
                    )
                    await asyncio.sleep(0.25)
                if order_no:
                    self.tracked_orders[order_no] = {
                        'code': code, 'qty': qty,
                        'time': time.time(), 'order_type': 'buy'
                    }
                    state.buy_step = 1
                    state.is_holding = True  # 선제적 보유 플래그 설정 (이중 매수 방어)
                    state.first_qty = qty
                    state.first_buy_candle_time = df_30m.index[-1]
                    state.signal_1 = signals['ll']  # LL 값 저장
                    state.is_w_rebound = is_w
                    state.buy_time = time.time()  # 매수 시각 기록 (30분 보호 유예용)
                    total_positions += 1
                    logger.info(
                        f"✅ [{name}] 매수 주문 전송: "
                        f"{price_limit:,}원 x {qty}주 = "
                        f"{price_limit * qty:,}원 (주문번호: {order_no})"
                    )
                    # SQLite DB에 매수 기록 저장
                    if self.db_logger:
                        self.db_logger.log_buy(
                            code=code, name=name, buy_price=price_limit,
                            buy_qty=qty, buy_reason=signals['reason'],
                            trade_intensity=intensity_ratio * 100,
                            is_aggressive=is_aggressive
                        )


# ═══════════════════════════════════════════════════════════════
# SellManager - 15분봉 WMA 3-5 데드크로스 매도 전용
# ═══════════════════════════════════════════════════════════════
class SellManager:
    """
    15분봉 WMA 3이 WMA 5를 하향 돌파(데드크로스)할 때만 시장가 전량 매도.
    장초반 강력 매수 후 상승 탄력이 꺾이는 꼭지 부근에서 신속히 이익을 확정하고 자금을 회전합니다.
    """

    def __init__(self, client: RealAPIAdapter, api_lock: asyncio.Lock,
                 trade_states: dict, tracked_orders: dict, watchlist: dict,
                 db_logger: TradeDBLogger = None):
        self.client = client
        self.api_lock = api_lock
        self.trade_states = trade_states
        self.tracked_orders = tracked_orders
        self.watchlist = watchlist
        self.db_logger = db_logger
        self.last_15m_fetch_time = {}  # TR 스로틀링 타이머 {code: float}

    async def run(self, holdings: dict):
        """매도 감시 사이클 실행 (보유 종목 대상 15분봉 3-5 WMA 데드크로스 감시)"""
        now = time.time()
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

            hold_info = holdings[code]
            buy_price = float(hold_info.get('buy_price', 0)) if isinstance(hold_info, dict) else 0.0
            current_price = float(hold_info.get('current_price', 0)) if isinstance(hold_info, dict) else 0.0
            qty_sell = hold_info.get('qty', 1) if isinstance(hold_info, dict) else hold_info

            # 15분봉 데이터 조회 (보유 2종목 미만이므로 매 사이클 신속 감시)
            async with self.api_lock:
                df_15m = await asyncio.to_thread(self.client.get_15m_candles, code)
                await asyncio.sleep(0.1)

            if df_15m is None or df_15m.empty or len(df_15m) < 5:
                continue

            # 15분봉 3-5 WMA 데드크로스 신호 판정
            signals = analyze_sell_signals(
                df_15m, buy_price=buy_price, current_price=current_price
            )

            # 15분봉 WMA 3 < WMA 5 데드크로스 발생 시에만 전량 시장가 매도 집행
            if signals.get('sell'):
                logger.info(f"🔴 [{name}] 15분봉 3-5 WMA 데드크로스 매도 신호 감지! {signals['reason']}")
                async with self.api_lock:
                    order_no = await asyncio.to_thread(
                        self.client.place_sell_order, code, qty_sell,
                        price=current_price if current_price > 0 else buy_price, order_type="03"
                    )
                if order_no:
                    self.tracked_orders[order_no] = {
                        'code': code, 'qty': qty_sell,
                        'time': time.time(), 'order_type': 'sell'
                    }
                    state.sold_once = True
                    state.is_holding = False
                    state.trade_ended = True
                    logger.info(f"✅ [{name}] 15분봉 3-5 WMA 데드크로스 시장가 매도 주문 전송 (주문번호: {order_no})")
                    # SQLite DB에 매도 손익 정산 기록
                    if self.db_logger:
                        sell_p = current_price if current_price > 0 else buy_price
                        self.db_logger.log_sell(
                            code=code, sell_price=sell_p,
                            sell_qty=qty_sell, sell_reason=signals.get('reason', '15분봉 3-5 WMA 데드크로스 매도')
                        )
                else:
                    logger.warning(f"⚠️ [{name}] 매도 주문 전송 실패! 다음 사이클에서 재시도합니다.")
            else:
                logger.debug(f"ℹ️ [{name}] 15분봉 3-5 WMA 정배열/상승 탄력 유지 중 (WMA3: {signals.get('wma3', 0):,.0f} >= WMA5: {signals.get('wma5', 0):,.0f}, 홀딩)")


# ═══════════════════════════════════════════════════════════════
# TradingBot - 통합 메인 클래스
# ═══════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self, condition_name="Traiding,traiding",
                 enable_buy=True, enable_sell=True,
                 buy_amount=5000000, max_positions=2):
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

        # ── SQLite 매매일지 로거 생성 ──
        self.db_logger = TradeDBLogger()
        self.cycle_count = 0
        self.auto_scanned_date = None  # 당일 20:00 자동 스캔 완료 일자 (중복 실행 방지)
        self.is_scanning = False

        # ── 실시간 테마 관리자 생성 ──
        self.theme_manager = ThemeManager()
        self.last_theme_refresh_time = 0

        # ── 매니저 생성 ──
        self.buy_manager = BuyManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist,
            market_guard=self.market_guard,
            db_logger=self.db_logger,
            buy_amount=buy_amount, max_positions=max_positions
        ) if enable_buy else None

        self.sell_manager = SellManager(
            self.client, self.api_lock,
            self.trade_states, self.tracked_orders, self.watchlist,
            db_logger=self.db_logger
        ) if enable_sell else None

    # ─────────────────────────────────────────────────
    # 조건검색 콜백
    # ─────────────────────────────────────────────────
    async def on_insert(self, code: str):
        logger.info(f"🟢 [조건검색 편입] 종목코드: {code}")
        if code not in self.watchlist:
            async with self.api_lock:
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
    # ─────────────────────────────────────────────────
    # 안전한 Atomic JSON 파일 저장 헬퍼
    # ─────────────────────────────────────────────────
    def _atomic_json_dump(self, filepath: str, data: dict, indent: int = 4):
        """임시 파일 작성 후 원자적(Atomic) 덮어쓰기로 파일 깨짐 및 데이터 유실 방지"""
        tmp_file = f"{filepath}.tmp"
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
            os.replace(tmp_file, filepath)
        except Exception as e:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            raise e

    def save_watchlist(self):
        watch_file = os.path.join(os.path.dirname(__file__), "today_picks.json")
        try:
            self._atomic_json_dump(watch_file, self.watchlist, indent=4)
        except Exception as e:
            logger.error(f"관심종목 저장 실패: {e}")

    def load_watchlist(self):
        watch_file = os.path.join(os.path.dirname(__file__), "today_picks.json")
        if os.path.exists(watch_file):
            try:
                with open(watch_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.watchlist.clear()
                    self.watchlist.update(data)
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
        state_file = os.path.join(os.path.dirname(__file__), "trade_states.json")
        try:
            data = {code: state.to_dict() for code, state in self.trade_states.items()}
            self._atomic_json_dump(state_file, data, indent=2)
        except Exception as e:
            logger.error(f"상태 정보 저장 실패: {e}")
        # watchlist(today_picks.json)도 함께 저장 (삭제된 종목 반영)
        self.save_watchlist()

    # ─────────────────────────────────────────────────
    # 장중 실시간 핫 테마 수집 및 가중치 동적 갱신
    # ─────────────────────────────────────────────────
    async def refresh_realtime_themes(self, force: bool = False):
        """장중 실시간 핫 테마 수집 및 관심종목 가중치(Top1~3: 1.35x, Top4~10: 1.25x, Top11~30: 1.15x) 동적 갱신 (15분 주기)"""
        now = time.time()
        if not force and (now - self.last_theme_refresh_time < 900):  # 15분(900초) 주기
            return

        try:
            logger.info("🔄 [장중 실시간 테마 갱신] 네이버증권 실시간 핫 테마 순위 재수집 중...")
            await asyncio.to_thread(self.theme_manager.load_top_themes, 30)
            self.last_theme_refresh_time = now

            # 관심종목 리스트 내 종목 가중치 즉시 동적 반영
            updated_count = 0
            for code, info in self.watchlist.items():
                if isinstance(info, dict):
                    new_w = self.theme_manager.get_stock_weight(code)
                    if info.get('weight') != new_w:
                        info['weight'] = new_w
                        updated_count += 1

            logger.info(
                f"✅ [실시간 테마 갱신 완료] 총 {len(self.watchlist)}개 관심종목 가중치 갱신 (가중치 변경: {updated_count}개 종목)"
            )
        except Exception as e:
            logger.warning(f"⚠️ 실시간 테마 갱신 중 예외 발생: {e}")

    # ─────────────────────────────────────────────────
    # 미체결 주문 관리
    # ─────────────────────────────────────────────────
    async def manage_unexecuted_orders(self):
        """접수 후 3분(180초) 경과한 미체결 주문 취소"""
        current_time = time.time()
        for order_no, info in list(self.tracked_orders.items()):
            if current_time - info['time'] > 180:
                logger.info(f"⏳ 3분 경과! 미체결 주문 자동 취소 진행 (종목: {info['code']}, 주문번호: {order_no})")
                async with self.api_lock:
                    await asyncio.to_thread(
                        self.client.cancel_order, order_no, info['code'], info['qty']
                    )
                del self.tracked_orders[order_no]

                state = self.trade_states.get(info['code'])
                if state:
                    order_type = str(info.get('order_type', 'buy'))
                    if order_type.startswith('buy'):
                        # 매수 취소 → 다시 매수 가능 상태로 복귀
                        state.first_buy_candle_time = None
                        state.first_qty = 0
                        state.buy_step = 0
                        state.is_holding = False

    # ─────────────────────────────────────────────────
    # 메인 사이클
    # ─────────────────────────────────────────────────
    async def run_cycle(self):
        tasks_str = []
        if self.enable_buy:
            tasks_str.append("매수")
        if self.enable_sell:
            tasks_str.append("매도")

        # 1. 미체결 주문 관리 (3분 경과 주문 자동 취소)
        await self.manage_unexecuted_orders()

        # 2. 계좌 상태 조회
        holdings = await asyncio.to_thread(self.client.get_account_holdings)
        unexecuted = await asyncio.to_thread(self.client.get_unexecuted_orders)

        # 3. 체결 확인 및 tracked_orders 동기화 (잔고에 들어왔을 때만 체결로 확정)
        for order_no, info in list(self.tracked_orders.items()):
            code = info['code']
            order_type = str(info.get('order_type', 'buy'))
            if order_type.startswith('buy'):
                # 매수 주문: 실제 계좌 잔고(holdings)에 들어왔을 때 체결 확정
                if code in holdings:
                    logger.info(
                        f"✅ 매수 주문 체결 확인됨: 종목 {code}, "
                        f"주문번호 {order_no}"
                    )
                    del self.tracked_orders[order_no]
            elif order_type.startswith('sell'):
                # 매도 주문: 계좌 잔고(holdings)에서 사라졌을 때 체결 확정
                if code not in holdings:
                    logger.info(
                        f"✅ 매도 주문 체결 확인됨: 종목 {code}, "
                        f"주문번호 {order_no}"
                    )
                    del self.tracked_orders[order_no]

        # 4. 잔고에서 사라진 종목 처리 (매도 체결 완료)
        for code, state in list(self.trade_states.items()):
            if state.is_holding and code not in holdings:
                is_sell_unexecuted = any(
                    o['code'] == code and str(o.get('order_type', '')).startswith('sell')
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
                    sync_buy_price = hold_info.get('buy_price', 0) if isinstance(hold_info, dict) else 0.0
                    sync_current_price = hold_info.get('current_price', 0) if isinstance(hold_info, dict) else 0.0
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
        # 각 매니저별 감시 실행:
        # 1. NXT 프리마켓:   08:00 ~ 08:50 (NXT 지정가 매매)
        # 2. KRX 정규장:    09:00 ~ 15:30 (정규장 실시간 매매)
        # 3. NXT 애프터마켓: 15:40 ~ 20:00 (NXT 지정가 매매, 오후 8시까지 연장 감시)
        # (08:50~09:00 정규장 준비, 15:30~15:40 애프터마켓 준비 구간은 대기)
        # ═══════════════════════════════════════════════════════════
        now_time = datetime.now().time()
        nxt_pre_open = dtime(8, 0, 0)
        nxt_pre_close = dtime(8, 50, 0)
        market_open = dtime(9, 0, 0)
        market_close = dtime(15, 30, 0)
        nxt_post_open = dtime(15, 40, 0)
        nxt_post_close = dtime(20, 0, 0)

        is_pre_session = (nxt_pre_open <= now_time < nxt_pre_close)
        is_regular_session = (market_open <= now_time <= market_close)
        is_post_session = (nxt_post_open <= now_time < nxt_post_close)

        is_active_session = (is_pre_session or is_regular_session or is_post_session)

        if not is_active_session:
            today_str = datetime.now().strftime("%Y-%m-%d")

            # ── [오후 8시(20:00) 애프터마켓 마감 직후 익일 공략주 자동 스캔 & 장전] ──
            if now_time >= nxt_post_close and self.auto_scanned_date != today_str and not self.is_scanning:
                self.auto_scanned_date = today_str
                self.is_scanning = True
                logger.info("=" * 65)
                logger.info(f"🌙 [20:00 애프터마켓 마감] 내일의 주도주/돌파 종목 자동 스캔을 시작합니다 ({today_str})...")
                logger.info("=" * 65)
                try:
                    # 키움 거래대금/등락률 상위 + 테마주 + 4대수식/W자반등 정밀 스캔
                    await asyncio.to_thread(run_scanner, max_picks=30)
                    self.load_watchlist()
                    logger.info(f"✨ [내일 관심종목 자동 장전 완료] 총 {len(self.watchlist)}개 종목이 today_picks.json에 저장되고 봇에 자동 로드되었습니다!")
                except Exception as e:
                    logger.error(f"❌ 20:00 자동 스캔 중 에러 발생: {e}")
                finally:
                    self.is_scanning = False

            if nxt_pre_close <= now_time < market_open:
                wait_reason = "08:50~09:00 정규장 개장 준비 구간 (NXT 프리마켓 마감)"
            elif market_close < now_time < nxt_post_open:
                wait_reason = "15:30~15:40 애프터마켓 개장 준비 구간 (KRX 정규장 마감)"
            elif now_time < nxt_pre_open:
                wait_reason = "08:00 NXT 프리마켓 개장 대기"
            else:
                wait_reason = "20:00 당일 전체 매매 세션(애프터마켓 포함) 마감 (익일 공략주 자동 장전 완료)"
            logger.info(
                f"⏳ [{wait_reason}] 현재 {now_time.strftime('%H:%M:%S')}. "
                f"(매매 세션: NXT 프리 08:00~08:50 / KRX 정규 09:00~15:30 / NXT 애프터 15:40~20:00) 잔고 동기화만 유지합니다."
            )
            self.save_states()
            return

        # [매도 봇] - 최우선 실행 (매도가 가장 급함)
        if self.sell_manager:
            try:
                await self.sell_manager.run(holdings)
            except Exception as e:
                logger.error(f"❌ SellManager 에러: {e}")

        # [매수 봇] - 매도 처리 후 실행
        if self.buy_manager:
            try:
                # 장중 실시간 핫 테마 수집 및 종목별 차등 가중치 동적 갱신 (15분 주기)
                await self.refresh_realtime_themes()
                await self.buy_manager.run(holdings, unexecuted)
            except Exception as e:
                logger.error(f"❌ BuyManager 에러: {e}")

        # 사이클 종료 후 상태 및 관심종목 저장 (save_states → save_watchlist 자동 호출)
        self.save_states()

        # 10사이클(약 100초)마다 일일 손익/승률 통계 요약 출력
        self.cycle_count += 1
        if self.cycle_count % 10 == 0 and self.db_logger:
            self.db_logger.print_daily_summary()

    async def start(self):
        """비동기 스케줄러: 10초 주기로 사이클 실행"""
        tasks_str = []
        if self.enable_buy:
            tasks_str.append("매수")
        if self.enable_sell:
            tasks_str.append("매도")

        logger.info("=" * 60)
        logger.info(" 🚀 [15분봉 수급변곡 최우선 스나이핑 + 30분봉 W자 반등 매수 봇] 시작")
        logger.info(f" 활성 임무: {', '.join(tasks_str)}")
        logger.info(f" 세션: [NXT 프리] 08:00~08:50 | [KRX 정규] 09:00~15:30 | [NXT 애프터] 15:40~20:00 (오후 8시까지 감시)")
        logger.info(f" 전략: [1순위] 15분봉 20억 수급 + 3일선 U턴 변곡 스나이퍼 매수 (Combo 3+4)")
        logger.info(f"       [2순위] 30분봉 260이평 W자 반등 종목 우선 매수")
        logger.info(f"       [3순위] 15분봉 3-20 골든크로스 / 3-5 더블 변곡 매수")
        logger.info(f"       [매도] 15분봉 WMA 3-5 데드크로스 발생 시 전량 시장가(03) 매도")
        logger.info(f" 매매 모드: 🎯 [최대 {self.buy_manager.max_positions if self.buy_manager else 2}종목 분산 모드] (종목당: {self.buy_manager.buy_amount if self.buy_manager else 5000000:,.0f}원 | 총 한도: {(self.buy_manager.buy_amount * self.buy_manager.max_positions) if self.buy_manager else 10000000:,.0f}원)")
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
        description="15분봉 수급변곡 + 30분봉 W자 반등 분산 트레이딩 봇"
    )
    parser.add_argument(
        '--task', nargs='+',
        choices=['buy', 'sell', 'all'],
        default=['all'],
        help="활성화할 임무 선택 (기본: all)"
    )
    parser.add_argument(
        '--condition', type=str, default='Traiding,traiding',
        help="키움증권 조건검색식 이름 (쉼표로 복수 지정 가능, 기본: Traiding,traiding)"
    )
    parser.add_argument(
        '--amount', type=int, default=5000000,
        help="종목당 매수 금액 (기본: 5,000,000원)"
    )
    parser.add_argument(
        '--max-positions', type=int, default=2,
        help="최대 보유 종목 수 (기본: 2 - 2종목 분산 매매)"
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
    lock = SingleInstanceLock(port=59128)
    if not lock.acquire():
        logger.error("=" * 60)
        logger.error("🛑 [중복 실행 방지] 이미 다른 trading_bot 프로세스가 실행 중입니다!")
        logger.error("   동일 종목 이중 매수 사고를 방지하기 위해 이 프로세스를 즉시 종료합니다.")
        logger.error("=" * 60)
        sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("프로그램을 종료합니다.")
    finally:
        lock.release()
