import os
from dotenv import load_dotenv

# Load .env from the PythonWorksplace folder as requested
dotenv_path = r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\.env"
load_dotenv(dotenv_path)

KIWOOM_APP_KEY = os.getenv("KIWOOM_APP_KEY", "")
KIWOOM_APP_SECRET = os.getenv("KIWOOM_APP_SECRET", "")
KIWOOM_REAL_APP_SECRET = os.getenv("KIWOOM_REAL_APP_SECRET", "")
KIWOOM_ACCOUNT_NO = os.getenv("KIWOOM_ACCOUNT_NO", "")
KIWOOM_ACCOUNT_NUM = os.getenv("KIWOOM_ACCOUNT_NUM", "")
KIWOOM_ACCOUNT_PWD = os.getenv("KIWOOM_ACCOUNT_PWD", "")

if not KIWOOM_APP_KEY:
    print(f"Warning: KIWOOM_APP_KEY not found in {dotenv_path}")
