import asyncio
import websockets
import json
import logging
from typing import Callable, Coroutine
from kiwoom_rest_api.auth.token import TokenManager
import os
import config

logger = logging.getLogger(__name__)

os.environ["KIWOOM_API_KEY"] = config.KIWOOM_APP_KEY
os.environ["KIWOOM_API_SECRET"] = config.KIWOOM_REAL_APP_SECRET
os.environ["KIWOOM_USE_SANDBOX"] = "false"

SOCKET_URL = 'wss://api.kiwoom.com:10000/api/dostk/websocket'

class KiwoomWebSocketClient:
    def __init__(self, target_condition_name: str, on_insert: Callable, on_delete: Callable):
        self.uri = SOCKET_URL
        self.websocket = None
        self.connected = False
        self.keep_running = True
        self.token_manager = TokenManager()
        
        self.target_condition_name = target_condition_name
        self.target_condition_sn = None
        self.target_condition_index = None
        
        self.on_insert = on_insert
        self.on_delete = on_delete

    async def connect(self):
        try:
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            logger.info("웹소켓 서버에 연결되었습니다.")

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

    async def receive_messages(self):
        while self.keep_running:
            try:
                msg = await self.websocket.recv()
                response = json.loads(msg)
                
                trnm = response.get('trnm')
                
                if trnm == 'PING':
                    await self.send_message(response)
                    continue
                
                if trnm == 'LOGIN':
                    if response.get('return_code') != 0:
                        logger.error(f"웹소켓 로그인 실패: {response.get('return_msg')}")
                        await self.disconnect()
                    else:
                        logger.info("웹소켓 로그인 성공! 조건식 목록을 요청합니다...")
                        req = {
                            "trnm": "CNSRLST"
                        }
                        asyncio.create_task(self.send_message(req))
                
                elif trnm == 'CNSRLST':
                    # 조건식 목록 응답
                    logger.info(f"CNSRLST 원본 응답: {response}")
                    cond_list = response.get('data', [])
                    logger.info(f"조건검색식 목록 수신: {len(cond_list)}개")
                    
                    found = False
                    for cond in cond_list:
                        if len(cond) >= 2:
                            cond_sn = cond[0]
                            cond_name = cond[1].strip()
                            if cond_name == self.target_condition_name:
                                self.target_condition_sn = cond_sn
                                self.target_condition_index = cond_sn
                                found = True
                                logger.info(f"목표 조건식 '{self.target_condition_name}' 발견! (일련번호: {cond_sn})")
                                break
                            
                    if found:
                        # 실시간 조건검색 등록 요청 (CNSRREQ)
                        req = {
                            "trnm": "CNSRREQ",
                            "seq": str(self.target_condition_sn),
                            "search_type": "1",
                            "stex_tp": "K"
                        }
                        logger.info(f"실시간 조건검색 등록 시도: CNSRREQ with seq={self.target_condition_sn}")
                        asyncio.create_task(self.send_message(req))
                    else:
                        logger.error(f"조건식 목록에서 '{self.target_condition_name}'을(를) 찾을 수 없습니다!")
                
                elif trnm == 'CNSRREQ':
                    # 초기 조건검색 포착 종목 리스트
                    logger.info(f"조건검색 초기 포착 응답: {response}")
                    data_list = response.get('data') or []
                    for item in data_list:
                        code = item.get('jmcode', '').replace('A', '')
                        if code:
                            logger.info(f"초기 포착 종목: {code}")
                            if asyncio.iscoroutinefunction(self.on_insert):
                                asyncio.create_task(self.on_insert(code))
                            else:
                                self.on_insert(code)
                            
                elif trnm == 'REAL':
                    # 실시간 데이터
                    data_list = response.get('data') or []
                    for data_item in data_list:
                        if data_item.get('name') == '조건검색':
                            values = data_item.get('values', {})
                            code = values.get('9001', '').replace('A', '')
                            evt_tp = values.get('843', '') # I: 편입, D: 이탈
                            cond_idx = values.get('841', '')
                            
                            if str(cond_idx) == str(self.target_condition_index):
                                logger.info(f"조건검색 실시간 신호: 종목코드={code}, 타입={evt_tp}")
                                if evt_tp == 'I':
                                    if asyncio.iscoroutinefunction(self.on_insert):
                                        asyncio.create_task(self.on_insert(code))
                                    else:
                                        self.on_insert(code)
                                elif evt_tp == 'D':
                                    if asyncio.iscoroutinefunction(self.on_delete):
                                        asyncio.create_task(self.on_delete(code))
                                    else:
                                        self.on_delete(code)

            except websockets.ConnectionClosed:
                logger.error("웹소켓 연결이 끊어졌습니다. 3초 후 재연결을 시도합니다.")
                self.connected = False
                await asyncio.sleep(3)
                await self.connect()
            except Exception as e:
                logger.error(f"receive_messages 에러: {e}")
                await asyncio.sleep(1)

    async def run(self):
        await self.connect()
        await self.receive_messages()

    async def disconnect(self):
        self.keep_running = False
        if self.connected and self.websocket:
            await self.websocket.close()
            self.connected = False
            logger.info('웹소켓 종료')
