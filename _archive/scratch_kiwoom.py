import sys
import logging
import json
import requests
import config
from kiwoom_client import KiwoomClient

logging.basicConfig(level=logging.INFO)

client = KiwoomClient()
token = client.token_manager.access_token

def test_rkinfo(api_id, body):
    try:
        url = f"{client.base_url}/api/dostk/rkinfo"
        headers = {
            "Authorization": f"Bearer {token}",
            "appkey": config.KIWOOM_APP_KEY,
            "appsecret": config.KIWOOM_APP_SECRET,
            "tr_id": api_id,
            "api-id": api_id,
            "cont-yn": "N",
            "next-key": "0",
            "content-type": "application/json"
        }
        res = requests.post(url, headers=headers, json=body)
        print(f"--- {api_id} Response ---")
        print(res.status_code)
        data = res.json()
        if "out_block_1" in data:
            data["out_block_1"] = data["out_block_1"][:5]
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error testing {api_id}: {e}")

test_rkinfo("ka10027", {
    "mrkt_tp": "0",
    "sort_tp": "1",
    "trde_qty_cnd": "0"
})

test_rkinfo("ka10032", {
    "mrkt_tp": "0",
    "mang_stk_incls": "0",
    "stex_tp": "0"
})
