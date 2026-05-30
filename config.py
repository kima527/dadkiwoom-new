import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Kiwoom API Settings
KIWOOM_APP_KEY = os.getenv("KIWOOM_APP_KEY", "")
KIWOOM_APP_SECRET = os.getenv("KIWOOM_APP_SECRET", "")
KIWOOM_IS_MOCK = os.getenv("KIWOOM_IS_MOCK", "True").lower() == "true"
KIWOOM_ACCOUNT_NUM = os.getenv("KIWOOM_ACCOUNT_NUM", "")

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# KakaoTalk Settings
KAKAO_APP_KEY = os.getenv("KAKAO_APP_KEY", "")
KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "")

# Watchlist Excel File Name
WATCHLIST_FILE = "my_pick.xlsx"

def print_config():
    print("=" * 40)
    print("         SYSTEM CONFIGURATION")
    print("=" * 40)
    print(f"Kiwoom App Key:    {KIWOOM_APP_KEY[:5]}...{KIWOOM_APP_KEY[-5:] if len(KIWOOM_APP_KEY) > 10 else ''}")
    print(f"Kiwoom Mode:       {'Mock (모의투자)' if KIWOOM_IS_MOCK else 'Real (실거래)'}")
    print(f"Telegram Config:   {'Configured' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else 'Not Configured'}")
    print(f"KakaoTalk Config:  {'Configured' if KAKAO_APP_KEY and KAKAO_REFRESH_TOKEN else 'Not Configured'}")
    print(f"Watchlist File:    {WATCHLIST_FILE}")
    print("=" * 40)

if __name__ == "__main__":
    print_config()
