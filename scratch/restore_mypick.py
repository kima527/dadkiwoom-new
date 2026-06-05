import sys
import os
import openpyxl

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from kiwoom_client import KiwoomClient
import config

def restore():
    client = KiwoomClient()
    codes = [
        '000660', '128940', '071320', '005300', '251270', '241710', '034730', '001040', '001680', 
        '023530', '025900', '005850', '105560', '068270', '215200', '002030', '021240', '178320', 
        '195940', '036570', '003090', '047050', '009830', '055550', '096770', '009540', '010120', 
        '251970', '003490', '004490', '280360'
    ]
    
    print("Fetching names for original user picks...")
    name_map = client.get_stock_names(codes)
    
    filepath = config.WATCHLIST_FILE
    print(f"Target Excel: {filepath}")
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "My Pick"
    ws.append(["종목코드", "종목명", "보유수량", "매입단가", "현재가"])
    
    for code in codes:
        name = name_map.get(code, "알 수 없음")
        ws.append([code, name, "", "", ""])
        
    wb.save(filepath)
    print("Successfully restored original user picks to Excel!")

if __name__ == "__main__":
    restore()
