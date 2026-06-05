import kiwoom_rest_api.koreanstock.account as ksa
import kiwoom_rest_api.koreanstock.chart as ksc
import kiwoom_rest_api.koreanstock.order as kso
import kiwoom_rest_api.koreanstock.rank_info as ksr
import kiwoom_rest_api.koreanstock.stockinfo as kss

import inspect

classes = [
    ("Account", ksa.Account),
    ("Chart", ksc.Chart),
    ("Order", kso.Order),
    ("RankInfo", ksr.RankInfo),
    ("StockInfo", kss.StockInfo)
]

print("=" * 60)
print("             EXPLORING ALL KIWOOM API METHODS")
print("=" * 60)

for class_name, cls in classes:
    print(f"\n--- Methods of {class_name} ---")
    for name, obj in inspect.getmembers(cls):
        if not name.startswith('_'):
            try:
                sig = inspect.signature(obj)
                print(f"  {name}{sig}")
            except Exception:
                print(f"  {name}")
                
print("\n" + "=" * 60)
