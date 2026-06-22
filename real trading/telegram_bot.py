import logging
import asyncio
import requests
import traceback
import os
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

# 전역 상태 (main.py에서 import하여 사용)
IS_BOT_ACTIVE = True

# 비밀번호 및 공제율 설정
BOT_PASSWORD = os.getenv("TELEGRAM_BOT_PASSWORD", "hani1302")
DEDUCTION_RATE = 0.00265  # 0.265%

# 인증된 Chat ID 목록 (config의 기본 Chat ID는 인증된 것으로 간주할 수 있으나,
# 비밀번호로 완벽히 통제하기 위해 메모리상에서 인증받은 ID만 허용)
authorized_chat_ids = set()
if TELEGRAM_CHAT_ID:
    authorized_chat_ids.add(str(TELEGRAM_CHAT_ID))

def send_message_sync(text: str):
    """동기식으로 텔레그램 메시지를 발송합니다."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("텔레그램 토큰이 설정되지 않아 메시지를 보낼 수 없습니다.")
        return
        
    if not authorized_chat_ids:
        logger.warning("인증된 텔레그램 채팅방이 없어 메시지를 보낼 수 없습니다.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    for chat_id in authorized_chat_ids:
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"텔레그램 메시지 발송 실패 ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"텔레그램 메시지 발송 중 오류: {e}")

async def send_message(text: str):
    """비동기 환경에서 텔레그램 메시지를 발송합니다."""
    await asyncio.to_thread(send_message_sync, text)

async def poll_telegram_updates():
    """텔레그램에서 명령어를 수신하는 백그라운드 루프"""
    global IS_BOT_ACTIVE
    
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("텔레그램 토큰이 설정되지 않아 제어 명령을 받을 수 없습니다.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    
    logger.info("텔레그램 제어 감시(Polling) 루프를 시작합니다.")
    
    while True:
        try:
            payload = {"offset": offset, "timeout": 30}
            # to_thread로 감싸서 루프 블로킹 방지
            response = await asyncio.to_thread(requests.get, url, params=payload, timeout=35)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    for item in data.get("result", []):
                        offset = item["update_id"] + 1
                        message = item.get("message", {})
                        text = str(message.get("text", "")).strip()
                        chat_id = str(message.get("chat", {}).get("id", ""))
                        
                        if not text or not chat_id:
                            continue
                            
                        # 명령어 처리
                        if text.startswith("/auth"):
                            parts = text.split()
                            if len(parts) >= 2 and parts[1] == BOT_PASSWORD:
                                authorized_chat_ids.add(chat_id)
                                await send_message("✅ 인증 성공! 봇 제어 권한이 부여되었습니다.\n\n사용 가능 명령어:\n/start_bot - 매수 감시 켜기\n/stop_bot - 신규 매수 차단(기존 종목 매도는 유지)")
                            else:
                                await asyncio.to_thread(requests.post, f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "❌ 비밀번호가 틀렸습니다."})
                        
                        elif chat_id in authorized_chat_ids:
                            if text == "/start_bot":
                                IS_BOT_ACTIVE = True
                                await send_message("🟢 봇이 [시작] 되었습니다. 신규 매수 로직이 활성화됩니다.")
                                logger.info(f"[텔레그램] 봇 시작 명령 수신 - 매수 활성화됨")
                            elif text == "/stop_bot":
                                IS_BOT_ACTIVE = False
                                await send_message("🔴 봇이 [중지] 되었습니다. 신규 매수가 차단됩니다.\n(※ 보유 중인 종목의 감시 및 자동 매도는 계속 정상 작동합니다)")
                                logger.info(f"[텔레그램] 봇 중지 명령 수신 - 신규 매수 차단됨")
                            elif text == "/status":
                                status = "🟢 실행 중" if IS_BOT_ACTIVE else "🔴 중지됨 (신규매수 차단)"
                                await send_message(f"현재 봇 상태: {status}\n인증된 사용자 수: {len(authorized_chat_ids)}명")
                else:
                    logger.warning(f"텔레그램 업데이트 실패: {data}")
            else:
                logger.error(f"텔레그램 API 에러: {response.status_code}")
                
        except requests.exceptions.RequestException:
            # 네트워크 오류 시 조용히 넘어가서 재시도
            pass
        except Exception as e:
            logger.error(f"텔레그램 폴링 루프 에러: {e}")
            logger.error(traceback.format_exc())
            
        await asyncio.sleep(1)

def format_trade_message(stock_name: str, buy_price: float, sell_price: float) -> str:
    """순수익률(공제율 반영)을 계산하여 간소화된 메시지를 생성합니다."""
    # 0 나누기 방지
    if buy_price <= 0:
        return f"[{stock_name}] 매도 완료 (평단가 오류)"
        
    # 단순 수익률 계산
    gross_profit_rate = (sell_price - buy_price) / buy_price
    
    # 순수익률 (골재율 0.265% 차감)
    net_profit_rate = gross_profit_rate - DEDUCTION_RATE
    net_profit_percent = net_profit_rate * 100
    
    # 이모지 선택
    emoji = "🔴" if net_profit_percent >= 0 else "🔵"
    if net_profit_percent > 3.0:
        emoji = "🚀"
        
    msg = (
        f"{emoji} <b>{stock_name} 매도 완료</b>\n"
        f"• 매수가: {buy_price:,.0f}원\n"
        f"• 매도가: {sell_price:,.0f}원\n"
        f"• 수익률: <b>{net_profit_percent:+.2f}%</b>"
    )
    return msg
