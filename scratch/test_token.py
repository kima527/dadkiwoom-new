import os
import requests
import json
import dotenv
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
dotenv.load_dotenv(dotenv_path=env_path)

appkey = os.getenv("KIWOOM_APP_KEY", "")
secretkey = os.getenv("KIWOOM_APP_SECRET", "")

print(f"Loaded credentials from .env: APP_KEY='{appkey}', SECRET='{secretkey}'")

# Request token from Mock API
url = "https://mockapi.kiwoom.com/oauth2/token"
data = {
    "grant_type": "client_credentials",
    "appkey": appkey,
    "secretkey": secretkey
}

res = requests.post(url, json=data)
print("Status Code:", res.status_code)
print("Response Text:")
try:
    print(json.dumps(res.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(res.text)
