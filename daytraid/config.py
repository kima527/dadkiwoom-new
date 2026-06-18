import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Kiwoom API Settings for Real Trading (실전투자용)
# 실전매매에서는 샌드박스(모의)가 아닌 실전 서버로 강제 고정됩니다.
KIWOOM_APP_KEY = os.getenv("KIWOOM_REAL_APP_KEY", "")
KIWOOM_REAL_APP_SECRET = os.getenv("KIWOOM_REAL_APP_SECRET", "")
KIWOOM_IS_MOCK = False # 실전매매용으로 False 고정
KIWOOM_ACCOUNT_NUM = os.getenv("KIWOOM_REAL_ACCOUNT_NUM", "")

# Telegram Settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# KakaoTalk Settings
KAKAO_APP_KEY = os.getenv("KAKAO_APP_KEY", "")
KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "")

# ── 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY] ──
# Watchlist Excel File Name (종목 선정은 반드시 이 파일에 있는 종목으로만 한정합니다)
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_pick.xlsx")

# TEMA Gate Line Settings
TEMA_PERIOD_SHORT = int(os.getenv("TEMA_PERIOD_SHORT", "5"))
TEMA_PERIOD_LONG = int(os.getenv("TEMA_PERIOD_LONG", "20"))

# Budget Settings
BUDGET_PER_STOCK = int(os.getenv("BUDGET_PER_STOCK", "1000000"))
TEST_MODE_1_SHARE = False
SINGLE_STOCK_BUDGET = int(os.getenv("SINGLE_STOCK_BUDGET", "10000000"))
TARGET_SINGLE_STOCK_CODE = os.getenv("TARGET_SINGLE_STOCK_CODE", "AUTO")

def print_real_config():
    print("=" * 50)
    print("      🔴 REAL TRADING SYSTEM CONFIGURATION 🔴")
    print("=" * 50)
    print(f"Kiwoom Real Key:    {KIWOOM_APP_KEY[:5]}...{KIWOOM_APP_KEY[-5:] if len(KIWOOM_APP_KEY) > 10 else ''}")
    print(f"Kiwoom Mode:        REAL TRADING (실전 매매)")
    print(f"Real Account Num:   {KIWOOM_ACCOUNT_NUM}")
    print(f"Telegram Config:    {'Configured' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else 'Not Configured'}")
    print(f"Single Stock Mode:  {TARGET_SINGLE_STOCK_CODE} (Budget: {SINGLE_STOCK_BUDGET:,} KRW)")
    print("=" * 50)

if __name__ == "__main__":
    print_real_config()


# HARDCODED TARGET STOCKS (User requested strictly these stocks)
HARDCODED_TARGET_STOCKS = ['006800', '035420', '028260', '240810', '042700', '018880', '034020', '298040', '475150', '028050', '204320', '005380', '403870', '089030', '402340', '066570', '009830', '036930', '000720', '012330', '000660', '009150', '003490', '005930', '010120', '011070', '267260', '064400', '006400', '058470', '093370', '042660', '329180', '001820', '080220', '015760']
