import kiwoom_rest_api.koreanstock.chart as ksc
import inspect

print(inspect.signature(ksc.Chart.stock_daily_chart_request_ka10081))
print(ksc.Chart.stock_daily_chart_request_ka10081.__doc__)
