import sys
import os
import time

# Add real trading folder to path to load config and kiwoom_client
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))

import config
from kiwoom_client import KiwoomClient
from kiwoom_rest_api.koreanstock.sector import Sector

def test_industry():
    client = KiwoomClient()
    
    # Initialize Sector API
    sector_api = Sector(base_url=client.base_url, token_manager=client.token_manager)
    
    print("Fetching KOSPI industry codes...")
    res_kospi_codes = client.stock_info_api.industry_code_list_request_ka10101(market_type="0")
    if res_kospi_codes and res_kospi_codes.get("return_code") == 0:
        lst = res_kospi_codes.get("inds_cd_out", [])
        print(f"KOSPI Industries count: {len(lst)}")
        for item in lst:
            if "200" in item.get("inds_nm", "") or "150" in item.get("inds_nm", ""):
                print(item)
    else:
        print("KOSPI codes fail:", res_kospi_codes)

    print("\nFetching KOSDAQ industry codes...")
    res_kosdaq_codes = client.stock_info_api.industry_code_list_request_ka10101(market_type="1")
    if res_kosdaq_codes and res_kosdaq_codes.get("return_code") == 0:
        lst = res_kosdaq_codes.get("inds_cd_out", [])
        print(f"KOSDAQ Industries count: {len(lst)}")
        for item in lst:
            if "150" in item.get("inds_nm", "") or "200" in item.get("inds_nm", "") or "코스닥 150" in item.get("inds_nm", ""):
                print(item)
    else:
        print("KOSDAQ codes fail:", res_kosdaq_codes)

    print("\nFetching KOSPI 200 components via Sector API...")
    # mrkt_tp: 0 (KOSPI), inds_cd: 201 (KOSPI 200), stex_tp: 1 (KRX)
    res_kpi200 = sector_api.industrywise_stock_price_request_ka20002(mrkt_tp="0", inds_cd="201", stex_tp="1")
    if res_kpi200 and res_kpi200.get("return_code") == 0:
        stocks = res_kpi200.get("inds_stkpc", [])
        print(f"KOSPI 200 count: {len(stocks)}")
        print("First 5 stocks:")
        for s in stocks[:5]:
            print(f"{s.get('stk_nm')} ({s.get('stk_cd')})")
    else:
        print("KOSPI 200 fail:", res_kpi200)

    print("\nFetching KOSDAQ 150 components via Sector API...")
    # mrkt_tp: 1 (KOSDAQ), inds_cd: 101? or something else?
    # Let's try to query with mrkt_tp="1", inds_cd="101"? Let's check.
    # Actually KOSDAQ 150 is usually 101 or 201 or 302?
    # Let's try various codes.
    for code in ["101", "201", "302", "150"]:
        print(f"Trying KOSDAQ inds_cd='{code}'...")
        res = sector_api.industrywise_stock_price_request_ka20002(mrkt_tp="1", inds_cd=code, stex_tp="1")
        if res and res.get("return_code") == 0:
            stocks = res.get("inds_stkpc", [])
            print(f"  Success for code {code}: count={len(stocks)}")
            if stocks:
                print(f"  First 3: {[s.get('stk_nm') for s in stocks[:3]]}")
        else:
            print(f"  Fail for code {code}: {res.get('return_msg')}")

if __name__ == "__main__":
    test_industry()
