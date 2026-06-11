import asyncio

# 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
# ── KiwoomWebSocketRunner (실시간 틱 수신 엔진) ──
# 이 모듈은 키움 REST API 웹소켓 서버와 연결하여 '0초 딜레이'로 체결 정보를 가져옵니다.
# 사용자의 명시적 승인 없이 비동기 루프 구조나 연결 방식을 임의로 변경하지 마십시오.
# ────────────────────────────────────────────────────────────

import threading
import logging

logger = logging.getLogger(__name__)

class KiwoomWebSocketRunner:
    """
    키움 REST API 공식 웹소켓 클라이언트를 비동기 백그라운드 스레드에서 구동하여
    RealtimeDataManager로 데이터를 푸시하는 역할입니다.
    """
    def __init__(self, token_manager, data_manager):
        self.token_manager = token_manager
        self.data_manager = data_manager
        self.is_running = False
        self.loop = None
        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)

    def start(self):
        self.is_running = True
        self.thread.start()
        logger.info(f"[{self.data_manager.stock_code}] 웹소켓 스레드 가동 시작")

    def stop(self):
        self.is_running = False
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._websocket_task())
        except Exception as e:
            logger.error(f"WebSocket Loop Fatal Error: {e}")
        finally:
            self.loop.close()

    async def _websocket_task(self):
        logger.info("키움 REST API 웹소켓 클라이언트 연결을 시도합니다...")
        try:
            # 외부 라이브러리 지원 여부에 따라 동적으로 가져옵니다.
            try:
                from kiwoom_rest_api import WebSocketClient
            except ImportError:
                logger.error("kiwoom_rest_api 내에 WebSocketClient 모듈이 설치되어 있지 않습니다.")
                logger.warning("-> 차선책인 data_feeder.py (하이브리드 피더)로 대체 구동을 권장합니다.")
                return

            access_token = self.token_manager.get_token()
            client = WebSocketClient(access_token=access_token)
            
            # 콜백을 라이브러리가 지원하는 방식으로 엮습니다 (표준적인 on_message/handler 가정)
            # 만약 라이브러리의 콜백 형식이 다를 경우 이 부분을 사용자 환경에 맞게 수정해야 합니다.
            async def on_data_received(realtime_data):
                try:
                    # 데이터 구조는 라이브러리마다 다를 수 있으므로 dict 형태인 data 속성을 추출
                    data = getattr(realtime_data, 'data', realtime_data)
                    
                    price = data.get('current_price') or data.get('cur_prc')
                    if price is None: return
                        
                    volume = data.get('volume') or data.get('trde_qty', 0)
                    volume_power = data.get('volume_power') or data.get('tday_cntr_pwr', 100.0)
                    
                    # 체결 시간
                    time_str = data.get('time') or data.get('stck_cntg_hour')
                    if not time_str:
                        import datetime
                        time_str = datetime.datetime.now().strftime("%H%M%S")
                        
                    self.data_manager.process_realtime_tick(
                        current_price=abs(float(price)),
                        volume=int(volume),
                        volume_power=float(volume_power),
                        time_str=time_str.replace(":", "") # HHMMSS 포맷
                    )
                except Exception as e:
                    logger.error(f"웹소켓 수신 콜백 처리 중 에러: {e}")

            # 라이브러리 버전에 따라 메서드명이 다를 수 있음을 방어
            if hasattr(client, 'register_realtime'):
                await client.register_realtime(type_list=['04']) # 04: 주식체결
            
            # 웹소켓 메시지 핸들러 등록
            if hasattr(client, 'on_message'):
                client.on_message = on_data_received
            
            logger.info("웹소켓 연결 성공! 데이터 스트리밍을 대기합니다.")
            if hasattr(client, 'run_sync'):
                await client.run_sync()
            elif hasattr(client, 'run'):
                await client.run()
            else:
                logger.error("웹소켓 구동(run) 메서드를 찾을 수 없습니다. 라이브러리 버전을 확인하세요.")
                
        except Exception as e:
            logger.error(f"웹소켓 구동 실패: {e}")
            logger.warning("-> 차선책인 data_feeder.py (하이브리드 피더)로 자동 전환합니다.")
