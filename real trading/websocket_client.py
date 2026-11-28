import asyncio
import time
import websockets
import json
import logging
from typing import Callable, Coroutine
import os
import config

# ⚠️ kiwoom_rest_api.config는 import 시점에 환경변수를 읽어 고정하므로
#    반드시 TokenManager import "이전에" 환경변수를 설정해야 한다.
os.environ["KIWOOM_API_KEY"] = config.KIWOOM_APP_KEY
os.environ["KIWOOM_API_SECRET"] = config.KIWOOM_REAL_APP_SECRET
os.environ["KIWOOM_USE_SANDBOX"] = "false"

import kiwoom_rest_api.config as _kw_config
from kiwoom_rest_api.auth.token import TokenManager

# 다른 모듈이 먼저 빈 환경변수로 import했더라도 키를 확실히 주입
_kw_config.API_KEY = config.KIWOOM_APP_KEY
_kw_config.API_SECRET = config.KIWOOM_REAL_APP_SECRET

logger = logging.getLogger(__name__)

SOCKET_URL = 'wss://api.kiwoom.com:10000/api/dostk/websocket'

class KiwoomWebSocketClient:
    def __init__(self, target_condition_name: str | list, on_insert: Callable, on_delete: Callable, on_real_tick: Callable = None, on_orderbook: Callable = None):
        self.uri = SOCKET_URL
        self.websocket = None
        self.connected = False
        self.keep_running = True
        self.token_manager = TokenManager()
        
        # 다중 조건검색식 지원 (쉼표 구분 문자열 또는 리스트 처리)
        if isinstance(target_condition_name, str):
            self.target_condition_names = [n.strip() for n in target_condition_name.split(',') if n.strip()]
        elif isinstance(target_condition_name, list):
            self.target_condition_names = [str(n).strip() for n in target_condition_name if str(n).strip()]
        else:
            self.target_condition_names = [str(target_condition_name).strip()]

        self.target_condition_map = {}      # {cond_sn: cond_name}
        self.target_condition_indices = set() # {cond_sn_str, ...}
        self.received_cnsrreq_seqs = set()    # 초기 CNSRREQ 응답 수신 완료된 일련번호 집합
        self.init_sync_event = None           # threading.Event (초기 조건검색 전수 수신 완료 시그널)
        self.default_stex_tp = "A"            # 'A': 통합(KRX+NXT 프리/정규/애프터 전 세션 대응), 'K': KRX 전용
        self._inflight_cnsrreq_seq = None
        self._inflight_cnsrreq_event = None
        self._inflight_cnsrreq_resp = None
        self._register_task = None
        self._loop = None
        self._subscribed_tick_codes = set()
        self._focus_ob_code = None
        self._last_top10_sync_key = None
        self._last_orderbook = {}
        self._last_tick_state = {}
        
        self.on_insert = on_insert
        self.on_delete = on_delete
        self.on_real_tick = on_real_tick
        self.on_orderbook = on_orderbook

    @staticmethod
    def _clean_stock_code(raw_code: str) -> str:
        """종목코드 정규화 (_AL/_NX 및 선행 'A' 1글자만 제거하여 6자리 영문/숫자 코드 보존)"""
        code = str(raw_code or "").replace("_AL", "").replace("_NX", "").strip()
        if code.startswith("A") and len(code) == 7:
            code = code[1:]
        if code.isdigit() and len(code) < 6:
            code = code.zfill(6)
        return code

    async def _invoke_callback(self, cb, code: str, cond_name: str = ""):
        """동기/비동기 조건검색 콜백을 인자 호환성을 유지하며 안전하게 호출합니다."""
        try:
            if asyncio.iscoroutinefunction(cb):
                asyncio.create_task(cb(code, cond_name))
            else:
                cb(code, cond_name)
        except TypeError:
            if asyncio.iscoroutinefunction(cb):
                asyncio.create_task(cb(code))
            else:
                cb(code)

    async def _register_conditions_seq(self):
        """허용 요청건수 제한(초당 5건, 105110)을 피하기 위해 순차 대기하며 조건검색을 등록합니다."""
        try:
            items = list(self.target_condition_map.items())
            for idx, (cond_sn, cond_name) in enumerate(items):
                if not self.connected or not self.keep_running:
                    break
                seq_str = str(cond_sn)
                stex_tp = self.default_stex_tp
                cont_yn = "N"
                next_key = ""
                cleared_900003_cnt = 0

                for _ in range(8):
                    req = {
                        "trnm": "CNSRREQ",
                        "seq": seq_str,
                        "search_type": "1",
                        "stex_tp": stex_tp,
                        "cont_yn": cont_yn,
                        "next_key": next_key,
                    }
                    self._inflight_cnsrreq_seq = seq_str
                    self._inflight_cnsrreq_resp = None
                    self._inflight_cnsrreq_event = asyncio.Event()

                    if cont_yn == "N":
                        logger.info(f"📡 실시간 조건검색 등록 요청 전송: [{cond_name}] (seq={seq_str}, stex_tp={stex_tp})")
                    await self.send_message(req)

                    try:
                        await asyncio.wait_for(self._inflight_cnsrreq_event.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"⏰ [조건식 '{cond_name}'(seq={seq_str})] CNSRREQ 응답 타임아웃")
                        break

                    resp = self._inflight_cnsrreq_resp or {}
                    rc = resp.get("return_code")
                    msg = resp.get("return_msg")

                    if rc in (0, "0", None):
                        if str(resp.get("cont_yn", "")).upper() == "Y" and str(resp.get("next_key", "")).strip():
                            cont_yn = "Y"
                            next_key = str(resp.get("next_key", "")).strip()
                            await asyncio.sleep(0.35)
                            continue
                        break
                    if str(rc) == "900003" and cleared_900003_cnt < 3:
                        cleared_900003_cnt += 1
                        wait_s = 0.6 * cleared_900003_cnt
                        logger.warning(
                            f"🔄 [조건식 '{cond_name}'(seq={seq_str})] 기등록 충돌(900003: {msg}) ➔ CNSRCLR 해제 후 {wait_s:.1f}초 뒤 재등록 ({cleared_900003_cnt}/3)"
                        )
                        try:
                            await self.send_message({"trnm": "CNSRCLR", "seq": seq_str})
                        except Exception as clr_err:
                            logger.warning(f"⚠️ CNSRCLR 전송 실패(seq={seq_str}): {clr_err}")
                        cont_yn = "N"
                        next_key = ""
                        await asyncio.sleep(wait_s)
                        continue
                    if str(rc) == "900001" and stex_tp != "K":
                        logger.warning(f"⚠️ [조건식 '{cond_name}'(seq={seq_str})] stex_tp={stex_tp} 미지원({msg}) ➔ KRX('K')로 폴백 재시도")
                        stex_tp = "K"
                        await asyncio.sleep(0.45)
                        continue
                    if str(rc) == "105110":
                        logger.warning(f"⏳ [조건식 '{cond_name}'(seq={seq_str})] 요청 건수 초과(105110) ➔ 1.2초 후 재시도")
                        await asyncio.sleep(1.2)
                        continue
                    logger.error(f"❌ [조건식 '{cond_name}'(seq={seq_str}) 등록 실패] return_code={rc} | return_msg={msg}")
                    break

                if idx < len(items) - 1:
                    await asyncio.sleep(0.45)
        finally:
            if self.init_sync_event and not self.init_sync_event.is_set():
                self.init_sync_event.set()

    async def refresh_token_preflight(self):
        """08:00 프리마켓 가동 전 강제 토큰 갱신 (Token Pre-flight Refresh)"""
        try:
            logger.info("🔑 [TokenManager] 08:00 프리마켓 가동 전 토큰 강제 사전 갱신 진행 중...")
            # TokenManager.get_token()에는 force_refresh 인자가 없으므로 캐시를 비워 재발급을 유도한다.
            self.token_manager._access_token = None
            self.token_manager._token_expiry = None
            token = self.token_manager.get_token()
            if token:
                logger.info("✅ [TokenManager] 신규 Access Token 사전 발급 완료 (유효기간 3시간 보장)")
            else:
                logger.error("❌ [TokenManager] 토큰이 비어 있습니다. APP_KEY/SECRET 설정을 확인하세요.")
            return token
        except Exception as e:
            logger.error(f"❌ [TokenManager] 사전 토큰 갱신 실패: {e}")
            return None

    async def connect(self):
        try:
            await self.refresh_token_preflight()
            self.websocket = await websockets.connect(self.uri, ping_interval=20, ping_timeout=20)
            self.connected = True
            logger.info("웹소켓 서버에 연결되었습니다. (ping_interval=20s 유지)")

            access_token = self.token_manager.get_token()
            if not access_token:
                logger.error("웹소켓 로그인 실패: 토큰이 없습니다.")
                return

            param = {
                'trnm': 'LOGIN',
                'token': access_token
            }

            logger.info("실시간 시세 서버로 로그인 패킷을 전송합니다.")
            await self.send_message(param)

        except Exception as e:
            logger.error(f'웹소켓 연결 에러: {e}')
            self.connected = False

    async def send_message(self, message):
        if not self.connected:
            await self.connect()
            
        if self.connected:
            if not isinstance(message, str):
                message = json.dumps(message)
            await self.websocket.send(message)

    async def subscribe_nxt_premarket(self, codes: list):
        """
        08:00 ~ 08:50 대체거래소(NXT) 프리마켓 실시간 구독 등록
        종목코드 뒤에 _NX를 붙여서 '0B'(주식체결), '0D'(주식호가잔량) 구독 요청
        """
        if not codes:
            return
        nxt_items = [f"{str(c).lstrip('A')}_NX" if not str(c).endswith('_NX') else str(c) for c in codes]
        msg = {
            "trnm": "REG",
            "grp_no": "1",
            "refresh": "1",
            "data": [
                {
                    "item": nxt_items,
                    "type": ["0B", "0D"]
                }
            ]
        }
        logger.info(f"⚡ [NXT 프리마켓] 대체거래소 실시간 구독 패킷 전송: {nxt_items}")
        await self.send_message(msg)

    async def switch_to_regular_session(self, codes: list):
        """
        09:00 정규장 개장 직후 세션 스위칭:
        1. _NX 대체거래소 웹소켓 해제 (UNREG)
        2. 일반 6자리 코드("078350") 정규장 웹소켓 재구독 (REG)
        """
        if not codes:
            return
        nxt_items = [f"{str(c).lstrip('A')}_NX" if not str(c).endswith('_NX') else str(c) for c in codes]
        unreg_msg = {
            "trnm": "UNREG",
            "grp_no": "1",
            "data": [{"item": nxt_items, "type": ["0B", "0D"]}]
        }
        logger.info(f"🔄 [09:00 세션 스위칭] NXT 프리마켓 웹소켓 해제 전송: {nxt_items}")
        await self.send_message(unreg_msg)
        await asyncio.sleep(0.5)

        raw_codes = [str(c).replace('_NX', '').lstrip('A') for c in codes]
        reg_msg = {
            "trnm": "REG",
            "grp_no": "2",
            "refresh": "1",
            "data": [{"item": raw_codes, "type": ["0B", "0D"]}]
        }
        logger.info(f"🚀 [09:00 세션 스위칭] KRX 정규장 웹소켓 재구독 전송: {raw_codes}")
        await self.send_message(reg_msg)

    async def subscribe_real_tick(self, code: str):
        """
        주식체결(0B) 실시간 데이터를 요청합니다.
        기존 grp_no='3' 배치 구독을 덮어쓰지 않도록 이미 구독 목록이 있으면 refresh='0'으로 추가합니다.
        (초기 조건검색 과다 편입으로 세션 구독 한도가 소진되지 않도록 grp_no='3'은 최대 80종목으로 제한하고,
         Top 10 핵심 감시 풀은 sync_top10_stream(grp_no='5')에서 0B+0D를 전용 보장합니다.)
        """
        clean_code = self._clean_stock_code(code)
        if not clean_code or clean_code in self._subscribed_tick_codes:
            return
        if len(self._subscribed_tick_codes) >= 80:
            return
        refresh_flag = "0" if self._subscribed_tick_codes else "1"
        req = {
            "trnm": "REG",
            "grp_no": "3",
            "refresh": refresh_flag,
            "data": [
                {
                    "item": [clean_code],
                    "type": ["0B"]
                }
            ]
        }
        self._subscribed_tick_codes.add(clean_code)
        logger.info(f"⚡ [실시간 주식체결(0B) REG 구독 등록] 종목: {clean_code} (refresh={refresh_flag})")
        await self.send_message(req)

    async def sync_top10_stream(self, codes: list, exchange_hint: str = "KRX"):
        """
        Top 10 + 보유 종목 전용 실시간 0B(주식체결)·0D(최우선호가) 스트림을 세션(KRX vs NXT _NX)에 맞춰 동기화합니다.
        전용 그룹(grp_no='5', refresh='1')을 사용해 1종목 보유 중에도 나머지 Top 9 전 종목의 체결강도를 실시간 누락 없이 계측합니다.
        """
        clean_list = []
        seen = set()
        for c in (codes or []):
            cc = self._clean_stock_code(c)
            if cc and cc.isalnum() and len(cc) == 6 and cc != "000000" and cc not in seen:
                seen.add(cc)
                clean_list.append(cc)
                if len(clean_list) >= 15:
                    break
        if not clean_list:
            return

        ex = "NXT" if str(exchange_hint).upper() == "NXT" else "KRX"
        items = [f"{cc}_NX" if ex == "NXT" else cc for cc in clean_list]
        sync_key = (tuple(items), ex)
        if sync_key == self._last_top10_sync_key:
            return

        self._last_top10_sync_key = sync_key
        req = {
            "trnm": "REG",
            "grp_no": "5",
            "refresh": "1",
            "data": [{"item": items, "type": ["0B", "0D"]}]
        }
        logger.info(f"📡 [Top10 실시간 0B+0D 배경계측 동기화({ex})] {len(items)}종목: {items}")
        await self.send_message(req)

    def sync_top10_stream_sync(self, codes: list, exchange_hint: str = "KRX"):
        """봇 메인 루프(동기 스레드)에서 Top 10 + 보유 종목 0B/0D 백그라운드 스트림을 안전하게 동기화합니다."""
        if not codes or not self.connected or not self._loop or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.sync_top10_stream(list(codes), exchange_hint=exchange_hint), self._loop)
        except Exception as e:
            logger.debug(f"Top10 0B+0D 동기화 예약 예외: {e}")

    async def sync_custom_stream(self, items: list):
        """혼합(KRX 6자리 + NXT '_NX') 종목 리스트에 대해 grp_no='5' 0B+0D 스트림을 동기화합니다."""
        clean_items = []
        seen = set()
        for raw in (items or []):
            s = str(raw or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            clean_items.append(s)
            if len(clean_items) >= 20:
                break
        if not clean_items:
            return
        sync_key = ("CUSTOM", tuple(clean_items))
        if sync_key == self._last_top10_sync_key:
            return
        self._last_top10_sync_key = sync_key
        req = {
            "trnm": "REG",
            "grp_no": "5",
            "refresh": "1",
            "data": [{"item": clean_items, "type": ["0B", "0D"]}]
        }
        logger.info(f"📡 [전용 0B+0D 시세 스트림 동기화] {len(clean_items)}종목: {clean_items}")
        await self.send_message(req)

    def sync_custom_stream_sync(self, items: list):
        """동기 루프에서 혼합(KRX + _NX) 0B+0D 스트림을 안전하게 동기화합니다."""
        if not items or not self.connected or not self._loop or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.sync_custom_stream(list(items)), self._loop)
        except Exception as e:
            logger.debug(f"전용 0B+0D 동기화 예약 예외: {e}")

    async def subscribe_focus_orderbook(self, code: str):
        """
        집중/보유 1종목에 한해 실시간 호가잔량(0D)을 구독하여 최우선 매도/매수 호가(ask1/bid1)를 확보합니다.
        (grp_no='4', refresh='1'로 1종목만 교체 구독해 트래픽·0B 그룹 간섭 원천 차단)
        """
        clean_code = self._clean_stock_code(code)
        if not clean_code or self._focus_ob_code == clean_code:
            return
        req = {
            "trnm": "REG",
            "grp_no": "4",
            "refresh": "1",
            "data": [{"item": [clean_code], "type": ["0D"]}]
        }
        self._focus_ob_code = clean_code
        logger.info(f"📘 [집중종목 실시간 호가(0D) REG 구독] 종목: {clean_code}")
        await self.send_message(req)

    def subscribe_focus_orderbook_sync(self, code: str):
        """봇 메인 루프(동기 스레드)에서 집중종목 0D 호가 구독을 안전하게 예약합니다."""
        clean_code = self._clean_stock_code(code)
        if not clean_code or not self.connected or not self._loop or self._loop.is_closed():
            return
        if self._focus_ob_code == clean_code:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.subscribe_focus_orderbook(clean_code), self._loop)
        except Exception as e:
            logger.debug(f"집중종목 0D 구독 예약 예외 ({clean_code}): {e}")

    async def receive_messages(self):
        while self.keep_running:
            try:
                msg = await self.websocket.recv()
                response = json.loads(msg)
                
                trnm = response.get('trnm')
                
                if trnm == 'PING':
                    await self.send_message(response)
                    continue

                if trnm == 'SYSTEM':
                    # 예: R10001 "동일한 App key로 접속이 되었습니다. 기존 세션은 종료가 됩니다"
                    # → 다른 스크립트가 같은 AppKey로 웹소켓 접속 시 봇 세션이 끊김 (자동 재연결됨)
                    sys_code = str(response.get('code', '') or '').strip()
                    if sys_code == 'R10001':
                        now_ts = time.time()
                        hist = getattr(self, '_r10001_timestamps', [])
                        hist = [t for t in hist if now_ts - t <= 30.0]
                        hist.append(now_ts)
                        self._r10001_timestamps = hist
                    logger.warning(f"⚠️ [웹소켓 SYSTEM] {response.get('code')} {response.get('message')}")
                    continue
                
                if trnm == 'LOGIN':
                    if response.get('return_code') != 0:
                        logger.error(f"웹소켓 로그인 실패: {response.get('return_msg')}")
                        await self.disconnect()
                    elif not self.target_condition_names:
                        logger.info("📡 웹소켓 로그인 성공! (시세 전용 0B/0D 모드 — 조건검색 생략)")
                        if self.init_sync_event:
                            self.init_sync_event.set()
                    else:
                        logger.info("웹소켓 로그인 성공! 조건식 목록을 요청합니다...")
                        req = {
                            "trnm": "CNSRLST"
                        }
                        asyncio.create_task(self.send_message(req))
                
                elif trnm == 'CNSRLST':
                    # 조건식 목록 응답
                    cond_list = response.get('data', [])
                    logger.info(f"📋 [키움 서버 조건검색식 목록 수신] 총 {len(cond_list)}개 등록 확인")
                    
                    self.target_condition_map.clear()
                    self.target_condition_indices.clear()
                    self.received_cnsrreq_seqs.clear()
                    
                    # 대소문자 무시 매칭을 위한 타겟 목록
                    targets_lower = {t.lower(): t for t in self.target_condition_names}

                    for cond in cond_list:
                        if len(cond) >= 2:
                            cond_sn = str(cond[0]).strip()
                            cond_name = cond[1].strip()
                            
                            # 정확 매칭 또는 대소문자 무시 매칭
                            if cond_name.lower() in targets_lower or cond_name in self.target_condition_names:
                                self.target_condition_map[cond_sn] = cond_name
                                self.target_condition_indices.add(cond_sn)
                                logger.info(f"🎯 목표 조건식 '{cond_name}' 발견! (일련번호: {cond_sn})")
                                
                    if self.target_condition_map:
                        logger.info(f"✅ 총 {len(self.target_condition_map)}개 목표 조건식 매칭 완료: {list(self.target_condition_map.values())}")
                        if self._register_task and not self._register_task.done():
                            self._register_task.cancel()
                        self._register_task = asyncio.create_task(self._register_conditions_seq())
                    else:
                        logger.error(f"❌ 조건식 목록에서 목표 조건식({self.target_condition_names})을 찾을 수 없습니다! 전체 목록: {cond_list}")
                        if self.init_sync_event:
                            self.init_sync_event.set()
                
                elif trnm == 'CNSRREQ':
                    # 초기 조건검색 포착 종목 리스트
                    rc = response.get('return_code')
                    ret_msg = response.get('return_msg')
                    seq_str = str(response.get('seq') or self._inflight_cnsrreq_seq or '').strip()
                    cond_name = self.target_condition_map.get(seq_str, f"seq:{seq_str}")

                    # 순차 등록 코루틴에 응답 전달
                    if rc not in (0, '0', None):
                        logger.warning(f"⚠️ [CNSRREQ 오류 응답] [{cond_name}](seq={seq_str}) return_code={rc} | return_msg={ret_msg}")
                        if self._inflight_cnsrreq_event and not self._inflight_cnsrreq_event.is_set():
                            self._inflight_cnsrreq_resp = response
                            self._inflight_cnsrreq_event.set()
                        continue

                    data_list = response.get('data') or []
                    captured_codes = []
                    for item in data_list:
                        code = self._clean_stock_code(item.get('jmcode', ''))
                        if code and code != "000000":
                            captured_codes.append(code)
                            await self._invoke_callback(self.on_insert, code, cond_name)

                    if captured_codes:
                        logger.info(f"🔔 [조건식 '{cond_name}'(seq={seq_str}) 초기 포착] {len(captured_codes)}종목 수신: {captured_codes}")
                        if self.on_real_tick:
                            # 다중 조건식(4개) 순차 등록 시 이전 조건식의 0B 구독이 refresh='1'에 덮어쓰이지 않도록 증분 병합 (80종목 한도)
                            slots_left = max(0, 80 - len(self._subscribed_tick_codes))
                            new_codes = [c for c in captured_codes if c not in self._subscribed_tick_codes][:slots_left]
                            if new_codes:
                                refresh_flag = "0" if self._subscribed_tick_codes else "1"
                                self._subscribed_tick_codes.update(new_codes)
                                reg_batch_msg = {
                                    "trnm": "REG",
                                    "grp_no": "3",
                                    "refresh": refresh_flag,
                                    "data": [{"item": new_codes, "type": ["0B"]}]
                                }
                                asyncio.create_task(self.send_message(reg_batch_msg))
                    else:
                        logger.info(f"📡 [조건식 '{cond_name}'(seq={seq_str}) 실시간 대기] 현재 초기 포착 0종목 (신규 편입 시 0.1초 즉시 포착)")

                    if seq_str and str(response.get('cont_yn', '')).upper() != 'Y':
                        self.received_cnsrreq_seqs.add(seq_str)
                    if self._inflight_cnsrreq_event and not self._inflight_cnsrreq_event.is_set():
                        self._inflight_cnsrreq_resp = response
                        self._inflight_cnsrreq_event.set()
                    if self.init_sync_event and len(self.received_cnsrreq_seqs) >= len(self.target_condition_indices):
                        self.init_sync_event.set()
                            
                elif trnm == 'REAL':
                    # 실시간 데이터
                    data_list = response.get('data') or []
                    for data_item in data_list:
                        name = data_item.get('name')
                        values = data_item.get('values', {})
                        
                        if name == '조건검색':
                            code = self._clean_stock_code(values.get('9001', ''))
                            evt_tp = values.get('843', '') # I: 편입, D: 이탈
                            raw_841 = str(values.get('841', '')).strip()
                            cond_idx = raw_841.split()[0] if raw_841 else ''
                            
                            if code and code != "000000" and cond_idx in self.target_condition_indices:
                                cond_name = self.target_condition_map.get(cond_idx, f"seq:{cond_idx}")
                                logger.info(f"🔔 [{cond_name}] 실시간 조건검색 신호: 종목코드={code}, 이벤트={evt_tp}")
                                if evt_tp == 'I':
                                    await self._invoke_callback(self.on_insert, code, cond_name)
                                    if self.on_real_tick:
                                        asyncio.create_task(self.subscribe_real_tick(code))
                                        
                                elif evt_tp == 'D':
                                    await self._invoke_callback(self.on_delete, code, cond_name)
                                        
                        elif name == '주식체결':
                            raw_code = str(values.get('9001') or data_item.get('item') or '')
                            tick_exch = 'NXT' if '_NX' in raw_code else 'KRX'
                            code = self._clean_stock_code(raw_code) # 종목코드
                            if not code or not code.isalnum() or code == "000000":
                                continue
                            # FID 10: 현재가(전일대비 부호), FID 15: 순간체결량('+' 매수체결 / '-' 매도체결), FID 13: 누적거래량, FID 228: 체결강도
                            try:
                                raw_price = float(str(values.get('10', 0) or 0).strip())
                                current_price = abs(raw_price)
                                raw_15 = str(values.get('15', '') or '').strip()
                                tick_qty = abs(int(float(raw_15.lstrip('+-') or 0)))
                                accum_volume = abs(int(float(str(values.get('13', 0) or 0).lstrip('+-') or 0)))
                                tick_time = str(values.get('20', '') or '').strip() # 체결시간
                                chegyul_gangdo = abs(float(str(values.get('228', 0) or 0).lstrip('+-') or 0))
                                ask1 = abs(float(str(values.get('27', 0) or 0).lstrip('+-') or 0))
                                bid1 = abs(float(str(values.get('28', 0) or 0).lstrip('+-') or 0))
                                ob_key = (code, tick_exch)
                                if (ask1 <= 0 or bid1 <= 0) and ob_key in self._last_orderbook:
                                    ob_ref = self._last_orderbook[ob_key]
                                    if (time.time() - ob_ref.get('ts', 0.0)) <= 15.0:
                                        ask1 = ask1 or float(ob_ref.get('ask1', 0.0) or 0.0)
                                        bid1 = bid1 or float(ob_ref.get('bid1', 0.0) or 0.0)

                                prev_st = self._last_tick_state.get(ob_key, {})
                                prev_price = float(prev_st.get('price', 0.0) or 0.0)
                                prev_is_buy = bool(prev_st.get('is_buy', True))

                                if raw_15.startswith('+'):
                                    is_buy = True
                                elif raw_15.startswith('-'):
                                    is_buy = False
                                elif ask1 > 0 and bid1 > 0 and current_price > 0:
                                    if current_price >= ask1:
                                        is_buy = True
                                    elif current_price <= bid1:
                                        is_buy = False
                                    else:
                                        mid_q = 0.5 * (ask1 + bid1)
                                        is_buy = True if current_price > mid_q else (False if current_price < mid_q else (current_price >= prev_price if prev_price > 0 else prev_is_buy))
                                elif prev_price > 0 and current_price > 0:
                                    is_buy = True if current_price > prev_price else (False if current_price < prev_price else prev_is_buy)
                                else:
                                    is_buy = prev_is_buy

                                if current_price > 0:
                                    self._last_tick_state[ob_key] = {'price': current_price, 'is_buy': is_buy}
                                tick_amount = current_price * tick_qty
                                
                                if current_price > 0 and self.on_real_tick:
                                    tick_data = {
                                        'code': code,
                                        'exchange': tick_exch,
                                        'price': current_price,
                                        'qty': tick_qty,
                                        'amount': tick_amount,
                                        'is_buy': is_buy,
                                        'raw_15': raw_15,
                                        'ask1': ask1,
                                        'bid1': bid1,
                                        'gangdo': chegyul_gangdo,
                                        'accum_volume': accum_volume,
                                        'time': tick_time
                                    }
                                    if asyncio.iscoroutinefunction(self.on_real_tick):
                                        asyncio.create_task(self.on_real_tick(tick_data))
                                    else:
                                        self.on_real_tick(tick_data)
                            except Exception as e:
                                logger.error(f"주식체결 파싱 에러: {e}")

                        elif name in ('주식호가잔량', '호가잔량'):
                            raw_code = str(values.get('9001') or data_item.get('item') or '')
                            ob_exch = 'NXT' if '_NX' in raw_code else 'KRX'
                            code = self._clean_stock_code(raw_code)
                            if not code or not code.isalnum() or code == "000000":
                                continue
                            try:
                                ask1 = abs(float(str(values.get('41', values.get('27', 0)) or 0).lstrip('+-') or 0))
                                bid1 = abs(float(str(values.get('51', values.get('28', 0)) or 0).lstrip('+-') or 0))
                                if ask1 > 0 or bid1 > 0:
                                    self._last_orderbook[(code, ob_exch)] = {'ask1': ask1, 'bid1': bid1, 'ts': time.time()}
                                    if self.on_orderbook:
                                        ob_data = {'code': code, 'exchange': ob_exch, 'ask1': ask1, 'bid1': bid1}
                                        if asyncio.iscoroutinefunction(self.on_orderbook):
                                            asyncio.create_task(self.on_orderbook(ob_data))
                                        else:
                                            self.on_orderbook(ob_data)
                            except Exception as e:
                                logger.debug(f"호가잔량 파싱 에러: {e}")

            except websockets.ConnectionClosed:
                self.connected = False
                if not self.keep_running:
                    break
                now_ts = time.time()
                r10001_hist = [t for t in getattr(self, '_r10001_timestamps', []) if now_ts - t <= 30.0]
                self._r10001_timestamps = r10001_hist
                reconnect_wait = 15 if len(r10001_hist) >= 2 else 3
                if reconnect_wait > 3:
                    logger.warning(
                        f"⚠️ [AppKey 중복 접속 R10001 반복({len(r10001_hist)}회/30초)] 무한 핑퐁 방지를 위해 {reconnect_wait}초 후 재연결합니다."
                    )
                else:
                    logger.error("웹소켓 연결이 끊어졌습니다. 3초 후 재연결을 시도합니다.")
                await asyncio.sleep(reconnect_wait)
                if self.keep_running:
                    self._subscribed_tick_codes.clear()
                    self._focus_ob_code = None
                    self._last_top10_sync_key = None
                    await self.connect()
            except Exception as e:
                if not self.keep_running:
                    break
                logger.error(f"receive_messages 에러: {e}")
                await asyncio.sleep(1)

    async def run(self):
        self._loop = asyncio.get_running_loop()
        self._subscribed_tick_codes.clear()
        self._focus_ob_code = None
        self._last_top10_sync_key = None
        await self.connect()
        await self.receive_messages()

    async def disconnect(self):
        self.keep_running = False
        if self._register_task and not self._register_task.done():
            self._register_task.cancel()
        if self.connected and self.websocket:
            await self.websocket.close()
            self.connected = False
            logger.info('웹소켓 종료')
