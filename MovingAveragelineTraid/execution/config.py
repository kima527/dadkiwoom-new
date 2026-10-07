import os
from pathlib import Path
from dotenv import load_dotenv

# Load from both possible .env locations (real trading and root)
real_env = r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading\.env"
root_env = r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\.env"

if os.path.exists(real_env):
    load_dotenv(real_env)
if os.path.exists(root_env):
    load_dotenv(root_env)

KIWOOM_APP_KEY = os.getenv("KIWOOM_REAL_APP_KEY") or os.getenv("KIWOOM_APP_KEY", "")
KIWOOM_REAL_APP_SECRET = os.getenv("KIWOOM_REAL_APP_SECRET") or os.getenv("KIWOOM_APP_SECRET", "")
KIWOOM_APP_SECRET = KIWOOM_REAL_APP_SECRET
KIWOOM_ACCOUNT_NUM = os.getenv("KIWOOM_REAL_ACCOUNT_NUM") or os.getenv("KIWOOM_ACCOUNT_NUM", "")
KIWOOM_ACCOUNT_NO = KIWOOM_ACCOUNT_NUM
KIWOOM_ACCOUNT_PWD = os.getenv("KIWOOM_REAL_ACCOUNT_PWD") or os.getenv("KIWOOM_ACCOUNT_PWD", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

if not KIWOOM_APP_KEY:
    print(f"Warning: KIWOOM_APP_KEY not found in {real_env} or {root_env}")
