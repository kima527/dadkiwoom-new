import sys
import os
import inspect

try:
    from kiwoom_rest_api.koreanstock.rank_info import RankInfo
    
    print("=== top_trading_value_request_ka10032 ===")
    print(inspect.signature(RankInfo.top_trading_value_request_ka10032))
    print(RankInfo.top_trading_value_request_ka10032.__doc__)
    
    print("=== top_day_over_day_change_rate_request_ka10027 ===")
    print(inspect.signature(RankInfo.top_day_over_day_change_rate_request_ka10027))
    print(RankInfo.top_day_over_day_change_rate_request_ka10027.__doc__)
    
except Exception as e:
    print("Error:", e)
