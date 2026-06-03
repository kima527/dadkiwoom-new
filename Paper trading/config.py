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
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_pick.xlsx")

# TEMA Gate Line Settings (테마급등관문선)
TEMA_PERIOD_SHORT = int(os.getenv("TEMA_PERIOD_SHORT", "5"))   # 기간1 (단기)
TEMA_PERIOD_LONG = int(os.getenv("TEMA_PERIOD_LONG", "20"))    # 기간2 (장기)

# Trading Budget Settings
BUDGET_PER_STOCK = int(os.getenv("BUDGET_PER_STOCK", "1000000")) # 종목별 매수 예산 (기본 100만 원)

# Single Stock Mode Settings (단일 종목 모드 설정)
# AUTO: 매일 장 시작 시 이격도가 가장 낮은 종목을 1순위로 선정하여 당일 매매 진행
# 특정 종목코드 지정 시 해당 종목으로 고정 (예: "000660")
TARGET_SINGLE_STOCK_CODE = os.getenv("TARGET_SINGLE_STOCK_CODE", "AUTO")
SINGLE_STOCK_BUDGET = int(os.getenv("SINGLE_STOCK_BUDGET", "10000000")) # 단일 종목 집중 투자 예산 (1,000만 원)

def print_config():
    print("=" * 40)
    print("         SYSTEM CONFIGURATION")
    print("=" * 40)
    print(f"Kiwoom App Key:    {KIWOOM_APP_KEY[:5]}...{KIWOOM_APP_KEY[-5:] if len(KIWOOM_APP_KEY) > 10 else ''}")
    print(f"Kiwoom Mode:       {'Mock (모의투자)' if KIWOOM_IS_MOCK else 'Real (실거래)'}")
    print(f"Telegram Config:   {'Configured' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else 'Not Configured'}")
    print(f"KakaoTalk Config:  {'Configured' if KAKAO_APP_KEY and KAKAO_REFRESH_TOKEN else 'Not Configured'}")
    print(f"Watchlist File:    {WATCHLIST_FILE}")
    print(f"Budget per Stock:  {BUDGET_PER_STOCK:,} KRW")
    print("=" * 40)

if __name__ == "__main__":
    print_config()
