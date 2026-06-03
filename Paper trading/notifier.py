import json
import requests
import logging
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self):
        self.telegram_bot_token = config.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = config.TELEGRAM_CHAT_ID
        
        self.kakao_app_key = config.KAKAO_APP_KEY
        self.kakao_refresh_token = config.KAKAO_REFRESH_TOKEN
        self.kakao_access_token = None
        
        # If Kakao keys are set, try to get the initial access token
        if self.kakao_app_key and self.kakao_refresh_token:
            self.refresh_kakao_access_token()

    def refresh_kakao_access_token(self):
        """Refreshes the Kakao access token using the refresh token."""
        url = "https://kauth.kakao.com/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.kakao_app_key,
            "refresh_token": self.kakao_refresh_token
        }
        try:
            response = requests.post(url, data=data)
            res_json = response.json()
            if response.status_code == 200:
                self.kakao_access_token = res_json.get("access_token")
                logger.info("KakaoTalk access token successfully refreshed.")
                # If a new refresh token is returned, update it (refresh tokens can be updated too)
                new_refresh_token = res_json.get("refresh_token")
                if new_refresh_token:
                    logger.info("New KakaoTalk refresh token received.")
                    self.kakao_refresh_token = new_refresh_token
                    # In a real app we might write this back to .env, but for now we update in memory
                return True
            else:
                logger.error(f"Failed to refresh Kakao token: {res_json}")
                return False
        except Exception as e:
            logger.error(f"Exception during Kakao token refresh: {e}")
            return False

    def send_telegram(self, message: str) -> bool:
        """Sends a notification to Telegram."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Telegram Bot Token or Chat ID is not configured.")
            return False
        
        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            res_json = response.json()
            if response.status_code == 200 and res_json.get("ok"):
                logger.info("Telegram alert sent successfully.")
                return True
            else:
                logger.error(f"Telegram API error: {res_json}")
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_kakao(self, message: str) -> bool:
        """Sends a 'Send to Me' message via KakaoTalk API."""
        if not self.kakao_app_key or not self.kakao_refresh_token:
            logger.warning("KakaoTalk App Key or Refresh Token is not configured.")
            return False

        if not self.kakao_access_token:
            if not self.refresh_kakao_access_token():
                logger.error("Cannot send KakaoTalk message: Token refresh failed.")
                return False

        url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
        headers = {
            "Authorization": f"Bearer {self.kakao_access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        template = {
            "object_type": "text",
            "text": message,
            "link": {
                "web_url": "https://www.kiwoom.com",
                "mobile_web_url": "https://www.kiwoom.com"
            },
            "button_title": "키움증권 이동"
        }
        data = {
            "template_object": json.dumps(template)
        }

        try:
            response = requests.post(url, headers=headers, data=data, timeout=10)
            res_json = response.json()
            if response.status_code == 200 and res_json.get("result_code") == 0:
                logger.info("KakaoTalk alert sent successfully.")
                return True
            elif response.status_code == 401 or res_json.get("code") == -401: # Token expired
                logger.warning("KakaoTalk access token expired. Attempting refresh...")
                if self.refresh_kakao_access_token():
                    headers["Authorization"] = f"Bearer {self.kakao_access_token}"
                    response = requests.post(url, headers=headers, data=data, timeout=10)
                    res_json = response.json()
                    if response.status_code == 200 and res_json.get("result_code") == 0:
                        logger.info("KakaoTalk alert sent successfully after token refresh.")
                        return True
                logger.error(f"KakaoTalk alert failed after token refresh: {res_json}")
                return False
            else:
                logger.error(f"KakaoTalk API error: {res_json}")
                return False
        except Exception as e:
            logger.error(f"Failed to send KakaoTalk message: {e}")
            return False

    def send_all(self, message: str):
        """Dispatches notification to all configured services."""
        logger.info(f"Dispatching notification: {message[:50]}...")
        # Try Telegram
        self.send_telegram(message)
        # Try Kakao
        self.send_kakao(message)

if __name__ == "__main__":
    # Test notification setup
    notifier = Notifier()
    test_msg = "🔔 [시스템 테스트]\nKiwoom 알림 시스템이 시작되었습니다."
    notifier.send_all(test_msg)
